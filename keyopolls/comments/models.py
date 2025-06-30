from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class GenericComment(models.Model):
    """
    Generic comment model for any content type (posts, community posts, articles, etc.)
    with PseudonymousProfile integration
    """

    MODERATION_STATUS_CHOICES = (
        ("pending", "Pending Review"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    )

    # Basic fields
    id = models.BigAutoField(primary_key=True)
    content = models.TextField(max_length=1000)

    # Generic foreign key to the content being commented on
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.BigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    # Profile reference - direct foreign key to PseudonymousProfile
    profile = models.ForeignKey(
        "profile.PseudonymousProfile", on_delete=models.CASCADE, related_name="comments"
    )

    # For anonymous comments, store a unique identifier for display
    anonymous_comment_identifier = models.CharField(
        max_length=10, null=True, blank=True
    )

    # Self-reference for threaded comments
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="replies"
    )

    # Denormalized fields for performance
    like_count = models.BigIntegerField(default=0)
    dislike_count = models.BigIntegerField(default=0)
    reply_count = models.BigIntegerField(default=0)
    share_count = models.BigIntegerField(default=0)
    impressions_count = models.BigIntegerField(default=0)
    bookmark_count = models.BigIntegerField(default=0)

    # Store the depth level to limit nesting
    depth = models.SmallIntegerField(default=0)

    # Generic relations to Media and Link models
    media = GenericRelation("common.Media")
    links = GenericRelation("common.Link")

    # Moderation fields
    is_flagged = models.BooleanField(default=False)
    flag_reason = models.CharField(max_length=100, blank=True)
    moderation_status = models.CharField(
        max_length=20,
        choices=MODERATION_STATUS_CHOICES,
        default="approved",
    )

    # Community and content type specific moderation
    requires_moderation = models.BooleanField(default=False)
    community_id = models.BigIntegerField(null=True, blank=True)
    comment_source = models.CharField(
        max_length=20,
        choices=[
            ("post", "Post Comment"),
            ("community_post", "Community Post Comment"),
            ("article", "Article Comment"),
            ("community_article", "Community Article Comment"),
        ],
        default="post",
    )

    # Takedown fields
    is_taken_down = models.BooleanField(default=False)
    takedown_reason = models.CharField(max_length=100, blank=True)
    takedown_date = models.DateTimeField(null=True, blank=True)
    takedown_by = models.ForeignKey(
        "profile.PseudonymousProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="takedown_actions",
        help_text="Profile who took down this comment",
    )
    auto_takedown = models.BooleanField(default=False)

    # Timestamps and soft deletion
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)
    is_edited = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["content_type", "object_id", "-created_at"]),
            models.Index(fields=["parent", "-created_at"]),
            models.Index(fields=["profile", "-created_at"]),
            models.Index(fields=["is_flagged", "moderation_status"]),
            models.Index(fields=["comment_source", "-created_at"]),
            models.Index(fields=["community_id", "-created_at"]),
            models.Index(fields=["is_taken_down"]),
        ]

    def __str__(self):
        return f"Comment {self.id} by {self.profile.username}"

    def save(self, *args, **kwargs):
        # Calculate depth if this is a reply
        if self.parent:
            self.depth = self.parent.depth + 1
        else:
            self.depth = 0

        super().save(*args, **kwargs)

    def _set_community_id(self):
        """Set community_id if this is a community-related comment"""
        if self.comment_source in ["community_post", "community_article"]:
            try:
                if hasattr(self.content_object, "community_id"):
                    self.community_id = self.content_object.community_id
                elif hasattr(self.content_object, "community"):
                    self.community_id = self.content_object.community.id
            except Exception:
                pass

    def flag(self, reason=""):
        """Flag a comment for moderation"""
        self.is_flagged = True
        self.flag_reason = reason
        self.moderation_status = "pending"
        self.save(update_fields=["is_flagged", "flag_reason", "moderation_status"])

    def approve(self):
        """Approve a flagged or moderated comment"""
        self.is_flagged = False
        self.moderation_status = "approved"
        self.save(update_fields=["is_flagged", "moderation_status"])

    def reject(self):
        """Reject a flagged or moderated comment"""
        self.is_flagged = False
        self.moderation_status = "rejected"
        self.is_taken_down = True
        self.takedown_reason = self.flag_reason or "Rejected by moderator"
        self.takedown_date = timezone.now()
        self.save(
            update_fields=[
                "is_flagged",
                "moderation_status",
                "is_taken_down",
                "takedown_reason",
                "takedown_date",
            ]
        )

    def take_down(
        self, reason="Violated community standards", by_profile=None, auto=False
    ):
        """Take down a comment (for violations)"""
        self.is_taken_down = True
        self.takedown_reason = reason
        self.takedown_date = timezone.now()
        self.takedown_by = by_profile
        self.auto_takedown = auto
        self.save(
            update_fields=[
                "is_taken_down",
                "takedown_reason",
                "takedown_date",
                "takedown_by",
                "auto_takedown",
            ]
        )

    def restore(self):
        """Restore a taken down comment"""
        self.is_taken_down = False
        self.takedown_reason = ""
        self.save(update_fields=["is_taken_down", "takedown_reason"])

    def delete(self, hard_delete=False):
        """Soft delete unless hard_delete is specified"""
        if hard_delete:
            super().delete()
        else:
            self.is_deleted = True
            self.save(update_fields=["is_deleted"])

    def increment_like_count(self):
        """Increment the like count"""
        self.like_count = models.F("like_count") + 1
        self.save(update_fields=["like_count"])

    def decrement_like_count(self):
        """Decrement the like count"""
        self.like_count = models.F("like_count") - 1
        self.save(update_fields=["like_count"])

    def increment_reply_count(self):
        """Increment the reply count"""
        self.reply_count = models.F("reply_count") + 1
        self.save(update_fields=["reply_count"])

    def decrement_reply_count(self):
        """Decrement the reply count"""
        self.reply_count = models.F("reply_count") - 1
        self.save(update_fields=["reply_count"])

    @property
    def is_visible(self):
        """Check if the comment is visible
        (not deleted, not taken down, and approved)"""
        return (
            not self.is_deleted
            and not self.is_taken_down
            and self.moderation_status == "approved"
        )

    @property
    def visible_replies(self):
        """Get only visible replies"""
        return self.replies.filter(
            is_deleted=False, is_taken_down=False, moderation_status="approved"
        )

    @property
    def author_display_name(self):
        """Get the display name of the comment author"""
        return self.profile.display_name

    @property
    def author_username(self):
        """Get the username of the comment author"""
        return self.profile.username

    @property
    def author_aura(self):
        """Get the total aura of the comment author"""
        return self.profile.total_aura
