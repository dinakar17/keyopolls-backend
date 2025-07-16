from datetime import datetime
from typing import Dict, Optional

from ninja import Schema

from keyopolls.articles.models import Article


class ArticleCreateSchema(Schema):
    """Schema for creating a new article"""

    title: str
    subtitle: Optional[str] = None
    content: str
    community_id: int
    is_published: bool = False


class ArticleUpdateSchema(Schema):
    """Schema for updating an article"""

    title: Optional[str] = None
    subtitle: Optional[str] = None
    content: Optional[str] = None
    is_published: Optional[bool] = None


class ArticleDetails(Schema):
    """Complete article schema used across all endpoints"""

    id: int
    title: str
    subtitle: Optional[str] = None
    main_image_url: Optional[str] = None
    content: str

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

        return {
            "id": article.id,
            "title": article.title,
            "subtitle": article.subtitle,
            "main_image_url": article.main_image.url if article.main_image else None,
            "content": article.content,
            "author_username": article.author.username,
            "author_display_name": article.author.display_name,
            "author_avatar": (
                article.author.avatar.url if article.author.avatar else None
            ),
            "author_aura": article.author.total_aura,
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


class ArticleListItem(Schema):
    """Simplified schema for article lists (without full content)"""

    id: int
    title: str
    subtitle: Optional[str] = None
    main_image_url: Optional[str] = None
    content_preview: str  # First 200 characters of content

    # Author info
    author_username: str
    author_display_name: str
    author_avatar: Optional[str] = None

    # Community info
    community_id: int
    community_name: str
    community_slug: Optional[str] = None

    # Status
    is_published: bool

    # Counts
    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0

    # User interaction
    is_author: bool = False
    is_bookmarked: bool = False

    # Timestamps
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_list(articles, profile=None):
        """
        Resolve a list of articles for list view.
        """
        return [ArticleListItem.resolve(article, profile) for article in articles]

    @staticmethod
    def resolve(article: Article, profile=None):
        """Resolve article data for list view"""

        # Initialize user-specific fields
        is_bookmarked = False
        is_author = False

        # Set user context if profile provided
        if profile:
            is_author = article.author.id == profile.id
            # is_bookmarked = Bookmark.is_bookmarked(profile, article)

        # Create content preview (first 200 characters)
        content_preview = (
            article.content[:200] + "..."
            if len(article.content) > 200
            else article.content
        )

        return {
            "id": article.id,
            "title": article.title,
            "subtitle": article.subtitle,
            "main_image_url": article.main_image.url if article.main_image else None,
            "content_preview": content_preview,
            "author_username": article.author.username,
            "author_display_name": article.author.display_name,
            "author_avatar": (
                article.author.avatar.url if article.author.avatar else None
            ),
            "community_id": article.community.id,
            "community_name": article.community.name,
            "community_slug": (
                article.community.slug if hasattr(article.community, "slug") else None
            ),
            "is_published": article.is_published,
            "view_count": getattr(article, "view_count", 0),
            "like_count": getattr(article, "like_count", 0),
            "comment_count": getattr(article, "comment_count", 0),
            "is_author": is_author,
            "is_bookmarked": is_bookmarked,
            "created_at": article.created_at,
            "updated_at": article.updated_at,
        }


class MessageSchema(Schema):
    """Standard message response schema"""

    message: str
