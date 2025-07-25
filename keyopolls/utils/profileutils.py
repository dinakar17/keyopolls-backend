import logging
from typing import Any, Dict

from django.apps import apps
from django.core.exceptions import ObjectDoesNotExist

from keyopolls.common.schemas import ContentTypeEnum
from keyopolls.profile.models import PseudonymousProfile

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
