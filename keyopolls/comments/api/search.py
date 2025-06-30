import logging
from enum import Enum
from typing import Any, Dict, List, Optional

from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest
from keyoconnect.comments.api import (
    CommentSortEnum,
    get_page_or_fallback,
    get_top_level_comment_id,
    validate_pagination_params,
)
from keyoconnect.comments.models import GenericComment
from keyoconnect.common.models import Reaction
from keyoconnect.common.schemas import ContentTypeEnum, LinkSchema, MediaSchema
from keyoconnect.posts.models import Post
from keyoconnect.profiles.middleware import OptionalPublicJWTAuth
from keyoconnect.profiles.models import PublicProfile
from keyoconnect.profiles.schemas import AuthorSchema, ProfileType
from keyoconnect.utils import get_author_info, get_content_object
from ninja import Field, Router, Schema
from shared.schemas import Message

logger = logging.getLogger(__name__)

router = Router(tags=["Search Comments"])


class CommentSearchTypeEnum(str, Enum):
    """Enum for comment search types"""

    ALL = "all"
    CONTENT = "content"
    AUTHOR = "author"
    MEDIA = "media"
    LINKS = "links"


class PostContentSchema(Schema):
    """Schema for post content when included in comment search results"""

    id: int
    profile_type: ProfileType
    content: str
    author_info: AuthorSchema
    media: List[MediaSchema] = []
    links: List[LinkSchema] = []


class CommentSearchResultOut(Schema):
    """Flat comment schema for search results - no nested replies"""

    # Core comment fields
    id: int
    content: str
    profile_type: str
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

    # Optional post content
    post_content: Optional[PostContentSchema] = None


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
    include_post_content: bool = Field(default=False)
    total_time_ms: int


@router.get(
    "/comments/search",
    response={200: PaginatedCommentSearchResponse, 400: Message},
    auth=OptionalPublicJWTAuth,
)
def search_comments(
    request: HttpRequest,
    q: Optional[str] = None,  # Search query (optional)
    search_type: CommentSearchTypeEnum = CommentSearchTypeEnum.ALL,
    content_type: Optional[ContentTypeEnum] = None,  # Filter by content type
    object_id: Optional[int] = None,  # Filter by specific object
    profile_id: Optional[int] = None,  # Filter by profile ID
    profile_type: Optional[str] = None,  # Filter by profile type (public/anonymous)
    include_post_content: bool = False,  # Include post content in response
    page: int = 1,
    page_size: int = 20,
    sort: CommentSortEnum = CommentSortEnum.NEWEST,
):
    """
    Search comments across the platform or fetch comments by profile

    Args:
        q: Search query string (optional)
        search_type: Type of search (all, content, author, media, links)
        content_type: Optional filter by content type (post, article, etc.)
        object_id: Optional filter by specific content object
        profile_id: Optional filter by profile ID
        profile_type: Optional filter by profile type (public/anonymous)
        include_post_content: Whether to include post content in response
        page: Page number
        page_size: Results per page (max 100)
        sort: Sort order for results
    """
    import time

    start_time = time.time()

    # Extract authentication info from OptionalPublicJWTAuth
    public_profile = request.auth if request.auth else None

    # Create auth data with public profile context
    auth_data = {"profiles": {"public": public_profile}} if public_profile else {}

    # Validate parameters
    if q and len(q.strip()) < 2:
        return 400, {"message": "Search query must be at least 2 characters long"}

    if profile_id and profile_type not in ["public", "anonymous"]:
        return 400, {"message": "Invalid profile_type. Must be 'public' or 'anonymous'"}

    if not q and not profile_id:
        return 400, {
            "message": (
                "Either search query (q) or profile filter "
                "(profile_id + profile_type) is required"
            )
        }

    validation_error = validate_pagination_params(page, page_size)
    if validation_error:
        return 400, {"message": validation_error}

    try:
        # Build the base query - only public and anonymous profiles
        base_query = GenericComment.objects.filter(
            is_taken_down=False,
            is_deleted=False,
            moderation_status="approved",
            profile_type__in=["public", "anonymous"],
        )

        # Apply profile filter if specified
        if profile_id and profile_type:
            # Handle profile filtering based on the simplified approach
            if profile_type == "public":
                base_query = base_query.filter(
                    profile_type="public", profile_id=profile_id
                )
            elif profile_type == "anonymous":
                # For anonymous comments, we need to find comments where the profile_id
                # matches the anonymous profile that belongs to the given public
                #  profile ID
                try:
                    public_profile_obj = PublicProfile.objects.get(id=profile_id)
                    if public_profile_obj.anonymous_profile:
                        base_query = base_query.filter(
                            profile_type="anonymous",
                            profile_id=public_profile_obj.anonymous_profile.id,
                        )
                    else:
                        # No anonymous profile exists, return empty results
                        base_query = base_query.none()
                except PublicProfile.DoesNotExist:
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
                comment, q or "", auth_data, include_post_content
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
            "include_post_content": include_post_content,
            "total_time_ms": total_time_ms,
        }

        # Add search info if query was provided
        if q:
            response_data["search_query"] = q
            response_data["search_type"] = search_type.value

        # Add profile filter info if profile filter was used
        if profile_id and profile_type:
            response_data["profile_filter"] = {
                "profile_id": profile_id,
                "profile_type": profile_type,
            }

        return 200, PaginatedCommentSearchResponse(**response_data)

    except Exception as e:
        logger.error(f"Error searching comments: {str(e)}", exc_info=True)
        return 400, {"message": "An error occurred while searching comments"}


def convert_comment_to_search_result(
    comment: GenericComment,
    search_query: str,
    auth_data: Dict[str, Any],
    include_post_content: bool = False,
) -> CommentSearchResultOut:
    """Convert a comment to search result format"""

    # Get author info using our utility function
    author_info = get_author_info(
        profile_id=comment.profile_id,
        profile_type=comment.profile_type,
        anonymous_identifier=comment.anonymous_comment_identifier,
    )

    # Check user engagement with simplified logic
    has_user_liked = False
    is_author = False

    public_profile = auth_data.get("profiles", {}).get("public")
    if public_profile:
        # Check if user is author
        if comment.profile_type == "public":
            is_author = comment.profile_id == public_profile.id
        elif comment.profile_type == "anonymous":
            try:
                is_author = (
                    public_profile.anonymous_profile
                    and comment.profile_id == public_profile.anonymous_profile.id
                )
            except AttributeError:
                is_author = False

        # Check if user liked this comment (always use public profile for reactions)
        try:
            user_reactions = Reaction.get_user_reactions_by_profile_info(
                "public", public_profile.id, comment
            )
            if user_reactions.get("like", False):
                has_user_liked = True
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
            link_domain = link_obj.domain
    except Exception:
        pass

    # Generate search snippet
    search_snippet = generate_search_snippet(comment.content, search_query)

    # Get relevance score if available
    relevance_score = getattr(comment, "relevance_score", 0.0)

    # Get post content if requested
    post_content = None
    if include_post_content:
        post_content = get_post_content(comment)

    return CommentSearchResultOut(
        id=comment.id,
        content=comment.content,
        profile_type=comment.profile_type,
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
        post_content=post_content,
    )


def get_post_content(comment: GenericComment) -> Optional[PostContentSchema]:
    """Extract post content if the comment is on a post"""
    try:
        # Check if the comment is on a post
        if comment.content_type.model != "post":
            return None

        try:
            post = Post.objects.get(id=comment.object_id, is_deleted=False)
        except Post.DoesNotExist:
            logger.warning(
                f"Post {comment.object_id} for comment {comment.id} "
                f"does not exist or is deleted"
            )
            return None

        # Validate profile type - only public and anonymous are supported
        if post.profile_type not in ["public", "anonymous"]:
            logger.warning(
                f"Unsupported profile type '{post.profile_type}' for post {post.id}"
            )
            return None

        # Get post author info using the same pattern as PostSchema.resolve_post
        try:
            # Get the profile object from the post
            author_profile = post.get_profile()
            profile_id = author_profile.id if author_profile else None

            # For anonymous posts, pass the anonymous identifier
            anonymous_identifier = None
            if post.profile_type == "anonymous":
                anonymous_identifier = post.anonymous_post_identifier

            post_author_info = get_author_info(
                profile_id=profile_id,
                profile_type=post.profile_type,
                anonymous_identifier=anonymous_identifier,
            )
        except Exception as e:
            logger.error(f"Error getting author info for post {post.id}: {str(e)}")
            # Return a default author info structure that matches AuthorSchema
            post_author_info = {
                "id": None,
                "display_name": "Unknown User",
                "handle": None,
                "avatar_url": None,
                "is_verified": False,
                "profile_type": post.profile_type,
            }

        # Get post media using the same pattern as PostSchema.resolve_post
        media_data = []
        try:
            # Use the property method just like PostSchema does
            media_data = [media.to_dict() for media in post.media.all()]
        except Exception as e:
            logger.error(f"Error processing media for post {post.id}: {str(e)}")
            media_data = []

        # Get post links using the same pattern as PostSchema.resolve_post
        links_data = []
        try:
            # Use the property method just like PostSchema does
            links_data = [link.to_dict() for link in post.links.all()]
        except Exception as e:
            logger.error(f"Error processing links for post {post.id}: {str(e)}")
            links_data = []

        return PostContentSchema(
            id=post.id,
            profile_type=post.profile_type,
            content=post.content,
            author_info=post_author_info,
            media=media_data,
            links=links_data,
        )

    except Exception as e:
        logger.error(f"Error getting post content for comment {comment.id}: {str(e)}")
        return None


def build_search_query(query: str, search_type: CommentSearchTypeEnum) -> Q:
    """Build Django Q object for search based on type"""
    query_lower = query.lower()

    if search_type == CommentSearchTypeEnum.CONTENT:
        # Search only in comment content
        return Q(content__icontains=query)

    elif search_type == CommentSearchTypeEnum.AUTHOR:
        # Search in author information using profile data
        # Only search public and anonymous profiles
        author_query = Q()

        # Public profiles
        author_query |= Q(
            profile_type="public",
            profile_id__in=get_matching_profile_ids("public", query_lower),
        )

        # Anonymous profiles - search by anonymous_comment_identifier
        author_query |= Q(
            profile_type="anonymous", anonymous_comment_identifier__icontains=query
        )

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


def get_matching_profile_ids(profile_type: str, query: str) -> List[int]:
    """Get profile IDs that match the search query for a specific profile type"""
    try:
        if profile_type == "public":
            matching_profiles = PublicProfile.objects.filter(
                Q(display_name__icontains=query) | Q(handle__icontains=query)
            ).values_list("id", flat=True)

        elif profile_type == "anonymous":
            # For anonymous profiles, we'll search by anonymous_comment_identifier
            # directly in the comment query, so return empty list here
            return []

        else:
            return []

        return list(matching_profiles)

    except Exception as e:
        logger.error(f"Error getting matching profile IDs for {profile_type}: {str(e)}")
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
