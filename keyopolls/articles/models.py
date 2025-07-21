from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.utils import timezone

from keyopolls.common.models import ImpressionTrackingMixin, TaggedItem
from keyopolls.communities.models import Community
from keyopolls.profile.models import PseudonymousProfile


class Article(models.Model, ImpressionTrackingMixin):
    """
    Model to store articles with title, subtitle, main image, and content.
    """

    title = models.CharField(max_length=200)
    subtitle = models.CharField(max_length=300, blank=True, null=True)
    main_image = models.ImageField(upload_to="articles/images/", blank=True, null=True)
    content = models.TextField(
        blank=True, null=True, help_text="Markdown content of the article"
    )

    link = models.URLField(
        max_length=500, blank=True, null=True, help_text="Optional link to the article"
    )
    author_name = models.CharField(
        max_length=100, blank=True, null=True, help_text="Name of the article author"
    )

    # Relationships
    community = models.ForeignKey(
        Community, on_delete=models.CASCADE, related_name="articles"
    )
    creator = models.ForeignKey(
        PseudonymousProfile, on_delete=models.CASCADE, related_name="articles"
    )

    # Add this line for tags relationship
    tagged_items = GenericRelation(TaggedItem)

    likes_count = models.PositiveIntegerField(default=0, editable=False)
    dislikes_count = models.PositiveIntegerField(default=0, editable=False)
    shares_count = models.PositiveIntegerField(default=0, editable=False)
    impressions_count = models.PositiveIntegerField(default=0, editable=False)

    # Metadata
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    is_published = models.BooleanField(default=False)

    @property
    def tags(self):
        """Property to get tags for this article"""
        from keyopolls.common.models import Tag

        return Tag.objects.filter(items__content_object=self)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["community", "is_published"]),
            models.Index(fields=["creator", "created_at"]),
        ]

    def __str__(self):
        return self.title
