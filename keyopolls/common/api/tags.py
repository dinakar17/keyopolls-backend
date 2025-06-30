from datetime import datetime, timedelta
from typing import List, Optional

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, F, Q, Sum
from django.http import HttpRequest
from django.utils import timezone
from keyoconnect.common.models import Tag, TaggedItem
from keyoconnect.posts.models import Post
from ninja import Query, Router, Schema
from shared.schemas import Message, PaginationSchema

router = Router(tags=["Tags"])


class TagStatsSchema(Schema):
    """Schema for tag statistics"""

    id: int
    name: str
    slug: str
    usage_count: int
    post_count: int  # Posts specifically using this tag
    recent_post_count: int  # Posts in last 30 days
    trending_score: float  # Custom trending calculation
    growth_rate: float  # Percentage growth in last 7 days vs previous 7 days
    created_at: str

    # Optional detailed stats
    public_post_count: Optional[int] = None
    anonymous_post_count: Optional[int] = None
    avg_likes_per_post: Optional[float] = None
    avg_comments_per_post: Optional[float] = None
    total_engagement: Optional[int] = None


class TagsListResponseSchema(Schema):
    """Response schema for tags list"""

    tags: List[TagStatsSchema]
    pagination: PaginationSchema
    meta: dict  # Additional metadata about the response


@router.get(
    "/tags",
    response={200: TagsListResponseSchema, 400: Message},
    summary="Get tags with comprehensive filtering and statistics",
)
def get_tags_with_stats(
    request: HttpRequest,
    # === SEARCH & FILTERING ===
    search: Optional[str] = None,
    name_contains: Optional[str] = None,
    name_starts_with: Optional[str] = None,
    tag_ids: Optional[str] = None,
    exclude_tags: Optional[str] = None,
    # === USAGE FILTERS ===
    min_usage: Optional[int] = None,
    max_usage: Optional[int] = None,
    min_posts: Optional[int] = None,
    max_posts: Optional[int] = None,
    # === ENGAGEMENT FILTERS ===
    min_avg_likes: Optional[float] = None,
    min_avg_comments: Optional[float] = None,
    min_total_engagement: Optional[int] = None,
    # === TIME-BASED FILTERS ===
    created_after: Optional[str] = None,
    created_before: Optional[str] = None,
    active_in_days: Optional[int] = None,
    trending_days: Optional[int] = 7,
    # === CONTENT TYPE FILTERS ===
    profile_type: Optional[str] = None,
    post_type: Optional[str] = None,
    category_id: Optional[int] = None,
    # === SORTING OPTIONS ===
    sort_by: Optional[str] = "usage_count",
    sort_order: Optional[str] = "desc",
    # === PAGINATION ===
    page: int = 1,
    page_size: int = 20,
    # === RESPONSE OPTIONS ===
    include_detailed_stats: bool = False,
    include_zero_posts: bool = True,
):
    """
    Get tags with comprehensive filtering, statistics, and sorting options.

    This endpoint provides detailed analytics for tags including:
    - Post counts and engagement metrics
    - Trending scores and growth rates
    - Time-based filtering
    - Profile type and content filtering
    - Comprehensive search and sorting
    """

    try:
        # Get Post content type for filtering
        post_content_type = ContentType.objects.get_for_model(Post)

        # Start with base queryset
        queryset = Tag.objects.all()

        # === SEARCH FILTERS ===
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(slug__icontains=search)
            )

        if name_contains:
            queryset = queryset.filter(name__icontains=name_contains)

        if name_starts_with:
            queryset = queryset.filter(name__istartswith=name_starts_with)

        if tag_ids:
            try:
                tag_id_list = [int(x.strip()) for x in tag_ids.split(",")]
                queryset = queryset.filter(id__in=tag_id_list)
            except ValueError:
                return 400, {"message": "Invalid tag_ids format"}

        if exclude_tags:
            try:
                exclude_id_list = [int(x.strip()) for x in exclude_tags.split(",")]
                queryset = queryset.exclude(id__in=exclude_id_list)
            except ValueError:
                return 400, {"message": "Invalid exclude_tags format"}

        # === USAGE FILTERS ===
        if min_usage is not None:
            queryset = queryset.filter(usage_count__gte=min_usage)

        if max_usage is not None:
            queryset = queryset.filter(usage_count__lte=max_usage)

        # === TIME-BASED FILTERS ===
        if created_after:
            try:
                date_after = datetime.strptime(created_after, "%Y-%m-%d").date()
                queryset = queryset.filter(created_at__date__gte=date_after)
            except ValueError:
                return 400, {
                    "message": "Invalid created_after date format. Use YYYY-MM-DD"
                }

        if created_before:
            try:
                date_before = datetime.strptime(created_before, "%Y-%m-%d").date()
                queryset = queryset.filter(created_at__date__lte=date_before)
            except ValueError:
                return 400, {
                    "message": "Invalid created_before date format. Use YYYY-MM-DD"
                }

        # Calculate time boundaries for trending and recent posts
        now = timezone.now()
        recent_boundary = now - timedelta(days=30)  # Last 30 days for "recent"
        trending_boundary = now - timedelta(days=trending_days)
        growth_boundary = now - timedelta(
            days=trending_days * 2
        )  # For growth calculation

        # === BUILD POST FILTERS FOR SUBQUERIES ===
        post_filters = Q(items__content_type=post_content_type)

        # Profile type filter
        if profile_type:
            if profile_type in ["public", "anonymous"]:
                # Filter posts by profile type through Post model
                post_ids_with_profile_type = Post.objects.filter(
                    profile_type=profile_type, is_deleted=False
                ).values_list("id", flat=True)
                post_filters &= Q(items__object_id__in=post_ids_with_profile_type)
            elif profile_type != "both":
                return 400, {
                    "message": "Invalid profile_type. Use: public, anonymous, or both"
                }

        # Category filter
        if category_id:
            post_ids_with_category = Post.objects.filter(
                category_id=category_id, is_deleted=False
            ).values_list("id", flat=True)
            post_filters &= Q(items__object_id__in=post_ids_with_category)

        # Post type filter
        if post_type:
            if post_type in ["text", "image", "video", "link", "poll"]:
                post_ids_with_type = Post.objects.filter(
                    post_type=post_type, is_deleted=False
                ).values_list("id", flat=True)
                post_filters &= Q(items__object_id__in=post_ids_with_type)
            else:
                return 400, {
                    "message": "Invalid post_type. Use: text, image, video, link, poll"
                }

        # Active in days filter
        if active_in_days:
            active_boundary = now - timedelta(days=active_in_days)
            active_tag_ids = (
                TaggedItem.objects.filter(
                    content_type=post_content_type, created_at__gte=active_boundary
                )
                .values_list("tag_id", flat=True)
                .distinct()
            )
            queryset = queryset.filter(id__in=active_tag_ids)

        # === ANNOTATE WITH STATISTICS ===
        queryset = queryset.annotate(
            # Post count (filtered)
            post_count=Count("items", filter=post_filters, distinct=True),
            # Recent post count (last 30 days)
            recent_post_count=Count(
                "items",
                filter=post_filters & Q(items__created_at__gte=recent_boundary),
                distinct=True,
            ),
            # Trending post count (configurable days)
            trending_post_count=Count(
                "items",
                filter=post_filters & Q(items__created_at__gte=trending_boundary),
                distinct=True,
            ),
            # Growth calculation (current period vs previous period)
            growth_period_count=Count(
                "items",
                filter=post_filters
                & Q(
                    items__created_at__gte=trending_boundary, items__created_at__lt=now
                ),
                distinct=True,
            ),
            previous_period_count=Count(
                "items",
                filter=post_filters
                & Q(
                    items__created_at__gte=growth_boundary,
                    items__created_at__lt=trending_boundary,
                ),
                distinct=True,
            ),
        )

        # === DETAILED STATS (if requested) ===
        if include_detailed_stats:
            # Get post statistics for each tag
            queryset = queryset.annotate(
                # Profile type breakdown
                public_post_count=Count(
                    "items",
                    filter=post_filters
                    & Q(
                        items__object_id__in=Post.objects.filter(
                            profile_type="public", is_deleted=False
                        ).values_list("id", flat=True)
                    ),
                    distinct=True,
                ),
                anonymous_post_count=Count(
                    "items",
                    filter=post_filters
                    & Q(
                        items__object_id__in=Post.objects.filter(
                            profile_type="anonymous", is_deleted=False
                        ).values_list("id", flat=True)
                    ),
                    distinct=True,
                ),
            )

        # === POST COUNT FILTERS (applied after annotation) ===
        if min_posts is not None:
            queryset = queryset.filter(post_count__gte=min_posts)

        if max_posts is not None:
            queryset = queryset.filter(post_count__lte=max_posts)

        # === EXCLUDE ZERO POSTS (if requested) ===
        if not include_zero_posts:
            queryset = queryset.filter(post_count__gt=0)

        # === SORTING ===
        valid_sort_fields = {
            "name": "name",
            "usage_count": "usage_count",
            "post_count": "post_count",
            "recent_post_count": "recent_post_count",
            # Use trending_post_count for trending_score
            "trending_score": "trending_post_count",
            "created_at": "created_at",
        }

        sort_field = valid_sort_fields.get(sort_by, "usage_count")
        order_prefix = "-" if sort_order == "desc" else ""
        queryset = queryset.order_by(f"{order_prefix}{sort_field}")

        # === PAGINATION ===
        total_count = queryset.count()
        offset = (page - 1) * page_size
        tags_page = queryset[offset : offset + page_size]

        # === BUILD RESPONSE DATA ===
        tags_data = []

        for tag in tags_page:
            # Calculate trending score (weighted recent activity)
            trending_score = float(tag.trending_post_count * 2 + tag.recent_post_count)

            # Calculate growth rate
            if tag.previous_period_count > 0:
                growth_rate = (
                    (tag.growth_period_count - tag.previous_period_count)
                    / tag.previous_period_count
                ) * 100
            else:
                growth_rate = 100.0 if tag.growth_period_count > 0 else 0.0

            # Base tag data
            tag_data = {
                "id": tag.id,
                "name": tag.name,
                "slug": tag.slug,
                "usage_count": tag.usage_count,
                "post_count": tag.post_count,
                "recent_post_count": tag.recent_post_count,
                "trending_score": trending_score,
                "growth_rate": round(growth_rate, 2),
                "created_at": tag.created_at.strftime("%Y-%m-%d"),
            }

            # Add detailed stats if requested
            if include_detailed_stats:
                # Calculate engagement stats
                tagged_posts = Post.objects.filter(
                    id__in=TaggedItem.objects.filter(
                        tag=tag, content_type=ContentType.objects.get_for_model(Post)
                    ).values_list("object_id", flat=True),
                    is_deleted=False,
                )

                if tagged_posts.exists():
                    avg_likes = (
                        tagged_posts.aggregate(avg_likes=Count("like_count"))[
                            "avg_likes"
                        ]
                        or 0
                    )
                    avg_comments = (
                        tagged_posts.aggregate(avg_comments=Count("comment_count"))[
                            "avg_comments"
                        ]
                        or 0
                    )
                    total_engagement = (
                        tagged_posts.aggregate(
                            total=Sum(
                                F("like_count") + F("comment_count") + F("share_count")
                            )
                        )["total"]
                        or 0
                    )
                else:
                    avg_likes = avg_comments = total_engagement = 0

                tag_data.update(
                    {
                        "public_post_count": getattr(tag, "public_post_count", 0),
                        "anonymous_post_count": getattr(tag, "anonymous_post_count", 0),
                        "avg_likes_per_post": round(avg_likes, 2),
                        "avg_comments_per_post": round(avg_comments, 2),
                        "total_engagement": total_engagement,
                    }
                )

            tags_data.append(tag_data)

        # === PAGINATION INFO ===
        total_pages = (total_count + page_size - 1) // page_size
        # === METADATA ===
        meta = {
            "filters_applied": {
                "search": search,
                "profile_type": profile_type,
                "post_type": post_type,
                "category_id": category_id,
                "min_posts": min_posts,
                "active_in_days": active_in_days,
            },
            "trending_calculation_days": trending_days,
            "total_tags_found": total_count,
            "include_detailed_stats": include_detailed_stats,
        }

        return 200, TagsListResponseSchema(
            tags=tags_data,
            pagination=PaginationSchema(
                current_page=page,
                total_pages=total_pages,
                total_count=total_count,
                has_next=page < total_pages,
                has_previous=page > 1,
                page_size=page_size,
            ),
            meta=meta,
        )

    except Exception as e:
        return 400, {"message": f"Error fetching tags: {str(e)}"}


# Additional utility endpoints
@router.get(
    "/tags/trending",
    response={200: TagsListResponseSchema, 400: Message},
    summary="Get trending tags (simplified endpoint)",
)
def get_trending_tags(
    request: HttpRequest,
    days: int = Query(7, description="Days to calculate trending"),
    limit: int = Query(
        10, ge=1, le=50, description="Number of trending tags to return"
    ),
    profile_type: Optional[str] = Query(None, description="Filter by profile type"),
):
    """Get top trending tags based on recent activity"""

    # Use the main endpoint with trending-specific parameters
    return get_tags_with_stats(
        request=request,
        sort_by="trending_score",
        sort_order="desc",
        trending_days=days,
        page_size=limit,
        profile_type=profile_type,
        include_zero_posts=False,
        min_posts=1,
    )


@router.get(
    "/tags/popular",
    response={200: List[TagStatsSchema], 400: Message},
    summary="Get most popular tags by usage count",
)
def get_popular_tags(
    request: HttpRequest,
    limit: int = Query(
        20, ge=1, le=100, description="Number of popular tags to return"
    ),
    profile_type: Optional[str] = Query(None, description="Filter by profile type"),
):
    """Get most popular tags by total usage count"""

    return get_tags_with_stats(
        request=request,
        sort_by="usage_count",
        sort_order="desc",
        page_size=limit,
        profile_type=profile_type,
        include_zero_posts=False,
    )


@router.get(
    "/tags/search/{query}",
    response={200: TagsListResponseSchema, 400: Message},
    summary="Search tags by name",
)
def search_tags(
    request: HttpRequest,
    query: str,
    limit: int = Query(10, ge=1, le=50, description="Number of results to return"),
):
    """Quick search for tags by name"""

    return get_tags_with_stats(
        request=request,
        search=query,
        page_size=limit,
        sort_by="usage_count",
        sort_order="desc",
    )
