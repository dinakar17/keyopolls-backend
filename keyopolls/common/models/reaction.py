from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class Reaction(models.Model):
    """Generic reactions for any content type - simplified for PseudonymousProfile"""

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

    # Profile reference (direct foreign key)
    profile = models.ForeignKey(
        "profile.PseudonymousProfile",  # Replace with your app name
        on_delete=models.CASCADE,
        related_name="reactions",
    )

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
                    "profile",
                    "content_type",
                    "object_id",
                    "reaction_type",
                ],
                name="unique_profile_reaction_per_object",
            ),
        ]

        indexes = [
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["profile", "-created_at"]),
            models.Index(fields=["content_type", "object_id", "reaction_type"]),
            models.Index(fields=["reaction_type"]),
        ]

    def __str__(self):
        content_type_name = self.content_type.model
        return (
            f"{self.reaction_type} by {self.profile.username} "
            f"on {content_type_name} {self.object_id}"
        )

    @classmethod
    def get_user_reactions_by_profile(cls, profile, content_obj):
        """
        Get all reactions a profile has on a content object.

        Args:
            profile: PseudonymousProfile instance
            content_obj: Any model instance (Poll, Comment, etc.)

        Returns:
            dict: Dictionary of {reaction_type: bool} indicating user's reactions
        """
        if not profile:
            return {r_type: False for r_type, _ in cls.REACTION_TYPES}

        content_type = ContentType.objects.get_for_model(content_obj)

        # Get all user reactions for this object
        user_reactions = cls.objects.filter(
            profile=profile,
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
    def toggle_reaction(cls, profile, content_obj, reaction_type="like"):
        """
        Toggle a reaction for any content object using pseudonymous profile.
        If the same reaction exists, it will be removed.
        If an opposite reaction exists, it will be switched.
        If no reaction exists, a new one will be created.

        Args:
            profile: PseudonymousProfile instance from authentication
            content_obj: Any model instance (Poll, Comment, etc.)
            reaction_type: The type of reaction ('like', 'dislike', etc.)

        Returns:
            tuple: (action_taken, reaction_counts)
                action_taken: 'added', 'removed', or 'switched'
                reaction_counts: dict of {reaction_type: count} for
                all reactions on this object
        """
        content_type = ContentType.objects.get_for_model(content_obj)

        # Check if there's an existing reaction of the requested type
        existing_reaction = cls.objects.filter(
            profile=profile,
            content_type=content_type,
            object_id=content_obj.id,
            reaction_type=reaction_type,
        ).first()

        # Get all other reactions from this profile on this object
        # (for potential switching)
        other_reactions = cls.objects.filter(
            profile=profile,
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
                profile=profile,
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
    def get_user_reactions(cls, profile, content_obj):
        """
        Get all reactions a profile has on a content object.

        Args:
            profile: PseudonymousProfile instance from authentication (can be None)
            content_obj: Any model instance (Poll, Comment, etc.)

        Returns:
            dict: Dictionary of {reaction_type: bool} indicating user's reactions
        """
        if not profile:
            return {r_type: False for r_type, _ in cls.REACTION_TYPES}

        return cls.get_user_reactions_by_profile(profile, content_obj)

    @classmethod
    def get_reaction_counts(cls, content_obj):
        """
        Get reaction counts for a content object.

        Args:
            content_obj: Any model instance (Poll, Comment, etc.)

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

    # Generic foreign key to any model (Poll, Comment, etc.)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    # Profile reference (nullable for unauthenticated shares)
    profile = models.ForeignKey(
        "profile.PseudonymousProfile",
        on_delete=models.CASCADE,
        related_name="shares",
        null=True,
        blank=True,
    )

    # Share details
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES)
    shared_at = models.DateTimeField(auto_now_add=True)

    # For unauthenticated users
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    referrer = models.URLField(blank=True)

    class Meta:
        ordering = ["-shared_at"]
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["profile", "-shared_at"]),
            models.Index(fields=["platform", "shared_at"]),
            # For unauthenticated users
            models.Index(fields=["ip_address", "platform"]),
        ]
        # Prevent duplicate shares
        constraints = [
            # For authenticated users
            models.UniqueConstraint(
                fields=[
                    "content_type",
                    "object_id",
                    "profile",
                    "platform",
                ],
                condition=models.Q(profile__isnull=False),
                name="unique_share_per_authenticated_profile_platform",
            ),
            # For unauthenticated users (IP-based)
            models.UniqueConstraint(
                fields=["content_type", "object_id", "ip_address", "platform"],
                condition=models.Q(profile__isnull=True),
                name="unique_share_per_unauthenticated_user_platform",
            ),
        ]

    def __str__(self):
        if self.profile:
            return (
                f"{self.profile.username} shared "
                f"{self.content_object} on {self.get_platform_display()}"
            )
        else:
            return (
                f"Unauthenticated user ({self.ip_address}) shared "
                f"{self.content_object} on {self.get_platform_display()}"
            )

    @classmethod
    def increment_share_count(cls, content_object, profile, platform, **kwargs):
        """
        Create a share record and increment the content object's share_count
        Returns (share_instance, created)

        Args:
            content_object: The object being shared (Poll, Comment, etc.)
            profile: PseudonymousProfile instance (None for unauthenticated users)
            platform: Platform where content is being shared
            **kwargs: Additional data like ip_address, user_agent, referrer
        """
        from django.db import transaction

        with transaction.atomic():
            # For unauthenticated users, use IP-based uniqueness
            if profile is None:
                share, created = cls.objects.get_or_create(
                    content_type=ContentType.objects.get_for_model(content_object),
                    object_id=content_object.id,
                    profile=None,
                    ip_address=kwargs.get("ip_address"),
                    platform=platform,
                    defaults={
                        "user_agent": kwargs.get("user_agent", ""),
                        "referrer": kwargs.get("referrer", ""),
                    },
                )
            else:
                # For authenticated users, use profile-based uniqueness
                share, created = cls.objects.get_or_create(
                    content_type=ContentType.objects.get_for_model(content_object),
                    object_id=content_object.id,
                    profile=profile,
                    platform=platform,
                    defaults=kwargs,
                )

            if created:
                # Increment the share count on the content object
                if hasattr(content_object, "share_count"):
                    content_object.share_count = models.F("share_count") + 1
                    content_object.save(update_fields=["share_count"])
                    # Refresh to get the actual value
                    content_object.refresh_from_db(fields=["share_count"])

            return share, created

    @classmethod
    def get_user_shares(cls, profile, content_obj):
        """
        Get all platforms a profile has shared a content object on.

        Args:
            profile: PseudonymousProfile instance (can be None)
            content_obj: Any model instance (Poll, Comment, etc.)

        Returns:
            list: List of platforms the user has shared this content on
        """
        if not profile:
            return []

        content_type = ContentType.objects.get_for_model(content_obj)

        return list(
            cls.objects.filter(
                profile=profile,
                content_type=content_type,
                object_id=content_obj.id,
            ).values_list("platform", flat=True)
        )

    @classmethod
    def get_share_counts_by_platform(cls, content_obj):
        """
        Get share counts by platform for a content object.

        Args:
            content_obj: Any model instance (Poll, Comment, etc.)

        Returns:
            dict: Dictionary of {platform: count}
        """
        content_type = ContentType.objects.get_for_model(content_obj)

        share_counts = {}
        for platform_key, platform_name in cls.PLATFORM_CHOICES:
            count = cls.objects.filter(
                content_type=content_type,
                object_id=content_obj.id,
                platform=platform_key,
            ).count()
            share_counts[platform_key] = count

        return share_counts
