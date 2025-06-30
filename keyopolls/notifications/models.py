from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class NotificationType(models.TextChoices):
    """Simplified notification types based on requirements"""

    # === POST OWNER NOTIFICATIONS ===
    COMMENT = "comment", "Comment"  # Someone commented on your post

    # === COMMENT OWNER NOTIFICATIONS ===
    REPLY = "reply", "Reply"  # Someone replied to your comment

    # === SOCIAL NOTIFICATIONS ===
    FOLLOW = "follow", "Follow"  # Someone started following you
    MENTION = "mention", "Mention"  # Someone mentioned you in their post/comment

    # === FOLLOW-BASED NOTIFICATIONS ===
    FOLLOWED_USER_POST = (
        "followed_user_post",
        "Followed User Post",
    )  # Someone you follow created a new post
    FOLLOWED_POST_COMMENT = (
        "followed_post_comment",
        "Followed Post Comment",
    )  # New comment on a post you follow
    FOLLOWED_COMMENT_REPLY = (
        "followed_comment_reply",
        "Followed Comment Reply",
    )  # New reply on a comment you follow

    # === MILESTONE NOTIFICATIONS ===
    LIKE_MILESTONE = (
        "like_milestone",
        "Like Milestone",
    )  # Your post/comment reached X likes
    SHARE_MILESTONE = (
        "share_milestone",
        "Share Milestone",
    )  # Your post was shared X times
    # Todo: Your post or comment was shared X times
    BOOKMARK_MILESTONE = (
        "bookmark_milestone",
        "Bookmark Milestone",
    )  # Your post was bookmarked X times
    IMPRESSION_MILESTONE = (
        "impression_milestone",
        "Impression Milestone",
    )  # Your post reached X impressions
    # Todo: Your post or comment reached X impressions
    FOLLOWER_MILESTONE = (
        "follower_milestone",
        "Follower Milestone",
    )  # You reached X followers
    REPLIES_MILESTONE = (
        "replies_milestone",
        "Replies Milestone",
    )  # Your post or comment received X replies

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
    Simplified notification model support for public profiles.
    """

    # Recipient (always Public profile)
    recipient_content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, related_name="notifications_received"
    )
    recipient_object_id = models.PositiveIntegerField()
    recipient = GenericForeignKey("recipient_content_type", "recipient_object_id")

    # Actor (who triggered the notification - always public)
    actor_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="notifications_sent",
        null=True,
        blank=True,
    )
    actor_object_id = models.PositiveIntegerField(null=True, blank=True)
    actor = GenericForeignKey("actor_content_type", "actor_object_id")

    # Target object (post, comment, etc. that the notification is about)
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
            models.Index(
                fields=["recipient_content_type", "recipient_object_id", "-created_at"]
            ),
            models.Index(fields=["notification_type", "-created_at"]),
            models.Index(fields=["is_read", "-created_at"]),
            models.Index(fields=["actor_content_type", "actor_object_id"]),
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


class PostFollow(models.Model):
    """
    Simplified model to track which users follow which posts
    Only notifies about comments on the post
    """

    # Follower (always Public profile)
    follower_content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, related_name="post_follows"
    )
    follower_object_id = models.PositiveIntegerField()
    follower = GenericForeignKey("follower_content_type", "follower_object_id")

    # Post being followed
    post = models.ForeignKey(
        "posts.Post", on_delete=models.CASCADE, related_name="followers"
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
        unique_together = ["follower_content_type", "follower_object_id", "post"]
        indexes = [
            models.Index(fields=["post", "is_active"]),
            models.Index(fields=["follower_content_type", "follower_object_id"]),
        ]


class CommentFollow(models.Model):
    """
    Simplified model to track which users follow which comments
    Only notifies about replies to the comment
    """

    # Follower (always Public profile)
    follower_content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, related_name="comment_follows"
    )
    follower_object_id = models.PositiveIntegerField()
    follower = GenericForeignKey("follower_content_type", "follower_object_id")

    # Comment being followed
    comment = models.ForeignKey(
        "comments.GenericComment", on_delete=models.CASCADE, related_name="followers"
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
        unique_together = ["follower_content_type", "follower_object_id", "comment"]
        indexes = [
            models.Index(fields=["comment", "is_active"]),
            models.Index(fields=["follower_content_type", "follower_object_id"]),
        ]


class FCMDevice(models.Model):
    """
    FCM device tokens for push notifications
    Only supports Public profiles (Anonymous profiles are interconnected)
    """

    DEVICE_TYPE_CHOICES = [
        ("android", "Android"),
        ("ios", "iOS"),
        ("web", "Web"),
    ]

    # Only Public profiles can register for push notifications
    profile = models.ForeignKey(
        "profiles.PublicProfile", on_delete=models.CASCADE, related_name="fcm_devices"
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
        return f"FCM Device for {self.profile.handle} ({self.device_type})"


class NotificationPreference(models.Model):
    """
    User preferences for notification delivery and types
    """

    # Profile (always Public profile)
    profile_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    profile_object_id = models.PositiveIntegerField()
    profile = GenericForeignKey("profile_content_type", "profile_object_id")

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
        unique_together = [
            "profile_content_type",
            "profile_object_id",
            "notification_type",
        ]
        indexes = [
            models.Index(fields=["profile_content_type", "profile_object_id"]),
            models.Index(fields=["notification_type"]),
        ]

    @classmethod
    def _create_default_preference_object(cls, profile, notification_type):
        """Create a default preference object WITHOUT saving to database"""
        from keyoconnect.profiles.models import PublicProfile

        can_receive_push = isinstance(profile, PublicProfile)

        # Create object but don't save
        preference = cls(
            profile_content_type=ContentType.objects.get_for_model(profile),
            profile_object_id=profile.id,
            notification_type=notification_type,
            in_app_enabled=True,
            push_enabled=can_receive_push
            and notification_type
            in [
                NotificationType.COMMENT,
                NotificationType.REPLY,
                NotificationType.FOLLOW,
                NotificationType.MENTION,
            ],
            email_enabled=notification_type
            in [
                NotificationType.FOLLOW,
                NotificationType.MENTION,
                NotificationType.VERIFICATION,
                NotificationType.REPLIES_MILESTONE,
            ],
        )

        # Set the profile relationship manually since we're not saving
        preference.profile = profile

        return preference

    @classmethod
    def get_or_create_for_type(cls, profile, notification_type):
        """Get or create a single preference for a specific notification type"""
        from keyoconnect.profiles.models import PublicProfile

        can_receive_push = isinstance(profile, PublicProfile)

        preference, created = cls.objects.get_or_create(
            profile_content_type=ContentType.objects.get_for_model(profile),
            profile_object_id=profile.id,
            notification_type=notification_type,
            defaults={
                "in_app_enabled": True,
                "push_enabled": can_receive_push
                and notification_type
                in [
                    NotificationType.COMMENT,
                    NotificationType.REPLY,
                    NotificationType.FOLLOW,
                    NotificationType.MENTION,
                ],
                "email_enabled": notification_type
                in [
                    NotificationType.FOLLOW,
                    NotificationType.MENTION,
                    NotificationType.VERIFICATION,
                    NotificationType.REPLIES_MILESTONE,
                ],
            },
        )
        return preference

    def can_receive_push(self):
        """Check if this profile can receive push notifications"""
        from keyoconnect.profiles.models import PublicProfile

        return isinstance(self.profile, PublicProfile)
