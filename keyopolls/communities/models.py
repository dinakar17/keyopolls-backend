from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from keyopolls.common.models import TaggedItem


class Community(models.Model):
    COMMUNITY_TYPE_CHOICES = [
        ("public", "Public"),
        ("private", "Private"),
        ("restricted", "Restricted"),  # Requires approval to join
    ]

    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(
        max_length=100,
        unique=True,
        help_text="Unique URL-friendly identifier for the community",
        null=True,
        blank=True,
    )
    description = models.TextField(blank=True)

    avatar = models.ImageField(
        upload_to="community_avatars/",
        blank=True,
        null=True,
        help_text="Community avatar image",
    )

    banner = models.ImageField(
        upload_to="community_banners/",
        blank=True,
        null=True,
        help_text="Community banner image",
    )

    # Community settings
    community_type = models.CharField(
        max_length=20, choices=COMMUNITY_TYPE_CHOICES, default="public"
    )

    # Category relationship
    category = models.ForeignKey(
        "common.Category",
        on_delete=models.CASCADE,
        related_name="communities",
        null=True,
        blank=True,
    )

    rules = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "List of community rules. Each rule should be between "
            "10 and 280 characters."
        ),
    )

    # Creator
    creator = models.ForeignKey(
        "profile.PseudonymousProfile",
        on_delete=models.CASCADE,
        related_name="created_communities",
    )

    # Denormalized counts
    member_count = models.PositiveIntegerField(default=1)  # Creator is first member
    poll_count = models.PositiveIntegerField(default=0)

    # Community rules and settings
    requires_aura_to_join = models.PositiveIntegerField(default=0)
    requires_aura_to_post = models.PositiveIntegerField(default=0)

    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    # Status
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["community_type", "-created_at"]),
            models.Index(fields=["-member_count"]),
            models.Index(fields=["is_active", "-created_at"]),
            models.Index(fields=["category", "-created_at"]),
        ]
        ordering = ["-created_at"]
        verbose_name_plural = "Communities"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.get_community_type_display()})"

    def can_join(self, profile):
        """Check if profile can join this community"""
        if not self.is_active:
            return False
        if (
            self.requires_aura_to_join > 0
            and profile.total_aura < self.requires_aura_to_join
        ):
            return False
        return True

    def can_post(self, profile):
        """Check if profile can post in this community"""
        if not self.is_active:
            return False
        if (
            self.requires_aura_to_post > 0
            and profile.total_aura < self.requires_aura_to_post
        ):
            return False
        return True

    def get_tags(self):
        """Get all tags associated with this community"""
        community_content_type = ContentType.objects.get_for_model(Community)
        return TaggedItem.objects.filter(
            content_type=community_content_type, object_id=self.id
        ).select_related("tag")


class CommunityMembership(models.Model):
    """Community membership - simple and efficient"""

    ROLE_CHOICES = [
        ("member", "Member"),
        ("moderator", "Moderator"),
        ("recruiter", "Recruiter"),
        ("creator", "Creator"),
    ]

    STATUS_CHOICES = [
        ("active", "Active"),
        ("pending", "Pending"),  # For restricted communities
        ("banned", "Banned"),
        ("left", "Left"),
    ]

    id = models.BigAutoField(primary_key=True)
    community = models.ForeignKey(
        Community, on_delete=models.CASCADE, related_name="memberships"
    )
    profile = models.ForeignKey(
        "profile.PseudonymousProfile",
        on_delete=models.CASCADE,
        related_name="community_memberships",
    )

    # Membership details
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="member")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")

    # Timestamps
    joined_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["community", "status"]),
            models.Index(fields=["profile", "status"]),
            models.Index(fields=["community", "role"]),
        ]
        unique_together = ["community", "profile"]

    def __str__(self):
        return f"{self.profile.username} - {self.community.name} ({self.role})"

    @property
    def is_active_member(self):
        """Check if this is an active membership"""
        return self.status == "active"

    @property
    def can_moderate(self):
        """Check if member can moderate"""
        return self.role in ["moderator", "admin", "creator"] and self.is_active_member
