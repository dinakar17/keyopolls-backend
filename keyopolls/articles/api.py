from typing import List, Optional

from communities.models import Community
from django.http import Http404
from django.shortcuts import get_object_or_404
from ninja import Query, Router, Schema
from ninja.pagination import PageNumberPagination, paginate

from keyopolls.articles.models import Article
from keyopolls.articles.schemas import (
    ArticleCreateSchema,
    ArticleDetails,
    ArticleListItem,
    ArticleUpdateSchema,
    MessageSchema,
)
from keyopolls.profile.middleware import (
    OptionalPseudonymousJWTAuth,
    PseudonymousJWTAuth,
)

router = Router()


@router.post("/", response=ArticleDetails, auth=PseudonymousJWTAuth())
def create_article(request, data: ArticleCreateSchema):
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
        is_published=data.is_published,
    )

    return ArticleDetails.resolve(article, request.auth)


@router.put("/{int:article_id}", response=ArticleDetails, auth=PseudonymousJWTAuth())
def update_article(request, article_id: int, data: ArticleUpdateSchema):
    """
    Update an existing article.
    Only the author can update their article.
    """
    article = get_object_or_404(Article, id=article_id)

    # Check if user is the author
    if article.author.id != request.auth.id:
        raise Http404("Article not found")  # Don't reveal existence to non-authors

    # Update only provided fields
    if data.title is not None:
        article.title = data.title
    if data.subtitle is not None:
        article.subtitle = data.subtitle
    if data.content is not None:
        article.content = data.content
    if data.is_published is not None:
        article.is_published = data.is_published

    article.save()

    return ArticleDetails.resolve(article, request.auth)


@router.delete("/{int:article_id}", response=MessageSchema, auth=PseudonymousJWTAuth())
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
    "/{int:article_id}", response=ArticleDetails, auth=OptionalPseudonymousJWTAuth()
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
    """Query parameters for filtering articles"""

    community_id: Optional[int] = None
    author_username: Optional[str] = None
    is_published: Optional[bool] = True  # Default to published only
    search: Optional[str] = None


@router.get("/", response=List[ArticleListItem], auth=OptionalPseudonymousJWTAuth())
@paginate(PageNumberPagination, page_size=20)
def list_articles(request, filters: ArticleFilters = Query(...)):
    """
    Get a paginated list of articles.
    Authentication is optional - provides additional context if authenticated.
    """
    queryset = Article.objects.select_related("author", "community").order_by(
        "-created_at"
    )

    # Apply filters
    if filters.community_id:
        queryset = queryset.filter(community_id=filters.community_id)

    if filters.author_username:
        queryset = queryset.filter(author__username=filters.author_username)

    # Handle published filter
    if filters.is_published is not None:
        if not request.auth:
            # Non-authenticated users can only see published articles
            queryset = queryset.filter(is_published=True)
        else:
            # Authenticated users can see their own unpublished articles
            if filters.is_published:
                queryset = queryset.filter(is_published=True)
            else:
                # Show unpublished articles only if they are the author
                queryset = queryset.filter(is_published=False, author=request.auth)
    else:
        # If no published filter specified, show published + user's unpublished
        if request.auth:
            from django.db.models import Q

            queryset = queryset.filter(Q(is_published=True) | Q(author=request.auth))
        else:
            queryset = queryset.filter(is_published=True)

    # Apply search filter
    if filters.search:
        from django.db.models import Q

        queryset = queryset.filter(
            Q(title__icontains=filters.search)
            | Q(subtitle__icontains=filters.search)
            | Q(content__icontains=filters.search)
        )

    return [ArticleListItem.resolve(article, request.auth) for article in queryset]


# Additional endpoints you might want to add:


@router.get(
    "/community/{int:community_id}",
    response=List[ArticleListItem],
    auth=OptionalPseudonymousJWTAuth(),
)
@paginate(PageNumberPagination, page_size=20)
def list_community_articles(request, community_id: int):
    """
    Get articles for a specific community.
    """
    # Verify community exists
    get_object_or_404(Community, id=community_id)

    queryset = (
        Article.objects.select_related("author", "community")
        .filter(community_id=community_id)
        .order_by("-created_at")
    )

    # Filter by published status based on authentication
    if not request.auth:
        queryset = queryset.filter(is_published=True)
    else:
        # Show published articles + user's own unpublished articles
        from django.db.models import Q

        queryset = queryset.filter(Q(is_published=True) | Q(author=request.auth))

    return [ArticleListItem.resolve(article, request.auth) for article in queryset]


@router.get("/my-articles", response=List[ArticleListItem], auth=PseudonymousJWTAuth())
@paginate(PageNumberPagination, page_size=20)
def list_my_articles(request):
    """
    Get current user's articles (both published and unpublished).
    Requires authentication.
    """
    queryset = (
        Article.objects.select_related("community")
        .filter(author=request.auth)
        .order_by("-created_at")
    )

    return [ArticleListItem.resolve(article, request.auth) for article in queryset]
