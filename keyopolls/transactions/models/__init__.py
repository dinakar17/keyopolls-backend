import uuid

from django.db import models
from django.utils import timezone

from keyopolls.profile.models import PseudonymousProfile


class Transaction(models.Model):
    """
    Handles all credit transactions - both debits and credits
    """

    TRANSACTION_TYPES = [
        ("purchase", "Credit Purchase"),  # User buys credits
        ("message_sent", "Message Sent"),  # User sends message (debit)
        ("message_received", "Message Received"),  # Mentor receives payment (credit)
        ("refund", "Refund"),  # Credit refund
        ("bonus", "Bonus Credits"),  # Free/bonus credits
    ]

    TRANSACTION_STATUS = [
        ("pending", "Pending"),
        ("completed", "Completed"),
        ("failed", "Failed"),
        ("cancelled", "Cancelled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        PseudonymousProfile, on_delete=models.CASCADE, related_name="transactions"
    )

    # Transaction details
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)  # Credit amount
    status = models.CharField(
        max_length=15, choices=TRANSACTION_STATUS, default="completed"
    )

    # Optional: Link to timeline item for message transactions
    timeline_item = models.ForeignKey(
        "chats.TimelineItem",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="transactions",
    )

    # Payment/transaction details
    payment_method = models.CharField(
        max_length=50, blank=True, null=True
    )  # 'stripe', 'paypal', etc.
    payment_reference = models.CharField(
        max_length=100, blank=True, null=True
    )  # Payment gateway reference

    # Descriptions and notes
    description = models.TextField(blank=True, null=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        sign = "+" if self.is_credit() else "-"
        return (
            f"{self.user.username}: {sign}{self.amount} credits "
            f"({self.get_transaction_type_display()})"
        )

    def is_credit(self):
        """Check if this transaction adds credits to user's balance"""
        return self.transaction_type in [
            "purchase",
            "message_received",
            "refund",
            "bonus",
        ]

    def is_debit(self):
        """Check if this transaction removes credits from user's balance"""
        return self.transaction_type in ["message_sent"]

    def save(self, *args, **kwargs):
        if not self.completed_at and self.status == "completed":
            self.completed_at = timezone.now()
        super().save(*args, **kwargs)
