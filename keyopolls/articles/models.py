from django.db import models
from django.utils import timezone

from keyopolls.communities.models import Community
from keyopolls.profile.models import PseudonymousProfile


class Article(models.Model):
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

    # Relationships
    community = models.ForeignKey(
        Community, on_delete=models.CASCADE, related_name="articles"
    )
    author = models.ForeignKey(
        PseudonymousProfile, on_delete=models.CASCADE, related_name="articles"
    )

    # Metadata
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    is_published = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["community", "is_published"]),
            models.Index(fields=["author", "created_at"]),
        ]

    def __str__(self):
        return self.title
