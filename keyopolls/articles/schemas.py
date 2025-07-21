from datetime import datetime
from typing import Dict, List, Optional

from ninja import Schema

from keyopolls.articles.models import Article
from keyopolls.common.schemas import PaginationSchema


class TagSchema(Schema):
    """Schema for tag representation"""

    id: int
    name: str
    slug: str
    description: Optional[str] = None
    usage_count: int = 0


class ArticleCreateSchema(Schema):
    """Schema for creating a new article"""

    title: str
    subtitle: Optional[str] = None
    author_name: Optional[str] = None
    content: Optional[str] = None
    link: Optional[str] = None
    community_id: int
    is_published: bool = False


class ArticleUpdateSchema(Schema):
    """Schema for updating an article"""

    title: Optional[str] = None
    subtitle: Optional[str] = None
    content: Optional[str] = None
    link: Optional[str] = None
    author_name: Optional[str] = None
    is_published: Optional[bool] = None


class ArticleDetails(Schema):
    """Complete article schema used across all endpoints"""

    id: int
    title: str
    subtitle: Optional[str] = None
    main_image_url: Optional[str] = None
    link: Optional[str] = None  # New field for article link
    content: str
    author_name: Optional[str] = None

    # Author info
    author_username: str
    author_display_name: str
    author_avatar: Optional[str] = None
    author_aura: int

    # Community info
    community_id: int
    community_name: str
    community_slug: Optional[str] = None
    community_avatar: Optional[str] = None

    # Status
    is_published: bool

    # Counts (if you have these fields or want to add them)
    view_count: int = 0
    like_count: int = 0
    dislike_count: int = 0
    share_count: int = 0
    comment_count: int = 0

    tags: Optional[List[TagSchema]] = None

    # User interaction (only set when user is authenticated)
    is_author: bool = False
    user_reactions: Dict[str, bool] = {}
    is_bookmarked: bool = False

    # Timestamps
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_list(articles, profile=None):
        """
        Resolve a list of articles.
        """
        return [ArticleDetails.resolve(article, profile) for article in articles]

    @staticmethod
    def resolve(article: Article, profile=None):
        """Resolve article data with optional user context"""

        # Initialize user-specific fields
        user_reactions = {}
        is_bookmarked = False
        is_author = False

        # Set user context if profile provided
        if profile:
            is_author = article.author.id == profile.id

            # Get user reactions if you have a Reaction model
            # user_reactions = Reaction.get_user_reactions(profile, article)

            # Check if bookmarked if you have a Bookmark model
            # is_bookmarked = Bookmark.is_bookmarked(profile, article)

        # Get tags with full schema
        tags = (
            [
                {
                    "id": tag.id,
                    "name": tag.name,
                    "slug": tag.slug,
                    "description": tag.description,
                    "usage_count": tag.usage_count,
                }
                for tag in article.tags.all()
            ]
            if article.tags.exists()
            else []
        )

        return {
            "id": article.id,
            "title": article.title,
            "subtitle": article.subtitle,
            "main_image_url": article.main_image.url if article.main_image else None,
            "link": article.link,
            "content": article.content,
            "tags": tags,
            "author_name": article.author_name,
            "author_username": article.creator.username,
            "author_display_name": article.creator.display_name,
            "author_avatar": (
                article.creator.avatar.url if article.creator.avatar else None
            ),
            "author_aura": article.creator.total_aura,
            "community_id": article.community.id,
            "community_name": article.community.name,
            "community_slug": (
                article.community.slug if hasattr(article.community, "slug") else None
            ),
            "community_avatar": (
                article.community.avatar.url
                if hasattr(article.community, "avatar") and article.community.avatar
                else None
            ),
            "is_published": article.is_published,
            "view_count": getattr(article, "view_count", 0),
            "like_count": getattr(article, "like_count", 0),
            "dislike_count": getattr(article, "dislike_count", 0),
            "share_count": getattr(article, "share_count", 0),
            "comment_count": getattr(article, "comment_count", 0),
            "is_author": is_author,
            "user_reactions": user_reactions,
            "is_bookmarked": is_bookmarked,
            "created_at": article.created_at,
            "updated_at": article.updated_at,
        }


class ArticlesList(Schema):
    articles: list[ArticleDetails]
    pagination: PaginationSchema
