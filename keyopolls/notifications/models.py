from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class NotificationType(models.TextChoices):
    """Simplified notification types based on requirements"""

    # === POLL OWNER NOTIFICATIONS ===
    POLL_COMMENT = "poll_comment", "Poll Comment"  # Someone commented on your poll
    POLL_VOTE = "poll_vote", "Poll Vote"  # Someone voted on your poll

    # === COMMENT OWNER NOTIFICATIONS ===
    REPLY = "reply", "Reply"  # Someone replied to your comment

    # === SOCIAL NOTIFICATIONS ===
    FOLLOW = "follow", "Follow"  # Someone started following you
    MENTION = "mention", "Mention"  # Someone mentioned you in their poll/comment

    # === COMMUNITY NOTIFICATIONS ===
    COMMUNITY_INVITE = (
        "community_invite",
        "Community Invite",
    )  # Invited to join community
    COMMUNITY_NEW_POLL = (
        "community_new_poll",
        "Community New Poll",
    )  # New poll in community
    COMMUNITY_ROLE_CHANGE = (
        "community_role_change",
        "Community Role Change",
    )  # Role changed in community

    # === FOLLOW-BASED NOTIFICATIONS ===
    FOLLOWED_USER_POLL = (
        "followed_user_poll",
        "Followed User Poll",
    )  # Someone you follow created a new poll
    FOLLOWED_POLL_COMMENT = (
        "followed_poll_comment",
        "Followed Poll Comment",
    )  # New comment on a poll you follow
    FOLLOWED_COMMENT_REPLY = (
        "followed_comment_reply",
        "Followed Comment Reply",
    )  # New reply on a comment you follow

    # === MILESTONE NOTIFICATIONS ===
    VOTE_MILESTONE = (
        "vote_milestone",
        "Vote Milestone",
    )  # Your poll reached X votes
    LIKE_MILESTONE = (
        "like_milestone",
        "Like Milestone",
    )  # Your poll/comment reached X likes
    SHARE_MILESTONE = (
        "share_milestone",
        "Share Milestone",
    )  # Your poll was shared X times
    BOOKMARK_MILESTONE = (
        "bookmark_milestone",
        "Bookmark Milestone",
    )  # Your poll was bookmarked X times
    VIEW_MILESTONE = (
        "view_milestone",
        "View Milestone",
    )  # Your poll reached X views
    FOLLOWER_MILESTONE = (
        "follower_milestone",
        "Follower Milestone",
    )  # You reached X followers
    REPLIES_MILESTONE = (
        "replies_milestone",
        "Replies Milestone",
    )  # Your poll or comment received X replies

    # === SYSTEM NOTIFICATIONS ===
    VERIFICATION = "verification", "Verification"
    WELCOME = "welcome", "Welcome"
    SYSTEM = "system", "System"


class NotificationPriority(models.TextChoices):
    """Priority levels for notifications"""

    LOW = "low", "Low"
    NORMAL = "normal", "Normal"
    HIGH = "high", "High"
    URGENT = "urgent", "Urgent"


class Notification(models.Model):
    """
    Simplified notification model for PseudonymousProfile.
    """

    # Recipient (PseudonymousProfile)
    recipient = models.ForeignKey(
        "profile.PseudonymousProfile",
        on_delete=models.CASCADE,
        related_name="notifications_received",
    )

    # Actor (who triggered the notification - PseudonymousProfile)
    actor = models.ForeignKey(
        "profile.PseudonymousProfile",
        on_delete=models.CASCADE,
        related_name="notifications_sent",
        null=True,
        blank=True,
    )

    # Target object (poll, comment, etc. that the notification is about)
    target_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="notifications_about",
        null=True,
        blank=True,
    )
    target_object_id = models.PositiveIntegerField(null=True, blank=True)
    target = GenericForeignKey("target_content_type", "target_object_id")

    # Notification content
    notification_type = models.CharField(
        max_length=50, choices=NotificationType.choices, default=NotificationType.SYSTEM
    )
    title = models.CharField(max_length=255)
    message = models.TextField()

    # URL routing for click handling
    click_url = models.URLField(
        max_length=500,
        null=True,
        blank=True,
        help_text="URL to redirect when notification is clicked",
    )

    # Deep link data for mobile apps
    deep_link_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Data for mobile app deep linking (screen, params, etc.)",
    )

    # Additional data (JSON field for flexibility)
    extra_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional data like milestone numbers, custom params, etc.",
    )

    # Notification metadata
    priority = models.CharField(
        max_length=20,
        choices=NotificationPriority.choices,
        default=NotificationPriority.NORMAL,
    )

    # Status tracking
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    is_clicked = models.BooleanField(default=False)
    clicked_at = models.DateTimeField(null=True, blank=True)

    # Delivery tracking
    push_sent = models.BooleanField(default=False)
    push_sent_at = models.DateTimeField(null=True, blank=True)
    email_sent = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Expiry (for temporary notifications)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["recipient", "-created_at"]),
            models.Index(fields=["notification_type", "-created_at"]),
            models.Index(fields=["is_read", "-created_at"]),
            models.Index(fields=["actor", "-created_at"]),
            models.Index(fields=["target_content_type", "target_object_id"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.notification_type}: {self.title}"

    def mark_as_read(self):
        """Mark notification as read"""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at"])

    def mark_as_clicked(self):
        """Mark notification as clicked"""
        if not self.is_clicked:
            self.is_clicked = True
            self.clicked_at = timezone.now()
            # Auto-mark as read when clicked
            if not self.is_read:
                self.is_read = True
                self.read_at = timezone.now()
            self.save(update_fields=["is_clicked", "clicked_at", "is_read", "read_at"])

    def is_expired(self):
        """Check if notification has expired"""
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False


class PollFollow(models.Model):
    """
    Simplified model to track which users follow which polls
    Only notifies about comments on the poll
    """

    # Follower (PseudonymousProfile)
    follower = models.ForeignKey(
        "profile.PseudonymousProfile",
        on_delete=models.CASCADE,
        related_name="poll_follows",
    )

    # Poll being followed
    poll = models.ForeignKey(
        "profile.Poll",
        on_delete=models.CASCADE,
        related_name="followers",
    )

    # Follow settings
    is_active = models.BooleanField(default=True)
    auto_followed = models.BooleanField(
        default=True,
        help_text="True if auto-followed by interaction, False if manually followed",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["follower", "poll"]
        indexes = [
            models.Index(fields=["poll", "is_active"]),
            models.Index(fields=["follower", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.follower.username} follows {self.poll.title}"


class CommentFollow(models.Model):
    """
    Simplified model to track which users follow which comments
    Only notifies about replies to the comment
    """

    # Follower (PseudonymousProfile)
    follower = models.ForeignKey(
        "profile.PseudonymousProfile",
        on_delete=models.CASCADE,
        related_name="comment_follows",
    )

    # Comment being followed
    comment = models.ForeignKey(
        "profile.GenericComment",
        on_delete=models.CASCADE,
        related_name="followers",
    )

    # Follow settings
    is_active = models.BooleanField(default=True)
    auto_followed = models.BooleanField(
        default=True,
        help_text="True if auto-followed by interaction, False if manually followed",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["follower", "comment"]
        indexes = [
            models.Index(fields=["comment", "is_active"]),
            models.Index(fields=["follower", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.follower.username} follows comment {self.comment.id}"


class FCMDevice(models.Model):
    """
    FCM device tokens for push notifications
    Supports PseudonymousProfile for push notifications
    """

    DEVICE_TYPE_CHOICES = [
        ("android", "Android"),
        ("ios", "iOS"),
        ("web", "Web"),
    ]

    # PseudonymousProfile can register for push notifications
    profile = models.ForeignKey(
        "profile.PseudonymousProfile",
        on_delete=models.CASCADE,
        related_name="fcm_devices",
    )

    # FCM token
    token = models.TextField(unique=True)
    device_type = models.CharField(max_length=10, choices=DEVICE_TYPE_CHOICES)

    # Device info
    device_id = models.CharField(max_length=255, null=True, blank=True)
    device_name = models.CharField(max_length=255, null=True, blank=True)

    # Status
    active = models.BooleanField(default=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["profile", "active"]),
            models.Index(fields=["token"]),
        ]

    def __str__(self):
        return f"FCM Device for {self.profile.username} ({self.device_type})"


class NotificationPreference(models.Model):
    """
    User preferences for notification delivery and types
    """

    # Profile (PseudonymousProfile)
    profile = models.ForeignKey(
        "profile.PseudonymousProfile",
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )

    # Notification type preferences
    notification_type = models.CharField(
        max_length=50, choices=NotificationType.choices
    )

    # Delivery preferences
    in_app_enabled = models.BooleanField(default=True)
    push_enabled = models.BooleanField(default=False)
    email_enabled = models.BooleanField(default=True)

    # Frequency control
    is_enabled = models.BooleanField(default=True)

    # Custom thresholds for milestone notifications
    custom_thresholds = models.JSONField(
        default=list,
        blank=True,
        help_text="Custom milestone numbers [1, 10, 100, 500, 1000]",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["profile", "notification_type"]
        indexes = [
            models.Index(fields=["profile", "notification_type"]),
            models.Index(fields=["notification_type"]),
        ]

    def __str__(self):
        return f"{self.profile.username} - {self.notification_type}"

    @classmethod
    def _create_default_preference_object(cls, profile, notification_type):
        """Create a default preference object WITHOUT saving to database"""
        # Create object but don't save
        preference = cls(
            profile=profile,
            notification_type=notification_type,
            in_app_enabled=True,
            push_enabled=notification_type
            in [
                NotificationType.POLL_COMMENT,
                NotificationType.POLL_VOTE,
                NotificationType.REPLY,
                NotificationType.FOLLOW,
                NotificationType.MENTION,
                NotificationType.COMMUNITY_INVITE,
            ],
            email_enabled=notification_type
            in [
                NotificationType.FOLLOW,
                NotificationType.MENTION,
                NotificationType.VERIFICATION,
                NotificationType.REPLIES_MILESTONE,
                NotificationType.VOTE_MILESTONE,
                NotificationType.COMMUNITY_INVITE,
            ],
        )

        return preference

    @classmethod
    def get_or_create_for_type(cls, profile, notification_type):
        """Get or create a single preference for a specific notification type"""
        preference, created = cls.objects.get_or_create(
            profile=profile,
            notification_type=notification_type,
            defaults={
                "in_app_enabled": True,
                "push_enabled": notification_type
                in [
                    NotificationType.POLL_COMMENT,
                    NotificationType.POLL_VOTE,
                    NotificationType.REPLY,
                    NotificationType.FOLLOW,
                    NotificationType.MENTION,
                    NotificationType.COMMUNITY_INVITE,
                ],
                "email_enabled": notification_type
                in [
                    NotificationType.FOLLOW,
                    NotificationType.MENTION,
                    NotificationType.VERIFICATION,
                    NotificationType.REPLIES_MILESTONE,
                    NotificationType.VOTE_MILESTONE,
                    NotificationType.COMMUNITY_INVITE,
                ],
            },
        )
        return preference

    def can_receive_push(self):
        """Check if this profile can receive push notifications"""
        # All PseudonymousProfiles can receive push notifications
        return True


class ProfileFollow(models.Model):
    """
    Track user follows - who follows whom
    """

    # Follower (who is following)
    follower = models.ForeignKey(
        "profile.PseudonymousProfile",
        on_delete=models.CASCADE,
        related_name="following",
    )

    # Following (who is being followed)
    following = models.ForeignKey(
        "profile.PseudonymousProfile",
        on_delete=models.CASCADE,
        related_name="followers",
    )

    # Follow settings
    is_active = models.BooleanField(default=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["follower", "following"]
        indexes = [
            models.Index(fields=["follower", "is_active"]),
            models.Index(fields=["following", "is_active"]),
            models.Index(fields=["-created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=~models.Q(follower=models.F("following")), name="no_self_follow"
            )
        ]

    def __str__(self):
        return f"{self.follower.username} follows {self.following.username}"
