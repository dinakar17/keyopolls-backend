import logging
from enum import Enum
from typing import List, Optional

from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest
from ninja import Field, Router, Schema

from keyopolls.comments.api import (
    CommentSortEnum,
    get_page_or_fallback,
    get_top_level_comment_id,
    validate_pagination_params,
)
from keyopolls.comments.models import GenericComment
from keyopolls.common.models import Reaction
from keyopolls.common.schemas import ContentTypeEnum, Message
from keyopolls.polls.models import Poll
from keyopolls.profile.middleware import (
    OptionalPseudonymousJWTAuth,
    PseudonymousProfile,
)
from keyopolls.profile.schemas import AuthorSchema
from keyopolls.utils import get_author_info, get_content_object

logger = logging.getLogger(__name__)

router = Router(tags=["Search Comments"])


class CommentSearchTypeEnum(str, Enum):
    """Enum for comment search types"""

    ALL = "all"
    CONTENT = "content"
    AUTHOR = "author"
    MEDIA = "media"
    LINKS = "links"


class PollContentSchema(Schema):
    """Schema for poll content when included in comment search results"""

    id: int
    title: str
    description: str
    poll_type: str
    author_info: AuthorSchema
    total_votes: int
    option_count: int


class CommentSearchResultOut(Schema):
    """Flat comment schema for search results - no nested replies"""

    # Core comment fields
    id: int
    content: str
    created_at: str
    updated_at: str
    is_edited: bool
    like_count: int
    reply_count: int
    depth: int

    # Author information
    author_info: AuthorSchema

    # Context information for navigation
    content_type: str
    content_object_id: int
    parent_comment_id: Optional[int] = None
    top_level_comment_id: int

    # Engagement fields
    has_user_liked: bool = Field(default=False)
    is_author: bool = Field(default=False)

    # Media and link info (simplified)
    has_media: bool = Field(default=False)
    media_type: Optional[str] = None
    has_link: bool = Field(default=False)
    link_domain: Optional[str] = None

    # Search relevance
    search_snippet: str = Field(default="")  # Highlighted snippet
    relevance_score: float = Field(default=0.0)

    # Optional poll content
    poll_content: Optional[PollContentSchema] = None


class PaginatedCommentSearchResponse(Schema):
    """Paginated response for comment search results"""

    items: List[CommentSearchResultOut]
    total: int
    page: int
    pages: int
    page_size: int
    has_next: bool
    has_previous: bool
    search_query: Optional[str] = None
    search_type: Optional[str] = None
    profile_filter: Optional[dict] = None
    include_poll_content: bool = Field(default=False)
    total_time_ms: int


@router.get(
    "/comments/search",
    response={200: PaginatedCommentSearchResponse, 400: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def search_comments(
    request: HttpRequest,
    q: Optional[str] = None,  # Search query (optional)
    search_type: CommentSearchTypeEnum = CommentSearchTypeEnum.ALL,
    content_type: Optional[ContentTypeEnum] = None,  # Filter by content type
    object_id: Optional[int] = None,  # Filter by specific object
    profile_id: Optional[int] = None,  # Filter by profile ID
    include_poll_content: bool = False,  # Include poll content in response
    page: int = 1,
    page_size: int = 20,
    sort: CommentSortEnum = CommentSortEnum.NEWEST,
):
    """
    Search comments across the platform or fetch comments by profile

    Args:
        q: Search query string (optional)
        search_type: Type of search (all, content, author, media, links)
        content_type: Optional filter by content type (poll, etc.)
        object_id: Optional filter by specific content object
        profile_id: Optional filter by profile ID (PseudonymousProfile ID)
        include_poll_content: Whether to include poll content in response
        page: Page number
        page_size: Results per page (max 100)
        sort: Sort order for results
    """
    import time

    start_time = time.time()

    # Extract authentication info from OptionalPseudonymousJWTAuth
    profile = request.auth if isinstance(request.auth, PseudonymousProfile) else None

    # Validate parameters
    if q and len(q.strip()) < 2:
        return 400, {"message": "Search query must be at least 2 characters long"}

    if not q and not profile_id:
        return 400, {
            "message": (
                "Either search query (q) or profile filter (profile_id) is required"
            )
        }

    validation_error = validate_pagination_params(page, page_size)
    if validation_error:
        return 400, {"message": validation_error}

    try:
        # Build the base query - only approved comments
        base_query = GenericComment.objects.filter(
            is_taken_down=False,
            is_deleted=False,
            moderation_status="approved",
        )

        # Apply profile filter if specified
        if profile_id:
            try:
                profile_obj = PseudonymousProfile.objects.get(id=profile_id)
                base_query = base_query.filter(profile=profile_obj)
            except PseudonymousProfile.DoesNotExist:
                # No profile exists, return empty results
                base_query = base_query.none()

        # Apply content filters if specified
        if content_type and object_id:
            content_obj = get_content_object(content_type, object_id)
            content_type_obj = ContentType.objects.get_for_model(content_obj)
            base_query = base_query.filter(
                content_type=content_type_obj, object_id=object_id
            )
        elif content_type:
            # Filter by content type only
            base_query = base_query.filter(content_type__model=content_type.value)

        # Apply search filters if query provided
        if q:
            search_query = build_search_query(q.strip(), search_type)
            filtered_comments = base_query.filter(search_query)
        else:
            filtered_comments = base_query

        # Apply sorting
        sort_mapping = {
            CommentSortEnum.NEWEST: "-created_at",
            CommentSortEnum.OLDEST: "created_at",
            CommentSortEnum.MOST_LIKED: "-like_count",
            CommentSortEnum.MOST_REPLIES: "-reply_count",
        }

        # For search, we might want to add relevance scoring
        if q and search_type == CommentSearchTypeEnum.ALL:
            # Add relevance-based sorting as primary, then fallback to user choice
            ordered_comments = apply_relevance_scoring(filtered_comments, q)
            ordered_comments = ordered_comments.order_by(
                "-relevance_score", sort_mapping[sort]
            )
        else:
            ordered_comments = filtered_comments.order_by(sort_mapping[sort])

        # Paginate results
        paginator = Paginator(ordered_comments, page_size)
        comments_page = get_page_or_fallback(paginator, page)

        # Convert to search result schema
        search_results = []
        for comment in comments_page:
            result = convert_comment_to_search_result(
                comment, q or "", profile, include_poll_content
            )
            search_results.append(result)

        # Calculate timing
        end_time = time.time()
        total_time_ms = int((end_time - start_time) * 1000)

        # Build response
        response_data = {
            "items": search_results,
            "total": paginator.count,
            "page": comments_page.number,
            "pages": paginator.num_pages,
            "page_size": page_size,
            "has_next": comments_page.has_next(),
            "has_previous": comments_page.has_previous(),
            "include_poll_content": include_poll_content,
            "total_time_ms": total_time_ms,
        }

        # Add search info if query was provided
        if q:
            response_data["search_query"] = q
            response_data["search_type"] = search_type.value

        # Add profile filter info if profile filter was used
        if profile_id:
            response_data["profile_filter"] = {
                "profile_id": profile_id,
            }

        return 200, PaginatedCommentSearchResponse(**response_data)

    except Exception as e:
        logger.error(f"Error searching comments: {str(e)}", exc_info=True)
        return 400, {"message": "An error occurred while searching comments"}


def convert_comment_to_search_result(
    comment: GenericComment,
    search_query: str,
    auth_profile,
    include_poll_content: bool = False,
) -> CommentSearchResultOut:
    """Convert a comment to search result format"""

    # Get author info using the simplified function
    author_info = get_author_info(comment.profile)

    # Check user engagement with simplified logic
    has_user_liked = False
    is_author = False

    if auth_profile:
        # Check if user is author
        is_author = comment.profile.id == auth_profile.id

        # Check if user liked this comment
        try:
            user_reactions = Reaction.get_user_reactions_by_profile(
                auth_profile, comment
            )
            has_user_liked = user_reactions.get("like", False)
        except Exception:
            pass

    # Get media info
    has_media = False
    media_type = None
    try:
        media_obj = comment.media.first()
        if media_obj:
            has_media = True
            media_type = media_obj.media_type
    except Exception:
        pass

    # Get link info
    has_link = False
    link_domain = None
    try:
        link_obj = comment.links.first()
        if link_obj:
            has_link = True
            link_domain = getattr(link_obj, "domain", None)
    except Exception:
        pass

    # Generate search snippet
    search_snippet = generate_search_snippet(comment.content, search_query)

    # Get relevance score if available
    relevance_score = getattr(comment, "relevance_score", 0.0)

    # Get poll content if requested
    poll_content = None
    if include_poll_content:
        poll_content = get_poll_content(comment)

    return CommentSearchResultOut(
        id=comment.id,
        content=comment.content,
        created_at=comment.created_at.isoformat(),
        updated_at=comment.updated_at.isoformat(),
        is_edited=comment.is_edited,
        like_count=comment.like_count,
        reply_count=comment.reply_count,
        depth=comment.depth,
        author_info=author_info,
        content_type=comment.content_type.model,
        content_object_id=comment.object_id,
        parent_comment_id=comment.parent_id,
        top_level_comment_id=get_top_level_comment_id(comment),
        has_user_liked=has_user_liked,
        is_author=is_author,
        has_media=has_media,
        media_type=media_type,
        has_link=has_link,
        link_domain=link_domain,
        search_snippet=search_snippet,
        relevance_score=relevance_score,
        poll_content=poll_content,
    )


def get_poll_content(comment: GenericComment) -> Optional[PollContentSchema]:
    """Extract poll content if the comment is on a poll"""
    try:
        # Check if the comment is on a poll
        if comment.content_type.model != "poll":
            return None

        try:
            poll = Poll.objects.get(id=comment.object_id, is_deleted=False)
        except Poll.DoesNotExist:
            logger.warning(
                f"Poll {comment.object_id} for comment {comment.id} "
                f"does not exist or is deleted"
            )
            return None

        # Get poll author info using the simplified function
        poll_author_info = get_author_info(poll.profile)

        return PollContentSchema(
            id=poll.id,
            title=poll.title,
            description=poll.description,
            poll_type=poll.poll_type,
            author_info=poll_author_info,
            total_votes=poll.total_votes,
            option_count=poll.option_count,
        )

    except Exception as e:
        logger.error(f"Error getting poll content for comment {comment.id}: {str(e)}")
        return None


def build_search_query(query: str, search_type: CommentSearchTypeEnum) -> Q:
    """Build Django Q object for search based on type"""
    query_lower = query.lower()

    if search_type == CommentSearchTypeEnum.CONTENT:
        # Search only in comment content
        return Q(content__icontains=query)

    elif search_type == CommentSearchTypeEnum.AUTHOR:
        # Search in author information using profile data
        author_query = Q()

        # Search by profile username and display_name
        matching_profile_ids = get_matching_profile_ids(query_lower)
        if matching_profile_ids:
            author_query |= Q(profile_id__in=matching_profile_ids)

        # Search by anonymous_comment_identifier
        author_query |= Q(anonymous_comment_identifier__icontains=query)

        return author_query

    elif search_type == CommentSearchTypeEnum.MEDIA:
        # Search in media alt text
        return Q(media__alt_text__icontains=query)

    elif search_type == CommentSearchTypeEnum.LINKS:
        # Search in link fields
        return Q(
            Q(links__title__icontains=query)
            | Q(links__description__icontains=query)
            | Q(links__display_text__icontains=query)
            | Q(links__url__icontains=query)
        )

    else:  # CommentSearchTypeEnum.ALL
        # Search across all fields
        content_query = Q(content__icontains=query)
        media_query = Q(media__alt_text__icontains=query)
        link_query = Q(
            Q(links__title__icontains=query)
            | Q(links__description__icontains=query)
            | Q(links__display_text__icontains=query)
            | Q(links__url__icontains=query)
        )

        # Author search for 'all' type
        author_query = build_search_query(query, CommentSearchTypeEnum.AUTHOR)

        return content_query | media_query | link_query | author_query


def get_matching_profile_ids(query: str) -> List[int]:
    """Get profile IDs that match the search query"""
    try:
        matching_profiles = PseudonymousProfile.objects.filter(
            Q(display_name__icontains=query) | Q(username__icontains=query)
        ).values_list("id", flat=True)

        return list(matching_profiles)

    except Exception as e:
        logger.error(f"Error getting matching profile IDs: {str(e)}")
        return []


def apply_relevance_scoring(queryset, search_query: str):
    """Apply relevance scoring to search results"""
    from django.db.models import Case, IntegerField, Value, When

    # Simple relevance scoring based on where the match appears
    return queryset.annotate(
        relevance_score=Case(
            # Exact match in content gets highest score
            When(content__iexact=search_query, then=Value(100)),
            # Content starts with query
            When(content__istartswith=search_query, then=Value(80)),
            # Content contains query
            When(content__icontains=search_query, then=Value(60)),
            # Media alt text contains query
            When(media__alt_text__icontains=search_query, then=Value(40)),
            # Link text contains query
            When(links__title__icontains=search_query, then=Value(30)),
            When(links__description__icontains=search_query, then=Value(20)),
            # Default score
            default=Value(10),
            output_field=IntegerField(),
        )
    )


def generate_search_snippet(
    content: str, search_query: str, snippet_length: int = 150
) -> str:
    """Generate a search snippet with the query highlighted"""
    if not search_query or search_query.lower() not in content.lower():
        # Return truncated content if no match
        return (
            content[:snippet_length] + "..."
            if len(content) > snippet_length
            else content
        )

    # Find the position of the search query
    query_lower = search_query.lower()
    content_lower = content.lower()
    query_pos = content_lower.find(query_lower)

    if query_pos == -1:
        return (
            content[:snippet_length] + "..."
            if len(content) > snippet_length
            else content
        )

    # Calculate snippet boundaries
    half_snippet = snippet_length // 2
    start_pos = max(0, query_pos - half_snippet)
    end_pos = min(len(content), start_pos + snippet_length)

    # Adjust start_pos if we hit the end
    if end_pos == len(content):
        start_pos = max(0, end_pos - snippet_length)

    # Extract snippet
    snippet = content[start_pos:end_pos]

    # Add ellipsis if needed
    if start_pos > 0:
        snippet = "..." + snippet
    if end_pos < len(content):
        snippet = snippet + "..."

    return snippet
