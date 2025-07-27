"""
Streak Service - Handles answer correctness calculation, aura management,
and streak tracking
"""

from datetime import date, timedelta
from typing import Any, Dict, List

from django.db import transaction
from django.db.models import F

from keyopolls.polls.models import (
    AuraTransaction,
    CommunityStreak,
    CommunityStreakActivity,
    Poll,
    PollAnswerResult,
)
from keyopolls.profile.models import PseudonymousProfile


class StreakService:
    """Service class for handling streaks, answer correctness, and aura management"""

    DAILY_POLL_TARGET = 5  # Number of polls needed per day for streak
    AURA_PER_POLL = 1  # Base aura awarded per poll participation

    @classmethod
    def calculate_poll_correctness(
        cls, poll: Poll, user_votes: List[Dict] = None, text_response: str = None
    ) -> bool:
        """
        Calculate if user's answer is correct based on poll type

        Args:
            poll: The poll instance
            user_votes: List of vote dictionaries with option_id and rank
            text_response: Text response for text input polls

        Returns:
            bool: True if answer is correct, False otherwise
        """
        if not poll.has_correct_answer:
            return True  # No correct answer defined, so participation counts as correct

        if poll.poll_type == "text_input":
            if not text_response or not poll.correct_text_answer:
                return False
            return (
                text_response.strip().lower()
                == poll.correct_text_answer.strip().lower()
            )

        elif poll.poll_type == "single":
            if not user_votes or len(user_votes) != 1:
                return False

            # Get the correct option
            correct_option = poll.options.filter(is_correct=True).first()
            if not correct_option:
                return False

            return user_votes[0]["option_id"] == correct_option.id

        elif poll.poll_type == "multiple":
            if not user_votes:
                return False

            # Get all correct option IDs
            correct_option_ids = set(
                poll.options.filter(is_correct=True).values_list("id", flat=True)
            )
            user_option_ids = set(vote["option_id"] for vote in user_votes)

            # Must select exactly all correct options
            return user_option_ids == correct_option_ids

        elif poll.poll_type == "ranking":
            if not user_votes or not poll.correct_ranking_order:
                return False

            # Build user's ranking order
            user_ranking = {}
            for vote in user_votes:
                user_ranking[vote["rank"]] = vote["option_id"]

            # Build ordered list from user's votes
            user_order = [
                user_ranking.get(rank)
                for rank in range(1, len(poll.correct_ranking_order) + 1)
            ]

            # Compare with correct order
            return user_order == poll.correct_ranking_order

        return False

    @classmethod
    def award_aura_for_poll(
        cls, profile: PseudonymousProfile, poll: Poll, is_correct: bool
    ) -> int:
        """
        Award aura to user for poll participation

        Args:
            profile: User profile
            poll: Poll instance
            is_correct: Whether answer was correct

        Returns:
            int: Amount of aura awarded
        """
        aura_amount = cls.AURA_PER_POLL

        # Create aura transaction record
        AuraTransaction.objects.create(
            profile=profile,
            transaction_type="poll_participation",
            amount=aura_amount,
            description=f"Participated in poll: {poll.title}",
            poll=poll,
            community=poll.community,
        )

        # Update user's total aura
        profile.total_aura = F("total_aura") + aura_amount
        profile.save(update_fields=["total_aura"])

        return aura_amount

    @classmethod
    def update_community_streak(
        cls, profile, community, activity_date: date = None
    ) -> Dict[str, Any]:
        """
        Update user's streak in a specific community

        Args:
            profile: User profile
            community: Community instance
            activity_date: Date of activity (defaults to today)

        Returns:
            dict: Updated streak information
        """
        if activity_date is None:
            activity_date = date.today()

        with transaction.atomic():
            # Get or create streak activity for this date
            activity, created = CommunityStreakActivity.objects.get_or_create(
                profile=profile,
                community=community,
                date=activity_date,
                defaults={"polls_answered": 0},
            )

            # Increment poll count
            activity.polls_answered = F("polls_answered") + 1
            activity.save(update_fields=["polls_answered", "updated_at"])
            activity.refresh_from_db()

            # Check if target is met for the first time today
            target_just_met = activity.check_target_met()

            if target_just_met:
                # Update the streak
                cls._update_streak_record(profile, community, activity_date)

            # Get updated streak info
            streak, created = CommunityStreak.objects.get_or_create(
                profile=profile, community=community
            )

            return {
                "current_streak": streak.current_streak,
                "max_streak": streak.max_streak,
                "polls_today": activity.polls_answered,
                "target_met": activity.target_met,
                "target_just_met": target_just_met,
            }

    @classmethod
    def _update_streak_record(cls, profile, community, activity_date: date):
        """
        Update the streak record when daily target is met
        """
        streak, created = CommunityStreak.objects.get_or_create(
            profile=profile,
            community=community,
            defaults={
                "current_streak": 0,
                "max_streak": 0,
                "last_activity_date": None,
                "streak_start_date": None,
            },
        )

        if created or streak.last_activity_date is None:
            # First time achieving target or no previous activity
            streak.current_streak = 1
            streak.last_activity_date = activity_date
            streak.streak_start_date = activity_date
            if streak.current_streak > streak.max_streak:
                streak.max_streak = streak.current_streak
        else:
            # Check if this continues the streak
            yesterday = activity_date - timedelta(days=1)

            if streak.last_activity_date == yesterday:
                # Continues streak
                streak.current_streak += 1
                streak.last_activity_date = activity_date
                if streak.current_streak > streak.max_streak:
                    streak.max_streak = streak.current_streak
            elif streak.last_activity_date == activity_date:
                # Same day, streak already updated
                pass
            else:
                # Gap in streak, reset
                streak.current_streak = 1
                streak.last_activity_date = activity_date
                streak.streak_start_date = activity_date

        streak.save()

    @classmethod
    def get_streak_calendar_data(
        cls, profile, community, days: int = 365
    ) -> Dict[str, Any]:
        """
        Get calendar data for streak visualization

        Args:
            profile: User profile
            community: Community instance
            days: Number of days to include in calendar

        Returns:
            dict: Calendar data with streak information
        """
        end_date = date.today()
        start_date = end_date - timedelta(days=days - 1)

        # Get streak record
        streak, created = CommunityStreak.objects.get_or_create(
            profile=profile, community=community
        )

        # Get activity data for the date range
        activities = CommunityStreakActivity.objects.filter(
            profile=profile, community=community, date__range=[start_date, end_date]
        ).values("date", "polls_answered", "target_met")

        # Create a lookup dict for activities
        activity_lookup = {activity["date"]: activity for activity in activities}

        # Build calendar data
        calendar_data = []
        current_date = start_date

        while current_date <= end_date:
            activity = activity_lookup.get(
                current_date, {"polls_answered": 0, "target_met": False}
            )

            calendar_data.append(
                {
                    "date": current_date.isoformat(),
                    "polls_count": activity["polls_answered"],
                    "target_met": activity["target_met"],
                    "is_today": current_date == end_date,
                }
            )

            current_date += timedelta(days=1)

        return {
            "current_streak": streak.current_streak,
            "max_streak": streak.max_streak,
            "streak_start_date": (
                streak.streak_start_date.isoformat()
                if streak.streak_start_date
                else None
            ),
            "last_activity_date": (
                streak.last_activity_date.isoformat()
                if streak.last_activity_date
                else None
            ),
            "calendar": calendar_data,
            "total_days_active": len([d for d in calendar_data if d["target_met"]]),
            "target_polls_per_day": cls.DAILY_POLL_TARGET,
        }

    @classmethod
    def get_user_streak_summary(cls, profile) -> List[Dict[str, Any]]:
        """
        Get summary of user's streaks across all communities

        Args:
            profile: User profile

        Returns:
            list: List of streak summaries for each community
        """
        streaks = (
            CommunityStreak.objects.filter(profile=profile)
            .select_related("community")
            .order_by("-current_streak")
        )

        summary = []
        for streak in streaks:
            summary.append(
                {
                    "community_id": streak.community.id,
                    "community_name": streak.community.name,
                    "current_streak": (
                        streak.current_streak if streak.current_streak else 0
                    ),
                    "max_streak": streak.max_streak if streak.max_streak else 0,
                    "last_activity_date": (
                        streak.last_activity_date.isoformat()
                        if streak.last_activity_date
                        else None
                    ),
                    "is_active": (
                        streak.last_activity_date == date.today()
                        if streak.last_activity_date
                        else False
                    ),
                }
            )

        return summary

    @classmethod
    def process_poll_answer(
        cls,
        profile,
        poll: Poll,
        user_votes: List[Dict] = None,
        text_response: str = None,
    ) -> Dict[str, Any]:
        """
        Main method to process a poll answer - handles correctness, aura, and streaks

        Args:
            profile: User profile
            poll: Poll instance
            user_votes: List of vote data for option-based polls
            text_response: Text response for text input polls

        Returns:
            dict: Complete processing result
        """
        with transaction.atomic():
            # Calculate correctness
            is_correct = cls.calculate_poll_correctness(poll, user_votes, text_response)

            # Create answer result record
            answer_result = PollAnswerResult.objects.create(
                poll=poll,
                profile=profile,
                is_correct=is_correct,
                aura_earned=cls.AURA_PER_POLL,
            )

            # Award aura
            aura_earned = cls.award_aura_for_poll(profile, poll, is_correct)

            # Update community streak
            streak_info = cls.update_community_streak(profile, poll.community)

            # Refresh profile to get updated aura
            profile.refresh_from_db()

            return {
                "is_correct": is_correct,
                "aura_earned": aura_earned,
                "total_aura": profile.total_aura,
                "streak_info": streak_info,
                "answer_result_id": answer_result.id,
            }
