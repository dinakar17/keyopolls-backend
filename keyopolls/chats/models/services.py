import uuid
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from keyopolls.communities.models import Community
from keyopolls.profile.models import PseudonymousProfile


class ServiceItem(models.Model):
    """
    Model representing a service item that moderators can create for their community.
    Users can purchase these services to interact with moderators in 1v1 sessions.
    """

    SERVICE_TYPES = [
        ("dm", "Direct Message"),
        ("live_chat", "Live Chat"),
        ("audio_call", "Audio Call"),
        ("video_call", "Video Call"),
        ("group_chat", "Group Chat"),
        ("group_audio_call", "Group Audio Call"),
        ("group_video_call", "Group Video Call"),
        ("custom", "Custom Service"),
    ]

    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
        ("draft", "Draft"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Service ownership
    creator = models.ForeignKey(
        PseudonymousProfile,
        on_delete=models.CASCADE,
        related_name="created_services",
        help_text="The moderator who created this service",
    )
    community = models.ForeignKey(
        Community,
        on_delete=models.CASCADE,
        related_name="services",
        help_text="The community this service belongs to",
    )

    preview_image = models.ImageField(
        upload_to="service_previews/",
        null=True,
        blank=True,
        help_text="Preview image for the service",
    )

    # Service details
    service_type = models.CharField(
        max_length=20, choices=SERVICE_TYPES, help_text="Type of service offered"
    )
    name = models.CharField(max_length=100, help_text="Display name for the service")
    description = models.TextField(
        help_text="Detailed description of what this service provides"
    )

    # Attachments Required for some services by users
    attachments_required = models.BooleanField(
        default=False,
        help_text="Whether users need to attach files (e.g., images, documents) "
        "when purchasing this service",
    )

    # Pricing and duration
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Price in credits for this service",
    )
    duration_minutes = models.PositiveIntegerField(
        default=10, help_text="Duration in minutes (for timed services like calls)"
    )

    # Service settings
    is_duration_based = models.BooleanField(
        default=False, help_text="Whether this service has a time limit"
    )

    # Availability
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="active")
    is_available = models.BooleanField(
        default=True, help_text="Whether users can currently purchase this service"
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Stats
    total_purchases = models.PositiveIntegerField(default=0)
    total_revenue = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )

    # Broadcast status
    is_broadcasted = models.BooleanField(
        default=False,
        help_text="Whether this service has been broadcasted to the community",
    )

    class Meta:
        ordering = ["-created_at"]
        unique_together = ["creator", "community", "service_type"]

    def __str__(self):
        return f"{self.name} by {self.creator.username} in {self.community.name}"

    def get_type_display_with_duration(self):
        """Get service type with duration info"""
        base = self.get_service_type_display()
        if self.is_duration_based:
            return f"{base} ({self.duration_minutes} min)"
        return base

    def increment_purchase_stats(self, amount):
        """Update purchase statistics"""
        self.total_purchases += 1
        self.total_revenue += amount
        self.save(update_fields=["total_purchases", "total_revenue"])


class ServiceAttachment(models.Model):
    """
    Model for attachments (photos, videos, documents) for services
    """

    ATTACHMENT_TYPES = [
        ("image", "Image"),
        ("video", "Video"),
        ("audio", "Audio"),
        ("document", "Document"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service = models.ForeignKey(
        ServiceItem, on_delete=models.CASCADE, related_name="attachments"
    )

    attachment_type = models.CharField(max_length=10, choices=ATTACHMENT_TYPES)
    file = models.FileField(
        upload_to="service_attachments/", help_text="File attachment for the service"
    )
    file_name = models.CharField(max_length=255)
    file_size = models.BigIntegerField(help_text="File size in bytes")

    # link the user if the attachment is uploaded by a user
    # (by default it is the creator)
    uploaded_by = models.ForeignKey(
        PseudonymousProfile,
        on_delete=models.CASCADE,
        related_name="service_attachments",
        null=True,
        blank=True,
        help_text="User who uploaded this attachment (if applicable)",
    )

    # Optional metadata
    title = models.CharField(
        max_length=100, blank=True, help_text="Optional title for the attachment"
    )
    description = models.TextField(
        blank=True, help_text="Optional description for the attachment"
    )

    # Ordering
    display_order = models.PositiveIntegerField(
        default=0, help_text="Order in which attachments are displayed"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["display_order", "created_at"]

    def __str__(self):
        return f"{self.attachment_type}: {self.file_name} for {self.service.name}"

    def save(self, *args, **kwargs):
        if self.file:
            self.file_name = self.file.name
            self.file_size = self.file.size
        super().save(*args, **kwargs)


# Helper functions for default services
def create_default_services_for_moderator(creator, community):
    """
    Create default 1v1 services (DM, Live Chat, Audio Call, Video Call)
    for a new moderator
    """
    default_services = [
        {
            "service_type": "dm",
            "name": "Direct Message",
            "description": "Send me a direct message and I'll respond within 24 hours.",
            "price": Decimal("5.00"),
            "duration_minutes": 0,
            "is_duration_based": False,
        },
        {
            "service_type": "live_chat",
            "name": "1v1 Live Chat",
            "description": "Real-time 1v1 chat session for instant communication.",
            "price": Decimal("15.00"),
            "duration_minutes": 30,
            "is_duration_based": True,
        },
        {
            "service_type": "audio_call",
            "name": "1v1 Audio Call",
            "description": "1v1 voice call session for personal consultation.",
            "price": Decimal("25.00"),
            "duration_minutes": 10,
            "is_duration_based": True,
        },
        {
            "service_type": "video_call",
            "name": "1v1 Video Call",
            "description": "1v1 face-to-face video call for comprehensive "
            "consultation.",
            "price": Decimal("35.00"),
            "duration_minutes": 10,
            "is_duration_based": True,
        },
    ]

    created_services = []
    for service_data in default_services:
        service, created = ServiceItem.objects.get_or_create(
            creator=creator,
            community=community,
            service_type=service_data["service_type"],
            defaults=service_data,
        )
        if created:
            created_services.append(service)

    return created_services
