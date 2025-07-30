from django.contrib.contenttypes.fields import GenericRelation
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from keyopolls.utils import generate_youtube_like_id


class PollList(models.Model):
    """
    Poll lists that can contain both polls and other lists (folders).
    Supports nested folder structures with efficient querying.
    """

    LIST_TYPE_CHOICES = [
        ("folder", "Folder"),
        ("list", "Poll List"),
    ]

    VISIBILITY_CHOICES = [
        ("public", "Public"),
        ("unlisted", "Unlisted"),
        ("private", "Private"),
    ]

    # Basic fields
    id = models.BigAutoField(primary_key=True)

    # Unique identifier similar to YouTube
    unique_id = models.CharField(
        max_length=11,
        unique=True,
        blank=True,
        null=True,
        help_text="11-character unique identifier for the list",
    )

    # URL-friendly slug
    slug = models.SlugField(
        max_length=100,
        unique=True,
        blank=True,
        null=True,
        help_text="URL-friendly identifier for the list",
    )

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    image = models.ImageField(
        upload_to="poll_lists/images/",
        blank=True,
        null=True,
        help_text="Optional image for the list",
    )

    prerequisites = models.JSONField(
        default=dict,
        blank=True,
        help_text="Optional prerequisites for viewing this list "
        "(e.g., must follow community)",
    )

    # List configuration
    list_type = models.CharField(
        max_length=20, choices=LIST_TYPE_CHOICES, default="list"
    )
    visibility = models.CharField(
        max_length=20, choices=VISIBILITY_CHOICES, default="public"
    )

    # Owner
    profile = models.ForeignKey(
        "profile.PseudonymousProfile",
        on_delete=models.CASCADE,
        related_name="poll_lists",
    )

    # Community (lists belong to communities like polls)
    community = models.ForeignKey(
        "communities.Community", on_delete=models.CASCADE, related_name="poll_lists"
    )

    # Self-referencing parent for nested structure
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        help_text="Parent folder (null for root-level lists)",
    )

    # Tree structure fields for efficient querying
    # Using materialized path pattern for better performance
    path = models.CharField(
        max_length=500,
        blank=True,
        help_text="Materialized path for efficient tree queries (e.g., '1/5/12/')",
    )
    depth = models.PositiveIntegerField(default=0)

    # Display order within parent
    order = models.PositiveIntegerField(default=0)

    # Denormalized counts for performance
    direct_polls_count = models.PositiveIntegerField(default=0)  # Direct children polls
    total_polls_count = models.PositiveIntegerField(default=0)  # Including nested
    direct_folders_count = models.PositiveIntegerField(
        default=0
    )  # Direct child folders
    total_items_count = models.PositiveIntegerField(
        default=0
    )  # All items including nested

    # List settings
    is_featured = models.BooleanField(default=False)
    is_collaborative = models.BooleanField(default=False)  # Allow others to add polls
    max_polls = models.PositiveIntegerField(null=True, blank=True)  # Optional limit

    # Engagement metrics
    view_count = models.PositiveIntegerField(default=0)
    bookmark_count = models.PositiveIntegerField(default=0)
    share_count = models.PositiveIntegerField(default=0)
    like_count = models.PositiveIntegerField(default=0)

    # Generic relations for reactions, etc.
    reactions = GenericRelation("common.Reaction")

    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    # Soft deletion
    is_deleted = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["profile", "-created_at"]),
            models.Index(fields=["community", "-created_at"]),
            models.Index(fields=["parent", "order"]),
            models.Index(fields=["path"]),
            models.Index(fields=["visibility", "-created_at"]),
            models.Index(fields=["list_type", "-created_at"]),
            models.Index(fields=["is_featured", "-created_at"]),
            models.Index(fields=["community", "parent", "order"]),
            models.Index(fields=["is_deleted", "visibility"]),
            models.Index(fields=["unique_id"]),
            models.Index(fields=["slug"]),
        ]
        unique_together = [
            ["parent", "order"],  # Unique ordering within parent
        ]
        ordering = ["order", "-created_at"]

    def __str__(self):
        type_icon = "📁" if self.list_type == "folder" else "📋"
        return f"{type_icon} {self.title}"

    def save(self, *args, **kwargs):
        """Override save to generate unique_id, slug, and update tree fields"""
        # Generate unique unique_id if not provided
        if not self.unique_id:
            max_attempts = 10
            for _ in range(max_attempts):
                new_id = generate_youtube_like_id()
                if not PollList.objects.filter(unique_id=new_id).exists():
                    self.unique_id = new_id
                    break
            else:
                raise ValueError(
                    f"Could not generate unique unique_id after {max_attempts} attempts"
                )

        # Generate slug if not provided
        if not self.slug:
            base_slug = slugify(self.title)[:90]
            slug = base_slug
            counter = 1

            while PollList.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                suffix = f"-{counter}"
                max_base_length = 100 - len(suffix)
                slug = f"{base_slug[:max_base_length]}{suffix}"
                counter += 1

            self.slug = slug

        # Update tree fields
        if self.parent:
            self.depth = self.parent.depth + 1
            self.path = f"{self.parent.path}{self.parent.id}/"
        else:
            self.depth = 0
            self.path = ""

        super().save(*args, **kwargs)

    def clean(self):
        """Validate model constraints"""
        # Prevent circular references
        if self.parent:
            if self.parent == self:
                raise ValidationError("A list cannot be its own parent")

            # Check for circular reference in ancestors
            current = self.parent
            while current:
                if current == self:
                    raise ValidationError(
                        "Circular reference detected in parent hierarchy"
                    )
                current = current.parent

        # Validate depth limit (prevent too deep nesting)
        if self.depth > 10:  # Configurable limit
            raise ValidationError("Maximum nesting depth of 10 levels exceeded")

    def get_absolute_url(self):
        """Get the absolute URL for this list"""
        from django.urls import reverse

        return reverse("poll_list_detail", kwargs={"slug": self.slug})

    @property
    def is_folder(self):
        """Check if this is a folder"""
        return self.list_type == "folder"

    @property
    def is_root_level(self):
        """Check if this is a root-level item"""
        return self.parent is None

    def get_ancestors(self):
        """Get all ancestors from root to parent"""
        if not self.parent:
            return PollList.objects.none()

        # Parse path to get ancestor IDs
        if self.path:
            ancestor_ids = [
                int(id_str) for id_str in self.path.strip("/").split("/") if id_str
            ]
            return PollList.objects.filter(id__in=ancestor_ids).order_by("depth")
        return PollList.objects.none()

    def get_descendants(self):
        """Get all descendants (children, grandchildren, etc.)"""
        return PollList.objects.filter(
            path__startswith=f"{self.path}{self.id}/", is_deleted=False
        ).order_by("depth", "order")

    def get_children(self):
        """Get direct children only"""
        return self.children.filter(is_deleted=False).order_by("order")

    def get_breadcrumbs(self):
        """Get breadcrumb navigation"""
        breadcrumbs = list(self.get_ancestors())
        breadcrumbs.append(self)
        return breadcrumbs

    def update_counts(self):
        """Update denormalized counts"""
        # Direct polls count
        self.direct_polls_count = self.poll_list.filter(is_deleted=False).count()

        # Direct folders count
        self.direct_folders_count = self.children.filter(
            list_type="folder", is_deleted=False
        ).count()

        # Total polls count (including nested)
        descendant_poll_counts = (
            self.get_descendants().aggregate(total=models.Sum("direct_polls_count"))[
                "total"
            ]
            or 0
        )
        self.total_polls_count = self.direct_polls_count + descendant_poll_counts

        # Total items count
        self.total_items_count = (
            self.direct_polls_count
            + self.direct_folders_count
            + self.get_descendants().count()
        )

        self.save(
            update_fields=[
                "direct_polls_count",
                "total_polls_count",
                "direct_folders_count",
                "total_items_count",
            ]
        )

    def can_add_polls(self, profile):
        """Check if profile can add polls to this list"""
        # Owner can always add
        if self.profile == profile:
            return True

        # Check if collaborative and user has permission
        if self.is_collaborative:
            # You might want to add more specific permission logic here
            # For now, any community member can add to collaborative lists
            try:
                membership = self.community.memberships.get(profile=profile)
                return membership.is_active_member
            except Exception:
                return False

        return False

    def move_to_parent(self, new_parent, new_order=None):
        """Move this list to a new parent"""
        if new_parent and new_parent.community != self.community:
            raise ValidationError("Cannot move list to different community")

        self.parent = new_parent
        if new_order is not None:
            self.order = new_order

        self.full_clean()  # This will update path and depth
        self.save()

        # Update all descendants' paths
        for descendant in self.get_descendants():
            descendant.save()  # This will recalculate path


class PollListCollaborator(models.Model):
    """
    Users who can collaborate on a list (add/remove polls, edit list)
    """

    PERMISSION_CHOICES = [
        ("view", "View Only"),
        ("add", "Can Add Polls"),
        ("edit", "Can Edit List"),
        ("admin", "Full Admin"),
    ]

    id = models.BigAutoField(primary_key=True)

    poll_list = models.ForeignKey(
        PollList, on_delete=models.CASCADE, related_name="collaborators"
    )

    profile = models.ForeignKey(
        "profile.PseudonymousProfile",
        on_delete=models.CASCADE,
        related_name="collaborated_lists",
    )

    permission_level = models.CharField(
        max_length=20, choices=PERMISSION_CHOICES, default="add"
    )

    # Who invited this collaborator
    invited_by = models.ForeignKey(
        "profile.PseudonymousProfile",
        on_delete=models.CASCADE,
        related_name="sent_list_invitations",
    )

    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=["poll_list", "permission_level"]),
            models.Index(fields=["profile", "-created_at"]),
        ]
        unique_together = ["poll_list", "profile"]

    def __str__(self):
        return (
            f"{self.profile.username} - {self.poll_list.title} "
            f"({self.get_permission_level_display()})"
        )

    def can_add_polls(self):
        """Check if collaborator can add polls"""
        return self.permission_level in ["add", "edit", "admin"]

    def can_edit_list(self):
        """Check if collaborator can edit list details"""
        return self.permission_level in ["edit", "admin"]

    def can_manage_collaborators(self):
        """Check if collaborator can manage other collaborators"""
        return self.permission_level == "admin"
