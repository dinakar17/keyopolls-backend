import logging
from typing import Any, Dict

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.utils.text import slugify
from ninja import UploadedFile
from PIL import Image

from keyopolls.common.models import Link, Media, Tag, TaggedItem
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
        ContentTypeEnum.POLL: "Post",
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


def validate_media_file(media_file: UploadedFile):
    """Validate media file type and size"""
    # Basic file type validation
    allowed_extensions = {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".mp4",
        ".mov",
        ".webm",
        ".webp",
        ".avi",
    }

    file_extension = (
        media_file.name.lower().split(".")[-1] if "." in media_file.name else ""
    )

    if f".{file_extension}" not in allowed_extensions:
        return False, "Unsupported file type"

    # File size validation (10MB limit)
    max_size = 10 * 1024 * 1024  # 10MB
    if media_file.size > max_size:
        return False, "File size too large. Maximum 10MB allowed"

    return True, None


def get_media_type(file_extension):
    """Determine media type based on file extension"""
    if file_extension in ["jpg", "jpeg", "png", "webp"]:
        return "image"
    elif file_extension == "gif":
        return "gif"
    elif file_extension in ["mp4", "mov", "webm", "avi"]:
        return "video"
    else:
        return "image"  # default fallback


def create_media_object(content_obj, media_file: UploadedFile, order=0):
    """Create a Media object for the content object"""
    file_extension = (
        media_file.name.lower().split(".")[-1] if "." in media_file.name else ""
    )

    media_type = get_media_type(file_extension)

    media = Media(
        content_object=content_obj,
        media_type=media_type,
        file=media_file,
        order=order,
        size_bytes=media_file.size,
    )

    # Extract dimensions for images
    if media_type in ["image", "gif"]:
        try:
            img = Image.open(media_file)
            media.width, media.height = img.size
        except Exception:
            # Set default dimensions if extraction fails
            media.width = 0
            media.height = 0

    # For videos, set placeholder info
    elif media_type == "video":
        media.width = 1280  # Placeholder
        media.height = 720  # Placeholder
        media.duration = 0.0
        media.is_processed = False

    media.save()
    return media


def create_link_object(content_obj, link_data):
    """Create a Link object for the content object"""
    # Validate URL format (basic validation)
    url = link_data.url if hasattr(link_data, "url") else link_data
    if not url.startswith(("http://", "https://")):
        raise ValidationError("Invalid URL format. Must start with http:// or https://")

    Link.objects.create(
        content_object=content_obj,
        url=url,
        display_text=getattr(link_data, "display_text", "") or url,
    )


def delete_media_files(media: UploadedFile):
    """Delete physical media files from storage"""
    try:
        if media.file and hasattr(media.file, "delete"):
            media.file.delete(save=False)
    except Exception as e:
        logger.warning(f"Failed to delete media file {media.id}: {str(e)}")


def delete_existing_media_and_links(content_obj):
    """Delete existing media files and links for a content object"""
    # Handle existing media files - delete them first
    existing_media = Media.objects.filter(
        content_type=ContentType.objects.get_for_model(content_obj),
        object_id=content_obj.id,
    )

    # Delete physical files from storage
    for media in existing_media:
        delete_media_files(media)

    # Delete media records from database
    existing_media.delete()

    # Handle existing links - delete them
    existing_links = Link.objects.filter(
        content_type=ContentType.objects.get_for_model(content_obj),
        object_id=content_obj.id,
    )
    existing_links.delete()


# Todo: Fix this (I don't think we have get_profile method on content objects)
def check_ownership(content_obj, profile, profile_type):
    """Check if the user owns the content object"""
    content_profile = content_obj.get_profile()
    if (
        not content_profile
        or content_obj.profile_type != profile_type
        or content_profile.id != profile.id
    ):
        return False
    return True


def validate_profile_permissions(
    profile_type, allowed_types, action="perform this action"
):
    """Validate that the profile type is allowed for the action"""
    if profile_type not in allowed_types:
        allowed_str = ", ".join(allowed_types)
        return False, f"Only {allowed_str} profiles can {action}"
    return True, None


def handle_tags(instance, tag_names, max_tags=5):
    """
    Generic function to handle adding tags to any model instance using TaggedItem.

    Args:
        instance: The model instance to tag (e.g., Post, Article, etc.)
        tag_names: List of tag names to add
        max_tags: Maximum number of tags to process (default: 5)
    """
    if not tag_names:
        return

    # Get the content type for the instance
    content_type = ContentType.objects.get_for_model(instance)

    for tag_name in tag_names[:max_tags]:
        if tag_name:
            tag_name = tag_name.strip()
            tag_slug = slugify(tag_name)

            # Get or create tag
            tag, created = Tag.objects.get_or_create(
                slug=tag_slug, defaults={"name": tag_name}
            )

            # Create TaggedItem if it doesn't exist
            TaggedItem.objects.get_or_create(
                tag=tag, content_type=content_type, object_id=instance.id
            )


def remove_tags(instance, tag_names=None):
    """
    Remove tags from a model instance.

    Args:
        instance: The model instance to remove tags from
        tag_names: List of tag names to remove. If None, removes all tags.
    """
    content_type = ContentType.objects.get_for_model(instance)

    queryset = TaggedItem.objects.filter(
        content_type=content_type, object_id=instance.id
    )

    if tag_names:
        # Remove specific tags
        tag_slugs = [slugify(name.strip()) for name in tag_names if name]
        queryset = queryset.filter(tag__slug__in=tag_slugs)

    # Delete the TaggedItems (this will trigger the counter decrement)
    queryset.delete()


def update_original_post_counters(original_post, is_repost, increment=True):
    """Update counters on original post for reposts/quotes"""
    if not original_post:
        return

    multiplier = 1 if increment else -1

    if is_repost:
        original_post.repost_count = max(0, original_post.repost_count + multiplier)
    else:
        original_post.quote_count = max(0, original_post.quote_count + multiplier)

    original_post.save()


# Helper Functions
def get_media_info(media_obj: Media) -> Dict[str, Any]:
    """
    Helper function to convert Media object to dictionary representation

    Args:
        media_obj: Media model instance

    Returns:
        Dictionary containing media information according to MediaSchema
    """
    if not media_obj:
        return {}

    try:
        return {
            "id": media_obj.id,
            "media_type": media_obj.media_type,
            "file_url": media_obj.file.url if media_obj.file else None,
            "thumbnail_url": media_obj.thumbnail.url if media_obj.thumbnail else None,
            "width": media_obj.width,
            "height": media_obj.height,
            "alt_text": media_obj.alt_text,
            "duration": media_obj.duration,
            "order": media_obj.order,
            "created_at": (
                media_obj.created_at.isoformat() if media_obj.created_at else None
            ),
        }
    except Exception:
        # Log error if logging is available
        # logger.error(f"Error converting media object {media_obj.id}: {str(e)}")
        return {}


def get_link_info(link_obj: Link) -> Dict[str, Any]:
    """
    Helper function to convert Link object to dictionary representation

    Args:
        link_obj: Link model instance

    Returns:
        Dictionary containing link information according to LinkSchema
    """
    if not link_obj:
        return {}

    try:
        return {
            "id": link_obj.id,
            "url": link_obj.url,
            "display_text": link_obj.display_text,
            "domain": link_obj.domain,
            "title": link_obj.title,
            "description": link_obj.description,
            "image_url": link_obj.image_url,
            "is_active": link_obj.is_active,
            "click_count": link_obj.click_count,
            "created_at": (
                link_obj.created_at.isoformat() if link_obj.created_at else None
            ),
        }
    except Exception:
        # Log error if logging is available
        # logger.error(f"Error converting link object {link_obj.id}: {str(e)}")
        return {}
