from typing import Optional

from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from ninja import File, Query, Router, Schema, UploadedFile

from keyopolls.articles.models import Article
from keyopolls.articles.schemas import (
    ArticleCreateSchema,
    ArticleDetails,
    ArticlesList,
    ArticleUpdateSchema,
)
from keyopolls.common.schemas import Message, PaginationSchema
from keyopolls.communities.models import Community
from keyopolls.profile.middleware import (
    OptionalPseudonymousJWTAuth,
    PseudonymousJWTAuth,
)

router = Router()


@router.post(
    "/", response={201: ArticleDetails, 400: Message}, auth=PseudonymousJWTAuth()
)
def create_article(
    request, data: ArticleCreateSchema, main_image: UploadedFile = File(None)
):
    """
    Create a new article.
    Requires authentication.
    """
    # Verify community exists and user has access
    community = get_object_or_404(Community, id=data.community_id)

    # You might want to add permission checks here
    # e.g., check if user can create articles in this community

    article = Article.objects.create(
        title=data.title,
        subtitle=data.subtitle,
        content=data.content,
        community=community,
        author=request.auth,  # PseudonymousProfile from JWT
        link=data.link,
        main_image=main_image,
        author_name=data.author_name,
        is_published=data.is_published,
    )

    return ArticleDetails.resolve(article, request.auth)


@router.put(
    "/{int:article_id}",
    response={200: ArticleDetails, 404: Message},
    auth=PseudonymousJWTAuth(),
)
def update_article(
    request,
    article_id: int,
    data: ArticleUpdateSchema,
    main_image: UploadedFile = File(None),
):
    """
    Update an existing article.
    Only the author can update their article.
    """
    article = get_object_or_404(Article, id=article_id)

    # Check if user is the author
    if article.author.id != request.auth.id:
        return 404, {"message": "Article not found"}

    # Update only provided fields
    if data.title is not None:
        article.title = data.title
    if data.subtitle is not None:
        article.subtitle = data.subtitle
    if data.content is not None:
        article.content = data.content
    if data.author_name is not None:
        article.author_name = data.author_name
    if data.link is not None:
        article.link = data.link
    if main_image:
        article.main_image = main_image
    if data.is_published is not None:
        article.is_published = data.is_published

    article.save()

    return ArticleDetails.resolve(article, request.auth)


@router.delete(
    "/{int:article_id}",
    response={204: Message, 404: Message},
    auth=PseudonymousJWTAuth(),
)
def delete_article(request, article_id: int):
    """
    Delete an article.
    Only the author can delete their article.
    """
    article = get_object_or_404(Article, id=article_id)

    # Check if user is the author
    if article.author.id != request.auth.id:
        raise Http404("Article not found")  # Don't reveal existence to non-authors

    article.delete()

    return {"message": "Article deleted successfully"}


@router.get(
    "/{int:article_id}",
    response={200: ArticleDetails, 404: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def get_article(request, article_id: int):
    """
    Get a specific article by ID.
    Authentication is optional - provides additional context if authenticated.
    """
    article = get_object_or_404(
        Article.objects.select_related("author", "community"), id=article_id
    )

    # Only show published articles to non-authors
    if not article.is_published and (
        not request.auth or article.author.id != request.auth.id
    ):
        raise Http404("Article not found")

    # Optionally increment view count here
    # article.view_count = F('view_count') + 1
    # article.save(update_fields=['view_count'])

    return ArticleDetails.resolve(article, request.auth)


class ArticleFilters(Schema):
    # Pagination
    page: int = 1
    per_page: int = 20

    # Filters
    community_id: Optional[int] = None
    community_slug: Optional[str] = None
    author_username: Optional[str] = None
    is_published: Optional[bool] = None
    my_articles: bool = False  # Filter for current user's articles

    # Search
    search: Optional[str] = None

    # Sorting
    order_by: str = "-created_at"  # Options: created_at, -created_at, title, -title


@router.get(
    "/",
    response={200: ArticlesList, 400: Message, 404: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def list_articles(request, filters: ArticleFilters = Query(...)):
    """
    Get a paginated list of articles with comprehensive filtering options.

    Features:
    - Pagination with configurable page size
    - Filter by community, creator, published status
    - Search across title, subtitle, and content
    - My articles filter for authenticated users
    - Multiple sorting options
    - Authentication-aware visibility (published vs drafts)

    Query Parameters:
    - page: Page number (default: 1)
    - per_page: Items per page (default: 20, max: 100)
    - community_id: Filter by community ID
    - community_slug: Filter by community slug
    - author_username: Filter by author username
    - is_published: Filter by published status (true/false/null for all)
    - my_articles: Show only current user's articles (requires auth)
    - search: Search term for title, subtitle, or content
    - order_by: Sort field (created_at, title with - for desc)
    """

    # Validate pagination parameters
    if filters.per_page > 100:
        filters.per_page = 100
    if filters.per_page < 1:
        filters.per_page = 20
    if filters.page < 1:
        filters.page = 1

    # Validate order_by options
    valid_order_fields = [
        "created_at",
        "-created_at",
        "title",
        "-title",
        "updated_at",
        "-updated_at",
    ]
    if filters.order_by not in valid_order_fields:
        filters.order_by = "-created_at"

    # Start with base queryset
    queryset = Article.objects.select_related("creator", "community")

    # Apply community filter (by ID or slug)
    if filters.community_id or filters.community_slug:
        try:
            if filters.community_id and filters.community_slug:
                # If both are provided, prioritize community_id but validate they match
                community = get_object_or_404(
                    Community,
                    id=filters.community_id,
                    slug=filters.community_slug,
                    is_active=True,
                )
                queryset = queryset.filter(community_id=filters.community_id)
            elif filters.community_id:
                # Filter by community ID
                community = get_object_or_404(
                    Community, id=filters.community_id, is_active=True
                )
                queryset = queryset.filter(community_id=filters.community_id)
            else:
                # Filter by community slug
                community = get_object_or_404(
                    Community, slug=filters.community_slug, is_active=True
                )
                queryset = queryset.filter(community_id=community.id)
        except Exception:
            return 404, {"message": "Community not found"}

    # Apply author filter
    if filters.author_username:
        queryset = queryset.filter(author__username=filters.author_username)

    # Apply my_articles filter (overrides other filters if authenticated)
    if filters.my_articles:
        if not request.auth:
            return 400, {"message": "Authentication required for my_articles filter"}
        queryset = queryset.filter(creator=request.auth)
    else:
        # Handle published status filter for general articles
        if filters.is_published is not None:
            if not request.auth:
                # Non-authenticated users can only see published articles
                queryset = queryset.filter(is_published=True)
            else:
                if filters.is_published:
                    # Show only published articles
                    queryset = queryset.filter(is_published=True)
                else:
                    # Show only unpublished articles (only user's own)
                    queryset = queryset.filter(is_published=False, creator=request.auth)
        else:
            # No published filter specified
            if request.auth:
                # Show published articles + user's unpublished articles
                queryset = queryset.filter(
                    Q(is_published=True) | Q(creator=request.auth)
                )
            else:
                # Show only published articles for unauthenticated users
                queryset = queryset.filter(is_published=True)

    # Apply search filter
    if filters.search:
        search_term = filters.search.strip()
        if search_term:
            queryset = queryset.filter(
                Q(title__icontains=search_term)
                | Q(subtitle__icontains=search_term)
                | Q(content__icontains=search_term)
            )

    # Apply ordering
    queryset = queryset.order_by(filters.order_by)

    # Get total count before pagination
    total_count = queryset.count()

    # Apply pagination using Django's core Paginator
    paginator = Paginator(queryset, filters.per_page)

    # Handle page number validation
    if filters.page > paginator.num_pages and paginator.num_pages > 0:
        filters.page = paginator.num_pages

    try:
        page_obj = paginator.page(filters.page)
    except Exception:
        return 400, {"message": "Invalid page number"}

    # Build pagination info
    pagination_data = PaginationSchema(
        current_page=filters.page,
        total_pages=paginator.num_pages,
        total_count=total_count,
        has_next=page_obj.has_next(),
        has_previous=page_obj.has_previous(),
        page_size=filters.per_page,
        next_page=page_obj.next_page_number() if page_obj.has_next() else None,
        previous_page=(
            page_obj.previous_page_number() if page_obj.has_previous() else None
        ),
    )

    # Resolve articles
    articles_data = [
        ArticleDetails.resolve(article, request.auth)
        for article in page_obj.object_list
    ]

    return ArticlesList(articles=articles_data, pagination=pagination_data)
