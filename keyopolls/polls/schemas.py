from datetime import datetime
from typing import Any, Dict, List, Optional

from django.contrib.contenttypes.models import ContentType
from ninja import Schema

from keyopolls.common.models import Bookmark, Reaction, TaggedItem
from keyopolls.polls.models import Poll, PollTodo, PollVote
from keyopolls.polls.services import (
    calculate_multiple_choice_distribution,
    calculate_option_ranking_results,
    calculate_rank_breakdown,
)
from keyopolls.profile.models import PseudonymousProfile


# Input Schemas
class PollOptionCreateSchema(Schema):
    text: str = ""
    order: int
    is_correct: bool = False  # For correct answers
    # Note: image will be handled separately via file upload


class TodoItemSchema(Schema):
    id: Optional[int] = None
    text: str

    def resolve(todo: PollTodo) -> Dict[str, str]:
        """Resolve PollTodo to dictionary"""
        return {
            "id": todo.id if todo.id else None,
            "text": todo.text,
        }


class PollCreateSchema(Schema):
    title: str
    description: Optional[str] = ""
    poll_type: str  # 'single', 'multiple', 'ranking', 'text_input'
    community_id: int

    explanation: Optional[str] = None  # Explanation for correct answers (optional)
    todos: Optional[List[TodoItemSchema]] = None  # List of todo items

    # Poll settings
    allow_multiple_votes: bool = False
    max_choices: Optional[int] = None
    requires_aura: int = 0
    expires_at: Optional[datetime] = None  # Poll expiration time

    # Correct answers feature (For single and multiple choice polls
    # correct answers are present in options)
    has_correct_answer: bool = False
    correct_text_answer: Optional[str] = None  # For text input polls
    correct_ranking_order: Optional[List[int]] = (
        None  # Option IDs in correct order for ranking polls
    )

    # Options (not used for text_input polls)
    options: List[PollOptionCreateSchema] = []

    tags: Optional[List[str]] = None  # Tags for categorization


class PollUpdateSchema(Schema):
    title: str
    description: str = ""
    tags: Optional[List[str]] = None  # Tags for categorization
    explanation: Optional[str] = None  # Explanation for correct answers (optional)


# Vote Input Schemas
class VoteData(Schema):
    option_id: int
    rank: Optional[int] = None  # Required for ranking polls


class CastVoteSchema(Schema):
    poll_id: int
    votes: List[VoteData] = []  # Empty for text input polls
    text_value: Optional[str] = None  # For text input polls


class TextInputVoteSchema(Schema):
    poll_id: int
    text_value: str


# Response Schemas
class PollOptionResponseSchema(Schema):
    id: int
    text: str
    image_url: Optional[str] = None
    order: int
    vote_count: int
    vote_percentage: float
    is_correct: bool = False

    @staticmethod
    def resolve(option):
        return {
            "id": option.id,
            "text": option.text,
            "image_url": option.image.url if option.image else None,
            "order": option.order,
            "vote_count": option.vote_count,
            "vote_percentage": option.vote_percentage,
            "is_correct": option.is_correct,
        }


class TextResponseSchema(Schema):
    text_value: str
    response_count: int
    percentage: float
    is_correct: bool = False


class MultipleChoiceStatsSchema(Schema):
    choice_count: int  # Number of options selected (1, 2, 3, etc.)
    user_count: int  # Number of users who selected exactly this many options
    percentage: float  # Percentage of total voters


# Single option schema that handles all poll types
class PollOptionSchema(Schema):
    id: int
    text: str
    image_url: Optional[str] = None
    order: int
    vote_count: int
    vote_percentage: float
    is_correct: bool = False

    # For ranking polls - best performing rank
    best_rank: Optional[int] = None
    best_rank_percentage: Optional[float] = None

    # Full rank breakdown (optional, for detailed view)
    rank_breakdown: Optional[Dict[int, float]] = None

    @staticmethod
    def resolve_with_results(option, poll, include_rank_breakdown=False):
        """Resolve option with full results"""
        base_data = {
            "id": option.id,
            "text": option.text,
            "image_url": option.image.url if option.image else None,
            "order": option.order,
            "vote_count": option.vote_count,
            "vote_percentage": option.vote_percentage,
            "is_correct": option.is_correct,
        }

        # Add ranking data for ranking polls
        if poll.poll_type == "ranking":
            ranking_data = calculate_option_ranking_results(option, poll)
            base_data.update(ranking_data)

            if include_rank_breakdown:
                base_data["rank_breakdown"] = calculate_rank_breakdown(option, poll)

        return base_data

    @staticmethod
    def resolve_without_results(option):
        """Resolve option without results (for users who haven't voted)"""
        return {
            "id": option.id,
            "text": option.text,
            "image_url": option.image.url if option.image else None,
            "order": option.order,
            "vote_count": 0,
            "vote_percentage": 0.0,
            "is_correct": False,  # Don't reveal correct answers until after voting
            "best_rank": None,
            "best_rank_percentage": None,
            "rank_breakdown": None,
        }


class UserVoteDetails(Schema):
    option_id: int
    rank: Optional[int] = None
    voted_at: datetime


class UserTextResponse(Schema):
    text_value: str
    responded_at: datetime


class CorrectAnswerStats(Schema):
    correct_count: int
    correct_percentage: float


class PollCreateError(Schema):
    """Schema for poll creation errors"""

    message: str
    poll_id: Optional[int] = None  # For audit purposes, if applicable


class PollDetails(Schema):
    """Common poll schema used across all endpoints"""

    id: int
    title: str
    description: str
    explanation: str
    image_url: Optional[str] = None  # Poll image (especially for text input polls)
    poll_type: str
    status: str
    tags: List[str] = []  # List of tag slugs

    # Author info
    author_username: str
    author_display_name: str
    author_avatar: Optional[str] = None  # Author's avatar URL
    author_aura: int

    # Community info
    community_id: int
    community_name: str
    community_slug: Optional[str] = None  # Slug for URL-friendly names
    community_avatar: Optional[str] = None

    # Settings
    allow_multiple_votes: bool
    max_choices: Optional[int] = None
    requires_aura: int
    is_pinned: bool

    # Correct answers
    has_correct_answer: bool
    correct_answer_stats: Optional[CorrectAnswerStats] = None
    correct_ranking_order: Optional[List[int]] = None  # For ranking polls
    correct_text_answer: Optional[str] = None  # For text input polls

    # NEW: Answer tracking fields
    user_answer_correct: Optional[bool] = None
    user_earned_aura: Optional[int] = None
    user_streak_info: Optional[Dict[str, Any]] = None

    # Status
    is_active: bool

    # Poll Todos
    todos: List[TodoItemSchema] = []  # List of todo items (if applicable)

    # Counts
    total_votes: int
    total_voters: int
    option_count: int
    view_count: int
    comment_count: int
    like_count: int
    dislike_count: int
    share_count: int
    impressions_count: int

    # Results (type depends on poll_type)
    options: List[PollOptionSchema] = []  # For single, multiple, ranking polls
    text_responses: List[TextResponseSchema] = []  # For text input polls
    multiple_choice_stats: List[MultipleChoiceStatsSchema] = (
        []
    )  # For multiple choice polls

    # User interaction (only set when user is authenticated)
    user_can_vote: bool = False
    user_has_voted: bool = False
    is_author: bool = False
    show_results: bool = False
    user_reactions: Dict[str, bool] = {}
    is_bookmarked: bool = False

    # User's actual votes/responses
    user_votes: List[UserVoteDetails] = []  # For option-based polls
    user_text_response: Optional[UserTextResponse] = None  # For text input polls

    # Timestamps
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_list(polls, profile=None):
        """
        Resolve a list of polls.
        """
        return [PollDetails.resolve(poll, profile) for poll in polls]

    @staticmethod
    def resolve(poll: Poll, profile: Optional[PseudonymousProfile] = None):
        """Resolve poll data with optional user context"""

        # Initialize user-specific fields
        user_can_vote = False
        user_has_voted = False
        user_reactions = {}
        is_bookmarked = False
        is_author = False
        show_results = False
        user_votes = []
        user_text_response = None

        # Set user context if profile provided
        if profile:
            is_author = poll.profile.id == profile.id
            user_can_vote = poll.can_vote(profile)

            user_reactions = Reaction.get_user_reactions(profile, poll)
            is_bookmarked = Bookmark.is_bookmarked(profile, poll)

            # Check if user has voted based on poll type
            if poll.poll_type == "text_input":
                try:
                    text_response = poll.text_responses.get(profile=profile)
                    user_has_voted = True
                    user_text_response = {
                        "text_value": text_response.text_value,
                        "responded_at": text_response.created_at,
                    }
                except poll.text_responses.model.DoesNotExist:
                    user_has_voted = False
            else:
                # Get user's votes for option-based polls
                user_poll_votes = PollVote.objects.filter(
                    poll=poll, profile=profile
                ).select_related("option")
                user_has_voted = user_poll_votes.exists()

                # Extract user vote details
                if user_has_voted:
                    user_votes = [
                        {
                            "option_id": vote.option.id,
                            "rank": vote.rank,
                            "voted_at": vote.created_at,
                        }
                        for vote in user_poll_votes
                    ]

        # Determine if we should show results
        show_results = (
            user_has_voted  # User has voted
            or is_author  # User is the author
            or poll.status in ["closed", "archived"]  # Poll is finished
            or not poll.is_active  # Poll is not active
        )

        # Get correct answer stats if applicable
        correct_answer_stats = None
        if poll.has_correct_answer and show_results:
            stats = poll.get_correct_answer_stats()
            correct_answer_stats = {
                "correct_count": stats["correct_count"],
                "correct_percentage": stats["correct_percentage"],
            }

        # Prepare response data based on poll type
        options_data = []
        text_responses_data = []
        multiple_choice_stats_data = []

        if poll.poll_type == "text_input":
            # Get text response aggregates
            if show_results:
                aggregates = poll.text_aggregates.all().order_by("-response_count")
                text_responses_data = [
                    {
                        "text_value": agg.text_value,
                        "response_count": agg.response_count,
                        "percentage": agg.percentage,
                        "is_correct": (
                            (
                                poll.has_correct_answer
                                and agg.text_value.lower()
                                == poll.correct_text_answer.lower()
                            )
                            if poll.correct_text_answer
                            else False
                        ),
                    }
                    for agg in aggregates
                ]
        else:
            # Get options for choice-based polls
            if show_results:
                options_data = [
                    PollOptionSchema.resolve_with_results(option, poll)
                    for option in poll.options.all().order_by("order")
                ]

                # Add multiple choice distribution stats
                if poll.poll_type == "multiple":
                    distribution = calculate_multiple_choice_distribution(poll)
                    multiple_choice_stats_data = [
                        {
                            "choice_count": choice_count,
                            "user_count": user_count,
                            "percentage": (
                                round((user_count / poll.total_voters) * 100, 1)
                                if poll.total_voters > 0
                                else 0
                            ),
                        }
                        for choice_count, user_count in sorted(distribution.items())
                    ]
            else:
                options_data = [
                    PollOptionSchema.resolve_without_results(option)
                    for option in poll.options.all().order_by("order")
                ]

        poll_content_type = ContentType.objects.get_for_model(poll)
        tagged_items = TaggedItem.objects.filter(
            content_type=poll_content_type, object_id=poll.id
        ).select_related("tag")

        tags_data = [tagged_item.tag.slug for tagged_item in tagged_items]

        return {
            "id": poll.id,
            "title": poll.title,
            "description": poll.description,
            "explanation": poll.explanation,
            "image_url": poll.image.url if poll.image else None,
            "poll_type": poll.poll_type,
            "status": poll.status,
            "tags": tags_data,  # Returns list of tag slugs
            "author_username": poll.profile.username,
            "author_display_name": poll.profile.display_name,
            "author_avatar": (poll.profile.avatar.url if poll.profile.avatar else None),
            "author_aura": poll.profile.total_aura,
            "community_id": poll.community.id,
            "community_name": poll.community.name,
            "community_slug": poll.community.slug if poll.community.slug else None,
            "community_avatar": (
                poll.community.avatar.url if poll.community.avatar else None
            ),
            "allow_multiple_votes": poll.allow_multiple_votes,
            "max_choices": poll.max_choices,
            "requires_aura": poll.requires_aura,
            "is_pinned": poll.is_pinned,
            "todos": [TodoItemSchema.resolve(todo) for todo in poll.todos.all()],
            "has_correct_answer": poll.has_correct_answer,
            "correct_answer_stats": correct_answer_stats,
            "correct_ranking_order": (
                poll.correct_ranking_order if poll.poll_type == "ranking" else None
            ),
            "correct_text_answer": (
                poll.correct_text_answer if poll.poll_type == "text_input" else None
            ),
            "is_active": poll.is_active,
            "total_votes": poll.total_votes,
            "total_voters": poll.total_voters,
            "option_count": poll.option_count,
            "view_count": poll.view_count,
            "impressions_count": poll.impressions_count,
            "like_count": poll.like_count,
            "dislike_count": poll.dislike_count,
            "share_count": poll.share_count,
            "comment_count": poll.comment_count,
            "options": options_data,
            "text_responses": text_responses_data,
            "multiple_choice_stats": multiple_choice_stats_data,
            "user_can_vote": user_can_vote,
            "user_has_voted": user_has_voted,
            "user_reactions": user_reactions,
            "is_bookmarked": is_bookmarked,
            "is_author": is_author,
            "show_results": show_results,
            "user_votes": user_votes,
            "user_text_response": user_text_response,
            "created_at": poll.created_at,
            "updated_at": poll.updated_at,
        }


class PollListResponseSchema(Schema):
    items: List[PollDetails]
    total: int
    page: int
    pages: int
    page_size: int
    has_next: bool
    has_previous: bool


# Streak-related schemas
class CommunityStreakSchema(Schema):
    """Community streak information"""

    community_id: int
    community_name: str
    current_streak: int
    max_streak: int
    last_activity_date: Optional[str] = None  # ISO date string
    streak_start_date: Optional[str] = None  # ISO date string


class CommunityStreakSummarySchema(Schema):
    """Summary of user's streak in a community"""

    community_id: int
    community_name: str
    current_streak: int
    max_streak: int
    last_activity_date: Optional[str] = None
    is_active: bool


class StreakCalendarDaySchema(Schema):
    """Single day in streak calendar"""

    date: str  # ISO date string
    polls_count: int
    target_met: bool
    is_today: bool


class StreakCalendarSchema(Schema):
    """Complete streak calendar data"""

    current_streak: int
    max_streak: int
    streak_start_date: Optional[str] = None
    last_activity_date: Optional[str] = None
    calendar: List[StreakCalendarDaySchema]
    total_days_active: int
    target_polls_per_day: int


class AuraTransactionSchema(Schema):
    """Aura transaction details"""

    id: int
    transaction_type: str
    amount: int
    description: str
    poll_id: Optional[int] = None
    poll_title: Optional[str] = None
    community_id: Optional[int] = None
    community_name: Optional[str] = None
    created_at: str  # ISO datetime string
