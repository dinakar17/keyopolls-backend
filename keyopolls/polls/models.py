from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.utils import timezone

from keyopolls.communities.models import CommunityMembership


class Poll(models.Model):
    """Main poll model - simple and scalable"""

    POLL_TYPE_CHOICES = [
        ("single", "Single Choice"),
        ("multiple", "Multiple Choice"),
        ("ranking", "Ranking Poll"),
        # Future types can be added easily
    ]

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("active", "Active"),
        ("closed", "Closed"),
        ("archived", "Archived"),
    ]

    # Basic fields
    id = models.BigAutoField(primary_key=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    # Poll configuration
    poll_type = models.CharField(
        max_length=20, choices=POLL_TYPE_CHOICES, default="single"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")

    # Author
    profile = models.ForeignKey(
        "profile.PseudonymousProfile",
        on_delete=models.CASCADE,
        related_name="polls",
    )

    # Community (polls are always part of a community)
    community = models.ForeignKey(
        "Community", on_delete=models.CASCADE, related_name="polls"
    )

    # Community-specific settings
    is_pinned = models.BooleanField(default=False)  # Can be pinned in community
    allow_multiple_votes = models.BooleanField(default=False)  # For multiple choice
    max_choices = models.PositiveIntegerField(
        null=True, blank=True
    )  # Limit for multiple choice
    requires_aura = models.PositiveIntegerField(default=0)  # Minimum aura to vote

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
    bookmark_count = models.PositiveIntegerField(default=0)
    like_count = models.PositiveIntegerField(default=0)
    dislike_count = models.PositiveIntegerField(default=0)

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
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.get_poll_type_display()})"

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

        # Check if user is a member of the community
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


class PollOption(models.Model):
    """Poll options - supports text and images"""

    id = models.BigAutoField(primary_key=True)
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="options")

    # Option content
    text = models.CharField(max_length=200, blank=True)
    image = models.ImageField(upload_to="poll_options/", null=True, blank=True)

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
        ]
        ordering = ["order"]
        unique_together = ["poll", "order"]

    def __str__(self):
        return f"{self.poll.title} - Option {self.order}: {self.text or 'Image'}"

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
