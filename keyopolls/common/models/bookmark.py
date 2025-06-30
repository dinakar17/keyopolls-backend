from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class BookmarkFolder(models.Model):
    """Folders to organize bookmarks - simplified for PseudonymousProfile"""

    # Direct profile reference
    profile = models.ForeignKey(
        "profile.PseudonymousProfile",
        on_delete=models.CASCADE,
        related_name="bookmark_folders",
    )

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
                fields=["profile", "name"],
                name="unique_folder_name_per_profile",
            )
        ]
        indexes = [
            models.Index(fields=["profile", "name"]),
            models.Index(fields=["profile", "-created_at"]),
        ]
        ordering = ["name"]

    def __str__(self):
        return f"{self.profile.username} - {self.name}"

    @property
    def bookmark_count(self):
        """Get count of bookmarks in this folder"""
        return self.bookmarks.count()


class Bookmark(models.Model):
    """Generic bookmark model for any content type - simplified for Profile"""

    # Direct profile reference
    profile = models.ForeignKey(
        "profile.PseudonymousProfile",
        on_delete=models.CASCADE,
        related_name="bookmarks",
    )

    # Generic foreign key to support any content type
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.BigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    # Optional folder organization
    folder = models.ForeignKey(
        BookmarkFolder,
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
                fields=["profile", "content_type", "object_id"],
                name="unique_bookmark_per_profile_per_content",
            )
        ]
        indexes = [
            models.Index(fields=["profile", "-created_at"]),
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["folder", "-created_at"]),
            models.Index(fields=["profile", "folder"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"{self.profile.username} bookmarked "
            f"{self.content_type.model} {self.object_id}"
        )

    @classmethod
    def is_bookmarked_by_profile(cls, profile, content_obj):
        """
        Check if content is bookmarked by profile.

        Args:
            profile: PseudonymousProfile instance
            content_obj: Any model instance (Poll, Comment, etc.)

        Returns:
            bool: True if content is bookmarked, False otherwise
        """
        if not profile:
            return False

        content_type = ContentType.objects.get_for_model(content_obj)
        return cls.objects.filter(
            profile=profile,
            content_type=content_type,
            object_id=content_obj.id,
        ).exists()

    @classmethod
    def is_bookmarked(cls, profile, content_obj):
        """
        Check if content is bookmarked by user.

        Args:
            profile: PseudonymousProfile instance
            content_obj: Any model instance to check bookmark status for

        Returns:
            bool: True if content is bookmarked, False otherwise
        """
        return cls.is_bookmarked_by_profile(profile, content_obj)

    @classmethod
    def get_user_bookmarks(cls, profile, content_type_filter=None, folder=None):
        """
        Get all bookmarks for a pseudonymous profile

        Args:
            profile: PseudonymousProfile instance
            content_type_filter: Optional ContentType to filter by
            folder: Optional BookmarkFolder to filter by

        Returns:
            QuerySet of Bookmark objects
        """
        queryset = cls.objects.filter(profile=profile)

        if content_type_filter:
            queryset = queryset.filter(content_type=content_type_filter)

        if folder:
            queryset = queryset.filter(folder=folder)

        return queryset

    @classmethod
    def toggle_bookmark(cls, profile, content_obj, folder=None, notes=""):
        """
        Toggle bookmark status for content using pseudonymous profile.

        Args:
            profile: PseudonymousProfile instance
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
            profile=profile,
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

    @classmethod
    def get_bookmarks_by_content_type(cls, profile, content_type_name):
        """
        Get bookmarks filtered by content type name.

        Args:
            profile: PseudonymousProfile instance
            content_type_name: String name of content type (e.g., 'poll', 'comment')

        Returns:
            QuerySet of Bookmark objects
        """
        try:
            content_type = ContentType.objects.get(model=content_type_name.lower())
            return cls.objects.filter(profile=profile, content_type=content_type)
        except ContentType.DoesNotExist:
            return cls.objects.none()

    @classmethod
    def get_bookmark_with_content(cls, profile, content_type_name=None):
        """
        Get bookmarks with their content objects efficiently loaded.

        Args:
            profile: PseudonymousProfile instance
            content_type_name: Optional content type filter

        Returns:
            QuerySet of Bookmark objects with content prefetched
        """
        queryset = cls.objects.filter(profile=profile).select_related(
            "content_type", "folder"
        )

        if content_type_name:
            try:
                content_type = ContentType.objects.get(model=content_type_name.lower())
                queryset = queryset.filter(content_type=content_type)
            except ContentType.DoesNotExist:
                return cls.objects.none()

        return queryset

    def get_content_url(self):
        """
        Get URL for the bookmarked content if it has a get_absolute_url method.

        Returns:
            str: URL of the content object or None
        """
        if self.content_object and hasattr(self.content_object, "get_absolute_url"):
            return self.content_object.get_absolute_url()
        return None

    def get_content_title(self):
        """
        Get title/name of the bookmarked content.

        Returns:
            str: Title of the content object
        """
        if not self.content_object:
            return f"Deleted {self.content_type.model}"

        # Try common title fields
        for field in ["title", "name", "subject", "content"]:
            if hasattr(self.content_object, field):
                value = getattr(self.content_object, field)
                if value:
                    # Truncate long content
                    if field == "content" and len(str(value)) > 100:
                        return f"{str(value)[:100]}..."
                    return str(value)

        return f"{self.content_type.model} #{self.object_id}"

    @property
    def content_summary(self):
        """Get a summary of the bookmarked content for display."""
        return {
            "type": self.content_type.model,
            "title": self.get_content_title(),
            "url": self.get_content_url(),
            "exists": self.content_object is not None,
        }
