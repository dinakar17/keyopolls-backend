from datetime import datetime
from enum import Enum
from typing import List, Optional

from ninja import Schema

from keyopolls.chats.models import TimelineItem
from keyopolls.chats.models.services import ServiceItem
from keyopolls.profile.models import PseudonymousProfile


class ChatUsersFiltersSchema(Schema):
    search: Optional[str] = None
    community_id: int
    unread_only: Optional[bool] = False
    page: int = 1
    per_page: int = 20


class LastMessageSchema(Schema):
    id: str
    content: Optional[str] = None
    message_type: str  # text, image, video, document, audio, voice_call, video_call
    file_name: Optional[str] = None
    call_duration: Optional[int] = None
    call_status: Optional[str] = None
    created_at: datetime
    is_read: bool
    sender_id: int
    sender_name: str


class ChatUserItemSchema(Schema):
    user_id: int
    username: str
    display_name: str
    headline: Optional[str] = None
    avatar: Optional[str] = None
    is_online: bool
    last_seen: Optional[datetime] = None
    is_mentor: bool
    message_rate: float
    role: str  # moderator

    # Chat specific data (only for authenticated users)
    chat_id: Optional[str] = None
    last_message: Optional[LastMessageSchema] = None
    unread_count: int = 0
    has_chatted: bool = False


class ChatUsersResponseSchema(Schema):
    users: List[ChatUserItemSchema]
    total_count: int
    page: int
    per_page: int
    total_pages: int
    has_next: bool
    has_previous: bool


class CreateChatRequestSchema(Schema):
    mentor_id: int
    community_id: int


class CreateChatResponseSchema(Schema):
    chat_id: str
    mentor_id: int
    mentor_username: str
    mentor_display_name: str
    community_id: int
    created: bool  # True if chat was created, False if it already existed
    message: str


# Service-related schemas


# Request Schemas
class ServiceFiltersSchema(Schema):
    search: Optional[str] = None
    community_id: Optional[int] = None
    community_slug: Optional[str] = None
    creator_id: Optional[int] = None
    service_type: Optional[str] = None
    service_types: Optional[str] = None  # Comma-separated string of service types
    attachments_required: Optional[bool] = None
    status: Optional[str] = None
    is_broadcasted: Optional[bool] = None
    page: int = 1
    per_page: int = 20


class CreateServiceSchema(Schema):
    community_slug: str
    service_type: str
    name: str
    description: str
    price: float
    duration_minutes: int = 10
    is_duration_based: bool = False
    status: str = "active"
    is_broadcasted: bool = False
    # User input required
    attachments_required: bool = False
    # DM Related Settings
    max_messages_a_day: Optional[int] = None
    reply_time: Optional[int] = None  # Expected reply time in days


class UpdateServiceSchema(Schema):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    duration_minutes: Optional[int] = None
    is_duration_based: Optional[bool] = None
    status: Optional[str] = None
    is_available: Optional[bool] = None
    is_broadcasted: Optional[bool] = None
    # User Input Setting
    attachments_required: Optional[bool] = None
    # DM Related Settings
    max_messages_a_day: Optional[int] = None
    reply_time: Optional[int] = None  # Expected reply time in days


# Response Schemas
class ServiceAttachmentSchema(Schema):
    id: str
    attachment_type: str
    file_name: str
    file_size: int
    title: Optional[str] = None
    description: Optional[str] = None
    display_order: int
    file_url: str


# enum type for service_type
class ServiceTypeEnum(str, Enum):
    DM = "dm"
    LIVE_CHAT = "live_chat"
    AUDIO_CALL = "audio_call"
    VIDEO_CALL = "video_call"
    GROUP_CHAT = "group_chat"
    GROUP_AUDIO_CALL = "group_audio_call"
    GROUP_VIDEO_CALL = "group_video_call"
    CUSTOM = "custom"
    COMMUNITY_POST = "community_post"


class ServiceItemSchema(Schema):
    id: str
    creator_id: int
    creator_username: str
    creator_display_name: str
    community_id: int
    community_name: str
    service_type: ServiceTypeEnum
    name: str
    description: str
    price: float
    duration_minutes: int
    is_duration_based: bool
    status: str
    is_available: bool
    is_broadcasted: bool
    preview_image: Optional[str] = None
    total_purchases: int
    total_revenue: float
    created_at: datetime
    updated_at: datetime
    attachments: List[ServiceAttachmentSchema] = []
    # user input setting
    attachments_required: bool = False
    # DM Related Settings
    max_messages_a_day: Optional[int] = None
    reply_time: Optional[int] = None  # Expected reply time in days
    can_edit: Optional[bool] = None  # Whether the user can edit this service

    @classmethod
    def resolve_details(
        cls, service: ServiceItem, profile: Optional[PseudonymousProfile] = None
    ):
        """
        Resolve a ServiceItem instance into a ServiceItemSchema-compatible dict.

        Args:
            service: ServiceItem instance
            profile: Optional user profile for permission-based data access

        Returns:
            dict: Service data ready for schema serialization
        """
        # Build attachments list
        attachments_data = []
        for attachment in service.attachments.all().order_by("display_order"):
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

        # Base service data
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
            "attachments_required": service.attachments_required,
            "preview_image": (
                service.preview_image.url if service.preview_image else None
            ),
            "created_at": service.created_at,
            "updated_at": service.updated_at,
            "attachments": attachments_data,
        }

        # Add DM and custom service specific fields
        if service.service_type in ["dm", "custom"]:
            service_data["max_messages_a_day"] = service.max_messages_a_day
            service_data["reply_time"] = service.reply_time
        else:
            # For consistency, include these fields as null for other service types
            service_data["max_messages_a_day"] = None
            service_data["reply_time"] = None

        # Optional: Add profile-specific data if needed
        if profile:
            # Example: Check if user can edit this service
            service_data["can_edit"] = (
                profile.id == service.creator.id
                or
                # Add additional permission checks here if needed
                False
            )

            # Example: Check if user has purchased this service
            # service_data["has_purchased"] = ServicePurchase.objects.filter(
            #     service=service, purchaser=profile
            # ).exists()

        return service_data

    @classmethod
    def resolve_list(
        cls, services: List[ServiceItem], profile: Optional[PseudonymousProfile] = None
    ):
        """
        Resolve a list of ServiceItem instances into ServiceItemSchema-compatible dicts.

        Args:
            services: QuerySet or list of ServiceItem instances
            profile: Optional user profile for permission-based data access

        Returns:
            list: List of service data dicts ready for schema serialization
        """
        return [cls.resolve_details(service, profile) for service in services]

    @classmethod
    def resolve_with_prefetch(
        cls, service: ServiceItem, profile: Optional[PseudonymousProfile] = None
    ):
        """
        Resolve a ServiceItem with prefetched relationships for better performance.
        Use this when you have already prefetched the necessary relationships.

        Args:
            service: ServiceItem instance with prefetched relationships
            profile: Optional user profile for permission-based data access

        Returns:
            dict: Service data ready for schema serialization
        """
        # Build attachments list from prefetched data
        attachments_data = []
        # Use prefetched_related data to avoid additional queries
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

        # Sort attachments by display_order in Python to avoid additional DB query
        attachments_data.sort(key=lambda x: x["display_order"])

        # Base service data using prefetched relationships
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
            "attachments_required": service.attachments_required,
            "preview_image": (
                service.preview_image.url if service.preview_image else None
            ),
            "created_at": service.created_at,
            "updated_at": service.updated_at,
            "attachments": attachments_data,
        }

        # Add DM and custom service specific fields
        if service.service_type in ["dm", "custom"]:
            service_data["max_messages_a_day"] = service.max_messages_a_day
            service_data["reply_time"] = service.reply_time
        else:
            service_data["max_messages_a_day"] = None
            service_data["reply_time"] = None

        # Optional: Add profile-specific data if needed
        if profile:
            service_data["can_edit"] = profile.id == service.creator.id or False

        return service_data


class ServicesListResponseSchema(Schema):
    services: List[ServiceItemSchema]
    total_count: int
    page: int
    per_page: int
    total_pages: int
    has_next: bool
    has_previous: bool


class ServiceResponseSchema(Schema):
    service: ServiceItemSchema


# Message-related schemas
# Request Schemas
class TimelineFiltersSchema(Schema):
    chat_id: Optional[str] = None
    community_id: Optional[int] = None
    sender_id: Optional[int] = None
    item_type: Optional[str] = None
    include_broadcasts: bool = True
    page: int = 1
    per_page: int = 20


class CreateTimelineItemSchema(Schema):
    chat_id: Optional[str] = None
    community_id: Optional[int] = None
    community_slug: Optional[str] = None
    service_item_id: Optional[str] = None
    item_type: str
    content: Optional[str] = None
    call_duration: Optional[int] = None
    call_status: Optional[str] = None


class UpdateTimelineItemSchema(Schema):
    content: Optional[str] = None
    is_read: Optional[bool] = None
    call_duration: Optional[int] = None
    call_status: Optional[str] = None


# Response Schemas
class MentorDetailsSchema(Schema):
    id: int
    username: str
    display_name: str
    avatar: Optional[str] = None
    is_online: bool
    last_seen: Optional[datetime] = None


class TimelineItemAttachmentSchema(Schema):
    id: str
    attachment_type: str
    file_name: str
    file_size: int
    display_order: int
    file_url: str


class TimelineItemSchema(Schema):
    id: str
    chat_id: Optional[str] = None
    community_id: Optional[int] = None
    sender: MentorDetailsSchema
    service_item: Optional[ServiceItemSchema] = None
    item_type: str
    content: Optional[str] = None
    attachments: List[TimelineItemAttachmentSchema] = []
    call_duration: Optional[int] = None
    call_status: Optional[str] = None
    is_delivered: bool
    is_read: bool
    delivered_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    created_at: datetime
    is_broadcast: bool  # True if chat_id is None

    @classmethod
    def resolve_details(cls, timeline_item: TimelineItem, profile=None):
        """
        Resolve a TimelineItem instance into a TimelineItemSchema-compatible dict.

        Args:
            timeline_item: TimelineItem instance
            profile: Optional user profile for permission-based data access

        Returns:
            dict: Timeline item data ready for schema serialization
        """
        # Build sender details
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

        # Build service item details using ServiceItemSchema if present
        service_data = None
        if timeline_item.service_item:
            # Use ServiceItemSchema for consistent service data structure
            service_data = ServiceItemSchema.resolve_details(
                timeline_item.service_item, profile
            )

        # Build attachments list
        attachments_data = []
        for attachment in timeline_item.attachments.all():
            attachments_data.append(
                {
                    "id": str(attachment.id),
                    "attachment_type": attachment.attachment_type,
                    "file_name": attachment.file_name,
                    "file_size": attachment.file_size,
                    "display_order": attachment.display_order,
                    "file_url": attachment.file.url if attachment.file else None,
                }
            )

        # Sort attachments by display_order
        attachments_data.sort(key=lambda x: x["display_order"])

        # Build main timeline item data
        timeline_data = {
            "id": str(timeline_item.id),
            "chat_id": str(timeline_item.chat.id) if timeline_item.chat else None,
            "community_id": (
                timeline_item.community.id if timeline_item.community else None
            ),
            "sender": sender_data,
            "service_item": service_data,
            "item_type": timeline_item.item_type,
            "content": timeline_item.content,
            "attachments": attachments_data,
            "call_duration": timeline_item.call_duration,
            "call_status": timeline_item.call_status,
            "is_delivered": timeline_item.is_delivered,
            "is_read": timeline_item.is_read,
            "delivered_at": timeline_item.delivered_at,
            "read_at": timeline_item.read_at,
            "created_at": timeline_item.created_at,
            "is_broadcast": timeline_item.chat is None,  # Broadcast if no chat
        }

        # Optional: Add profile-specific data if needed
        if profile:
            # Example: Check if user can delete this timeline item
            timeline_data["can_delete"] = (
                profile.id == timeline_item.sender.id
                or
                # Add additional permission checks here if needed
                False
            )

            # Example: Check if this message is from the current user
            timeline_data["is_own_message"] = profile.id == timeline_item.sender.id

        return timeline_data

    @classmethod
    def resolve_list(cls, timeline_items: list[TimelineItem], profile=None):
        """
        Resolve a list of TimelineItem instances into TimelineItemSchema-compatible
          dicts.

        Args:
            timeline_items: QuerySet or list of TimelineItem instances
            profile: Optional user profile for permission-based data access

        Returns:
            list: List of timeline item data dicts ready for schema serialization
        """
        return [cls.resolve_details(item, profile) for item in timeline_items]

    @classmethod
    def resolve_with_prefetch(cls, timeline_item: TimelineItem, profile=None):
        """
        Resolve a TimelineItem with prefetched relationships for better performance.
        Use this when you have already prefetched the necessary relationships.

        Args:
            timeline_item: TimelineItem instance with prefetched relationships
            profile: Optional user profile for permission-based data access

        Returns:
            dict: Timeline item data ready for schema serialization
        """
        # Build sender details from prefetched data
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

        # Build service item details using ServiceItemSchema if present
        service_data = None
        if timeline_item.service_item:
            # Use the optimized resolve method for prefetched service data
            service_data = ServiceItemSchema.resolve_with_prefetch(
                timeline_item.service_item, profile
            )

        # Build attachments list from prefetched data
        attachments_data = []
        for attachment in timeline_item.attachments.all():
            attachments_data.append(
                {
                    "id": str(attachment.id),
                    "attachment_type": attachment.attachment_type,
                    "file_name": attachment.file_name,
                    "file_size": attachment.file_size,
                    "display_order": attachment.display_order,
                    "file_url": attachment.file.url if attachment.file else None,
                }
            )

        # Sort attachments in Python to avoid additional DB query
        attachments_data.sort(key=lambda x: x["display_order"])

        # Build main timeline item data
        timeline_data = {
            "id": str(timeline_item.id),
            "chat_id": str(timeline_item.chat.id) if timeline_item.chat else None,
            "community_id": (
                timeline_item.community.id if timeline_item.community else None
            ),
            "sender": sender_data,
            "service_item": service_data,
            "item_type": timeline_item.item_type,
            "content": timeline_item.content,
            "attachments": attachments_data,
            "call_duration": timeline_item.call_duration,
            "call_status": timeline_item.call_status,
            "is_delivered": timeline_item.is_delivered,
            "is_read": timeline_item.is_read,
            "delivered_at": timeline_item.delivered_at,
            "read_at": timeline_item.read_at,
            "created_at": timeline_item.created_at,
            "is_broadcast": timeline_item.chat is None,
        }

        # Optional: Add profile-specific data if needed
        if profile:
            timeline_data["can_delete"] = profile.id == timeline_item.sender.id
            timeline_data["is_own_message"] = profile.id == timeline_item.sender.id

        return timeline_data

    @classmethod
    def resolve_basic_details(cls, timeline_item, profile=None):
        """
        Resolve a TimelineItem with minimal service data for lightweight responses.
        Use this when you only need basic service info and want to avoid deep object
        resolution.

        Args:
            timeline_item: TimelineItem instance
            profile: Optional user profile for permission-based data access

        Returns:
            dict: Timeline item data with basic service info
        """
        # Build sender details
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

        # Build minimal service item details if present
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

        # Build attachments list
        attachments_data = []
        for attachment in timeline_item.attachments.all():
            attachments_data.append(
                {
                    "id": str(attachment.id),
                    "attachment_type": attachment.attachment_type,
                    "file_name": attachment.file_name,
                    "file_size": attachment.file_size,
                    "display_order": attachment.display_order,
                    "file_url": attachment.file.url if attachment.file else None,
                }
            )

        return {
            "id": str(timeline_item.id),
            "chat_id": str(timeline_item.chat.id) if timeline_item.chat else None,
            "community_id": (
                timeline_item.community.id if timeline_item.community else None
            ),
            "sender": sender_data,
            "service_item": service_data,
            "item_type": timeline_item.item_type,
            "content": timeline_item.content,
            "attachments": attachments_data,
            "call_duration": timeline_item.call_duration,
            "call_status": timeline_item.call_status,
            "is_delivered": timeline_item.is_delivered,
            "is_read": timeline_item.is_read,
            "delivered_at": timeline_item.delivered_at,
            "read_at": timeline_item.read_at,
            "created_at": timeline_item.created_at,
            "is_broadcast": timeline_item.chat is None,
        }


class TimelineResponseSchema(Schema):
    timeline_items: List[TimelineItemSchema]
    total_count: int
    page: int
    per_page: int
    total_pages: int
    has_next: bool
    has_previous: bool


class TimelineItemResponseSchema(Schema):
    timeline_item: TimelineItemSchema


class MentorDetails(Schema):
    id: int
    username: str
    display_name: str
    avatar: Optional[str] = None
    is_online: bool
    last_seen: Optional[datetime] = None
