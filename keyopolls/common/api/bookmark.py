from django.apps import apps
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpRequest
from keyoconnect.common.models import Bookmark, BookmarkFolder
from keyoconnect.common.schemas import (
    ContentTypeEnum,
    ToggleBookmarkResponseSchema,
    ToggleBookmarkSchema,
)
from keyoconnect.profiles.middleware import PublicJWTAuth
from ninja import Router
from shared.schemas import Message

router = Router(tags=["Bookmarks"])


def get_content_object(content_type: ContentTypeEnum, object_id: int):
    """Helper to get content object"""
    content_type_map = {
        ContentTypeEnum.POST: "Post",
    }

    model_name = content_type_map[content_type]

    try:
        for app_config in apps.get_app_configs():
            try:
                model_class = apps.get_model(app_config.label, model_name)
                return model_class.objects.get(id=object_id, is_deleted=False)
            except LookupError:
                continue
        raise ValueError(f"Model {model_name} not found")
    except ObjectDoesNotExist:
        raise ObjectDoesNotExist(f"{model_name} with ID {object_id} not found")


@router.post(
    "/{content_type}/{object_id}/bookmark",
    response={
        200: ToggleBookmarkResponseSchema,
        400: Message,
        404: Message,
        401: Message,
    },
    auth=PublicJWTAuth(),
)
def toggle_bookmark(
    request: HttpRequest,
    content_type: ContentTypeEnum,
    object_id: int,
    data: ToggleBookmarkSchema,
):
    """
    Toggle bookmark status for content using public profile only.

    All bookmarks are created and managed through the user's public profile.
    This provides consistent bookmark management and better organization.
    """
    # Get the authenticated public profile
    public_profile = request.auth

    if not public_profile:
        return 401, {"message": "Authentication required"}

    try:
        content_obj = get_content_object(content_type, object_id)
    except ObjectDoesNotExist as e:
        return 404, {"message": str(e)}
    except ValueError as e:
        return 400, {"message": str(e)}

    # Get folder if specified
    folder = None
    if data.folder_id:
        try:
            # Check if folder belongs to the public profile
            folder = BookmarkFolder.objects.get(
                id=data.folder_id,
                profile_type="public",  # Only public profile folders
                profile_id=public_profile.id,
            )
        except BookmarkFolder.DoesNotExist:
            return 400, {"message": "Folder not found or does not belong to you"}

    # Toggle bookmark using public profile
    created, bookmark = Bookmark.toggle_bookmark(
        profile_obj=public_profile,
        content_obj=content_obj,
        folder=folder,
        notes=data.notes or "",
    )

    # Update bookmark_count on content object if it has this field
    if hasattr(content_obj, "bookmark_count"):
        from django.db.models import F

        if created:
            # Bookmark was created - increment count
            content_obj.__class__.objects.filter(id=content_obj.id).update(
                bookmark_count=F("bookmark_count") + 1
            )
        else:
            # Bookmark was removed - decrement count (but don't go below 0)
            content_obj.__class__.objects.filter(id=content_obj.id).update(
                bookmark_count=F("bookmark_count") - 1
            )
            # Ensure count doesn't go below 0
            content_obj.__class__.objects.filter(
                id=content_obj.id, bookmark_count__lt=0
            ).update(bookmark_count=0)

    return {
        "bookmarked": created,
        "message": "Bookmarked" if created else "Bookmark removed",
        "bookmark_id": bookmark.id if bookmark else None,
    }
