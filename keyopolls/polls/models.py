from django.contrib.contenttypes.fields import GenericRelation
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from keyopolls.common.models import ImpressionTrackingMixin
from keyopolls.communities.models import CommunityMembership


class Poll(models.Model, ImpressionTrackingMixin):
    """Main poll model - simple and scalable"""

    POLL_TYPE_CHOICES = [
        ("single", "Single Choice"),
        ("multiple", "Multiple Choice"),
        ("ranking", "Ranking Poll"),
        ("text_input", "Text Input Poll"),
        # Future types can be added easily
    ]

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("pending_moderation", "Pending Moderation"),
        ("active", "Active"),
        ("rejected", "Rejected"),
        ("closed", "Closed"),
        ("archived", "Archived"),
    ]

    # Basic fields
    id = models.BigAutoField(primary_key=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    # Explanation
    explanation = models.TextField(blank=True)

    # Image for the poll (especially useful for text input polls)
    image = models.ImageField(upload_to="poll_images/", null=True, blank=True)

    # Poll configuration
    poll_type = models.CharField(
        max_length=20, choices=POLL_TYPE_CHOICES, default="single"
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="pending_moderation"
    )

    # Author
    profile = models.ForeignKey(
        "profile.PseudonymousProfile",
        on_delete=models.CASCADE,
        related_name="polls",
    )

    # Community (polls are always part of a community)
    community = models.ForeignKey(
        "communities.Community", on_delete=models.CASCADE, related_name="polls"
    )

    # Community-specific settings
    is_pinned = models.BooleanField(default=False)  # Can be pinned in community
    allow_multiple_votes = models.BooleanField(default=False)  # For multiple choice
    max_choices = models.PositiveIntegerField(
        null=True, blank=True
    )  # Limit for multiple choice
    requires_aura = models.PositiveIntegerField(default=0)  # Minimum aura to vote

    # Correct answers feature
    has_correct_answer = models.BooleanField(default=False)
    correct_text_answer = models.CharField(
        max_length=50, blank=True, null=True
    )  # For text input polls
    correct_ranking_order = models.JSONField(
        null=True, blank=True
    )  # For ranking polls - list of option IDs in correct order

    # Timing
    expires_at = models.DateTimeField(null=True, blank=True)

    # Denormalized counts for performance
    total_votes = models.PositiveIntegerField(default=0)
    total_voters = models.PositiveIntegerField(default=0)  # Unique voters
    option_count = models.PositiveIntegerField(default=0)

    # Engagement metrics
    view_count = models.PositiveIntegerField(default=0)
    comment_count = models.PositiveIntegerField(default=0)
    share_count = models.PositiveIntegerField(default=0)
    impressions_count = models.PositiveIntegerField(default=0)
    bookmark_count = models.PositiveIntegerField(default=0)
    like_count = models.PositiveIntegerField(default=0)
    dislike_count = models.PositiveIntegerField(default=0)

    # Moderation fields
    moderation_reason = models.TextField(blank=True, null=True)
    moderated_at = models.DateTimeField(null=True, blank=True)

    # Generic relations for comments, reactions, etc.
    comments = GenericRelation("comments.GenericComment")
    reactions = GenericRelation("common.Reaction")

    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    # Soft deletion
    is_deleted = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["profile", "-created_at"]),
            models.Index(fields=["community", "-created_at"]),
            models.Index(fields=["community", "is_pinned", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["poll_type", "-created_at"]),
            models.Index(fields=["expires_at"]),
            models.Index(fields=["-total_votes"]),
            models.Index(fields=["is_deleted", "status"]),
            models.Index(fields=["status", "community", "-created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.get_poll_type_display()})"

    def clean(self):
        """Validate model constraints"""
        if self.has_correct_answer:
            if self.poll_type == "text_input" and not self.correct_text_answer:
                raise ValidationError(
                    (
                        "Text input polls with correct answers must have "
                        "correct_text_answer set"
                    )
                )
            elif self.poll_type == "ranking" and not self.correct_ranking_order:
                raise ValidationError(
                    (
                        "Ranking polls with correct answers must have "
                        "correct_ranking_order set"
                    )
                )

    @property
    def is_active(self):
        """Check if poll is active and not expired"""
        if self.status != "active":
            return False
        if self.expires_at and timezone.now() > self.expires_at:
            return False
        return True

    @property
    def is_expired(self):
        """Check if poll has expired"""
        return self.expires_at and timezone.now() > self.expires_at

    def can_vote(self, profile):
        """Check if profile can vote on this poll"""
        if not self.is_active:
            return False
        if self.requires_aura > 0 and profile.total_aura < self.requires_aura:
            return False

        # Check membership only for private and restricted communities
        if self.community.community_type in ["private", "restricted"]:
            try:
                membership = self.community.memberships.get(profile=profile)
                if not membership.is_active_member:
                    return False
            except CommunityMembership.DoesNotExist:
                return False

        return True

    def increment_vote_count(self, is_new_voter=False):
        """Increment vote counts efficiently"""
        self.total_votes = models.F("total_votes") + 1
        if is_new_voter:
            self.total_voters = models.F("total_voters") + 1
        self.save(update_fields=["total_votes", "total_voters"])

    def decrement_vote_count(self, is_removing_voter=False):
        """Decrement vote counts efficiently"""
        self.total_votes = models.F("total_votes") - 1
        if is_removing_voter:
            self.total_voters = models.F("total_voters") - 1
        self.save(update_fields=["total_votes", "total_voters"])

    def approve_poll(self):
        """Approve the poll after successful moderation"""
        self.status = "active"
        self.moderated_at = timezone.now()
        self.save(update_fields=["status", "moderated_at"])

    def reject_poll(self, reason=""):
        """Reject the poll after failed moderation"""
        self.status = "rejected"
        self.moderation_reason = reason
        self.moderated_at = timezone.now()
        self.save(update_fields=["status", "moderation_reason", "moderated_at"])

    def get_correct_answer_stats(self):
        """Get statistics about correct answers"""
        if not self.has_correct_answer or self.total_voters == 0:
            return {"correct_count": 0, "correct_percentage": 0.0}

        correct_count = 0

        if self.poll_type == "single":
            # Count votes for the correct option
            correct_option = self.options.filter(is_correct=True).first()
            if correct_option:
                correct_count = (
                    correct_option.votes.values("profile").distinct().count()
                )

        elif self.poll_type == "multiple":
            # Count users who selected exactly all correct options
            correct_option_ids = set(
                self.options.filter(is_correct=True).values_list("id", flat=True)
            )
            if correct_option_ids:
                # Get users and their selected option IDs
                user_votes = {}
                for vote in self.votes.all():
                    if vote.profile_id not in user_votes:
                        user_votes[vote.profile_id] = set()
                    user_votes[vote.profile_id].add(vote.option_id)

                # Count users who selected exactly the correct options
                for user_options in user_votes.values():
                    if user_options == correct_option_ids:
                        correct_count += 1

        elif self.poll_type == "ranking":
            # Count users who ranked in the correct order
            if self.correct_ranking_order:
                correct_order = self.correct_ranking_order
                user_votes = {}
                for vote in self.votes.all():
                    if vote.profile_id not in user_votes:
                        user_votes[vote.profile_id] = {}
                    user_votes[vote.profile_id][vote.rank] = vote.option_id

                # Check each user's ranking
                for user_rankings in user_votes.values():
                    user_order = [
                        user_rankings.get(rank)
                        for rank in range(1, len(correct_order) + 1)
                    ]
                    if user_order == correct_order:
                        correct_count += 1

        elif self.poll_type == "text_input":
            # Count text responses that match the correct answer
            correct_count = self.text_responses.filter(
                text_value__iexact=self.correct_text_answer
            ).count()

        correct_percentage = round((correct_count / self.total_voters) * 100, 1)
        return {
            "correct_count": correct_count,
            "correct_percentage": correct_percentage,
        }


class PollOption(models.Model):
    """Poll options - supports text and images"""

    id = models.BigAutoField(primary_key=True)
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="options")

    # Option content
    text = models.CharField(max_length=200, blank=True)
    image = models.ImageField(upload_to="poll_options/", null=True, blank=True)

    # Correct answer flag
    is_correct = models.BooleanField(default=False)

    # Display order
    order = models.PositiveIntegerField(default=0)

    # Denormalized vote count for performance
    vote_count = models.PositiveIntegerField(default=0)

    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=["poll", "order"]),
            models.Index(fields=["poll", "-vote_count"]),
            models.Index(fields=["poll", "is_correct"]),
        ]
        ordering = ["order"]
        unique_together = ["poll", "order"]

    def __str__(self):
        return f"{self.poll.title} - Option {self.order}: {self.text or 'Image'}"

    def clean(self):
        """Validate that text input polls don't have options"""
        if self.poll and self.poll.poll_type == "text_input":
            raise ValidationError("Text input polls cannot have predefined options")

    @property
    def vote_percentage(self):
        """Calculate vote percentage for this option"""
        if self.poll.total_votes == 0:
            return 0
        return round((self.vote_count / self.poll.total_votes) * 100, 1)

    def increment_vote_count(self):
        """Increment vote count efficiently"""
        self.vote_count = models.F("vote_count") + 1
        self.save(update_fields=["vote_count"])

    def decrement_vote_count(self):
        """Decrement vote count efficiently"""
        self.vote_count = models.F("vote_count") - 1
        self.save(update_fields=["vote_count"])


class PollVote(models.Model):
    """Individual votes - handles all poll types efficiently"""

    id = models.BigAutoField(primary_key=True)
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="votes")
    option = models.ForeignKey(
        PollOption, on_delete=models.CASCADE, related_name="votes"
    )
    profile = models.ForeignKey(
        "profile.PseudonymousProfile",
        on_delete=models.CASCADE,
        related_name="poll_votes",
    )

    # For ranking polls - store the rank (1 = first choice, 2 = second, etc.)
    rank = models.PositiveIntegerField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["poll", "profile"]),
            models.Index(fields=["option", "-created_at"]),
            models.Index(fields=["profile", "-created_at"]),
            models.Index(fields=["poll", "option", "profile"]),  # For quick lookups
        ]
        # Allow multiple votes per user for multiple choice and ranking
        # Uniqueness is enforced at the application level based on poll type

    def __str__(self):
        rank_str = f" (Rank {self.rank})" if self.rank else ""
        return f"{self.profile.username} voted for {self.option.text}{rank_str}"


class PollTextResponse(models.Model):
    """Text responses for text input polls"""

    id = models.BigAutoField(primary_key=True)
    poll = models.ForeignKey(
        Poll, on_delete=models.CASCADE, related_name="text_responses"
    )
    profile = models.ForeignKey(
        "profile.PseudonymousProfile",
        on_delete=models.CASCADE,
        related_name="text_responses",
    )

    # The user's text input (single word/number, no spaces)
    text_value = models.CharField(max_length=50)

    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["poll", "text_value"]),
            models.Index(fields=["poll", "profile"]),
            models.Index(fields=["profile", "-created_at"]),
        ]
        unique_together = ["poll", "profile"]  # One response per user per poll

    def clean(self):
        """Validate text input"""
        if self.text_value and " " in self.text_value.strip():
            raise ValidationError("Text input cannot contain spaces")

        if self.poll and self.poll.poll_type != "text_input":
            raise ValidationError(
                "Text responses can only be added to text input polls"
            )

    def save(self, *args, **kwargs):
        # Clean and validate the text value
        self.text_value = self.text_value.strip()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.profile.username} responded '{self.text_value}' "
            f"to {self.poll.title}"
        )


class PollTextAggregate(models.Model):
    """Aggregated text responses for efficient querying"""

    id = models.BigAutoField(primary_key=True)
    poll = models.ForeignKey(
        Poll, on_delete=models.CASCADE, related_name="text_aggregates"
    )

    # The text value and its count
    text_value = models.CharField(max_length=50)
    response_count = models.PositiveIntegerField(default=0)

    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["poll", "-response_count"]),
            models.Index(fields=["poll", "text_value"]),
        ]
        unique_together = ["poll", "text_value"]
        ordering = ["-response_count", "text_value"]

    def __str__(self):
        return (
            f"{self.poll.title} - '{self.text_value}': {self.response_count} responses"
        )

    @classmethod
    def update_aggregates_for_poll(cls, poll):
        """Update aggregates for a specific poll"""
        if poll.poll_type != "text_input":
            return

        # Get current counts from responses
        from django.db.models import Count

        response_counts = (
            poll.text_responses.values("text_value")
            .annotate(count=Count("text_value"))
            .values_list("text_value", "count")
        )

        # Update or create aggregates
        existing_aggregates = {
            agg.text_value: agg for agg in cls.objects.filter(poll=poll)
        }

        for text_value, count in response_counts:
            if text_value in existing_aggregates:
                agg = existing_aggregates[text_value]
                if agg.response_count != count:
                    agg.response_count = count
                    agg.save(update_fields=["response_count", "updated_at"])
            else:
                cls.objects.create(
                    poll=poll, text_value=text_value, response_count=count
                )

        # Remove aggregates that no longer have responses
        current_values = {text_value for text_value, _ in response_counts}
        cls.objects.filter(poll=poll).exclude(text_value__in=current_values).delete()

    @property
    def percentage(self):
        """Calculate percentage of total responses"""
        if self.poll.total_voters == 0:
            return 0
        return round((self.response_count / self.poll.total_voters) * 100, 1)


class PollTodo(models.Model):
    """Simple todo items for polls"""

    id = models.BigAutoField(primary_key=True)
    poll = models.ForeignKey(
        "polls.Poll", on_delete=models.CASCADE, related_name="todos"
    )
    profile = models.ForeignKey(
        "profile.PseudonymousProfile",
        on_delete=models.CASCADE,
        related_name="poll_todos",
    )

    text = models.CharField(max_length=200)
    is_completed = models.BooleanField(default=False)

    created_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["poll", "-created_at"]),
            models.Index(fields=["profile", "-created_at"]),
        ]
        ordering = ["is_completed", "-created_at"]

    def __str__(self):
        status = "✅" if self.is_completed else "⏳"
        return f"{status} {self.text}"

    def mark_completed(self):
        """Mark todo as completed"""
        self.is_completed = True
        self.completed_at = timezone.now()
        self.save()

    def mark_incomplete(self):
        """Mark todo as incomplete"""
        self.is_completed = False
        self.completed_at = None
        self.save()
