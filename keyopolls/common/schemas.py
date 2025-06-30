from datetime import datetime
from enum import Enum
from typing import Dict, Literal, Optional
from uuid import UUID

from keyoconnect.common.models import UploadedImage
from ninja import ModelSchema, Schema


class MediaSchema(Schema):
    """Schema for media attachments"""

    id: int
    media_type: str
    file_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    alt_text: Optional[str] = None
    duration: Optional[float] = None
    order: int
    created_at: str


class LinkSchema(Schema):
    """Schema for link attachments"""

    id: int
    url: str
    display_text: str
    domain: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    is_active: bool
    click_count: int
    created_at: str


class TagSchema(Schema):
    """Schema for tags"""

    id: int
    name: str
    slug: str


"""
Reaction Related Schemas
"""


class ReactionRequest(Schema):
    """Schema for reaction request"""

    reaction_type: Literal["like", "dislike"]


class ReactionResponse(Schema):
    """Schema for reaction response"""

    action: str  # 'added', 'removed', or 'switched'
    counts: Dict[str, int]  # Dictionary of all reaction counts
    object_type: str  # 'post', 'comment', 'article', etc.
    object_id: int
    user_reactions: Dict[str, bool]  # User's reaction status for all types


"""
Image Upload Schemas
"""


class ImageSizes(Schema):
    width: int
    height: int


class UploadResponseSchema(Schema):
    id: UUID
    src: str
    alt: Optional[str] = None
    sizes: ImageSizes
    created_at: datetime


class ImageDetailSchema(ModelSchema):
    sizes: ImageSizes = None

    @staticmethod
    def resolve_sizes(obj):
        if obj.width and obj.height:
            return ImageSizes(width=obj.width, height=obj.height)
        return None

    class Config:
        model = UploadedImage
        model_fields = [
            "id",
            "file",
            "file_name",
            "alt_text",
            "content_type",
            "file_size",
            "created_at",
        ]
        model_fields_optional = ["alt_text"]


class ErrorSchema(Schema):
    message: str
    detail: Optional[str] = None


class DeleteResponseSchema(Schema):
    success: bool
    message: str


class FollowResponse(Schema):
    success: bool
    message: str
    is_following: bool
    follower_count: Optional[int] = None
    following_count: Optional[int] = None


class FollowRequest(Schema):
    action: Literal["follow", "unfollow"]
    profile_type: Literal["public", "professional"]
    profile_id: int


class ContentTypeEnum(str, Enum):
    """Enum for valid content types"""

    POST = "post"
    POST_COMMENT = "post_comment"


"""
Bookmark Related Schemas
"""


class ToggleBookmarkSchema(Schema):
    """Schema for toggling bookmark"""

    folder_id: Optional[int] = None
    notes: Optional[str] = ""


class ToggleBookmarkResponseSchema(Schema):
    """Response schema for toggling bookmark"""

    bookmarked: bool
    message: str
    bookmark_id: Optional[int] = None


"""
Share Related Schemas
"""


class ShareRequestSchema(Schema):
    platform: str
    referrer: Optional[str] = None


class ShareResponseSchema(Schema):
    success: bool
    message: str
    total_shares: int
    already_shared: bool
