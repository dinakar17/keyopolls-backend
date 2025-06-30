from django.core.exceptions import ValidationError
from django.db import models

# Todo: Remove null=True and blank=True from ForeignKey fields later


class Follow(models.Model):
    """
    Follow relationship between public profiles only.
    A public profile can follow another public profile.
    """

    # Who is following (the follower) - always a PublicProfile
    follower = models.ForeignKey(
        "profiles.PublicProfile",
        on_delete=models.CASCADE,
        related_name="following_relationships",
        null=True,
        blank=True,
    )

    # Who is being followed (the followee) - always a PublicProfile
    followee = models.ForeignKey(
        "profiles.PublicProfile",
        on_delete=models.CASCADE,
        related_name="follower_relationships",
        null=True,
        blank=True,
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)  # For soft deletes/blocks

    # Notification preferences
    notify_on_posts = models.BooleanField(default=True)

    class Meta:
        # Ensure unique follow relationships
        unique_together = ("follower", "followee")

        indexes = [
            # Index for finding followers of a profile
            models.Index(fields=["followee", "is_active"]),
            # Index for finding who a profile follows
            models.Index(fields=["follower", "is_active"]),
            # Index for recent follows
            models.Index(fields=["-created_at"]),
        ]

        ordering = ["-created_at"]

    def __str__(self):
        follower_name = self.follower.display_name or f"@{self.follower.handle}"
        followee_name = self.followee.display_name or f"@{self.followee.handle}"
        return f"{follower_name} follows {followee_name}"

    def clean(self):
        """Validate the follow relationship"""
        # Prevent self-following
        if self.follower == self.followee:
            raise ValidationError("A profile cannot follow itself")

        # Prevent following profiles from the same member
        if self.follower.id == self.followee.id:
            raise ValidationError("Cannot follow profiles from the same member")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

        # Update follower/following counts after saving
        self._update_counts()

    def delete(self, *args, **kwargs):
        # Store references before deletion
        follower = self.follower
        followee = self.followee

        super().delete(*args, **kwargs)

        # Update counts after deletion
        self._update_counts_for_profiles(follower, followee)

    def _update_counts(self):
        """Update follower/following counts for both profiles"""
        self._update_counts_for_profiles(self.follower, self.followee)

    def _update_counts_for_profiles(self, follower_profile, followee_profile):
        """Update counts for specific profiles"""
        # Update follower's following count
        following_count = Follow.objects.filter(
            follower=follower_profile,
            is_active=True,
        ).count()
        follower_profile.following_count = following_count
        follower_profile.save(update_fields=["following_count"])

        # Update followee's follower count
        follower_count = Follow.objects.filter(
            followee=followee_profile,
            is_active=True,
        ).count()
        followee_profile.follower_count = follower_count
        followee_profile.save(update_fields=["follower_count"])


class FollowRequest(models.Model):
    """
    Follow requests for private/restricted public profiles that require approval.
    """

    # Who wants to follow (the requester) - always a PublicProfile
    requester = models.ForeignKey(
        "profiles.PublicProfile",
        on_delete=models.CASCADE,
        related_name="follow_requests_made",
        null=True,
        blank=True,
    )

    # Who is being requested to follow (the target) - always a PublicProfile
    target = models.ForeignKey(
        "profiles.PublicProfile",
        on_delete=models.CASCADE,
        related_name="follow_requests_received",
        null=True,
        blank=True,
    )

    # Request status
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("expired", "Expired"),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")

    # Optional message from requester
    message = models.TextField(max_length=500, blank=True, null=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(null=True, blank=True)  # Auto-expire requests

    class Meta:
        unique_together = ("requester", "target")

        indexes = [
            # Index for pending requests to a profile
            models.Index(fields=["target", "status"]),
            # Index for requests made by a profile
            models.Index(fields=["requester", "status"]),
            # Index for recent requests
            models.Index(fields=["-created_at"]),
        ]

        ordering = ["-created_at"]

    def __str__(self):
        requester_name = self.requester.display_name or f"@{self.requester.handle}"
        target_name = self.target.display_name or f"@{self.target.handle}"
        return f"{requester_name} requests to follow {target_name}"

    def clean(self):
        """Validate the follow request"""
        # Prevent self-follow request
        if self.requester == self.target:
            raise ValidationError("A profile cannot request to follow itself")

        # Prevent requesting to follow profiles from the same member
        if hasattr(self.requester, "member") and hasattr(self.target, "member"):
            if self.requester.member == self.target.member:
                raise ValidationError(
                    "Cannot request to follow profiles from the same member"
                )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def approve(self):
        """Approve the follow request and create the follow relationship"""
        if self.status != "pending":
            raise ValidationError("Only pending requests can be approved")

        # Create the follow relationship
        Follow.objects.create(
            follower=self.requester,
            followee=self.target,
        )

        # Update request status
        self.status = "approved"
        self.save(update_fields=["status", "updated_at"])

    def reject(self):
        """Reject the follow request"""
        if self.status != "pending":
            raise ValidationError("Only pending requests can be rejected")

        self.status = "rejected"
        self.save(update_fields=["status", "updated_at"])


class Block(models.Model):
    """
    Block relationships between public profiles.
    When a public profile blocks another, it prevents following and interactions.
    """

    # Who is blocking (the blocker) - always a PublicProfile
    blocker = models.ForeignKey(
        "profiles.PublicProfile",
        on_delete=models.CASCADE,
        related_name="blocks_made",
        null=True,
        blank=True,
    )

    # Who is being blocked (the blocked) - always a PublicProfile
    blocked = models.ForeignKey(
        "profiles.PublicProfile",
        on_delete=models.CASCADE,
        related_name="blocks_received",
        null=True,
        blank=True,
    )

    # Block reason (optional)
    reason = models.CharField(
        max_length=50,
        choices=[
            ("spam", "Spam"),
            ("harassment", "Harassment"),
            ("inappropriate", "Inappropriate Content"),
            ("other", "Other"),
        ],
        blank=True,
        null=True,
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("blocker", "blocked")

        indexes = [
            # Index for finding who a profile has blocked
            models.Index(fields=["blocker"]),
            # Index for finding who has blocked a profile
            models.Index(fields=["blocked"]),
            # Index for recent blocks
            models.Index(fields=["-created_at"]),
        ]

        ordering = ["-created_at"]

    def __str__(self):
        blocker_name = self.blocker.display_name or f"@{self.blocker.handle}"
        blocked_name = self.blocked.display_name or f"@{self.blocked.handle}"
        return f"{blocker_name} blocked {blocked_name}"

    def clean(self):
        """Validate the block relationship"""
        # Prevent self-blocking
        if self.blocker == self.blocked:
            raise ValidationError("A profile cannot block itself")

        # Prevent blocking profiles from the same member
        if hasattr(self.blocker, "member") and hasattr(self.blocked, "member"):
            if self.blocker.member == self.blocked.member:
                raise ValidationError("Cannot block profiles from the same member")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

        # Remove any existing follow relationships between these profiles
        Follow.objects.filter(
            follower=self.blocker,
            followee=self.blocked,
        ).delete()

        Follow.objects.filter(
            follower=self.blocked,
            followee=self.blocker,
        ).delete()
