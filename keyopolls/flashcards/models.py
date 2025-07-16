from django.db import models
from django.utils import timezone

from keyopolls.communities.models import Community
from keyopolls.profile.models import PseudonymousProfile


class FlashcardSet(models.Model):
    """
    Model to store a set of flashcards.
    """

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)

    # Relationships
    community = models.ForeignKey(
        Community, on_delete=models.CASCADE, related_name="flashcard_sets"
    )
    creator = models.ForeignKey(
        PseudonymousProfile, on_delete=models.CASCADE, related_name="flashcard_sets"
    )

    # Metadata
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    is_public = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["community", "is_public"]),
            models.Index(fields=["creator", "created_at"]),
        ]

    def __str__(self):
        return self.title

    def flashcard_count(self):
        """Return the number of flashcards in this set."""
        return self.flashcards.count()


class Flashcard(models.Model):
    """
    Individual flashcard belonging to a flashcard set.
    """

    question = models.TextField()
    answer = models.TextField()

    # Relationship to flashcard set
    flashcard_set = models.ForeignKey(
        FlashcardSet, on_delete=models.CASCADE, related_name="flashcards"
    )

    # Optional fields for enhanced functionality
    hint = models.TextField(blank=True, null=True)
    difficulty = models.CharField(
        max_length=20,
        choices=[
            ("easy", "Easy"),
            ("medium", "Medium"),
            ("hard", "Hard"),
        ],
        default="medium",
    )

    # Metadata
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "created_at"]
        indexes = [
            models.Index(fields=["flashcard_set", "order"]),
        ]

    def __str__(self):
        return f"{self.flashcard_set.title} - Card {self.order}"
