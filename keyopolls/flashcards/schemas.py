from datetime import datetime
from typing import Dict, List, Optional

from ninja import Schema

from keyopolls.flashcards.models import Flashcard, FlashcardProgress, FlashcardSet


class FlashcardSchema(Schema):
    """Schema for individual flashcard"""

    id: int
    question: str
    answer: str
    hint: Optional[str] = None
    difficulty: str
    order: int
    created_at: datetime
    updated_at: datetime

    # User progress (only included when user is authenticated)
    user_progress: Optional[Dict] = None

    @staticmethod
    def resolve(flashcard: Flashcard, profile=None):
        """Resolve flashcard data with optional user progress"""
        user_progress = None

        if profile:
            try:
                progress = FlashcardProgress.objects.get(
                    user=profile, flashcard=flashcard
                )
                user_progress = {
                    "times_studied": progress.times_studied,
                    "times_correct": progress.times_correct,
                    "accuracy": progress.accuracy,
                    "mastery_level": progress.mastery_level,
                    "last_studied": progress.last_studied,
                }
            except FlashcardProgress.DoesNotExist:
                user_progress = {
                    "times_studied": 0,
                    "times_correct": 0,
                    "accuracy": 0,
                    "mastery_level": "learning",
                    "last_studied": None,
                }

        return {
            "id": flashcard.id,
            "question": flashcard.question,
            "answer": flashcard.answer,
            "hint": flashcard.hint,
            "difficulty": flashcard.difficulty,
            "order": flashcard.order,
            "created_at": flashcard.created_at,
            "updated_at": flashcard.updated_at,
            "user_progress": user_progress,
        }


class FlashcardCreateSchema(Schema):
    """Schema for creating a new flashcard"""

    question: str
    answer: str
    hint: Optional[str] = None
    difficulty: str = "medium"
    order: Optional[int] = None


class FlashcardUpdateSchema(Schema):
    """Schema for updating a flashcard"""

    question: Optional[str] = None
    answer: Optional[str] = None
    hint: Optional[str] = None
    difficulty: Optional[str] = None
    order: Optional[int] = None


class FlashcardSetCreateSchema(Schema):
    """Schema for creating a new flashcard set"""

    title: str
    description: Optional[str] = None
    community_id: int
    is_public: bool = True
    flashcards: List[FlashcardCreateSchema] = []


class FlashcardSetUpdateSchema(Schema):
    """Schema for updating a flashcard set"""

    title: Optional[str] = None
    description: Optional[str] = None
    is_public: Optional[bool] = None


class FlashcardSetDetails(Schema):
    """Complete flashcard set schema used across all endpoints"""

    id: int
    title: str
    description: Optional[str] = None

    # Creator info
    creator_username: str
    creator_display_name: str
    creator_avatar: Optional[str] = None
    creator_aura: int

    # Community info
    community_id: int
    community_name: str
    community_slug: Optional[str] = None
    community_avatar: Optional[str] = None

    # Settings
    is_public: bool

    # Counts
    flashcard_count: int
    view_count: int = 0
    like_count: int = 0
    dislike_count: int = 0
    share_count: int = 0
    study_count: int = 0  # Number of times this set has been studied

    # User interaction (only set when user is authenticated)
    is_creator: bool = False
    user_reactions: Dict[str, bool] = {}
    is_bookmarked: bool = False

    # User progress summary (only when authenticated)
    user_progress_summary: Optional[Dict] = None

    # Flashcards (included in detail view)
    flashcards: List[FlashcardSchema] = []

    # Timestamps
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_list(flashcard_sets, profile=None, include_flashcards=False):
        """
        Resolve a list of flashcard sets.
        """
        return [
            FlashcardSetDetails.resolve(fs, profile, include_flashcards)
            for fs in flashcard_sets
        ]

    @staticmethod
    def resolve(flashcard_set: FlashcardSet, profile=None, include_flashcards=True):
        """Resolve flashcard set data with optional user context"""

        # Initialize user-specific fields
        user_reactions = {}
        is_bookmarked = False
        is_creator = False
        user_progress_summary = None

        # Set user context if profile provided
        if profile:
            is_creator = flashcard_set.creator.id == profile.id

            # Get user reactions if you have a Reaction model
            # user_reactions = Reaction.get_user_reactions(profile, flashcard_set)

            # Check if bookmarked if you have a Bookmark model
            # is_bookmarked = Bookmark.is_bookmarked(profile, flashcard_set)

            # Calculate user progress summary
            if include_flashcards:
                total_flashcards = flashcard_set.flashcard_count()
                if total_flashcards > 0:
                    progress_data = FlashcardProgress.objects.filter(
                        user=profile, flashcard__flashcard_set=flashcard_set
                    )

                    studied_count = progress_data.count()
                    mastered_count = progress_data.filter(
                        mastery_level="mastered"
                    ).count()
                    total_accuracy = (
                        sum(p.accuracy for p in progress_data) / studied_count
                        if studied_count > 0
                        else 0
                    )

                    user_progress_summary = {
                        "total_flashcards": total_flashcards,
                        "studied_count": studied_count,
                        "mastered_count": mastered_count,
                        "progress_percentage": round(
                            (studied_count / total_flashcards) * 100, 1
                        ),
                        "mastery_percentage": round(
                            (mastered_count / total_flashcards) * 100, 1
                        ),
                        "average_accuracy": round(total_accuracy, 1),
                    }

        # Get flashcards if requested
        flashcards_data = []
        if include_flashcards:
            flashcards = flashcard_set.flashcards.all().order_by("order", "created_at")
            flashcards_data = [
                FlashcardSchema.resolve(fc, profile) for fc in flashcards
            ]

        return {
            "id": flashcard_set.id,
            "title": flashcard_set.title,
            "description": flashcard_set.description,
            "creator_username": flashcard_set.creator.username,
            "creator_display_name": flashcard_set.creator.display_name,
            "creator_avatar": (
                flashcard_set.creator.avatar.url
                if flashcard_set.creator.avatar
                else None
            ),
            "creator_aura": flashcard_set.creator.total_aura,
            "community_id": flashcard_set.community.id,
            "community_name": flashcard_set.community.name,
            "community_slug": (
                flashcard_set.community.slug
                if hasattr(flashcard_set.community, "slug")
                else None
            ),
            "community_avatar": (
                flashcard_set.community.avatar.url
                if hasattr(flashcard_set.community, "avatar")
                and flashcard_set.community.avatar
                else None
            ),
            "is_public": flashcard_set.is_public,
            "flashcard_count": flashcard_set.flashcard_count(),
            "view_count": getattr(flashcard_set, "view_count", 0),
            "like_count": getattr(flashcard_set, "like_count", 0),
            "dislike_count": getattr(flashcard_set, "dislike_count", 0),
            "share_count": getattr(flashcard_set, "share_count", 0),
            "study_count": getattr(flashcard_set, "study_count", 0),
            "is_creator": is_creator,
            "user_reactions": user_reactions,
            "is_bookmarked": is_bookmarked,
            "user_progress_summary": user_progress_summary,
            "flashcards": flashcards_data,
            "created_at": flashcard_set.created_at,
            "updated_at": flashcard_set.updated_at,
        }


class FlashcardSetListItem(Schema):
    """Simplified schema for flashcard set lists (without individual flashcards)"""

    id: int
    title: str
    description: Optional[str] = None

    # Creator info
    creator_username: str
    creator_display_name: str
    creator_avatar: Optional[str] = None

    # Community info
    community_id: int
    community_name: str
    community_slug: Optional[str] = None

    # Settings
    is_public: bool

    # Counts
    flashcard_count: int
    view_count: int = 0
    like_count: int = 0
    study_count: int = 0

    # User interaction
    is_creator: bool = False
    is_bookmarked: bool = False

    # User progress summary
    user_progress_summary: Optional[Dict] = None

    # Timestamps
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_list(flashcard_sets, profile=None):
        """
        Resolve a list of flashcard sets for list view.
        """
        return [FlashcardSetListItem.resolve(fs, profile) for fs in flashcard_sets]

    @staticmethod
    def resolve(flashcard_set: FlashcardSet, profile=None):
        """Resolve flashcard set data for list view"""

        # Initialize user-specific fields
        is_bookmarked = False
        is_creator = False
        user_progress_summary = None

        # Set user context if profile provided
        if profile:
            is_creator = flashcard_set.creator.id == profile.id
            # is_bookmarked = Bookmark.is_bookmarked(profile, flashcard_set)

            # Calculate basic progress summary
            total_flashcards = flashcard_set.flashcard_count()
            if total_flashcards > 0:
                studied_count = FlashcardProgress.objects.filter(
                    user=profile, flashcard__flashcard_set=flashcard_set
                ).count()

                mastered_count = FlashcardProgress.objects.filter(
                    user=profile,
                    flashcard__flashcard_set=flashcard_set,
                    mastery_level="mastered",
                ).count()

                user_progress_summary = {
                    "total_flashcards": total_flashcards,
                    "studied_count": studied_count,
                    "mastered_count": mastered_count,
                    "progress_percentage": round(
                        (studied_count / total_flashcards) * 100, 1
                    ),
                    "mastery_percentage": round(
                        (mastered_count / total_flashcards) * 100, 1
                    ),
                }

        return {
            "id": flashcard_set.id,
            "title": flashcard_set.title,
            "description": flashcard_set.description,
            "creator_username": flashcard_set.creator.username,
            "creator_display_name": flashcard_set.creator.display_name,
            "creator_avatar": (
                flashcard_set.creator.avatar.url
                if flashcard_set.creator.avatar
                else None
            ),
            "community_id": flashcard_set.community.id,
            "community_name": flashcard_set.community.name,
            "community_slug": (
                flashcard_set.community.slug
                if hasattr(flashcard_set.community, "slug")
                else None
            ),
            "is_public": flashcard_set.is_public,
            "flashcard_count": flashcard_set.flashcard_count(),
            "view_count": getattr(flashcard_set, "view_count", 0),
            "like_count": getattr(flashcard_set, "like_count", 0),
            "study_count": getattr(flashcard_set, "study_count", 0),
            "is_creator": is_creator,
            "is_bookmarked": is_bookmarked,
            "user_progress_summary": user_progress_summary,
            "created_at": flashcard_set.created_at,
            "updated_at": flashcard_set.updated_at,
        }


class StudySessionSchema(Schema):
    """Schema for recording study session results"""

    flashcard_id: int
    was_correct: bool


class StudySessionResultSchema(Schema):
    """Schema for study session results"""

    flashcard_id: int
    previous_mastery_level: str
    new_mastery_level: str
    accuracy: float
    times_studied: int


class MessageSchema(Schema):
    """Standard message response schema"""

    message: str
