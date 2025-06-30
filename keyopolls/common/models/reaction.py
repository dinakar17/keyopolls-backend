from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class Reaction(models.Model):
    """Generic reactions for any content type -
    supports all profile types: professional, public, pseudonymous, and anonymous"""

    # Currently supported reaction types
    REACTION_TYPES = (
        ("like", "Like"),
        ("dislike", "Dislike"),
        # Future reaction types can be added here:
        # ('love', 'Love'),
        # ('haha', 'Haha'),
        # ('wow', 'Wow'),
        # ('sad', 'Sad'),
        # ('angry', 'Angry'),
    )

    # Profile type choices - updated for new auth system
    PROFILE_TYPES = (
        ("professional", "Professional"),
        ("public", "Public"),
        ("pseudonymous", "Pseudonymous"),
        ("anonymous", "Anonymous"),
    )

    # Profile type and ID (instead of specific foreign keys)
    profile_type = models.CharField(max_length=20, choices=PROFILE_TYPES)
    profile_id = models.BigIntegerField()

    # Reaction type
    reaction_type = models.CharField(
        max_length=20, choices=REACTION_TYPES, default="like"
    )

    # Generic foreign key to support multiple content types
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.BigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Ensure a profile can only have one reaction type per content object
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "profile_type",
                    "profile_id",
                    "content_type",
                    "object_id",
                    "reaction_type",
                ],
                name="unique_profile_reaction_per_object",
            ),
        ]

        indexes = [
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["profile_type", "profile_id", "-created_at"]),
            models.Index(fields=["content_type", "object_id", "reaction_type"]),
            models.Index(fields=["reaction_type"]),
        ]

    def __str__(self):
        content_type_name = self.content_type.model
        return (
            f"{self.reaction_type} by {self.profile_type} profile {self.profile_id} "
            f"on {content_type_name} {self.object_id}"
        )

    @classmethod
    def get_user_reactions_by_profile_info(cls, profile_type, profile_id, content_obj):
        """
        Get all reactions a profile has on a content object using profile type and ID.
        This avoids circular imports by not importing profile models.

        Args:
            profile_type: The type of profile ("professional", "public", etc.)
            profile_id: The ID of the profile
            content_obj: Any model instance (Post, Comment, CommunityPost, etc.)

        Returns:
            dict: Dictionary of {reaction_type: bool} indicating user's reactions
        """
        if not profile_type or not profile_id:
            return {r_type: False for r_type, _ in cls.REACTION_TYPES}

        content_type = ContentType.objects.get_for_model(content_obj)

        # Get all user reactions for this object
        user_reactions = cls.objects.filter(
            profile_type=profile_type,
            profile_id=profile_id,
            content_type=content_type,
            object_id=content_obj.id,
        ).values_list("reaction_type", flat=True)

        # Create a dictionary of all possible reaction types set to False
        reaction_status = {r_type: False for r_type, _ in cls.REACTION_TYPES}

        # Set True for reactions that exist
        for reaction in user_reactions:
            reaction_status[reaction] = True

        return reaction_status

    @classmethod
    def toggle_reaction(cls, public_profile, content_obj, reaction_type="like"):
        """
        Toggle a reaction for any content object using public profile.
        If the same reaction exists, it will be removed.
        If an opposite reaction exists, it will be switched.
        If no reaction exists, a new one will be created.

        Args:
            public_profile: PublicProfile instance from authentication
            content_obj: Any model instance (Post, Comment, CommunityPost, etc.)
            reaction_type: The type of reaction ('like', 'dislike', etc.)

        Returns:
            tuple: (action_taken, reaction_counts)
                action_taken: 'added', 'removed', or 'switched'
                reaction_counts: dict of {reaction_type: count} for
                all reactions on this object
        """
        content_type = ContentType.objects.get_for_model(content_obj)
        profile_type = "public"  # Always public for new auth system
        profile_id = public_profile.id

        # Check if there's an existing reaction of the requested type
        existing_reaction = cls.objects.filter(
            profile_type=profile_type,
            profile_id=profile_id,
            content_type=content_type,
            object_id=content_obj.id,
            reaction_type=reaction_type,
        ).first()

        # Get all other reactions from this profile on this object
        # (for potential switching)
        other_reactions = cls.objects.filter(
            profile_type=profile_type,
            profile_id=profile_id,
            content_type=content_type,
            object_id=content_obj.id,
        ).exclude(id=existing_reaction.id if existing_reaction else None)

        action_taken = None

        # Delete any other reactions from this profile (if exclusive reactions)
        if other_reactions.exists():
            other_reactions.delete()
            action_taken = "switched"

        # Update reaction state based on existing state
        if existing_reaction:
            # If the same reaction type exists, remove it (toggle off)
            existing_reaction.delete()
            action_taken = "removed" if action_taken is None else action_taken
        else:
            # No existing reaction of this type, create a new one
            cls.objects.create(
                profile_type=profile_type,
                profile_id=profile_id,
                content_type=content_type,
                object_id=content_obj.id,
                reaction_type=reaction_type,
            )
            action_taken = "added" if action_taken is None else action_taken

        # Get current counts for all reaction types
        reaction_counts = {}
        for r_type, _ in cls.REACTION_TYPES:
            count = cls.objects.filter(
                content_type=content_type,
                object_id=content_obj.id,
                reaction_type=r_type,
            ).count()
            reaction_counts[r_type] = count

        # Update counters on the content object if it has them
        cls._update_content_object_counters(content_obj, reaction_counts)

        return action_taken, reaction_counts

    @staticmethod
    def _update_content_object_counters(content_obj, reaction_counts):
        """
        Update counter fields on the content object if they exist.

        Args:
            content_obj: The content object instance
            reaction_counts: Dict of {reaction_type: count}
        """
        # Check and update fields if they exist
        updated_fields = []

        # Standard like_count field
        if hasattr(content_obj, "like_count") and "like" in reaction_counts:
            content_obj.like_count = reaction_counts["like"]
            updated_fields.append("like_count")

        # Dislike count if it exists
        if hasattr(content_obj, "dislike_count") and "dislike" in reaction_counts:
            content_obj.dislike_count = reaction_counts["dislike"]
            updated_fields.append("dislike_count")

        # Other potential reaction counters
        for reaction_type in reaction_counts:
            counter_field = f"{reaction_type}_count"
            if hasattr(content_obj, counter_field):
                setattr(content_obj, counter_field, reaction_counts[reaction_type])
                updated_fields.append(counter_field)

        # Save only if we have fields to update
        if updated_fields:
            content_obj.save(update_fields=updated_fields)

    @classmethod
    def get_user_reactions(cls, public_profile, content_obj):
        """
        Get all reactions a public profile has on a content object.

        Args:
            public_profile: PublicProfile instance from authentication (can be None)
            content_obj: Any model instance (Post, Comment, CommunityPost, etc.)

        Returns:
            dict: Dictionary of {reaction_type: bool} indicating user's reactions
        """
        if not public_profile:
            return {r_type: False for r_type, _ in cls.REACTION_TYPES}

        return cls.get_user_reactions_by_profile_info(
            "public", public_profile.id, content_obj
        )

    @classmethod
    def get_reaction_counts(cls, content_obj):
        """
        Get reaction counts for a content object.

        Args:
            content_obj: Any model instance (Post, Comment, CommunityPost, etc.)

        Returns:
            dict: Dictionary of {reaction_type: count}
        """
        content_type = ContentType.objects.get_for_model(content_obj)

        reaction_counts = {}
        for r_type, _ in cls.REACTION_TYPES:
            count = cls.objects.filter(
                content_type=content_type,
                object_id=content_obj.id,
                reaction_type=r_type,
            ).count()
            reaction_counts[r_type] = count

        return reaction_counts


class Share(models.Model):
    """Generic share tracking model for any content type"""

    PLATFORM_CHOICES = [
        ("twitter", "Twitter"),
        ("facebook", "Facebook"),
        ("linkedin", "LinkedIn"),
        ("reddit", "Reddit"),
        ("email", "Email"),
        ("link", "Direct Link"),
        ("embed", "Embed Code"),
        ("native", "Native Share"),
        ("other", "Other"),
    ]

    # Updated profile type choices for new auth system
    PROFILE_TYPE_CHOICES = [
        ("professional", "Professional"),
        ("public", "Public"),
        ("pseudonymous", "Pseudonymous"),
        ("anonymous", "Anonymous"),
        ("unauthenticated", "Unauthenticated"),
    ]

    # Generic foreign key to any model (Post, CommunityPost, Article, etc.)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    # Profile information (instead of User FK)
    profile_type = models.CharField(max_length=20, choices=PROFILE_TYPE_CHOICES)
    profile_id = models.PositiveIntegerField()

    # Share details
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES)
    shared_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    referrer = models.URLField(blank=True)

    class Meta:
        ordering = ["-shared_at"]
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["profile_type", "profile_id"]),
            models.Index(fields=["platform", "shared_at"]),
        ]
        # Prevent duplicate shares from same profile for same content within short time
        # For unauthenticated users, we use IP + User Agent to prevent duplicates
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "content_type",
                    "object_id",
                    "profile_type",
                    "profile_id",
                    "platform",
                ],
                condition=models.Q(
                    profile_type__in=[
                        "professional",
                        "public",
                        "pseudonymous",
                        "anonymous",
                    ]
                ),
                name="unique_share_per_authenticated_profile_platform",
            ),
            models.UniqueConstraint(
                fields=["content_type", "object_id", "ip_address", "platform"],
                condition=models.Q(profile_type="unauthenticated"),
                name="unique_share_per_unauthenticated_user_platform",
            ),
        ]

    def __str__(self):
        if self.profile_type == "unauthenticated":
            return (
                f"Unauthenticated user ({self.ip_address}) shared "
                f"{self.content_object} on {self.get_platform_display()}"
            )
        return (
            f"{self.profile_type} {self.profile_id} shared "
            f"{self.content_object} on {self.get_platform_display()}"
        )

    @classmethod
    def increment_share_count(
        cls, content_object, profile_type, profile_id, platform, **kwargs
    ):
        """
        Create a share record and increment the content object's share_count
        Returns (share_instance, created)

        Updated to work with new auth system where authenticated users are
        always public profiles
        """
        from django.db import transaction

        with transaction.atomic():
            # For unauthenticated users, use IP-based uniqueness
            if profile_type == "unauthenticated":
                share, created = cls.objects.get_or_create(
                    content_type=ContentType.objects.get_for_model(content_object),
                    object_id=content_object.id,
                    profile_type=profile_type,
                    ip_address=kwargs.get("ip_address"),
                    platform=platform,
                    defaults={
                        "profile_id": profile_id,
                        "user_agent": kwargs.get("user_agent", ""),
                        "referrer": kwargs.get("referrer", ""),
                    },
                )
            else:
                # For authenticated users (now always public profiles),
                # use profile-based uniqueness
                share, created = cls.objects.get_or_create(
                    content_type=ContentType.objects.get_for_model(content_object),
                    object_id=content_object.id,
                    profile_type=profile_type,
                    profile_id=profile_id,
                    platform=platform,
                    defaults=kwargs,
                )

            if created:
                # Increment the share count on the content object
                content_object.share_count = models.F("share_count") + 1
                content_object.save(update_fields=["share_count"])
                # Refresh to get the actual value
                content_object.refresh_from_db(fields=["share_count"])

            return share, created
