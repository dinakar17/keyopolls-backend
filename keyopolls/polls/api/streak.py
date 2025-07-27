from typing import List

from ninja import Router

from keyopolls.common.schemas import Message
from keyopolls.communities.models import Community
from keyopolls.polls.models import AuraTransaction, CommunityStreak
from keyopolls.polls.schemas import (
    AuraTransactionSchema,
    CommunityStreakSchema,
    CommunityStreakSummarySchema,
    StreakCalendarSchema,
)
from keyopolls.profile.middleware import PseudonymousJWTAuth
from keyopolls.profile.models import PseudonymousProfile

router = Router(tags=["Streaks"])


@router.get(
    "/communities/{community_id}/streak",
    response={
        200: CommunityStreakSchema,
        404: Message,
    },
    auth=PseudonymousJWTAuth(),
)
def get_community_streak(request, community_id: int):
    """Get user's streak information for a specific community"""
    profile: PseudonymousProfile = request.auth

    try:
        community = Community.objects.get(id=community_id)
    except Community.DoesNotExist:
        return 404, {"message": "Community not found"}

    # Check if user has access to this community
    if not community.can_user_access(profile):
        return 404, {"message": "Community not found"}

    try:
        streak = CommunityStreak.objects.get(profile=profile, community=community)
        streak_data = {
            "community_id": community.id,
            "community_name": community.name,
            "current_streak": streak.current_streak,
            "max_streak": streak.max_streak,
            "last_activity_date": (
                streak.last_activity_date.isoformat()
                if streak.last_activity_date
                else None
            ),
            "streak_start_date": (
                streak.streak_start_date.isoformat()
                if streak.streak_start_date
                else None
            ),
        }
    except CommunityStreak.DoesNotExist:
        streak_data = {
            "community_id": community.id,
            "community_name": community.name,
            "current_streak": 0,
            "max_streak": 0,
            "last_activity_date": None,
            "streak_start_date": None,
        }

    return 200, streak_data


@router.get(
    "/communities/{community_id}/streak/calendar",
    response={
        200: StreakCalendarSchema,
        404: Message,
    },
    auth=PseudonymousJWTAuth(),
)
def get_streak_calendar(request, community_id: int, days: int = 365):
    """Get streak calendar data for visualization"""
    profile: PseudonymousProfile = request.auth

    try:
        community = Community.objects.get(id=community_id)
    except Community.DoesNotExist:
        return 404, {"message": "Community not found"}

    # Check if user has access to this community
    if not community.can_user_access(profile):
        return 404, {"message": "Community not found"}

    from keyopolls.polls.services.streak_service import StreakService

    calendar_data = StreakService.get_streak_calendar_data(
        profile, community, days=min(days, 730)  # Max 2 years
    )

    return 200, calendar_data


@router.get(
    "/profile/streaks",
    response={
        200: List[CommunityStreakSummarySchema],
        404: Message,
    },
    auth=PseudonymousJWTAuth(),
)
def get_user_streaks(request):
    """Get user's streaks across all communities"""
    profile: PseudonymousProfile = request.auth

    from keyopolls.polls.services.streak_service import StreakService

    streaks_summary = StreakService.get_user_streak_summary(profile)

    return 200, streaks_summary


@router.get(
    "/profile/aura/transactions",
    response={
        200: List[AuraTransactionSchema],
        404: Message,
    },
    auth=PseudonymousJWTAuth(),
)
def get_aura_transactions(request, limit: int = 50, offset: int = 0):
    """Get user's aura transaction history"""
    profile: PseudonymousProfile = request.auth

    transactions = (
        AuraTransaction.objects.filter(profile=profile)
        .select_related("poll", "community")
        .order_by("-created_at")[offset : offset + limit]
    )

    transaction_data = []
    for transaction in transactions:
        transaction_data.append(
            {
                "id": transaction.id,
                "transaction_type": transaction.transaction_type,
                "amount": transaction.amount,
                "description": transaction.description,
                "poll_id": transaction.poll.id if transaction.poll else None,
                "poll_title": transaction.poll.title if transaction.poll else None,
                "community_id": (
                    transaction.community.id if transaction.community else None
                ),
                "community_name": (
                    transaction.community.name if transaction.community else None
                ),
                "created_at": transaction.created_at.isoformat(),
            }
        )

    return 200, transaction_data
