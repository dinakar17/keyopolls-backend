import uuid

from django.db import models
from django.utils import timezone

from keyopolls.chats.models.services import ServiceItem
from keyopolls.common.models import ImpressionTrackingMixin
from keyopolls.communities.models import Community
from keyopolls.profile.models import PseudonymousProfile


class Chat(models.Model):
    """
    Represents a 1v1 conversation between two users
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    participant_1 = models.ForeignKey(
        PseudonymousProfile,
        on_delete=models.CASCADE,
        related_name="chats_as_participant_1",
    )
    participant_2 = models.ForeignKey(
        PseudonymousProfile,
        on_delete=models.CASCADE,
        related_name="chats_as_participant_2",
    )
    community = models.ForeignKey(
        Community,
        on_delete=models.CASCADE,
        related_name="chats",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ["participant_1", "participant_2"]
        ordering = ["-last_activity_at"]

    def __str__(self):
        return (
            f"Chat between {self.participant_1.username} "
            f"and {self.participant_2.username}"
        )

    def get_other_participant(self, user):
        """Get the other participant in the chat"""
        if user == self.participant_1:
            return self.participant_2
        return self.participant_1

    def get_timeline(self):
        """
        Get all timeline items (messages + calls) ordered by time
        This is what you'll use in your chat view!
        """
        return self.timeline_items.all().order_by("created_at")


class TimelineItem(models.Model, ImpressionTrackingMixin):
    """
    Base model for all items that appear in chat timeline
    (messages, calls, etc.)
    """

    ITEM_TYPES = [
        ("text", "Text Message"),
        ("image", "Image"),
        ("video", "Video"),
        ("document", "Document"),
        ("audio", "Audio Message"),
        ("voice_call", "Voice Call"),
        ("video_call", "Video Call"),
        # Service created by the content creator
        ("service", "Service Item"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chat = models.ForeignKey(
        Chat,
        on_delete=models.CASCADE,
        related_name="timeline_items",
        null=True,
        blank=True,
    )
    sender = models.ForeignKey(
        PseudonymousProfile, on_delete=models.CASCADE, related_name="timeline_items"
    )
    service_item = models.ForeignKey(
        ServiceItem,
        on_delete=models.CASCADE,
        related_name="timeline_items",
        null=True,
        blank=True,
    )
    community = models.ForeignKey(
        Community,
        on_delete=models.CASCADE,
        related_name="timeline_items",
        null=True,
        blank=True,
    )
    item_type = models.CharField(max_length=15, choices=ITEM_TYPES)
    created_at = models.DateTimeField(auto_now_add=True)

    # For messages
    content = models.TextField(blank=True, null=True)

    # For calls
    call_duration = models.IntegerField(blank=True, null=True)  # in seconds
    call_status = models.CharField(
        max_length=15, blank=True, null=True
    )  # answered, missed, declined

    # User can reply to a timeline item (message)
    reply_to = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="replies",
        null=True,
        blank=True,
    )

    # Message status
    is_delivered = models.BooleanField(default=False)
    is_read = models.BooleanField(default=False)
    delivered_at = models.DateTimeField(blank=True, null=True)
    read_at = models.DateTimeField(blank=True, null=True)

    # de-normalized counters
    impressions_count = models.PositiveIntegerField(default=0)
    like_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        if self.item_type in ["voice_call", "video_call"]:
            duration = self.get_duration_display() if self.call_duration else "0:00"
            return (
                f"{self.sender.username}: {self.item_type} ({duration}) - "
                f"{self.call_status}"
            )
        elif self.item_type == "text":
            return f"{self.sender.username}: {self.content[:50]}..."
        else:
            attachment_count = self.attachments.count()
            return (
                f"{self.sender.username}: [{self.item_type.upper()}] "
                f"{attachment_count} attachment(s)"
            )

    def get_duration_display(self):
        """Return human-readable duration for calls"""
        if not self.call_duration:
            return "0:00"

        minutes = self.call_duration // 60
        seconds = self.call_duration % 60
        return f"{minutes}:{seconds:02d}"

    def is_call(self):
        """Check if this timeline item is a call"""
        return self.item_type in ["voice_call", "video_call"]

    def is_message(self):
        """Check if this timeline item is a message"""
        return self.item_type in ["text", "image", "video", "document", "audio"]

    def save(self, *args, **kwargs):
        # Update chat's last_activity_at when a new item is created
        if not self.pk:  # Only for new items
            super().save(*args, **kwargs)
            if self.chat:  # Only update if it's a chat message
                self.chat.last_activity_at = self.created_at
                self.chat.save(update_fields=["last_activity_at"])
        else:
            super().save(*args, **kwargs)


class TimelineItemAttachment(models.Model):
    """
    Model for attachments (photos, videos, documents) for timeline items
    """

    ATTACHMENT_TYPES = [
        ("image", "Image"),
        ("video", "Video"),
        ("audio", "Audio"),
        ("document", "Document"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timeline_item = models.ForeignKey(
        TimelineItem, on_delete=models.CASCADE, related_name="attachments"
    )

    attachment_type = models.CharField(max_length=10, choices=ATTACHMENT_TYPES)
    file = models.FileField(
        upload_to="timeline_attachments/",
        help_text="File attachment for the timeline item",
    )
    file_name = models.CharField(max_length=255)
    file_size = models.BigIntegerField(help_text="File size in bytes")
    display_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["display_order", "created_at"]

    def __str__(self):
        return f"{self.attachment_type}: {self.file_name} for {self.timeline_item.id}"

    def save(self, *args, **kwargs):
        if self.file:
            self.file_name = self.file.name
            self.file_size = self.file.size
        super().save(*args, **kwargs)


class ChatParticipant(models.Model):
    """
    Helper model to manage chat participants and their specific settings
    """

    chat = models.ForeignKey(
        Chat, on_delete=models.CASCADE, related_name="participants"
    )
    user = models.ForeignKey(PseudonymousProfile, on_delete=models.CASCADE)

    # User-specific chat settings
    is_muted = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    last_read_item = models.ForeignKey(
        TimelineItem,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="read_by_participants",
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["chat", "user"]

    def __str__(self):
        return f"{self.user.username} in {self.chat}"

    def get_unread_count(self):
        """Get count of unread items for this participant"""
        if not self.last_read_item:
            return self.chat.timeline_items.exclude(sender=self.user).count()

        return (
            self.chat.timeline_items.filter(
                created_at__gt=self.last_read_item.created_at
            )
            .exclude(sender=self.user)
            .count()
        )
