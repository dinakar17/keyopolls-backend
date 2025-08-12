import mimetypes

from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone
from ninja import File, Query, Router
from ninja.files import UploadedFile

from keyopolls.chats.models import Chat, TimelineItem
from keyopolls.chats.models.services import ServiceItem
from keyopolls.chats.schemas import (
    CreateTimelineItemSchema,
    MentorDetails,
    TimelineFiltersSchema,
    TimelineItemResponseSchema,
    TimelineResponseSchema,
    UpdateTimelineItemSchema,
)
from keyopolls.common.schemas import Message
from keyopolls.communities.models import Community, CommunityMembership
from keyopolls.profile.middleware import OptionalPseudonymousJWTAuth
from keyopolls.profile.models import PseudonymousProfile

router = Router(tags=["Chat Messages"])


@router.get(
    "/mentor/{chat_id}",
    response={200: MentorDetails, 404: Message},
)
def get_mentor_details(request, chat_id: str):
    # Get the chat and its participants
    try:
        chat = Chat.objects.get(id=chat_id)
    except Chat.DoesNotExist:
        return 404, {"message": "Chat not found"}

    # Find the mentor (moderator) in the chat participants
    mentor_details = None
    for participant in [chat.participant_1, chat.participant_2]:
        membership = CommunityMembership.objects.filter(
            community=chat.community, profile=participant, role="moderator"
        ).first()
        if membership:
            mentor_details = MentorDetails(
                id=membership.profile.id,
                username=membership.profile.username,
                display_name=membership.profile.display_name,
                avatar=(
                    membership.profile.avatar.url if membership.profile.avatar else None
                ),
                is_online=membership.profile.is_online,
                last_seen=membership.profile.last_seen,
            )
            break

    return 200, mentor_details


@router.get(
    "/timeline",
    response={200: TimelineResponseSchema, 400: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def get_timeline_items(request, filters: TimelineFiltersSchema = Query(...)):
    """
    Get timeline items (messages) including both chat messages and broadcast messages.

    For chat messages: Requires chat_id, shows messages between two users
    For broadcast messages: Requires community_id, shows creator broadcasts
    mixed with chat messages

    Features:
    - Pagination support
    - Filter by item type, sender, etc.
    - Includes mentor details for each message
    - Mixed timeline of chat + broadcast messages ordered by time

    Query Parameters:
    - chat_id: Get messages for specific chat
    - community_id: Get messages for community (includes broadcasts)
    - sender_id: Filter by message sender
    - item_type: Filter by message type
    - include_broadcasts: Include broadcast messages (default: True)
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
    queryset = TimelineItem.objects.select_related(
        "sender", "chat", "community", "service_item"
    )

    # Apply main filters
    conditions = Q()

    if filters.chat_id:
        # Get messages for specific chat
        try:
            chat = Chat.objects.get(id=filters.chat_id)
            # Ensure user has access to this chat
            if profile and profile not in [chat.participant_1, chat.participant_2]:
                return 400, {"message": "Access denied to this chat"}

            # Chat messages + broadcasts in the same community
            conditions = Q(chat=chat)
            if filters.include_broadcasts and chat.community:
                conditions |= Q(community=chat.community, chat__isnull=True)

        except Chat.DoesNotExist:
            return 400, {"message": "Chat not found"}

    elif filters.community_id:
        # Get messages for community
        try:
            community = Community.objects.get(id=filters.community_id, is_active=True)

            if filters.include_broadcasts:
                # All messages in community (chat + broadcast)
                conditions = Q(community=community)
            else:
                # Only chat messages in community
                conditions = Q(community=community, chat__isnull=False)

        except Community.DoesNotExist:
            return 400, {"message": "Community not found"}
    else:
        return 400, {"message": "Either chat_id or community_id is required"}

    # Apply the main conditions
    queryset = queryset.filter(conditions)

    # Apply additional filters
    if filters.sender_id:
        queryset = queryset.filter(sender_id=filters.sender_id)

    if filters.item_type:
        # Validate item type
        valid_types = [choice[0] for choice in TimelineItem.ITEM_TYPES]
        if filters.item_type in valid_types:
            queryset = queryset.filter(item_type=filters.item_type)
        else:
            return 400, {
                "message": f"Invalid item_type. Valid types: {', '.join(valid_types)}"
            }

    # Order by creation time (most recent first for pagination,
    # but we'll reverse for chat display)
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

    # Build response
    timeline_data = []
    for item in page_obj.object_list:
        # Build sender details
        sender_data = {
            "id": item.sender.id,
            "username": item.sender.username,
            "display_name": item.sender.display_name,
            "avatar": item.sender.avatar.url if item.sender.avatar else None,
            "is_online": item.sender.is_online,
            "last_seen": item.sender.last_seen,
        }

        # Build service item details if present
        service_data = None
        if item.service_item:
            service_data = {
                "id": str(item.service_item.id),
                "name": item.service_item.name,
                "service_type": item.service_item.service_type,
                "price": float(item.service_item.price),
                "duration_minutes": item.service_item.duration_minutes,
                "is_duration_based": item.service_item.is_duration_based,
            }

        timeline_item_data = {
            "id": str(item.id),
            "chat_id": str(item.chat.id) if item.chat else None,
            "community_id": item.community.id if item.community else None,
            "sender": sender_data,
            "service_item": service_data,
            "item_type": item.item_type,
            "content": item.content,
            "file_url": item.file.url if item.file else None,
            "file_name": item.file_name,
            "file_size": item.file_size,
            "call_duration": item.call_duration,
            "call_status": item.call_status,
            "is_delivered": item.is_delivered,
            "is_read": item.is_read,
            "delivered_at": item.delivered_at,
            "read_at": item.read_at,
            "created_at": item.created_at,
            "is_broadcast": item.chat is None,  # Broadcast if no chat
        }
        timeline_data.append(timeline_item_data)

    return {
        "timeline_items": timeline_data,
        "total_count": total_count,
        "page": filters.page,
        "per_page": filters.per_page,
        "total_pages": paginator.num_pages,
        "has_next": page_obj.has_next(),
        "has_previous": page_obj.has_previous(),
    }


@router.post(
    "/timeline",
    response={
        201: TimelineItemResponseSchema,
        400: Message,
        403: Message,
        404: Message,
    },
    auth=OptionalPseudonymousJWTAuth,
)
def create_timeline_item(
    request, data: CreateTimelineItemSchema, file: UploadedFile = File(None)
):
    """
    Create a new timeline item (message).

    For chat messages: Provide chat_id
    For broadcast messages: Provide community_id (moderators only)

    Required fields:
    - item_type: Type of message (text, image, video, document, audio,
      voice_call, video_call, service)

    Optional fields:
    - chat_id: For chat messages
    - community_id: For broadcast messages
    - content: Text content
    - service_item_id: For service-related messages
    - file: File attachment
    - call_duration: For call messages
    - call_status: For call messages
    """

    profile = request.auth if isinstance(request.auth, PseudonymousProfile) else None
    if not profile:
        return 403, {"message": "Authentication required"}

    # Validate item type
    valid_types = [choice[0] for choice in TimelineItem.ITEM_TYPES]
    if data.item_type not in valid_types:
        return 400, {
            "message": f"Invalid item_type. Valid types: {', '.join(valid_types)}"
        }

    chat = None
    community = None

    if data.chat_id:
        # Chat message
        try:
            chat = Chat.objects.get(id=data.chat_id)
            community = chat.community

            # Ensure user is participant in this chat
            if profile not in [chat.participant_1, chat.participant_2]:
                return 403, {"message": "You are not a participant in this chat"}

        except Chat.DoesNotExist:
            return 404, {"message": "Chat not found"}

    elif data.community_id:
        # Broadcast message - only moderators can create
        try:
            community = Community.objects.get(id=data.community_id, is_active=True)

            try:
                CommunityMembership.objects.get(
                    community=community,
                    profile=profile,
                    status="active",
                    role="moderator",
                )
            except CommunityMembership.DoesNotExist:
                return 403, {"message": "Only moderators can create broadcast messages"}

        except Community.DoesNotExist:
            return 404, {"message": "Community not found"}
    else:
        return 400, {"message": "Either chat_id or community_id is required"}

    # Validate service item if provided
    service_item = None
    if data.service_item_id:
        try:
            service_item = ServiceItem.objects.get(id=data.service_item_id)
        except ServiceItem.DoesNotExist:
            return 404, {"message": "Service item not found"}

    # Validate file if provided
    if file:
        # Check file size (max 50MB)
        if file.size > 50 * 1024 * 1024:
            return 400, {"message": "File too large. Maximum size is 50MB"}

        # Validate file type based on item_type
        mime_type, _ = mimetypes.guess_type(file.name)
        if data.item_type == "image" and not (
            mime_type and mime_type.startswith("image/")
        ):
            return 400, {"message": "Invalid file type for image message"}
        elif data.item_type == "video" and not (
            mime_type and mime_type.startswith("video/")
        ):
            return 400, {"message": "Invalid file type for video message"}
        elif data.item_type == "audio" and not (
            mime_type and mime_type.startswith("audio/")
        ):
            return 400, {"message": "Invalid file type for audio message"}

    # Create timeline item
    timeline_item = TimelineItem.objects.create(
        chat=chat,
        community=community,
        sender=profile,
        service_item=service_item,
        item_type=data.item_type,
        content=data.content,
        file=file,
        call_duration=data.call_duration,
        call_status=data.call_status,
    )

    # Build response
    sender_data = {
        "id": timeline_item.sender.id,
        "username": timeline_item.sender.username,
        "display_name": timeline_item.sender.display_name,
        "avatar": (
            timeline_item.sender.avatar.url if timeline_item.sender.avatar else None
        ),
        "is_online": timeline_item.sender.is_online,
        "last_seen": timeline_item.sender.last_seen,
    }

    service_data = None
    if timeline_item.service_item:
        service_data = {
            "id": str(timeline_item.service_item.id),
            "name": timeline_item.service_item.name,
            "service_type": timeline_item.service_item.service_type,
            "price": float(timeline_item.service_item.price),
            "duration_minutes": timeline_item.service_item.duration_minutes,
            "is_duration_based": timeline_item.service_item.is_duration_based,
        }

    timeline_data = {
        "id": str(timeline_item.id),
        "chat_id": str(timeline_item.chat.id) if timeline_item.chat else None,
        "community_id": timeline_item.community.id if timeline_item.community else None,
        "sender": sender_data,
        "service_item": service_data,
        "item_type": timeline_item.item_type,
        "content": timeline_item.content,
        "file_url": timeline_item.file.url if timeline_item.file else None,
        "file_name": timeline_item.file_name,
        "file_size": timeline_item.file_size,
        "call_duration": timeline_item.call_duration,
        "call_status": timeline_item.call_status,
        "is_delivered": timeline_item.is_delivered,
        "is_read": timeline_item.is_read,
        "delivered_at": timeline_item.delivered_at,
        "read_at": timeline_item.read_at,
        "created_at": timeline_item.created_at,
        "is_broadcast": timeline_item.chat is None,
    }

    return 201, {"timeline_item": timeline_data}


@router.put(
    "/timeline/{item_id}",
    response={
        200: TimelineItemResponseSchema,
        400: Message,
        403: Message,
        404: Message,
    },
    auth=OptionalPseudonymousJWTAuth,
)
def update_timeline_item(request, item_id: str, data: UpdateTimelineItemSchema):
    """
    Update an existing timeline item.
    Only the sender can update their own messages.

    Updatable fields:
    - content: Message content (for text messages)
    - is_read: Read status
    - call_duration: For call messages
    - call_status: For call messages
    """

    profile = request.auth if isinstance(request.auth, PseudonymousProfile) else None
    if not profile:
        return 403, {"message": "Authentication required"}

    # Get the timeline item
    try:
        timeline_item = TimelineItem.objects.select_related(
            "sender", "chat", "community", "service_item"
        ).get(id=item_id)
    except TimelineItem.DoesNotExist:
        return 404, {"message": "Timeline item not found"}

    # Check permissions
    can_update = False

    if timeline_item.sender == profile:
        # Sender can update their own messages
        can_update = True
    elif timeline_item.chat and profile in [
        timeline_item.chat.participant_1,
        timeline_item.chat.participant_2,
    ]:
        # Chat participants can update read status
        can_update = True

    if not can_update:
        return 403, {"message": "You don't have permission to update this message"}

    # Update fields
    update_fields = []

    if data.content is not None and timeline_item.sender == profile:
        # Only sender can update content
        timeline_item.content = data.content
        update_fields.append("content")

    if data.is_read is not None:
        timeline_item.is_read = data.is_read
        if data.is_read and not timeline_item.read_at:
            timeline_item.read_at = timezone.now()
            update_fields.append("read_at")
        update_fields.append("is_read")

    if data.call_duration is not None and timeline_item.sender == profile:
        timeline_item.call_duration = data.call_duration
        update_fields.append("call_duration")

    if data.call_status is not None and timeline_item.sender == profile:
        timeline_item.call_status = data.call_status
        update_fields.append("call_status")

    # Save if there are changes
    if update_fields:
        timeline_item.save(update_fields=update_fields)

    # Build response
    sender_data = {
        "id": timeline_item.sender.id,
        "username": timeline_item.sender.username,
        "display_name": timeline_item.sender.display_name,
        "avatar": (
            timeline_item.sender.avatar.url if timeline_item.sender.avatar else None
        ),
        "is_online": timeline_item.sender.is_online,
        "last_seen": timeline_item.sender.last_seen,
    }

    service_data = None
    if timeline_item.service_item:
        service_data = {
            "id": str(timeline_item.service_item.id),
            "name": timeline_item.service_item.name,
            "service_type": timeline_item.service_item.service_type,
            "price": float(timeline_item.service_item.price),
            "duration_minutes": timeline_item.service_item.duration_minutes,
            "is_duration_based": timeline_item.service_item.is_duration_based,
        }

    timeline_data = {
        "id": str(timeline_item.id),
        "chat_id": str(timeline_item.chat.id) if timeline_item.chat else None,
        "community_id": timeline_item.community.id if timeline_item.community else None,
        "sender": sender_data,
        "service_item": service_data,
        "item_type": timeline_item.item_type,
        "content": timeline_item.content,
        "file_url": timeline_item.file.url if timeline_item.file else None,
        "file_name": timeline_item.file_name,
        "file_size": timeline_item.file_size,
        "call_duration": timeline_item.call_duration,
        "call_status": timeline_item.call_status,
        "is_delivered": timeline_item.is_delivered,
        "is_read": timeline_item.is_read,
        "delivered_at": timeline_item.delivered_at,
        "read_at": timeline_item.read_at,
        "created_at": timeline_item.created_at,
        "is_broadcast": timeline_item.chat is None,
    }

    return {"timeline_item": timeline_data}


@router.delete(
    "/timeline/{item_id}",
    response={200: Message, 403: Message, 404: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def delete_timeline_item(request, item_id: str):
    """
    Delete a timeline item.
    Only the sender can delete their own messages.
    """

    profile = request.auth if isinstance(request.auth, PseudonymousProfile) else None
    if not profile:
        return 403, {"message": "Authentication required"}

    # Get the timeline item
    try:
        timeline_item = TimelineItem.objects.get(id=item_id)
    except TimelineItem.DoesNotExist:
        return 404, {"message": "Timeline item not found"}

    # Check if user is the sender
    if timeline_item.sender != profile:
        return 403, {"message": "Only the sender can delete this message"}

    # Store item type for response
    item_type = timeline_item.get_item_type_display()

    # Delete the timeline item
    timeline_item.delete()

    return {"message": f"{item_type} has been successfully deleted"}
