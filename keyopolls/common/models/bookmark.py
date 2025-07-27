"""
Using these models the users are going to create paid polls list.
"""

import secrets

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from keyopolls.common.schemas import ContentTypeEnum


def generate_youtube_like_id():
    """
    Generate an 11-character YouTube-like ID
    YouTube uses base64url encoding: A-Z, a-z, 0-9, -, _
    This mimics YouTube's actual ID generation pattern
    """
    # YouTube's character set (base64url)
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ" "abcdefghijklmnopqrstuvwxyz" "0123456789" "-_"

    # Use cryptographically secure random for better uniqueness
    return "".join(secrets.choice(chars) for _ in range(11))


class BookmarkFolder(models.Model):
    """Folders to organize bookmarks - simplified for PseudonymousProfile"""

    # Access level choices
    ACCESS_PRIVATE = "private"
    ACCESS_PUBLIC = "public"
    ACCESS_PAID = "paid"

    ACCESS_CHOICES = [
        (ACCESS_PRIVATE, "Private"),
        (ACCESS_PUBLIC, "Public"),
        (ACCESS_PAID, "Paid"),
    ]

    # Unique identifier similar to YouTube
    folder_id = models.CharField(
        max_length=11,
        unique=True,
        blank=True,
        help_text="11-character unique identifier for the folder",
    )

    # URL-friendly slug
    slug = models.SlugField(
        max_length=100, unique=True, help_text="URL-friendly identifier for the folder"
    )

    # Direct profile reference
    profile = models.ForeignKey(
        "profile.PseudonymousProfile",
        on_delete=models.CASCADE,
        related_name="bookmark_folders",
    )
    community = models.ForeignKey(
        "communities.Community",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="bookmark_folders",
        help_text="Community this folder belongs to, if any",
    )

    # Content type for this folder (all bookmarks must be of this type)
    content_type = models.CharField(
        max_length=20,
        choices=[(ct.value, ct.value) for ct in ContentTypeEnum],
        null=True,
        blank=True,
        help_text="Content type that this folder contains (e.g., Poll, Comment)",
    )

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    color = models.CharField(
        max_length=7, default="#3B82F6", help_text="Hex color code for folder display"
    )

    # Access control
    access_level = models.CharField(
        max_length=10,
        choices=ACCESS_CHOICES,
        default=ACCESS_PRIVATE,
        help_text="Who can access this folder",
    )

    # Pricing for paid folders
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Price for paid access (required if access_level is 'paid')",
    )

    # Bookmark Folder could of type Todo or regular folder
    is_todo_folder = models.BooleanField(
        default=False,
        help_text="If true, this folder is used for todo items",
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
            ),
            # Ensure paid folders have a price
            models.CheckConstraint(
                check=models.Q(access_level__in=["private", "public"])
                | (models.Q(access_level="paid") & models.Q(price__isnull=False)),
                name="paid_folders_must_have_price",
            ),
        ]
        indexes = [
            models.Index(fields=["profile", "name"]),
            models.Index(fields=["profile", "-created_at"]),
            models.Index(fields=["folder_id"]),
            models.Index(fields=["slug"]),
            models.Index(fields=["access_level"]),
            models.Index(fields=["access_level", "-created_at"]),
            models.Index(fields=["content_type"]),
            models.Index(fields=["profile", "content_type"]),
            models.Index(fields=["content_type", "is_todo_folder"]),
        ]
        ordering = ["name"]

    def __str__(self):
        return (
            f"{self.profile.username} - {self.name} ({self.get_access_level_display()})"
        )

    def save(self, *args, **kwargs):
        """Override save to generate folder_id, slug and validate constraints"""
        # Generate unique folder_id if not provided
        if not self.folder_id:
            max_attempts = 10
            for _ in range(max_attempts):
                new_id = generate_youtube_like_id()
                if not BookmarkFolder.objects.filter(folder_id=new_id).exists():
                    self.folder_id = new_id
                    break
            else:
                # If we couldn't generate a unique ID after max_attempts
                raise ValueError(
                    f"Could not generate unique folder_id after {max_attempts} attempts"
                )

        # Generate slug if not provided
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1

            # Ensure slug uniqueness
            while BookmarkFolder.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1

            self.slug = slug

        # Validate paid folder constraints
        if self.access_level == self.ACCESS_PAID and not self.price:
            raise ValueError("Paid folders must have a price set")

        super().save(*args, **kwargs)

    @property
    def bookmark_count(self):
        """Get count of bookmarks in this folder"""
        return self.bookmarks.count()

    @property
    def is_private(self):
        """Check if folder is private"""
        return self.access_level == self.ACCESS_PRIVATE

    @property
    def is_public(self):
        """Check if folder is public"""
        return self.access_level == self.ACCESS_PUBLIC

    @property
    def is_paid(self):
        """Check if folder requires payment"""
        return self.access_level == self.ACCESS_PAID

    def can_access(self, user_profile):
        """
        Check if a user profile can access this folder

        Args:
            user_profile: PseudonymousProfile instance

        Returns:
            bool: True if user can access, False otherwise
        """
        # Owner can always access
        if self.profile == user_profile:
            return True

        # Public folders are accessible to everyone
        if self.is_public:
            return True

        # Private folders only accessible to owner
        if self.is_private:
            return False

        # Paid folders require membership check
        if self.is_paid:
            # This would need to be implemented based on your payment/membership system
            # For now, return False - you'll need to add the actual logic
            return self.has_paid_access(user_profile)

        return False

    def has_paid_access(self, user_profile):
        """
        Check if user has paid for access to this folder
        You'll need to implement this based on your payment system

        Args:
            user_profile: PseudonymousProfile instance

        Returns:
            bool: True if user has paid access
        """
        # TODO: Implement payment/membership check
        # This might involve checking a FolderMembership model or similar
        return False

    def get_absolute_url(self):
        """Get the absolute URL for this folder"""
        from django.urls import reverse

        return reverse("bookmark_folder_detail", kwargs={"slug": self.slug})

    @classmethod
    def get_accessible_folders(cls, requesting_profile=None, content_type_filter=None):
        """
        Get folders that are accessible to the requesting profile

        Args:
            requesting_profile: PseudonymousProfile instance or None for anonymous
            content_type_filter: Optional ContentTypeEnum to filter by content type

        Returns:
            QuerySet of accessible BookmarkFolder objects
        """
        if not requesting_profile:
            # Anonymous users can only see public folders
            queryset = cls.objects.filter(access_level=cls.ACCESS_PUBLIC)
        else:
            # Users can see their own folders + public folders + paid folders
            # they have access to
            queryset = cls.objects.filter(
                models.Q(profile=requesting_profile)  # Own folders
                | models.Q(access_level=cls.ACCESS_PUBLIC)  # Public folders
                # TODO: Add paid folder access check when payment system is implemented
            )

        # Filter by content type if specified
        if content_type_filter:
            if isinstance(content_type_filter, ContentTypeEnum):
                queryset = queryset.filter(content_type=content_type_filter.value)
            else:
                queryset = queryset.filter(content_type=content_type_filter)

        return queryset

    @classmethod
    def get_folders_by_type(cls, profile, content_type, is_todo=None):
        """
        Get folders filtered by content type and optionally todo status

        Args:
            profile: PseudonymousProfile instance
            content_type: ContentTypeEnum or string
            is_todo: Optional boolean to filter by todo folder status

        Returns:
            QuerySet of BookmarkFolder objects
        """
        content_type_value = (
            content_type.value
            if isinstance(content_type, ContentTypeEnum)
            else content_type
        )

        queryset = cls.objects.filter(profile=profile, content_type=content_type_value)

        if is_todo is not None:
            queryset = queryset.filter(is_todo_folder=is_todo)

        return queryset


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

    # BookMark can also act as todo item (PollTodo is ContentType)
    is_todo = models.BooleanField(
        default=False,
        help_text="If true, this bookmark acts as a todo item",
    )
    todo_completed = models.BooleanField(
        default=False,
        help_text="If true, this todo item is marked as completed",
    )
    todo_due_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Due date for the todo item, if applicable",
    )

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
    def toggle_bookmark(
        cls,
        profile,
        content_obj,
        folder=None,
        notes="",
        is_todo=False,
        todo_due_date=None,
    ):
        """
        Toggle bookmark status for content using pseudonymous profile.

        Args:
            profile: PseudonymousProfile instance
            content_obj: Any model instance to bookmark/unbookmark
            folder: Optional BookmarkFolder to organize bookmark
            notes: Optional notes for the bookmark
            is_todo: Whether this bookmark is a todo item
            todo_due_date: Optional due date for todo items

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
                "is_todo": is_todo,
                "todo_due_date": todo_due_date,
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


class FolderAccess(models.Model):
    """
    Unified model for tracking folder access
    (saved public folders and paid subscriptions)
    """

    ACCESS_TYPE_CHOICES = [
        ("saved", "Saved Public Folder"),
        ("subscribed", "Paid Subscription"),
    ]

    profile = models.ForeignKey(
        "profile.PseudonymousProfile",
        on_delete=models.CASCADE,
        related_name="folder_accesses",
    )
    folder = models.ForeignKey(
        BookmarkFolder,
        on_delete=models.CASCADE,
        related_name="folder_accesses",
    )
    access_type = models.CharField(
        max_length=20,
        choices=ACCESS_TYPE_CHOICES,
        help_text="Type of access: saved public folder or paid subscription",
    )

    # Common fields
    created_at = models.DateTimeField(default=timezone.now)
    is_active = models.BooleanField(
        default=True, help_text="Whether this access is currently active"
    )

    # Subscription-specific fields (null for saved folders)
    expires_at = models.DateTimeField(
        null=True, blank=True, help_text="Expiration date for paid subscriptions"
    )
    payment_reference = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Payment reference ID for subscriptions",
    )

    class Meta:
        # User can't have duplicate access to same folder
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "folder", "access_type"],
                name="unique_folder_access_per_profile_per_type",
            )
        ]
        indexes = [
            models.Index(fields=["profile", "is_active"]),
            models.Index(fields=["folder", "access_type"]),
            models.Index(fields=["profile", "access_type", "is_active"]),
            models.Index(fields=["expires_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"{self.profile.username} - {self.get_access_type_display()} - "
            f"{self.folder.name}"
        )

    @property
    def is_expired(self):
        """Check if subscription access has expired"""
        if self.access_type == "subscribed" and self.expires_at:
            return timezone.now() > self.expires_at
        return False

    @classmethod
    def has_folder_access(cls, profile, folder):
        """
        Check if profile has access to folder through saved or subscription

        Args:
            profile: PseudonymousProfile instance
            folder: BookmarkFolder instance

        Returns:
            bool: True if profile has active access to folder
        """
        if not profile:
            return False

        return (
            cls.objects.filter(profile=profile, folder=folder, is_active=True)
            .exclude(
                # Exclude expired subscriptions
                access_type="subscribed",
                expires_at__lt=timezone.now(),
            )
            .exists()
        )
