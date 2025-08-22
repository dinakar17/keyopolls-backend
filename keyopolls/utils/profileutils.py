import logging
from decimal import Decimal
from typing import Any, Dict

from django.apps import apps
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone

from keyopolls.common.schemas import ContentTypeEnum
from keyopolls.profile.models import PseudonymousProfile
from keyopolls.transactions.models import Transaction

logger = logging.getLogger(__name__)


def get_author_info(profile: PseudonymousProfile) -> Dict[str, Any]:
    """
    Helper function to get author information for pseudonymous profiles.
    Much simpler than the previous multi-profile-type version.

    Args:
        profile: PseudonymousProfile instance

    Returns:
        Dictionary containing author information according to AuthorSchema
    """
    if not profile:
        # Return default values for missing profile
        return {
            "id": 0,
            "username": "Unknown",
            "display_name": "Unknown User",
            "total_aura": 0,
        }

    return {
        "id": profile.id,
        "username": profile.username,
        "display_name": profile.display_name,
        "total_aura": profile.total_aura,
    }


def get_content_object(content_type: ContentTypeEnum, object_id: int):
    """Get the content object based on content type enum and ID"""
    # Map of content type enums to model classes
    content_type_map = {
        ContentTypeEnum.POLL: "Poll",
        ContentTypeEnum.COMMENT: "GenericComment",
    }

    model_name = content_type_map[content_type]

    try:
        # Get the model class
        model_class = None
        for app_config in apps.get_app_configs():
            try:
                model_class = apps.get_model(app_config.label, model_name)
                break
            except LookupError:
                continue

        if not model_class:
            raise ValueError(f"Model {model_name} not found")

        # Get the content object
        content_obj = model_class.objects.get(id=object_id)
        return content_obj

    except ObjectDoesNotExist:
        raise ObjectDoesNotExist(f"{model_name} with ID {object_id} not found")


def award_new_user_bonus_credits(profile: PseudonymousProfile) -> Dict[str, Any]:
    """
    Awards bonus credits to new users who are among the first 1100 users
    and haven't had any transactions yet.

    Args:
        profile: PseudonymousProfile instance

    Returns:
        dict: Contains information about whether bonus was awarded
        {
            'bonus_awarded': bool,
            'reason': str,
            'transaction': Transaction instance or None
        }
    """

    BONUS_AMOUNT = Decimal("4.00")
    ELIGIBLE_USER_LIMIT = 1100

    # Check if user is among the first 1100 users
    # Assuming the profile has an auto-incrementing primary key or created_at field
    # We'll use the profile ID to determine user order

    user_number = profile.id

    # Check if user is among first 1100
    if user_number > ELIGIBLE_USER_LIMIT:
        return {
            "bonus_awarded": False,
            "reason": (
                f"User #{user_number} is not among the first "
                f"{ELIGIBLE_USER_LIMIT} users"
            ),
            "transaction": None,
        }

    # Check if user already has any transactions
    existing_transactions = Transaction.objects.filter(user=profile).exists()
    if existing_transactions:
        return {
            "bonus_awarded": False,
            "reason": "User already has existing transactions",
            "transaction": None,
        }

    # Award bonus credits
    try:
        with transaction.atomic():
            # Create bonus transaction
            bonus_transaction = Transaction.objects.create(
                user=profile,
                transaction_type="bonus",
                amount=BONUS_AMOUNT,
                status="completed",
                description=(
                    f"Welcome bonus for new user #{user_number} "
                    f"(First {ELIGIBLE_USER_LIMIT} users)"
                ),
                completed_at=timezone.now(),
            )

            # Update user's total credits
            profile.total_credits += BONUS_AMOUNT
            profile.save(update_fields=["total_credits"])

            return {
                "bonus_awarded": True,
                "reason": f"Bonus awarded to user #{user_number}",
                "transaction": bonus_transaction,
            }

    except Exception:
        return {
            "message": "Failed to award bonus credits",
        }
