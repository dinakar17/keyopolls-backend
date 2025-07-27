from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from keyopolls.common.models.bookmark import Bookmark, BookmarkFolder, FolderAccess
from keyopolls.common.models.impressions import Impression, ImpressionTrackingMixin
from keyopolls.common.models.media import Link, Media, UploadedImage
from keyopolls.common.models.reaction import Reaction, Share

__all__ = [
    "Bookmark",
    "BookmarkFolder",
    "Media",
    "Link",
    "Reaction",
    "UploadedImage",
    "ImpressionTrackingMixin",
    "Impression",
    "Reaction",
    "Share",
    "FolderAccess",
]


class Category(models.Model):
    """
    Main categories for posts with configurable media permissions
    """

    # Type choices
    CATEGORY_TYPE_CHOICES = [
        ("standard", "Standard Category"),
        ("feed", "Feed Type"),
    ]

    # Basic info
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=50, unique=True)
    description = models.TextField(blank=True)

    # Categorization
    category_type = models.CharField(
        max_length=20, choices=CATEGORY_TYPE_CHOICES, default="standard"
    )

    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def to_dict(self):
        """Convert Category object to dictionary representation"""
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "category_type": self.category_type,
        }


class Tag(models.Model):
    """Generic tags that can be attached to any model"""

    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=50, unique=True)
    description = models.TextField(blank=True, null=True)
    usage_count = models.BigIntegerField(default=0)  # Denormalized counter

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["usage_count"]),  # For trending tags
        ]

    def __str__(self):
        return self.name

    def to_dict(self):
        """Convert Tag object to dictionary representation"""
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "usage_count": self.usage_count,
        }


class TaggedItem(models.Model):
    """Intermediate model for connecting tags to any model"""

    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, related_name="items")
    community = models.ForeignKey(
        "communities.Community",
        on_delete=models.CASCADE,
        related_name="tagged_items",
        blank=True,
        null=True,
    )

    # Generic relation fields (for poll and article tagging)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
        ]
        unique_together = [["tag", "content_type", "object_id"]]

    def __str__(self):
        return f"{self.tag.name} on {self.content_type.model} {self.object_id}"

    def save(self, *args, **kwargs):
        # Increment tag counter on creation
        created = not self.pk
        super().save(*args, **kwargs)
        if created:
            self.tag.usage_count += 1
            self.tag.save(update_fields=["usage_count"])

    def delete(self, *args, **kwargs):
        # Decrement tag counter on deletion
        self.tag.usage_count -= 1
        self.tag.save(update_fields=["usage_count"])
        super().delete(*args, **kwargs)
