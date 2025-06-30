from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class BookmarkFolder(models.Model):
    """Folders to organize bookmarks - public profile only"""

    # Profile type choices - only public supported now
    PROFILE_TYPES = (("public", "Public"),)

    # Profile type and ID (kept for backward compatibility and future flexibility)
    profile_type = models.CharField(
        max_length=20,
        choices=PROFILE_TYPES,
        default="public",
        help_text="Profile type - currently only 'public' is supported",
    )
    profile_id = models.BigIntegerField(help_text="ID of the public profile")

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    color = models.CharField(
        max_length=7, default="#3B82F6", help_text="Hex color code for folder display"
    )

    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # User can't have duplicate folder names
        constraints = [
            models.UniqueConstraint(
                fields=["profile_type", "profile_id", "name"],
                name="unique_folder_name_per_profile",
            )
        ]
        indexes = [
            models.Index(fields=["profile_type", "profile_id", "name"]),
            models.Index(fields=["profile_type", "profile_id", "-created_at"]),
            models.Index(
                fields=["profile_id", "-created_at"]
            ),  # Public profile specific index
        ]
        ordering = ["name"]

    def __str__(self):
        return f"Public profile {self.profile_id} - {self.name}"

    @property
    def bookmark_count(self):
        """Get count of bookmarks in this folder"""
        return self.bookmarks.count()

    def save(self, *args, **kwargs):
        """Override save to ensure profile_type is always 'public'"""
        self.profile_type = "public"
        super().save(*args, **kwargs)


class Bookmark(models.Model):
    """Generic bookmark model for any content type - public profile only"""

    # Profile type choices - only public supported now
    PROFILE_TYPES = (("public", "Public"),)

    # Profile type and ID (kept for backward compatibility and future flexibility)
    profile_type = models.CharField(
        max_length=20,
        choices=PROFILE_TYPES,
        default="public",
        help_text="Profile type - currently only 'public' is supported",
    )
    profile_id = models.BigIntegerField(help_text="ID of the public profile")

    # Generic foreign key to support any content type
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.BigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    # Optional folder organization
    folder = models.ForeignKey(
        "BookmarkFolder",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bookmarks",
    )

    # Optional personal notes
    notes = models.TextField(blank=True, max_length=500)

    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # User can't bookmark the same content twice
        constraints = [
            models.UniqueConstraint(
                fields=["profile_type", "profile_id", "content_type", "object_id"],
                name="unique_bookmark_per_profile_per_content",
            )
        ]
        indexes = [
            models.Index(fields=["profile_type", "profile_id", "-created_at"]),
            models.Index(
                fields=["profile_id", "-created_at"]
            ),  # Public profile specific index
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["folder", "-created_at"]),
            models.Index(fields=["profile_type", "profile_id", "folder"]),
            models.Index(
                fields=["profile_id", "folder"]
            ),  # Public profile specific folder index
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"Public profile {self.profile_id} bookmarked "
            f"{self.content_type.model} {self.object_id}"
        )

    def save(self, *args, **kwargs):
        """Override save to ensure profile_type is always 'public'"""
        self.profile_type = "public"
        super().save(*args, **kwargs)

    @classmethod
    def is_bookmarked_by_profile_info(cls, profile_type, profile_id, content_obj):
        """
        Check if content is bookmarked by profile using profile type and ID.
        This avoids circular imports by not importing profile models.

        Note: profile_type is kept for backward compatibility but will always be
        'public'

        Args:
            profile_type: The type of profile (will be normalized to "public")
            profile_id: The ID of the public profile
            content_obj: Any model instance (Post, Comment, etc.)

        Returns:
            bool: True if content is bookmarked, False otherwise
        """
        if not profile_id:
            return False

        # Normalize profile_type to public (for backward compatibility)
        profile_type = "public"

        content_type = ContentType.objects.get_for_model(content_obj)
        return cls.objects.filter(
            profile_type=profile_type,
            profile_id=profile_id,
            content_type=content_type,
            object_id=content_obj.id,
        ).exists()

    @classmethod
    def is_bookmarked(cls, profile_obj, content_obj):
        """
        Check if content is bookmarked by user.

        Args:
            profile_obj: PublicProfile instance
            content_obj: Any model instance to check bookmark status for

        Returns:
            bool: True if content is bookmarked, False otherwise
        """
        return cls.is_bookmarked_by_profile_info("public", profile_obj.id, content_obj)

    @classmethod
    def get_user_bookmarks(cls, profile_obj, content_type_filter=None, folder=None):
        """
        Get all bookmarks for a public profile

        Args:
            profile_obj: PublicProfile instance
            content_type_filter: Optional ContentType to filter by
            folder: Optional BookmarkFolder to filter by

        Returns:
            QuerySet of Bookmark objects
        """
        profile_id = profile_obj.id

        queryset = cls.objects.filter(
            profile_type="public",
            profile_id=profile_id,
        )

        if content_type_filter:
            queryset = queryset.filter(content_type=content_type_filter)

        if folder:
            queryset = queryset.filter(folder=folder)

        return queryset

    @classmethod
    def toggle_bookmark(cls, profile_obj, content_obj, folder=None, notes=""):
        """
        Toggle bookmark status for content using public profile.

        Args:
            profile_obj: PublicProfile instance
            content_obj: Any model instance to bookmark/unbookmark
            folder: Optional BookmarkFolder to organize bookmark
            notes: Optional notes for the bookmark

        Returns:
            tuple: (created: bool, bookmark: Bookmark or None)
                - created: True if bookmark was created, False if removed
                - bookmark: Bookmark instance if created, None if removed
        """
        content_type = ContentType.objects.get_for_model(content_obj)

        bookmark, created = cls.objects.get_or_create(
            profile_type="public",
            profile_id=profile_obj.id,
            content_type=content_type,
            object_id=content_obj.id,
            defaults={
                "folder": folder,
                "notes": notes,
            },
        )

        if not created:
            # Bookmark existed, so remove it
            bookmark.delete()
            return False, None
        else:
            # Bookmark was created
            return True, bookmark
