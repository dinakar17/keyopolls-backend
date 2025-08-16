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
    ServiceItemSchema,
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
from keyopolls.profile.models import PseudonymousProfile

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
    - community_id: Filter by community ID
    - community_slug: Filter by community slug
    - creator_id: Filter by service creator
    - service_type: Filter by single service type (dm, live_chat, audio_call,
      video_call, custom, community_post, group_*)
    - service_types: String of comma-separated service types for multiple filtering
    - is_broadcasted: Filter by broadcast status (true/false)
    - status: Filter by status (active, inactive, draft)
    - page: Page number (default: 1)
    - per_page: Items per page (default: 20, max: 100)
    """

    profile = request.auth if isinstance(request.auth, PseudonymousProfile) else None

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

    if filters.is_broadcasted is not None:
        queryset = queryset.filter(is_broadcasted=filters.is_broadcasted)

    # Handle service_type (single type filter)
    if filters.service_type:
        # Validate service type
        valid_types = [choice[0] for choice in ServiceItem.SERVICE_TYPES]
        if filters.service_type not in valid_types:
            return 400, {
                "message": (
                    f"Invalid service_type: {filters.service_type}. "
                    f"Valid types: {', '.join(valid_types)}"
                )
            }
        queryset = queryset.filter(service_type=filters.service_type)

    # Handle service_types (comma-separated string of multiple types)
    elif filters.service_types:
        # Parse comma-separated string into list
        service_types_list = [
            s.strip() for s in filters.service_types.split(",") if s.strip()
        ]

        if service_types_list:
            # Map service_types to actual filtering logic
            service_type_conditions = Q()

            for service_type in service_types_list:
                if service_type == "dm":
                    service_type_conditions |= Q(service_type="dm")
                elif service_type == "live_chat":
                    service_type_conditions |= Q(service_type="live_chat")
                elif service_type == "audio_call":
                    service_type_conditions |= Q(service_type="audio_call")
                elif service_type == "video_call":
                    service_type_conditions |= Q(service_type="video_call")
                elif service_type == "custom":
                    service_type_conditions |= Q(service_type="custom")
                elif service_type == "community_post":
                    service_type_conditions |= Q(service_type="community_post")
                elif service_type == "group_chat":
                    service_type_conditions |= Q(service_type="group_chat")
                elif service_type == "group_audio_call":
                    service_type_conditions |= Q(service_type="group_audio_call")
                elif service_type == "group_video_call":
                    service_type_conditions |= Q(service_type="group_video_call")
                # Legacy support for frontend filters
                elif service_type == "custom_services":
                    service_type_conditions |= Q(service_type="custom")
                elif service_type == "community_posts":
                    service_type_conditions |= Q(service_type="community_post")
                else:
                    return 400, {
                        "message": (
                            f"Invalid service_type in service_types: {service_type}. "
                            f"Valid types: dm, live_chat, audio_call, video_call, "
                            f"custom, community_post, group_chat, group_audio_call, "
                            f"group_video_call"
                        )
                    }

            if service_type_conditions:
                queryset = queryset.filter(service_type_conditions)

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

    # Order by created_at descending (newest first)
    queryset = queryset.order_by("-created_at")

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

    # Use the resolve method instead of manual data building
    services_data = ServiceItemSchema.resolve_list(page_obj.object_list, profile)

    return {
        "services": services_data,
        "total_count": total_count,
        "page": filters.page,
        "per_page": filters.per_page,
        "total_pages": paginator.num_pages,
        "has_next": page_obj.has_next(),
        "has_previous": page_obj.has_previous(),
    }


@router.get(
    "/services/{service_id}",
    response={200: ServiceResponseSchema, 404: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def get_service(request, service_id: str):
    """
    Get a single service by ID with all details and attachments.
    """

    profile = request.auth

    try:
        service = (
            ServiceItem.objects.select_related("creator", "community")
            .prefetch_related("attachments")
            .get(id=service_id)
        )
    except ServiceItem.DoesNotExist:
        return 404, {"message": "Service not found"}

    # Use the resolve method for consistent data structure
    service_data = ServiceItemSchema.resolve_details(service, profile)

    return {"service": service_data}


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
    - community_slug: Slug of the community
    - service_type: Type of service (dm, live_chat, audio_call, video_call, custom,
    community_post, group_*)
    - name: Service name
    - description: Service description
    - price: Price in credits (minimum 0.00, 0 for free services)

    Optional fields:
    - duration_minutes: Duration for timed services (default: 10)
    - is_duration_based: Whether service has time limit (default: False)
    - status: Service status (default: active)
    - attachments: List of files to attach to the service
    - max_messages_a_day: For DM and custom services, max messages per day
    - reply_time: For DM and custom services, reply time in days
    - attachments_required: For custom services (always True), for community_post
    (always False)

    Service creation limits:
    - dm, live_chat, audio_call, video_call, group_*: Only one of each type per
    community per creator
    - custom, community_post: Multiple services allowed per community per creator

    Auto-broadcast rules:
    - community_post, group_*: Always broadcasted
    - Others: Not broadcasted
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
            "message": f"Invalid status. Valid statuses: {', '.join(valid_statuses)}"
        }

    # Validate price (allow free services)
    if data.price < 0:
        return 400, {"message": "Price cannot be negative"}

    # Check for duplicate service type restrictions
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
                "group_chat": "Group Chat",
                "group_audio_call": "Group Audio Call",
                "group_video_call": "Group Video Call",
            }
            service_label = service_type_labels.get(
                data.service_type, data.service_type
            )
            return 400, {
                "message": (
                    f"You already have a {service_label} service in this "
                    f"community. Only one service of this type is allowed "
                    f"per community."
                )
            }

    # Validate and set attachments_required based on service type
    if data.service_type == "custom":
        attachments_required = True
    elif data.service_type == "community_post":
        attachments_required = False
    else:
        attachments_required = getattr(data, "attachments_required", False)

    # Determine if service should be auto-broadcasted
    auto_broadcast_types = [
        "community_post",
        "group_chat",
        "group_audio_call",
        "group_video_call",
    ]
    is_broadcasted = data.service_type in auto_broadcast_types

    # Validate DM-specific fields
    if data.service_type == "dm":
        if hasattr(data, "max_messages_a_day") and data.max_messages_a_day is not None:
            if data.max_messages_a_day < 1:
                return 400, {"message": "Max messages per day must be at least 1"}

        if hasattr(data, "reply_time") and data.reply_time is not None:
            if data.reply_time < 1:
                return 400, {"message": "Reply time must be at least 1 day"}

    # Validate custom service fields
    if data.service_type == "custom":
        if hasattr(data, "max_messages_a_day") and data.max_messages_a_day is not None:
            if data.max_messages_a_day < 1:
                return 400, {
                    "message": "Max custom service requests per day must be at least 1"
                }

        if hasattr(data, "reply_time") and data.reply_time is not None:
            if data.reply_time < 1:
                return 400, {
                    "message": "Custom service delivery time must be at least 1 day"
                }

    # Validate attachments if provided
    if attachments:
        if len(attachments) > 10:
            return 400, {"message": "Maximum 10 attachments allowed per service"}

        for attachment in attachments:
            if attachment.size > 50 * 1024 * 1024:
                return 400, {
                    "message": (
                        f"File {attachment.name} is too large. Maximum size is 50MB"
                    )
                }

            mime_type, _ = mimetypes.guess_type(attachment.name)
            valid_types = {
                "image": ["image/jpeg", "image/png", "image/gif", "image/webp"],
                "video": ["video/mp4", "video/avi", "video/mov", "video/wmv"],
                "audio": ["audio/mp3", "audio/wav", "audio/m4a", "audio/aac"],
                "document": [
                    "application/pdf",
                    "application/msword",
                    "application/vnd.openxmlformats-"
                    "officedocument.wordprocessingml.document",
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
                        "group_chat": "Group Chat",
                        "group_audio_call": "Group Audio Call",
                        "group_video_call": "Group Video Call",
                    }
                    service_label = service_type_labels.get(
                        data.service_type, data.service_type
                    )
                    return 400, {
                        "message": (
                            f"You already have a {service_label} service in this "
                            f"community. Only one service of this type is allowed "
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
                "attachments_required": attachments_required,
                "duration_minutes": data.duration_minutes,
                "is_duration_based": data.is_duration_based,
                "is_broadcasted": is_broadcasted,
                "status": data.status,
            }

            # Add DM-specific fields
            if data.service_type == "dm":
                if (
                    hasattr(data, "max_messages_a_day")
                    and data.max_messages_a_day is not None
                ):
                    service_data["max_messages_a_day"] = data.max_messages_a_day
                if hasattr(data, "reply_time") and data.reply_time is not None:
                    service_data["reply_time"] = data.reply_time

            # Add custom service fields
            if data.service_type == "custom":
                if (
                    hasattr(data, "max_messages_a_day")
                    and data.max_messages_a_day is not None
                ):
                    service_data["max_messages_a_day"] = data.max_messages_a_day
                if hasattr(data, "reply_time") and data.reply_time is not None:
                    service_data["reply_time"] = data.reply_time

            # Create the service
            service = ServiceItem.objects.create(**service_data)

            # If broadcasted, create a timeline item
            if service.is_broadcasted:
                TimelineItem.objects.create(
                    chat=None,
                    sender=profile,
                    service_item=service,
                    community=community,
                    item_type="service",
                )

            # Create attachments if provided
            if attachments:
                for index, attachment in enumerate(attachments):
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
                        attachment_type = "document"

                    ServiceAttachment.objects.create(
                        service=service,
                        attachment_type=attachment_type,
                        file=attachment,
                        title=f"Attachment {index + 1}",
                        display_order=index,
                    )

            # Use the resolve method for consistent response
            response_data = ServiceItemSchema.resolve_details(service, profile)

            return 201, {"service": response_data}

    except IntegrityError as e:
        return 400, {"message": f"Database constraint violation: {str(e)}"}
    except Exception:
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
    - attachments_required: Whether service requires user attachments
    - max_messages_a_day: For DM and custom services
    - reply_time: For DM and custom services
    - attachments: List of files to attach to the service
    - replace_attachments: If True, replace all existing attachments. If False,
    add to existing ones.
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

    # Handle attachments_required based on service type
    if data.attachments_required is not None:
        if service.service_type == "custom":
            # Custom services always require attachments
            service.attachments_required = True
        elif service.service_type == "community_post":
            # Community posts never require attachments
            service.attachments_required = False
        else:
            service.attachments_required = data.attachments_required
        update_fields.append("attachments_required")

    # Handle auto-broadcasting logic
    auto_broadcast_types = [
        "community_post",
        "group_chat",
        "group_audio_call",
        "group_video_call",
    ]
    if service.service_type in auto_broadcast_types:
        # These service types are always broadcasted
        if not service.is_broadcasted:
            service.is_broadcasted = True
            update_fields.append("is_broadcasted")
            # Create timeline item
            TimelineItem.objects.update_or_create(
                chat=None,
                sender=profile,
                service_item=service,
                community=service.community,
                defaults={"item_type": "service"},
            )

    if data.max_messages_a_day is not None:
        if service.service_type in ["dm", "custom"]:
            if data.max_messages_a_day < 1:
                return 400, {"message": "Max messages per day must be at least 1"}
            service.max_messages_a_day = data.max_messages_a_day
            update_fields.append("max_messages_a_day")

    if data.reply_time is not None:
        if service.service_type in ["dm", "custom"]:
            if data.reply_time < 1:
                return 400, {"message": "Reply time must be at least 1 day"}
            service.reply_time = data.reply_time
            update_fields.append("reply_time")

    if preview_image:
        service.preview_image = preview_image
        update_fields.append("preview_image")

    if data.price is not None:
        if data.price < 0:
            return 400, {"message": "Price cannot be negative"}
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

        if total_attachments > 10:
            return 400, {"message": "Maximum 10 attachments allowed per service"}

        # Validate each new attachment
        for attachment in attachments:
            if attachment.size > 50 * 1024 * 1024:
                return 400, {
                    "message": (
                        f"File {attachment.name} is too large. Maximum size is 50MB"
                    )
                }

            mime_type, _ = mimetypes.guess_type(attachment.name)
            valid_types = {
                "image": ["image/jpeg", "image/png", "image/gif", "image/webp"],
                "video": ["video/mp4", "video/avi", "video/mov", "video/wmv"],
                "audio": ["audio/mp3", "audio/wav", "audio/m4a", "audio/aac"],
                "document": [
                    "application/pdf",
                    "application/msword",
                    "application/vnd.openxmlformats-"
                    "officedocument.wordprocessingml.document",
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
            service.attachments.all().delete()
            start_order = 0
        else:
            last_attachment = service.attachments.order_by("-display_order").first()
            start_order = (last_attachment.display_order + 1) if last_attachment else 0

        # Create new attachments
        for index, attachment in enumerate(attachments):
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
                attachment_type = "document"

            ServiceAttachment.objects.create(
                service=service,
                attachment_type=attachment_type,
                file=attachment,
                title=f"Attachment {start_order + index + 1}",
                display_order=start_order + index,
            )

    # Refresh the service to get updated data including new attachments
    service.refresh_from_db()

    # Use the resolve method for consistent response
    service_data = ServiceItemSchema.resolve_details(service, profile)

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
