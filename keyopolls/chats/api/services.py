import mimetypes
from decimal import Decimal
from typing import List

from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from ninja import File, Query, Router, UploadedFile

from keyopolls.chats.models import TimelineItem
from keyopolls.chats.models.services import ServiceAttachment, ServiceItem
from keyopolls.chats.schemas import (
    CreateServiceSchema,
    ServiceFiltersSchema,
    ServiceResponseSchema,
    ServicesListResponseSchema,
    UpdateServiceSchema,
)
from keyopolls.common.schemas import Message
from keyopolls.communities.models import Community, CommunityMembership
from keyopolls.profile.middleware import (
    OptionalPseudonymousJWTAuth,
    PseudonymousJWTAuth,
)

router = Router()


@router.get(
    "/services",
    response={200: ServicesListResponseSchema, 400: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def get_services(request, filters: ServiceFiltersSchema = Query(...)):
    """
    Get a paginated list of services with optional filtering.

    Features:
    - Search by service name or description
    - Filter by community, creator, service type, broadcast, or status
    - Pagination support
    - Includes service attachments

    Query Parameters:
    - search: Search term for name or description
    - community_id: Filter by community
    - creator_id: Filter by service creator
    - service_type: Filter by service type (dm, live_chat, audio_call, video_call,
      custom)
    - status: Filter by status (active, inactive, draft)
    - page: Page number (default: 1)
    - per_page: Items per page (default: 20, max: 100)
    """

    # Validate per_page limit
    if filters.per_page > 100:
        filters.per_page = 100
    if filters.per_page < 1:
        filters.per_page = 20

    # Start with base queryset
    queryset = ServiceItem.objects.select_related(
        "creator", "community"
    ).prefetch_related("attachments")

    # Apply filters
    if filters.community_id:
        queryset = queryset.filter(community_id=filters.community_id)

    if filters.community_slug:
        queryset = queryset.filter(community__slug=filters.community_slug)

    if filters.creator_id:
        queryset = queryset.filter(creator_id=filters.creator_id)

    if filters.is_broadcasted:
        queryset = queryset.filter(is_broadcasted=filters.is_broadcasted)

    if filters.service_type:
        # Validate service type
        valid_types = [choice[0] for choice in ServiceItem.SERVICE_TYPES]
        if filters.service_type in valid_types:
            queryset = queryset.filter(service_type=filters.service_type)
        else:
            return 400, {
                "message": (
                    f"Invalid service_type. Valid types: {', '.join(valid_types)}"
                )
            }

    if filters.status:
        # Validate status
        valid_statuses = [choice[0] for choice in ServiceItem.STATUS_CHOICES]
        if filters.status in valid_statuses:
            queryset = queryset.filter(status=filters.status)
        else:
            return 400, {
                "message": (
                    f"Invalid status. Valid statuses: {', '.join(valid_statuses)}"
                )
            }

    # Apply search
    if filters.search:
        search_term = filters.search.strip()
        if search_term:
            queryset = queryset.filter(
                Q(name__icontains=search_term) | Q(description__icontains=search_term)
            )

    # Get total count before pagination
    total_count = queryset.count()

    # Apply pagination
    paginator = Paginator(queryset, filters.per_page)

    if filters.page > paginator.num_pages and paginator.num_pages > 0:
        filters.page = paginator.num_pages

    try:
        page_obj = paginator.page(filters.page)
    except Exception:
        return 400, {"message": "Invalid page number"}

    # Build response
    services_data = []
    for service in page_obj.object_list:
        # Build attachments list
        attachments_data = []
        for attachment in service.attachments.all():
            attachments_data.append(
                {
                    "id": str(attachment.id),
                    "attachment_type": attachment.attachment_type,
                    "file_name": attachment.file_name,
                    "file_size": attachment.file_size,
                    "title": attachment.title,
                    "description": attachment.description,
                    "display_order": attachment.display_order,
                    "file_url": attachment.file.url if attachment.file else None,
                }
            )

        service_data = {
            "id": str(service.id),
            "creator_id": service.creator.id,
            "creator_username": service.creator.username,
            "creator_display_name": service.creator.display_name,
            "community_id": service.community.id,
            "community_name": service.community.name,
            "service_type": service.service_type,
            "name": service.name,
            "description": service.description,
            "price": float(service.price),
            "duration_minutes": service.duration_minutes,
            "is_duration_based": service.is_duration_based,
            "status": service.status,
            "is_available": service.is_available,
            "total_purchases": service.total_purchases,
            "total_revenue": float(service.total_revenue),
            "is_broadcasted": service.is_broadcasted,
            "preview_image": (
                service.preview_image.url if service.preview_image else None
            ),
            "created_at": service.created_at,
            "updated_at": service.updated_at,
            "attachments": attachments_data,
            # User Input Setting
            "attachments_required": service.attachments_required,
            # DM-specific fields
            "max_messages_a_day": service.max_messages_a_day,
            "reply_time": service.reply_time,
        }
        services_data.append(service_data)

    return {
        "services": services_data,
        "total_count": total_count,
        "page": filters.page,
        "per_page": filters.per_page,
        "total_pages": paginator.num_pages,
        "has_next": page_obj.has_next(),
        "has_previous": page_obj.has_previous(),
    }


@router.post(
    "/services",
    response={201: ServiceResponseSchema, 400: Message, 403: Message, 404: Message},
    auth=PseudonymousJWTAuth(),
)
def create_service(
    request,
    data: CreateServiceSchema,
    attachments: List[UploadedFile] = File(None),
    preview_image: UploadedFile = File(None),
):
    """
    Create a new service. Only moderators can create services.

    Required fields:
    - community_id: ID of the community
    - service_type: Type of service (dm, live_chat, audio_call, video_call, custom)
    - name: Service name
    - description: Service description
    - price: Price in credits (minimum 0.01)

    Optional fields:
    - duration_minutes: Duration for timed services (default: 10)
    - is_duration_based: Whether service has time limit (default: False)
    - status: Service status (default: active)
    - attachments: List of files to attach to the service
    - max_messages_a_day: For DM services, max messages per day
    - reply_time: For DM services, reply time in days

    Service creation limits:
    - dm, live_chat, audio_call, video_call: Only one of each type per community per
      creator
    - custom: Multiple custom services allowed per community per creator
    """

    profile = request.auth

    # Validate community exists
    try:
        community = Community.objects.get(slug=data.community_slug, is_active=True)
    except Community.DoesNotExist:
        return 404, {"message": "Community not found"}

    # Check if user is a moderator of this community
    try:
        CommunityMembership.objects.get(
            community=community, profile=profile, status="active", role="moderator"
        )
    except CommunityMembership.DoesNotExist:
        return 403, {"message": "Only moderators can create services"}

    # Validate service type
    valid_types = [choice[0] for choice in ServiceItem.SERVICE_TYPES]
    if data.service_type not in valid_types:
        return 400, {
            "message": f"Invalid service_type. Valid types: {', '.join(valid_types)}"
        }

    # Validate status
    valid_statuses = [choice[0] for choice in ServiceItem.STATUS_CHOICES]
    if data.status not in valid_statuses:
        return 400, {
            "message": (f"Invalid status. Valid statuses: {', '.join(valid_statuses)}")
        }

    # Check for duplicate service type restrictions
    # Only allow one service of types: dm, live_chat, audio_call, video_call
    # per community per creator
    # Allow multiple custom services
    restricted_service_types = [
        "dm",
        "live_chat",
        "audio_call",
        "video_call",
        "group_chat",
        "group_audio_call",
        "group_video_call",
    ]

    if data.service_type in restricted_service_types:
        existing_service = ServiceItem.objects.filter(
            creator=profile, community=community, service_type=data.service_type
        ).first()

        if existing_service:
            service_type_labels = {
                "dm": "Direct Message",
                "live_chat": "Live Chat",
                "audio_call": "Audio Call",
                "video_call": "Video Call",
            }
            service_label = service_type_labels.get(
                data.service_type, data.service_type
            )
            return 400, {
                "message": (
                    (
                        f"You already have a {service_label} service in this community."
                        f"Only one service of this type is allowed per community."
                    )
                )
            }

    # Validate DM-specific fields
    if data.service_type == "dm":
        if hasattr(data, "max_messages_a_day") and data.max_messages_a_day is not None:
            if data.max_messages_a_day < 1:
                return 400, {"message": "Max messages per day must be at least 1"}

        if hasattr(data, "reply_time") and data.reply_time is not None:
            if data.reply_time < 1:
                return 400, {"message": "Reply time must be at least 1 day"}

    # Validate attachments if provided
    if attachments:
        # Validate file count (max 10 attachments)
        if len(attachments) > 10:
            return 400, {"message": "Maximum 10 attachments allowed per service"}

        # Validate each attachment
        for attachment in attachments:
            # Check file size (max 50MB per file)
            if attachment.size > 50 * 1024 * 1024:
                return 400, {
                    "message": (
                        f"File {attachment.name} is too large. " f"Maximum size is 50MB"
                    )
                }

            # Validate file type
            mime_type, _ = mimetypes.guess_type(attachment.name)
            valid_types = {
                "image": ["image/jpeg", "image/png", "image/gif", "image/webp"],
                "video": ["video/mp4", "video/avi", "video/mov", "video/wmv"],
                "audio": ["audio/mp3", "audio/wav", "audio/m4a", "audio/aac"],
                "document": [
                    "application/pdf",
                    "application/msword",
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document",
                    "text/plain",
                ],
            }

            attachment_type = None
            for type_name, mime_types in valid_types.items():
                if mime_type in mime_types:
                    attachment_type = type_name
                    break

            if not attachment_type:
                return 400, {
                    "message": f"Unsupported file type for {attachment.name}. "
                    f"Supported types: images, videos, audio, documents"
                }

    # Use atomic transaction for all database operations
    try:
        with transaction.atomic():
            # Double-check for race conditions on restricted service types
            if data.service_type in restricted_service_types:
                existing_service = (
                    ServiceItem.objects.select_for_update()
                    .filter(
                        creator=profile,
                        community=community,
                        service_type=data.service_type,
                    )
                    .first()
                )

                if existing_service:
                    service_type_labels = {
                        "dm": "Direct Message",
                        "live_chat": "Live Chat",
                        "audio_call": "Audio Call",
                        "video_call": "Video Call",
                    }
                    service_label = service_type_labels.get(
                        data.service_type, data.service_type
                    )
                    return 400, {
                        "message": (
                            f"You already have a {service_label} service in this "
                            f"community.Only one service of this type is allowed"
                            f"per community."
                        )
                    }

            # Prepare service creation data
            service_data = {
                "creator": profile,
                "community": community,
                "preview_image": preview_image if preview_image else None,
                "service_type": data.service_type,
                "name": data.name,
                "description": data.description,
                "price": Decimal(str(data.price)),
                "attachments_required": data.attachments_required,
                "duration_minutes": data.duration_minutes,
                "is_duration_based": data.is_duration_based,
                "is_broadcasted": data.is_broadcasted,
                "status": data.status,
            }

            # Add DM-specific fields if service type is dm
            if data.service_type == "dm":
                if (
                    hasattr(data, "max_messages_a_day")
                    and data.max_messages_a_day is not None
                ):
                    service_data["max_messages_a_day"] = data.max_messages_a_day

                if hasattr(data, "reply_time") and data.reply_time is not None:
                    service_data["reply_time"] = data.reply_time

            # Create the service
            service = ServiceItem.objects.create(**service_data)

            # if broadcasted, create a timeline item
            if service.is_broadcasted:
                TimelineItem.objects.create(
                    chat=None,  # No chat for broadcasted services
                    sender=profile,
                    service_item=service,
                    community=community,
                    item_type="service",
                )

            # Create attachments if provided
            attachments_data = []
            if attachments:
                for index, attachment in enumerate(attachments):
                    # Determine attachment type based on MIME type
                    mime_type, _ = mimetypes.guess_type(attachment.name)

                    if mime_type:
                        if mime_type.startswith("image/"):
                            attachment_type = "image"
                        elif mime_type.startswith("video/"):
                            attachment_type = "video"
                        elif mime_type.startswith("audio/"):
                            attachment_type = "audio"
                        else:
                            attachment_type = "document"
                    else:
                        attachment_type = "document"  # Default fallback

                    # Create service attachment
                    service_attachment = ServiceAttachment.objects.create(
                        service=service,
                        attachment_type=attachment_type,
                        file=attachment,
                        title=f"Attachment {index + 1}",  # Default title
                        display_order=index,
                    )

                    attachments_data.append(
                        {
                            "id": str(service_attachment.id),
                            "attachment_type": service_attachment.attachment_type,
                            "file_name": service_attachment.file_name,
                            "file_size": service_attachment.file_size,
                            "title": service_attachment.title,
                            "description": service_attachment.description,
                            "display_order": service_attachment.display_order,
                            "file_url": (
                                service_attachment.file.url
                                if service_attachment.file
                                else None
                            ),
                        }
                    )

            # Build response data
            response_data = {
                "id": str(service.id),
                "creator_id": service.creator.id,
                "creator_username": service.creator.username,
                "creator_display_name": service.creator.display_name,
                "community_id": service.community.id,
                "community_name": service.community.name,
                "service_type": service.service_type,
                "name": service.name,
                "description": service.description,
                "price": float(service.price),
                "duration_minutes": service.duration_minutes,
                "is_duration_based": service.is_duration_based,
                "status": service.status,
                "is_available": service.is_available,
                "total_purchases": service.total_purchases,
                "total_revenue": float(service.total_revenue),
                "is_broadcasted": service.is_broadcasted,
                "preview_image": (
                    service.preview_image.url if service.preview_image else None
                ),
                "created_at": service.created_at,
                "updated_at": service.updated_at,
                "attachments": attachments_data,
                "max_messages_a_day": service.max_messages_a_day,
                "reply_time": service.reply_time,
            }

            return 201, {"service": response_data}

    except IntegrityError as e:
        return 400, {"message": f"Database constraint violation: {str(e)}"}
    except Exception:
        # Log the error for debugging
        # logger.error(f"Error creating service: {str(e)}")
        return 400, {"message": "An error occurred while creating the service"}


@router.post(
    "/services/update/{service_id}",
    response={200: ServiceResponseSchema, 400: Message, 403: Message, 404: Message},
    auth=PseudonymousJWTAuth(),
)
def update_service(
    request,
    service_id: str,
    data: UpdateServiceSchema,
    attachments: List[UploadedFile] = File(None),
    preview_image: UploadedFile = File(None),
    replace_attachments: bool = False,
):
    """
    Update an existing service. Only the creator can update their service.

    Optional fields (only provided fields will be updated):
    - name: Service name
    - description: Service description
    - price: Price in credits
    - duration_minutes: Duration for timed services
    - is_duration_based: Whether service has time limit
    - status: Service status
    - is_available: Whether service is available for purchase
    - attachments: List of files to attach to the service
    - replace_attachments: If True, replace all existing attachments. If False, add to
      existing ones.
    """

    profile = request.auth

    # Get the service
    try:
        service = ServiceItem.objects.select_related("creator", "community").get(
            id=service_id
        )
    except ServiceItem.DoesNotExist:
        return 404, {"message": "Service not found"}

    # Check if user is the creator
    if service.creator != profile:
        return 403, {"message": "Only the service creator can update this service"}

    # Validate and update fields
    update_fields = []

    if data.name is not None:
        service.name = data.name
        update_fields.append("name")

    if data.description is not None:
        service.description = data.description
        update_fields.append("description")

    if data.attachments_required is not None:
        print(data.attachments_required)
        service.attachments_required = data.attachments_required
        update_fields.append("attachments_required")

    if data.is_broadcasted is not None:
        service.is_broadcasted = data.is_broadcasted
        update_fields.append("is_broadcasted")
        # If broadcasted, create or update a timeline item
        if service.is_broadcasted:
            TimelineItem.objects.update_or_create(
                chat=None,  # No chat for broadcasted services
                sender=profile,
                service_item=service,
                community=service.community,
                defaults={"item_type": "service"},
            )

    if data.max_messages_a_day is not None:
        if data.max_messages_a_day < 1:
            return 400, {"message": "Max messages per day must be at least 1"}
        service.max_messages_a_day = data.max_messages_a_day
        update_fields.append("max_messages_a_day")

    if data.reply_time is not None:
        if data.reply_time < 1:
            return 400, {"message": "Reply time must be at least 1 day"}
        service.reply_time = data.reply_time
        update_fields.append("reply_time")

    if preview_image:
        service.preview_image = preview_image
        update_fields.append("preview_image")

    if data.price is not None:
        service.price = Decimal(str(data.price))
        update_fields.append("price")

    if data.duration_minutes is not None:
        service.duration_minutes = data.duration_minutes
        update_fields.append("duration_minutes")

    if data.is_duration_based is not None:
        service.is_duration_based = data.is_duration_based
        update_fields.append("is_duration_based")

    if data.status is not None:
        valid_statuses = [choice[0] for choice in ServiceItem.STATUS_CHOICES]
        if data.status not in valid_statuses:
            return 400, {
                "message": (
                    f"Invalid status. Valid statuses: {', '.join(valid_statuses)}"
                )
            }
        service.status = data.status
        update_fields.append("status")

    if data.is_available is not None:
        service.is_available = data.is_available
        update_fields.append("is_available")

    # Save if there are changes
    if update_fields:
        update_fields.append("updated_at")
        service.save(update_fields=update_fields)

    # Handle attachments if provided
    if attachments:
        # Validate attachments
        existing_attachments_count = service.attachments.count()
        new_attachments_count = len(attachments)

        if replace_attachments:
            total_attachments = new_attachments_count
        else:
            total_attachments = existing_attachments_count + new_attachments_count

        # Check total attachment limit
        if total_attachments > 10:
            return 400, {"message": "Maximum 10 attachments allowed per service"}

        # Validate each new attachment
        for attachment in attachments:
            # Check file size (max 50MB per file)
            if attachment.size > 50 * 1024 * 1024:
                return 400, {
                    "message": (
                        f"File {attachment.name} is too large. " f"Maximum size is 50MB"
                    )
                }

            # Validate file type
            mime_type, _ = mimetypes.guess_type(attachment.name)
            valid_types = {
                "image": ["image/jpeg", "image/png", "image/gif", "image/webp"],
                "video": ["video/mp4", "video/avi", "video/mov", "video/wmv"],
                "audio": ["audio/mp3", "audio/wav", "audio/m4a", "audio/aac"],
                "document": [
                    "application/pdf",
                    "application/msword",
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document",
                    "text/plain",
                ],
            }

            attachment_type = None
            for type_name, mime_types in valid_types.items():
                if mime_type in mime_types:
                    attachment_type = type_name
                    break

            if not attachment_type:
                return 400, {
                    "message": f"Unsupported file type for {attachment.name}. "
                    f"Supported types: images, videos, audio, documents"
                }

        # Replace or add attachments
        if replace_attachments:
            # Delete all existing attachments
            service.attachments.all().delete()
            start_order = 0
        else:
            # Get the highest display order for new attachments
            last_attachment = service.attachments.order_by("-display_order").first()
            start_order = (last_attachment.display_order + 1) if last_attachment else 0

        # Create new attachments
        for index, attachment in enumerate(attachments):
            # Determine attachment type based on MIME type
            mime_type, _ = mimetypes.guess_type(attachment.name)

            if mime_type:
                if mime_type.startswith("image/"):
                    attachment_type = "image"
                elif mime_type.startswith("video/"):
                    attachment_type = "video"
                elif mime_type.startswith("audio/"):
                    attachment_type = "audio"
                else:
                    attachment_type = "document"
            else:
                attachment_type = "document"  # Default fallback

            # Create service attachment
            ServiceAttachment.objects.create(
                service=service,
                attachment_type=attachment_type,
                file=attachment,
                title=f"Attachment {start_order + index + 1}",  # Default title
                display_order=start_order + index,
            )

    # Build response with all attachments (existing + new)
    attachments_data = []
    for attachment in service.attachments.all():
        attachments_data.append(
            {
                "id": str(attachment.id),
                "attachment_type": attachment.attachment_type,
                "file_name": attachment.file_name,
                "file_size": attachment.file_size,
                "title": attachment.title,
                "description": attachment.description,
                "display_order": attachment.display_order,
                "file_url": attachment.file.url if attachment.file else None,
            }
        )

    service_data = {
        "id": str(service.id),
        "creator_id": service.creator.id,
        "creator_username": service.creator.username,
        "creator_display_name": service.creator.display_name,
        "community_id": service.community.id,
        "community_name": service.community.name,
        "service_type": service.service_type,
        "name": service.name,
        "description": service.description,
        "price": float(service.price),
        "duration_minutes": service.duration_minutes,
        "is_duration_based": service.is_duration_based,
        "status": service.status,
        "is_available": service.is_available,
        "total_purchases": service.total_purchases,
        "total_revenue": float(service.total_revenue),
        "is_broadcasted": service.is_broadcasted,
        "preview_image": service.preview_image.url if service.preview_image else None,
        "created_at": service.created_at,
        "updated_at": service.updated_at,
        "attachments": attachments_data,
    }

    return {"service": service_data}


@router.delete(
    "/services/{service_id}",
    response={200: Message, 403: Message, 404: Message},
    auth=PseudonymousJWTAuth(),
)
def delete_service(request, service_id: str):
    """
    Delete a service. Only the creator can delete their service.

    This will permanently delete the service and all its attachments.
    Consider setting status to 'inactive' instead if you want to preserve data.
    """

    profile = request.auth

    # Get the service
    try:
        service = ServiceItem.objects.get(id=service_id)
    except ServiceItem.DoesNotExist:
        return 404, {"message": "Service not found"}

    # Check if user is the creator
    if service.creator != profile:
        return 403, {"message": "Only the service creator can delete this service"}

    # Store service name for response
    service_name = service.name

    # Delete the service (this will cascade delete attachments)
    service.delete()

    return {"message": f"Service '{service_name}' has been successfully deleted"}


@router.get(
    "/services/{service_id}",
    response={200: ServiceResponseSchema, 404: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def get_service(request, service_id: str):
    """
    Get a single service by ID with all details and attachments.
    """

    try:
        service = (
            ServiceItem.objects.select_related("creator", "community")
            .prefetch_related("attachments")
            .get(id=service_id)
        )
    except ServiceItem.DoesNotExist:
        return 404, {"message": "Service not found"}

    # Build attachments list
    attachments_data = []
    for attachment in service.attachments.all():
        attachments_data.append(
            {
                "id": str(attachment.id),
                "attachment_type": attachment.attachment_type,
                "file_name": attachment.file_name,
                "file_size": attachment.file_size,
                "title": attachment.title,
                "description": attachment.description,
                "display_order": attachment.display_order,
                "file_url": attachment.file.url if attachment.file else None,
            }
        )

    service_data = {
        "id": str(service.id),
        "creator_id": service.creator.id,
        "creator_username": service.creator.username,
        "creator_display_name": service.creator.display_name,
        "community_id": service.community.id,
        "community_name": service.community.name,
        "service_type": service.service_type,
        "name": service.name,
        "description": service.description,
        "price": float(service.price),
        "duration_minutes": service.duration_minutes,
        "is_duration_based": service.is_duration_based,
        "status": service.status,
        "is_available": service.is_available,
        "total_purchases": service.total_purchases,
        "total_revenue": float(service.total_revenue),
        "is_broadcasted": service.is_broadcasted,
        "preview_image": service.preview_image.url if service.preview_image else None,
        "created_at": service.created_at,
        "updated_at": service.updated_at,
        "attachments": attachments_data,
    }

    return {"service": service_data}


# broadcast a service to all users in a community
@router.post(
    "/services/{service_id}/broadcast/{action}",
    response={200: Message, 403: Message, 404: Message},
    auth=PseudonymousJWTAuth(),
)
def broadcast_service(request, service_id: str, action: str):
    """
    Broadcast a service to all users in the community.
    Only moderators can broadcast services.
    """

    profile = request.auth

    # Get the service
    try:
        service = ServiceItem.objects.get(id=service_id)
    except ServiceItem.DoesNotExist:
        return 404, {"message": "Service not found"}

    # Check if user is a moderator of the service's community
    try:
        CommunityMembership.objects.get(
            community=service.community, profile=profile, role="moderator"
        )
    except CommunityMembership.DoesNotExist:
        return 403, {"message": "Only moderators can broadcast services"}

    # Use atomic transaction to ensure both operations succeed or fail together
    with transaction.atomic():
        if action == "unbroadcast":
            # Check if service is already unbroadcasted
            if not service.is_broadcasted:
                return 400, {"message": "Service is not currently broadcasted"}

            # Update service broadcast status
            service.is_broadcasted = False
            service.save(update_fields=["is_broadcasted"])

            # Delete existing timeline items for this service
            TimelineItem.objects.filter(service=service).delete()

            return {
                "message": f"Service '{service.name}' has been successfully "
                f"unbroadcasted"
            }

        elif action != "broadcast":
            return 400, {"message": "Invalid action. Use 'broadcast' or 'unbroadcast'"}

        # Update service broadcast status
        service.is_broadcasted = True
        service.save(update_fields=["is_broadcasted"])

        # create a timeline item for the service
        TimelineItem.objects.create(
            community=service.community,
            creator=profile,
            service=service,
        )

    return {"message": f"Service '{service.name}' has been successfully broadcasted"}
