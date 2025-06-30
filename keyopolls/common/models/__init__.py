from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone
from keyoconnect.common.models.bookmark import Bookmark, BookmarkFolder
from keyoconnect.common.models.follow import Block, Follow, FollowRequest
from keyoconnect.common.models.impressions import Impression, ImpressionTrackingMixin
from keyoconnect.common.models.media import Link, Media, UploadedImage
from keyoconnect.common.models.reaction import Reaction, Share

__all__ = [
    "Bookmark",
    "BookmarkFolder",
    "Follow",
    "FollowRequest",
    "Block",
    "Media",
    "Link",
    "Reaction",
    "UploadedImage",
    "ImpressionTrackingMixin",
    "Impression",
    "Reaction",
    "Share",
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

    # Display properties
    icon = models.CharField(max_length=50, blank=True)  # Icon name/class
    icon_color = models.CharField(max_length=20, blank=True)  # Color code for icon
    display_order = models.PositiveIntegerField(default=0)  # For ordering in UI
    is_featured = models.BooleanField(default=False)  # For promoted categories

    # Content constraints
    character_limit = models.PositiveIntegerField(default=2000)  # Default char limit

    # Media permissions
    allows_images = models.BooleanField(default=True)
    allows_gifs = models.BooleanField(default=True)
    allows_videos = models.BooleanField(default=True)
    allows_links = models.BooleanField(default=True)
    allows_polls = models.BooleanField(default=True)
    allows_location = models.BooleanField(default=True)

    # Maximum allowed media
    max_images = models.PositiveSmallIntegerField(default=4)
    max_video_duration = models.PositiveIntegerField(
        null=True, blank=True
    )  # in seconds

    # Tags settings
    allows_tags = models.BooleanField(default=True)
    max_tags = models.PositiveSmallIntegerField(default=5)

    # System fields
    is_active = models.BooleanField(default=True)
    requires_approval = models.BooleanField(default=False)  # For moderated categories

    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name

    @property
    def has_subcategories(self):
        return self.subcategories.filter(is_active=True).exists()

    @property
    def allowed_media_types(self):
        """Returns a list of allowed media types for this category"""
        allowed = []
        if self.allows_images:
            allowed.append("image")
        if self.allows_videos:
            allowed.append("video")
        if self.allows_gifs:
            allowed.append("gif")
        if self.allows_links:
            allowed.append("link")
        if self.allows_polls:
            allowed.append("poll")
        if self.allows_location:
            allowed.append("location")
        return allowed

    def to_dict(self):
        """Convert Category object to dictionary representation"""
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "category_type": self.category_type,
            "icon": self.icon,
            "icon_color": self.icon_color,
            "is_featured": self.is_featured,
            "allows_images": self.allows_images,
            "allows_videos": self.allows_videos,
            "allows_gifs": self.allows_gifs,
            "allows_links": self.allows_links,
            "allows_tags": self.allows_tags,
            "max_tags": self.max_tags,
        }


class SubCategory(models.Model):
    """
    Subcategories that belong to main categories
    """

    # Basic info
    name = models.CharField(max_length=50)
    slug = models.SlugField(max_length=50, unique=True)
    description = models.TextField(blank=True)

    # Parent category
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, related_name="subcategories"
    )

    # Display properties
    icon = models.CharField(max_length=50, blank=True)
    icon_color = models.CharField(max_length=20, blank=True)
    display_order = models.PositiveIntegerField(default=0)

    # System fields
    is_active = models.BooleanField(default=True)

    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Sub Categories"
        ordering = ["category", "display_order", "name"]
        unique_together = [
            ["name", "category"]
        ]  # Allow same name in different categories

    def __str__(self):
        return f"{self.category.name} › {self.name}"

    # Inherit permissions from parent category
    @property
    def allowed_media_types(self):
        return self.category.allowed_media_types

    @property
    def character_limit(self):
        return self.category.character_limit

    @property
    def max_images(self):
        return self.category.max_images

    @property
    def max_tags(self):
        return self.category.max_tags


class Tag(models.Model):
    """Generic tags that can be attached to any model"""

    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=50, unique=True)
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
            "usage_count": self.usage_count,
        }


class TaggedItem(models.Model):
    """Intermediate model for connecting tags to any model"""

    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, related_name="items")

    # Generic relation fields
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
