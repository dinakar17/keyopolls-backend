from datetime import datetime
from enum import Enum
from typing import List, Optional

from ninja import Schema


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

    class Config:
        schema_extra = {
            "example": {
                "chat_id": "uuid-string",
                "community_id": 123,
                "item_type": "text",
                "include_broadcasts": True,
                "page": 1,
                "per_page": 20,
            }
        }


class CreateTimelineItemSchema(Schema):
    chat_id: Optional[str] = None  # None for broadcast messages
    community_id: Optional[int] = None  # Required for broadcasts
    item_type: str
    content: Optional[str] = None
    service_item_id: Optional[str] = None
    # For calls
    call_duration: Optional[int] = None
    call_status: Optional[str] = None

    class Config:
        schema_extra = {
            "example": {
                "chat_id": "uuid-string",
                "item_type": "text",
                "content": "Hello, this is a message!",
            }
        }


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


class ServiceItemBasicSchema(Schema):
    id: str
    name: str
    service_type: str
    price: float
    duration_minutes: int
    is_duration_based: bool


class TimelineItemSchema(Schema):
    id: str
    chat_id: Optional[str] = None
    community_id: Optional[int] = None
    sender: MentorDetailsSchema
    service_item: Optional[ServiceItemBasicSchema] = None
    item_type: str
    content: Optional[str] = None
    file_url: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    call_duration: Optional[int] = None
    call_status: Optional[str] = None
    is_delivered: bool
    is_read: bool
    delivered_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    created_at: datetime
    is_broadcast: bool  # True if chat_id is None


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
