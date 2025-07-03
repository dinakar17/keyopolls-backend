import logging
from datetime import timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import transaction
from django.db.models import F
from django.http import HttpRequest
from django.utils import timezone
from ninja import Field, File, Router, Schema, UploadedFile
from ninja.errors import ValidationError

from keyopolls.comments.models import GenericComment
from keyopolls.comments.schemas import (
    CommentCreateSchema,
    CommentDeleteSchema,
    CommentOut,
    CommentResponse,
    CommentUpdateSchema,
    PaginatedCommentResponse,
)
from keyopolls.common.schemas import ContentTypeEnum, Message

# Commented out notification imports - will update later
# from keyopolls.connect_notifications.notification_utils import (
#     auto_follow_comment,
#     auto_follow_post,
#     notify_comment_reply,
#     notify_followed_comment_reply,
#     notify_followed_post_comment,
#     notify_post_comment,
#     notify_replies_milestone,
# )
from keyopolls.profile.middleware import (
    OptionalPseudonymousJWTAuth,
    PseudonymousJWTAuth,
)
from keyopolls.utils import (
    create_link_object,
    create_media_object,
    delete_existing_media_and_links,
    get_content_object,
    validate_media_file,
)

logger = logging.getLogger(__name__)

router = Router(tags=["Comments"])


"""
================
CUD operations for Comments
================
"""


@router.post(
    "/{content_type}/{object_id}/comments",
    response={201: CommentResponse, 400: Message, 404: Message},
    auth=PseudonymousJWTAuth(),
)
def create_comment(
    request: HttpRequest,
    content_type: ContentTypeEnum,
    object_id: int,
    data: CommentCreateSchema,
    media_files: List[UploadedFile] = File(None),
):
    """Create a new comment on a content object using pseudonymous profile"""
    profile = request.auth

    if not profile:
        return 400, {"message": "Authentication required"}

    try:
        # Get the content object
        content_obj = get_content_object(content_type, object_id)

        # Get parent comment if provided
        parent = None
        if hasattr(data, "parent_id") and data.parent_id and data.parent_id > 0:
            try:
                parent = GenericComment.objects.get(
                    id=data.parent_id,
                    is_deleted=False,
                    is_taken_down=False,
                    moderation_status="approved",
                )
            except GenericComment.DoesNotExist:
                return 400, {"message": "Parent comment not found or not visible"}

        # Validate media files count (limit to 1 as per model constraints)
        if media_files and len(media_files) > 1:
            return 400, {"message": "Only one media file is allowed per comment"}

        # Validate media file if provided
        if media_files and media_files[0]:
            is_valid, error_message = validate_media_file(media_files[0])
            if not is_valid:
                return 400, {"message": error_message}

        # Use database transaction to ensure data consistency
        with transaction.atomic():
            # Create the comment with pseudonymous profile reference
            comment_data = {
                "content": data.content,
                "profile": profile,
                "parent": parent,
                "content_type": ContentType.objects.get_for_model(content_obj),
                "object_id": content_obj.id,
                "comment_source": content_type.value,
            }

            # Create and save the comment
            comment = GenericComment(**comment_data)
            comment.save()

            # Handle media file upload
            if media_files and media_files[0]:
                create_media_object(comment, media_files[0])

            # Handle link creation
            if hasattr(data, "link") and data.link:
                create_link_object(comment, data.link)

            # Create auth data with profile context
            auth_data = {"profile": profile}

            comment.refresh_from_db()

            # Convert to CommentOut schema
            comment_schema = CommentOut.from_orm_with_replies(
                comment, auth_data, include_replies=True
            )

            # === ALWAYS INCREMENT MAIN CONTENT COMMENT COUNT ===
            # Increment comment count on main content object for ALL comments
            # (direct + replies)
            content_obj.comment_count = F("comment_count") + 1
            content_obj.save(update_fields=["comment_count"])

            # === NOTIFICATION TRIGGERS - COMMENTED OUT FOR NOW ===
            # Will be updated later when notification system is implemented

            # # Determine what we're commenting on
            # if parent:
            #     # This is a reply to a comment

            #     # 1. Reply notification: Notify comment owner about the reply
            #     notify_comment_reply(
            #         parent, comment, profile, send_push=True
            #     )

            #     # 2. Followed comment notification: Notify users following this
            # comment
            #     notify_followed_comment_reply(
            #         parent, comment, profile, send_push=False
            #     )

            #     # 3. Auto-follow the parent comment for future notifications
            #     auto_follow_comment(profile, parent)

            #     # 4. Increment reply count on parent comment
            #     parent.increment_reply_count()

            #     # 5. Check if parent comment reached replies milestone
            #     parent.refresh_from_db()  # Get updated reply_count
            #     notify_replies_milestone(parent, parent.reply_count, send_push=True)

            #     # 6. Also auto-follow the main post for post-level notifications
            #     if hasattr(content_obj, "id"):  # Ensure it's a Post object
            #         auto_follow_post(
            #             profile, content_obj, interaction_type="reply"
            #         )

            # else:
            #     # This is a direct comment on the main content (post)

            #     # 1. Comment notification: Notify post owner about the comment
            #     notify_post_comment(
            #         content_obj, comment, profile, send_push=True
            #     )

            #     # 2. Followed post notification: Notify users following this post
            #     notify_followed_post_comment(
            #         content_obj, comment, profile, send_push=False
            #     )

            #     # 3. Auto-follow the post for future notifications
            #     auto_follow_post(
            #         profile, content_obj, interaction_type="comment"
            #     )

            # # === CHECK FOR POST REPLIES MILESTONE (for both direct comments
            # #  and replies) ===
            # # Refresh to get the updated comment_count after increment
            # if hasattr(content_obj, "comment_count"):
            #     content_obj.refresh_from_db()  # Get the updated comment_count
            #     notify_replies_milestone(
            #         content_obj, content_obj.comment_count, send_push=True
            #     )

            # Update parent reply count if this is a reply
            if parent:
                parent.increment_reply_count()

            # === END NOTIFICATION TRIGGERS ===

        # Return success response
        return 201, {
            "success": True,
            "message": "Comment created successfully",
            "comment_id": comment.id,
            "data": comment_schema,  # Include the full comment data
        }

    except ObjectDoesNotExist as e:
        return 404, {"message": str(e)}
    except ValueError as e:
        return 400, {"message": str(e)}
    except ValidationError as e:
        return 400, {"message": str(e)}
    except Exception as e:
        # Log the error for debugging
        logger.error(f"Error creating comment: {str(e)}", exc_info=True)
        return 400, {"message": "An error occurred while creating the comment"}


@router.post(
    "/comments/{comment_id}",
    response={200: CommentResponse, 400: Message, 403: Message, 404: Message},
    auth=PseudonymousJWTAuth(),
)
def update_comment(
    request: HttpRequest,
    comment_id: int,
    data: CommentUpdateSchema,
    media_files: List[UploadedFile] = File(None),
):
    """Update a comment using pseudonymous profile"""
    profile = request.auth

    if not profile:
        return 400, {"message": "Authentication required"}

    try:
        # Get the comment
        comment = GenericComment.objects.get(
            id=comment_id, is_deleted=False, is_taken_down=False
        )

        # Check if the user is authorized to edit this comment
        if not check_comment_ownership(comment, profile):
            return 403, {"message": "You are not authorized to edit this comment"}

        # Validate media files count (limit to 1 as per model constraints)
        if media_files and len(media_files) > 1:
            return 400, {"message": "Only one media file is allowed per comment"}

        # Validate media file if provided
        if media_files and media_files[0]:
            is_valid, error_message = validate_media_file(media_files[0])
            if not is_valid:
                return 400, {"message": error_message}

        # Validate link URL if provided
        if (
            hasattr(data, "link")
            and data.link
            and not data.link.url.startswith(("http://", "https://"))
        ):
            return 400, {
                "message": "Invalid URL format. Must start with http:// or https://"
            }

        # Use database transaction to ensure data consistency
        with transaction.atomic():
            # Update the comment content
            comment.content = data.content
            comment.is_edited = True
            comment.save()

            # Delete existing media and links
            delete_existing_media_and_links(comment)

            # Add new media file if provided
            if media_files and media_files[0]:
                create_media_object(comment, media_files[0])

            # Add new link if provided
            if hasattr(data, "link") and data.link:
                create_link_object(comment, data.link)

            # Create auth data with profile context
            auth_data = {"profile": profile}

            comment.refresh_from_db()

            # Convert to CommentOut schema
            comment_schema = CommentOut.from_orm_with_replies(
                comment, auth_data, include_replies=True
            )

        return 200, {
            "success": True,
            "message": "Comment updated successfully",
            "comment_id": comment.id,
            "data": comment_schema,
        }

    except GenericComment.DoesNotExist:
        return 404, {"message": "Comment not found"}
    except ValidationError as e:
        return 400, {"message": str(e)}
    except Exception as e:
        # Log the error for debugging
        logger.error(f"Error updating comment {comment_id}: {str(e)}", exc_info=True)
        return 400, {"message": "An error occurred while updating the comment"}


@router.delete(
    "/comments/{comment_id}",
    response={200: CommentDeleteSchema, 400: Message, 403: Message, 404: Message},
    auth=PseudonymousJWTAuth(),
)
def delete_comment(request: HttpRequest, comment_id: int):
    """Delete a comment using pseudonymous profile"""
    profile = request.auth

    if not profile:
        return 400, {"message": "Authentication required"}

    try:
        # Get the comment
        comment = GenericComment.objects.get(id=comment_id, is_deleted=False)

        # Check if the user is authorized to delete this comment
        if not check_comment_ownership(comment, profile):
            return 403, {"message": "You are not authorized to delete this comment"}

        # Soft delete the comment
        comment.is_deleted = True
        comment.save(update_fields=["is_deleted"])

        # Decrement comment count on the main content object
        content_obj = comment.content_object

        if hasattr(content_obj, "comment_count"):
            content_obj.comment_count = F("comment_count") - 1
            content_obj.save(update_fields=["comment_count"])

        return 200, {
            "comment_id": comment.id,
            "message": "Comment deleted successfully",
        }

    except GenericComment.DoesNotExist:
        return 404, {"message": "Comment not found"}
    except Exception as e:
        # Log the error for debugging
        logger.error(f"Error deleting comment {comment_id}: {str(e)}", exc_info=True)
        return 400, {"message": "An error occurred while deleting the comment"}


def check_comment_ownership(comment: GenericComment, profile) -> bool:
    """
    Check if the profile owns the given comment.

    Args:
        comment: The comment to check ownership for
        profile: The authenticated user's pseudonymous profile

    Returns:
        True if the user owns the comment, False otherwise
    """
    try:
        return comment.profile.id == profile.id
    except AttributeError:
        return False


class CommentSortEnum(str, Enum):
    """Enum for comment sorting options"""

    NEWEST = "newest"
    OLDEST = "oldest"
    MOST_LIKED = "most_liked"
    MOST_REPLIES = "most_replies"


class CommentThreadResponse(Schema):
    """Response schema for comment thread with context"""

    focal_comment: CommentOut
    parent_context: List[CommentOut] = Field(default_factory=list)
    thread_info: Dict[str, Any] = Field(default_factory=dict)


# ============================================================================
# MAIN API ENDPOINTS
# ============================================================================


@router.get(
    "/{content_type}/{object_id}/comments",
    response={200: PaginatedCommentResponse, 400: Message, 404: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def get_comments(
    request: HttpRequest,
    content_type: ContentTypeEnum,
    object_id: int,
    page: int = 1,
    page_size: int = 20,
    sort: CommentSortEnum = CommentSortEnum.NEWEST,
):
    """Get paginated top-level comments with nested replies up to depth 6"""
    # Extract authentication info from OptionalPseudonymousJWTAuth
    profile = request.auth

    # Create auth data with profile context
    auth_data = {"profile": profile} if profile else {}

    # Validate parameters
    validation_error = validate_pagination_params(page, page_size)
    if validation_error:
        return 400, {"message": validation_error}

    try:
        # Get content object and top-level comments
        content_obj = get_content_object(content_type, object_id)
        content_type_obj = ContentType.objects.get_for_model(content_obj)

        top_level_comments = get_top_level_comments(content_type_obj, object_id, sort)

        # Paginate top-level comments
        paginator = Paginator(top_level_comments, page_size)
        comments_page = get_page_or_fallback(paginator, page)
        top_level_ids = [comment.id for comment in comments_page]

        # Build comment tree
        comments_tree = build_complete_comment_tree(top_level_ids, max_depth=4)

        # Convert to schema
        comments_data = convert_comments_to_schema(
            comments_tree, top_level_ids, auth_data
        )

        return 200, PaginatedCommentResponse(
            items=comments_data,
            total=paginator.count,
            page=comments_page.number,
            pages=paginator.num_pages,
            page_size=page_size,
            has_next=comments_page.has_next(),
            has_previous=comments_page.has_previous(),
        )

    except ObjectDoesNotExist:
        return 404, {"message": "Content object not found"}
    except Exception as e:
        logger.error(f"Error fetching comments: {str(e)}", exc_info=True)
        return 400, {"message": "An error occurred while fetching comments"}


@router.get(
    "/comments/{comment_id}/thread",
    response={200: CommentThreadResponse, 400: Message, 404: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def get_comment_thread(
    request: HttpRequest, comment_id: int, parent_levels: int = 3, reply_depth: int = 6
):
    """Get a specific comment with parent context and nested replies"""
    # Extract authentication info from OptionalPseudonymousJWTAuth
    profile = request.auth

    # Create auth data with profile context
    auth_data = {"profile": profile} if profile else {}

    # Validate parameters
    if not (0 <= parent_levels <= 5):
        return 400, {"message": "parent_levels must be between 0 and 5"}
    if not (1 <= reply_depth <= 10):
        return 400, {"message": "reply_depth must be between 1 and 10"}

    try:
        # Get focal comment
        focal_comment = get_focal_comment(comment_id)

        # Get parent context
        parent_comments = get_parent_context(focal_comment, parent_levels)

        # Build thread tree from focal comment
        thread_tree = build_thread_from_focal_comment(focal_comment, reply_depth)

        # Convert to schema
        focal_data = CommentOut.from_orm_with_replies(thread_tree, auth_data)
        parent_data = [
            CommentOut.from_orm_with_replies(parent, auth_data, include_replies=False)
            for parent in parent_comments
        ]

        thread_info = {
            "focal_comment_id": focal_comment.id,
            "focal_comment_depth": focal_comment.depth,
            "parent_levels_included": len(parent_data),
            "reply_depth_limit": reply_depth,
            "is_top_level_comment": focal_comment.parent_id is None,
            "original_top_level_id": get_top_level_comment_id(focal_comment),
        }

        return 200, CommentThreadResponse(
            focal_comment=focal_data,
            parent_context=parent_data,
            thread_info=thread_info,
        )

    except GenericComment.DoesNotExist:
        return 404, {"message": "Comment not found"}
    except Exception as e:
        logger.error(
            f"Error fetching comment thread {comment_id}: {str(e)}", exc_info=True
        )
        return 400, {"message": "An error occurred while fetching the comment thread"}


# ============================================================================
# CORE REUSABLE FUNCTIONS
# ============================================================================


def validate_pagination_params(page: int, page_size: int) -> Optional[str]:
    """Validate pagination parameters"""
    if page_size < 1 or page_size > 100:
        return "page_size must be between 1 and 100"
    if page < 1:
        return "page must be greater than 0"
    return None


def get_top_level_comments(content_type_obj, object_id: int, sort: CommentSortEnum):
    """Get top-level comments for a content object with sorting"""
    sort_mapping = {
        CommentSortEnum.NEWEST: "-created_at",
        CommentSortEnum.OLDEST: "created_at",
        CommentSortEnum.MOST_LIKED: "-like_count",
        CommentSortEnum.MOST_REPLIES: "-reply_count",
    }

    return GenericComment.objects.filter(
        content_type=content_type_obj,
        object_id=object_id,
        parent__isnull=True,
        is_taken_down=False,
        moderation_status="approved",
    ).order_by(sort_mapping[sort])


def get_page_or_fallback(paginator, page: int):
    """Get page or fallback to valid page"""
    try:
        return paginator.page(page)
    except PageNotAnInteger:
        return paginator.page(1)
    except EmptyPage:
        return paginator.page(paginator.num_pages)


def get_focal_comment(comment_id: int) -> GenericComment:
    """Get and validate focal comment"""
    return GenericComment.objects.get(
        id=comment_id,
        is_taken_down=False,
        is_deleted=False,
        moderation_status="approved",
    )


def fetch_comments_with_depth_limit(
    root_comment_ids: List[int], max_depth: int
) -> List[GenericComment]:
    """
    Fetch comments and their nested replies up to max_depth
    Works for both top-level comments and focal comment scenarios
    """
    all_comments = []

    # Get root comments
    root_comments = GenericComment.objects.filter(
        id__in=root_comment_ids,
        is_taken_down=False,
        moderation_status="approved",
    )
    all_comments.extend(root_comments)

    # Recursively get replies
    current_parent_ids = root_comment_ids
    current_depth = 0

    while current_parent_ids and current_depth < max_depth:
        replies = GenericComment.objects.filter(
            parent_id__in=current_parent_ids,
            is_taken_down=False,
            moderation_status="approved",
        ).order_by("created_at")

        if not replies:
            break

        all_comments.extend(replies)
        current_parent_ids = [reply.id for reply in replies]
        current_depth += 1

    return all_comments


def calculate_collapse_status(comments: List[GenericComment]) -> List[GenericComment]:
    """Calculate default_collapsed status for comments"""
    now = timezone.now()
    RECENT_THRESHOLD = timedelta(hours=24)
    OLD_THRESHOLD = timedelta(days=7)

    # Group comments by age
    groups = {"recent": [], "medium": [], "old": []}

    for comment in comments:
        age = now - comment.created_at
        if age <= RECENT_THRESHOLD:
            groups["recent"].append(comment)
        elif age <= OLD_THRESHOLD:
            groups["medium"].append(comment)
        else:
            groups["old"].append(comment)

    # Process each group
    process_comment_group(groups["recent"], min_likes=2, percentile_threshold=25)
    process_comment_group(groups["medium"], min_likes=3, percentile_threshold=30)
    process_comment_group(groups["old"], min_likes=5, percentile_threshold=35)

    return comments


def process_comment_group(
    comments: List[GenericComment], min_likes: int, percentile_threshold: int
):
    """Process a group of comments and set collapse status"""
    if not comments:
        return

    like_counts = sorted([comment.like_count for comment in comments])
    percentile_index = int(len(like_counts) * (percentile_threshold / 100))
    percentile_value = (
        like_counts[percentile_index] if percentile_index < len(like_counts) else 0
    )

    for comment in comments:
        should_collapse = (
            comment.like_count < min_likes
            or comment.like_count <= percentile_value
            or (comment.reply_count > 3 and comment.like_count == 0)
            or (
                len(comment.content) > 500
                and comment.like_count == 0
                and comment.reply_count == 0
            )
        )
        comment._default_collapsed = should_collapse


def build_comment_tree(
    comments: List[GenericComment], root_ids: List[int], max_depth: int
) -> Dict[int, GenericComment]:
    """Build tree structure from flat comment list"""
    comments_by_id = {comment.id: comment for comment in comments}
    comments_by_parent = {}

    # Group by parent
    for comment in comments:
        if comment.parent_id and comment.depth <= max_depth:
            if comment.parent_id not in comments_by_parent:
                comments_by_parent[comment.parent_id] = []
            comments_by_parent[comment.parent_id].append(comment)

    def attach_replies(comment, is_focal_tree=False):
        comment_id = comment.id
        if comment_id in comments_by_parent:
            replies = sorted(comments_by_parent[comment_id], key=lambda x: x.created_at)

            processed_replies = []
            for reply in replies:
                attach_replies(reply, is_focal_tree)

                # Check for more replies at depth limit
                if (not is_focal_tree and reply.depth == max_depth) or (
                    is_focal_tree and comment.depth - reply.depth >= max_depth
                ):
                    has_more_replies = GenericComment.objects.filter(
                        parent_id=reply.id,
                        is_taken_down=False,
                        moderation_status="approved",
                    ).exists()

                    reply._has_more_replies = has_more_replies
                    reply._truncated_at_depth = reply.depth

                processed_replies.append(reply)

            comment._nested_replies = processed_replies
        else:
            comment._nested_replies = []

    # Process all root comments
    result = {}
    for root_id in root_ids:
        if root_id in comments_by_id:
            comment = comments_by_id[root_id]
            attach_replies(comment)
            result[root_id] = comment

    return result


def build_complete_comment_tree(
    top_level_ids: List[int], max_depth: int = 6
) -> Dict[int, GenericComment]:
    """Build complete comment tree for top-level comments"""
    all_comments = fetch_comments_with_depth_limit(top_level_ids, max_depth)
    comments_with_status = calculate_collapse_status(all_comments)
    return build_comment_tree(comments_with_status, top_level_ids, max_depth)


def build_thread_from_focal_comment(
    focal_comment: GenericComment, reply_depth: int
) -> GenericComment:
    """Build tree from focal comment as root"""
    all_comments = fetch_comments_with_depth_limit([focal_comment.id], reply_depth)
    comments_with_status = calculate_collapse_status(all_comments)
    tree = build_comment_tree(comments_with_status, [focal_comment.id], reply_depth)
    return tree[focal_comment.id]


def convert_comments_to_schema(
    comments_tree: Dict[int, GenericComment],
    ordered_ids: List[int],
    auth_data: Dict[str, Any],
) -> List[CommentOut]:
    """Convert comment tree to schema objects"""
    result = []
    for comment_id in ordered_ids:
        if comment_id in comments_tree:
            comment_data = CommentOut.from_orm_with_replies(
                comments_tree[comment_id], auth_data
            )
            result.append(comment_data)
    return result


def get_parent_context(
    focal_comment: GenericComment, parent_levels: int
) -> List[GenericComment]:
    """Get parent comments for context"""
    parents = []
    current = focal_comment
    levels = 0

    while current.parent_id and levels < parent_levels:
        try:
            parent = GenericComment.objects.get(
                id=current.parent_id,
                is_taken_down=False,
                moderation_status="approved",
            )
            parents.append(parent)
            current = parent
            levels += 1
        except GenericComment.DoesNotExist:
            break

    return list(reversed(parents))


def get_top_level_comment_id(comment: GenericComment) -> int:
    """Get the original top-level comment ID"""
    current = comment
    while current.parent_id:
        try:
            current = GenericComment.objects.get(id=current.parent_id)
        except GenericComment.DoesNotExist:
            break
    return current.id
