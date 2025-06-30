import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class Media(models.Model):
    """Generic media attachments (images, videos) for any model"""

    MEDIA_TYPE_CHOICES = [
        ("image", "Image"),
        ("gif", "GIF"),
        ("video", "Video"),
    ]

    # Generic relation fields
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    media_type = models.CharField(max_length=10, choices=MEDIA_TYPE_CHOICES)
    file = models.FileField(upload_to="media/%Y/%m/%d/")
    thumbnail = models.FileField(
        upload_to="media/thumbnails/%Y/%m/%d/", null=True, blank=True
    )

    # Metadata
    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    alt_text = models.CharField(
        max_length=255, blank=True, null=True
    )  # For accessibility

    # Video-specific fields
    duration = models.FloatField(null=True, blank=True)  # Duration in seconds
    video_codec = models.CharField(max_length=50, null=True, blank=True)
    audio_codec = models.CharField(max_length=50, null=True, blank=True)

    # Processing status
    is_processed = models.BooleanField(default=False)  # For tracking video processing
    processing_error = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    # For ordering multiple media items
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=["content_type", "object_id", "media_type"]),
            models.Index(fields=["created_at"]),
        ]
        ordering = ["order", "created_at"]
        verbose_name_plural = "Media"

    def __str__(self):
        return f"{self.media_type} for {self.content_type.model} {self.object_id}"

    def save(self, *args, **kwargs):
        """Extract metadata from media files on save"""
        # Only process new files
        if not self.pk:
            self._process_metadata()
        super().save(*args, **kwargs)

    def _process_metadata(self):
        """Extract metadata from the file (size, dimensions, etc.)"""
        if not self.file:
            return

        # Get file size
        self.size_bytes = self.file.size

        # Process image metadata
        if self.media_type == "image":
            try:
                from PIL import Image

                img = Image.open(self.file)
                self.width, self.height = img.size
            except Exception:
                pass

        # Process video metadata
        elif self.media_type == "video":
            # This would use a library like moviepy or ffmpeg to extract
            # video metadata (dimensions, duration, codec)
            pass

    def to_dict(self):
        """Convert Media object to dictionary representation"""
        return {
            "id": self.id,
            "media_type": self.media_type,
            "file_url": self.file.url if self.file else None,
            "thumbnail": self.thumbnail.url if self.thumbnail else None,
            "width": self.width,
            "height": self.height,
            "alt_text": self.alt_text,
            "duration": self.duration,
            "order": self.order,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Link(models.Model):
    """
    Generic stored links for tracking and analysis across different models.
    """

    # Generic relation fields
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    url = models.URLField(max_length=2000)  # URLs can be long
    display_text = models.CharField(
        max_length=2000, blank=True
    )  # The text displayed for the link

    # Metadata about the link
    domain = models.CharField(max_length=255, blank=True, null=True)
    title = models.CharField(max_length=500, blank=True, null=True)  # Scraped title
    description = models.TextField(blank=True, null=True)  # Scraped description
    image_url = models.URLField(max_length=2000, blank=True, null=True)  # Scraped image

    # Status and tracking
    is_active = models.BooleanField(default=True)  # For disabling malicious links
    click_count = models.PositiveIntegerField(default=0)  # Track engagement
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["domain"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"Link {self.url} for {self.content_type.model} {self.object_id}"

    def save(self, *args, **kwargs):
        """Extract domain from URL if not provided"""
        if not self.domain and self.url:
            from urllib.parse import urlparse

            parsed_url = urlparse(self.url)
            self.domain = parsed_url.netloc.replace("www.", "")
        super().save(*args, **kwargs)

    def record_click(self):
        """Increment the click count for this link"""
        self.click_count += 1
        self.save(update_fields=["click_count"])

    def to_dict(self):
        """Convert Link object to dictionary representation"""
        return {
            "id": self.id,
            "url": self.url,
            "display_text": self.display_text,
            "domain": self.domain,
            "title": self.title,
            "description": self.description,
            "image_url": self.image_url,
            "is_active": self.is_active,
            "click_count": self.click_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class UploadedImage(models.Model):
    """Model for storing information about uploaded images."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.FileField(upload_to="article_image_uploads/%Y/%m/%d/")
    file_name = models.CharField(max_length=255)
    alt_text = models.CharField(max_length=255, blank=True, null=True)
    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    file_size = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.file_name} ({self.id})"

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Uploaded Image"
        verbose_name_plural = "Uploaded Images"
