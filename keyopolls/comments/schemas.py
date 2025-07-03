from typing import Any, Dict, List, Optional

from ninja import Field, Schema

from keyopolls.comments.models import GenericComment
from keyopolls.common.models import Reaction
from keyopolls.common.schemas import LinkSchema, MediaSchema
from keyopolls.profile.schemas import AuthorSchema
from keyopolls.utils import get_author_info, get_link_info, get_media_info


class CreateLinkSchema(Schema):
    url: str
    display_text: Optional[str] = None


class CommentCreateSchema(Schema):
    """Schema for comment creation"""

    content: str
    parent_id: Optional[int] = None
    link: Optional[CreateLinkSchema] = None


class CommentUpdateSchema(Schema):
    """Schema for updating a comment"""

    content: str
    link: Optional[CreateLinkSchema] = None


class CommentDeleteSchema(Schema):
    """Schema for deleting a comment"""

    comment_id: int
    message: Optional[str] = None


class CommentOut(Schema):
    """Comment output schema with nested replies limited to depth 6
    and default_collapsed support"""

    # Core comment fields
    id: int
    content: str
    parent_id: Optional[int] = None  # For parent context comments
    created_at: str
    updated_at: str
    is_edited: bool
    like_count: int
    reply_count: int
    depth: int

    # Additional fields
    replies: List["CommentOut"] = Field(default_factory=list)
    user_reactions: Dict[str, bool] = Field(
        default_factory=dict
    )  # Generic reactions dict
    is_author: bool = Field(default=False)
    media: Optional[MediaSchema] = None  # MediaSchema format
    link: Optional[LinkSchema] = None  # LinkSchema format
    is_deleted: bool = Field(default=False)

    # Author information using standardized schema
    author_info: AuthorSchema  # AuthorSchema format

    # Fields for handling truncated replies at depth limit
    has_more_replies: bool = Field(default=False)
    truncated_at_depth: Optional[int] = None

    # New field for low-engagement comments
    default_collapsed: bool = Field(default=False)

    # Computed properties for backward compatibility
    @property
    def has_user_liked(self) -> bool:
        """Backward compatibility property"""
        return self.user_reactions.get("like", False)

    @property
    def has_user_disliked(self) -> bool:
        """Check if user has disliked this comment"""
        return self.user_reactions.get("dislike", False)

    @property
    def has_user_reacted(self) -> bool:
        """Check if user has any reaction on this comment"""
        return any(self.user_reactions.values())

    @staticmethod
    def from_orm_with_replies(
        comment: GenericComment, auth_data: Dict[str, Any], include_replies: bool = True
    ):
        """
        Convert comment ORM instance to schema with optional nested replies

        Args:
            comment: GenericComment instance
            auth_data: Authentication data containing user profile
            include_replies: Whether to include nested replies (default: True)
                           Set to False for parent context comments in thread view
        """

        # Get user reactions for authenticated profile
        user_reactions = {}
        profile = auth_data.get("profile")

        if profile:
            try:
                profile_reactions = Reaction.get_user_reactions_by_profile(
                    profile, comment
                )
                # Use profile reactions directly
                user_reactions = profile_reactions
            except Exception:
                pass

        # Check if user is the author
        is_author = False
        try:
            if profile and comment.profile.id == profile.id:
                is_author = True
        except Exception:
            pass

        # Use get_author_info to get standardized author information
        author_info = get_author_info(
            profile=comment.profile,
        )

        # Get nested replies only if include_replies is True
        replies = []
        has_more_replies = False
        truncated_at_depth = None

        if include_replies:
            try:
                # Check if replies were pre-loaded by our tree building function
                if hasattr(comment, "_nested_replies"):
                    for reply in comment._nested_replies:
                        replies.append(
                            CommentOut.from_orm_with_replies(
                                reply, auth_data, include_replies=True
                            )
                        )
                else:
                    # Fallback: query replies from database (less efficient)
                    # Only get replies up to depth 6 to prevent infinite loading
                    max_depth_to_fetch = 6
                    if comment.depth < max_depth_to_fetch:
                        for reply in comment.replies.filter(
                            is_taken_down=False,
                            is_deleted=False,
                            moderation_status="approved",
                            depth__lte=max_depth_to_fetch,
                        ).order_by("created_at"):
                            replies.append(
                                CommentOut.from_orm_with_replies(
                                    reply, auth_data, include_replies=True
                                )
                            )
            except Exception:
                replies = []

            # Check for metadata about truncated replies
            has_more_replies = getattr(comment, "_has_more_replies", False)
            truncated_at_depth = getattr(comment, "_truncated_at_depth", None)

            # If we don't have the metadata, check if this comment
            # at depth 6 has more replies
            if not has_more_replies and comment.depth == 6:
                try:
                    has_more_replies = comment.replies.filter(
                        is_taken_down=False,
                        is_deleted=False,
                        moderation_status="approved",
                    ).exists()
                    if has_more_replies:
                        truncated_at_depth = 6
                except Exception:
                    pass

        # Determine default_collapsed status
        default_collapsed = getattr(comment, "_default_collapsed", False)

        # Override collapse status: Never collapse comments from the authenticated user
        if is_author:
            default_collapsed = False

        # Override collapse status: Never collapse comments that the user has reacted to
        if user_reactions:
            default_collapsed = False

        # Use helper functions to resolve media and link information
        media_obj = None
        link_obj = None

        try:
            media_instance = comment.media.filter(
                media_type__in=["image", "gif", "video"]
            ).first()
            if media_instance:
                media_obj = get_media_info(media_instance)
        except Exception:
            pass

        try:
            link_instance = comment.links.first()
            if link_instance:
                link_obj = get_link_info(link_instance)
        except Exception:
            pass

        return CommentOut(
            id=comment.id,
            parent_id=comment.parent_id,
            content=comment.content,
            created_at=comment.created_at.isoformat(),
            updated_at=comment.updated_at.isoformat(),
            is_edited=comment.is_edited,
            like_count=comment.like_count,
            reply_count=comment.reply_count,
            depth=comment.depth,
            author_info=author_info,
            media=media_obj,
            link=link_obj,
            replies=replies,
            user_reactions=user_reactions,
            is_author=is_author,
            is_deleted=comment.is_deleted,
            has_more_replies=has_more_replies,
            truncated_at_depth=truncated_at_depth,
            default_collapsed=default_collapsed,
        )


class CommentResponse(Schema):
    """Standard response for comment operations"""

    success: bool
    message: str
    comment_id: Optional[int] = None
    data: CommentOut


class PaginatedCommentResponse(Schema):
    """Paginated response for comment lists"""

    items: List[CommentOut]
    total: int
    page: int
    pages: int
    page_size: int
    has_next: bool
    has_previous: bool
