from datetime import datetime
from enum import Enum
from typing import Dict, List, Literal, Optional
from uuid import UUID

from ninja import Schema


class Message(Schema):
    """Schema for a simple message response"""

    message: str


class PaginationSchema(Schema):
    current_page: int
    total_pages: int
    total_count: int
    has_next: bool
    has_previous: bool
    page_size: int
    next_page: Optional[int] = None
    previous_page: Optional[int] = None


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
    order: Optional[int] = None
    created_at: Optional[str] = None


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


# class ImageDetailSchema(ModelSchema):
#     sizes: ImageSizes = None

#     @staticmethod
#     def resolve_sizes(obj):
#         if obj.width and obj.height:
#             return ImageSizes(width=obj.width, height=obj.height)
#         return None

#     class Config:
#         model = UploadedImage
#         model_fields = [
#             "id",
#             "file",
#             "file_name",
#             "alt_text",
#             "content_type",
#             "file_size",
#             "created_at",
#         ]
#         model_fields_optional = ["alt_text"]


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

    POLL = "Poll"
    COMMENT = "GenericComment"
    ARTICLE = "Article"
    POLL_TODO = "PollTodo"


"""
Bookmark Related Schemas
"""


class BookmarkFolderCreateSchema(Schema):
    """Schema for creating a bookmark folder"""

    name: str
    description: Optional[str] = None
    color: Optional[str] = "#3B82F6"  # Default color
    access_level: str = "private"  # private, public, paid
    price: Optional[float] = None  # Only required for paid folders
    is_todo_folder: bool = False  # Default to false
    content_type: Optional[ContentTypeEnum] = (
        None  # Poll, GenericComment, Article, PollTodo
    )
    community_id: Optional[int] = None  # For community folders


class BookmarkFolderQueryParams(Schema):
    """Query parameters for filtering bookmark folders"""

    page: Optional[int] = 1
    page_size: Optional[int] = 20
    access_level: Optional[str] = None  # private, public, paid
    content_type: Optional[str] = None  # Poll, GenericComment, Article, PollTodo
    is_todo_folder: Optional[bool] = None
    search: Optional[str] = None  # Search in name and description
    community_id: Optional[int] = None  # Filter by community ID
    ordering: Optional[str] = (
        "name"  # name, -name, created_at, -created_at, bookmark_count, -bookmark_count
    )


class BookmarkFolderDetailsSchema(Schema):
    """Detailed schema for bookmark folder with all information"""

    id: int
    folder_id: str
    slug: str
    name: str
    description: str
    color: str
    access_level: str
    access_level_display: str
    price: Optional[str] = None
    is_todo_folder: bool
    content_type: Optional[str] = None
    is_private: bool
    is_public: bool
    is_paid: bool
    bookmark_count: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def resolve_details(cls, folder) -> dict:
        """
        Custom method to resolve folder details with computed properties

        Args:
            folder: BookmarkFolder instance

        Returns:
            dict: Resolved folder details
        """
        return {
            "id": folder.id,
            "folder_id": folder.folder_id,
            "slug": folder.slug,
            "name": folder.name,
            "description": folder.description,
            "color": folder.color,
            "access_level": folder.access_level,
            "access_level_display": folder.get_access_level_display(),
            "price": str(folder.price) if folder.price else None,
            "is_todo_folder": folder.is_todo_folder,
            "content_type": folder.content_type,
            "is_private": folder.is_private,
            "is_public": folder.is_public,
            "is_paid": folder.is_paid,
            "bookmark_count": folder.bookmark_count,
            "created_at": folder.created_at,
            "updated_at": folder.updated_at,
        }


class BookmarkFoldersListResponseSchema(Schema):
    """Response schema for paginated bookmark folders list"""

    folders: list[BookmarkFolderDetailsSchema]
    pagination: PaginationSchema


class UpdateBookmarkFolderSchema(Schema):
    """Schema for updating bookmark folder"""

    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None  # Hex color code
    access_level: Optional[str] = None  # private, public, paid
    price: Optional[float] = None  # Only for paid folders
    is_todo_folder: Optional[bool] = None
    # Poll, GenericComment, Article, PollTodo
    content_type: Optional[ContentTypeEnum] = None


class TodoBookmarkStatusSchema(Schema):
    """Schema for checking bookmark status of todos"""

    todo_ids: List[int]

    class Config:
        schema_extra = {"example": {"todo_ids": [1, 2, 3, 4, 5]}}


class TodoBookmarkStatusResponseSchema(Schema):
    """Response schema for todo bookmark status"""

    todo_id: int
    is_bookmarked: bool
    folder_id: Optional[int] = None
    folder_name: Optional[str] = None

    class Config:
        schema_extra = {
            "example": {
                "todo_id": 1,
                "is_bookmarked": True,
                "folder_id": 123,
                "folder_name": "Default PollTodo",
            }
        }


class TodoBookmarkStatusListResponseSchema(Schema):
    """List response schema for todo bookmark statuses"""

    statuses: List[TodoBookmarkStatusResponseSchema]


class ToggleBookmarkSchema(Schema):
    """Schema for toggling bookmark"""

    folder_id: Optional[int] = None
    notes: Optional[str] = ""
    # for poll todo items
    is_todo: Optional[bool] = False
    todo_due_date: Optional[str] = None  # ISO format date string


class ToggleBookmarkResponseSchema(Schema):
    """Response schema for toggling bookmark"""

    bookmarked: bool
    message: str
    bookmark_id: Optional[int] = None


class ProfileType(str, Enum):
    """Enum for profile types"""

    PSEUDONYMOUS = "pseudonymous"


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
