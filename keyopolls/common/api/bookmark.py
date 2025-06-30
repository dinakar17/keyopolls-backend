from django.apps import apps
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpRequest
from ninja import Router
from shared.schemas import Message

from keyopolls.common.models import Bookmark, BookmarkFolder
from keyopolls.common.schemas import (
    ContentTypeEnum,
    ToggleBookmarkResponseSchema,
    ToggleBookmarkSchema,
)
from keyopolls.profile.middleware import PseudonymousJWTAuth

router = Router(tags=["Bookmarks"])


def get_content_object(content_type: ContentTypeEnum, object_id: int):
    """Helper to get content object"""
    content_type_map = {
        ContentTypeEnum.POLL: "Poll",
        ContentTypeEnum.COMMENT: "GenericComment",
        # Add other content types as needed
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
    auth=PseudonymousJWTAuth(),
)
def toggle_bookmark(
    request: HttpRequest,
    content_type: ContentTypeEnum,
    object_id: int,
    data: ToggleBookmarkSchema,
):
    """
    Toggle bookmark status for content using pseudonymous profile.

    All bookmarks are created and managed through the user's pseudonymous profile.
    This provides consistent bookmark management and better organization.
    """
    # Get the authenticated pseudonymous profile
    profile = request.auth

    if not profile:
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
            # Check if folder belongs to the pseudonymous profile
            folder = BookmarkFolder.objects.get(
                id=data.folder_id,
                profile=profile,
            )
        except BookmarkFolder.DoesNotExist:
            return 400, {"message": "Folder not found or does not belong to you"}

    # Toggle bookmark using pseudonymous profile
    created, bookmark = Bookmark.toggle_bookmark(
        profile=profile,
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


@router.get(
    "/folders",
    response={200: list, 401: Message},
    auth=PseudonymousJWTAuth(),
)
def get_bookmark_folders(request: HttpRequest):
    """Get all bookmark folders for the authenticated user"""
    profile = request.auth

    if not profile:
        return 401, {"message": "Authentication required"}

    folders = BookmarkFolder.objects.filter(profile=profile).order_by("name")

    return [
        {
            "id": folder.id,
            "name": folder.name,
            "description": folder.description,
            "color": folder.color,
            "bookmark_count": folder.bookmark_count,
            "created_at": folder.created_at.isoformat(),
        }
        for folder in folders
    ]


@router.post(
    "/folders",
    response={200: dict, 400: Message, 401: Message},
    auth=PseudonymousJWTAuth(),
)
def create_bookmark_folder(request: HttpRequest, data: dict):
    """Create a new bookmark folder"""
    profile = request.auth

    if not profile:
        return 401, {"message": "Authentication required"}

    # Validate required fields
    name = data.get("name", "").strip()
    if not name:
        return 400, {"message": "Folder name is required"}

    if len(name) > 100:
        return 400, {"message": "Folder name must be 100 characters or less"}

    # Check for duplicate folder names
    if BookmarkFolder.objects.filter(profile=profile, name=name).exists():
        return 400, {"message": "A folder with this name already exists"}

    # Create the folder
    folder = BookmarkFolder.objects.create(
        profile=profile,
        name=name,
        description=data.get("description", "").strip(),
        color=data.get("color", "#3B82F6"),
    )

    return {
        "id": folder.id,
        "name": folder.name,
        "description": folder.description,
        "color": folder.color,
        "bookmark_count": 0,
        "created_at": folder.created_at.isoformat(),
        "message": "Folder created successfully",
    }


@router.get(
    "/bookmarks",
    response={200: list, 401: Message},
    auth=PseudonymousJWTAuth(),
)
def get_user_bookmarks(
    request: HttpRequest,
    folder_id: int = None,
    content_type: str = None,
    page: int = 1,
    page_size: int = 20,
):
    """Get user's bookmarks with optional filtering"""
    profile = request.auth

    if not profile:
        return 401, {"message": "Authentication required"}

    # Validate page_size
    if page_size > 100:
        page_size = 100

    # Get bookmarks queryset
    queryset = Bookmark.objects.filter(profile=profile)

    # Apply filters
    if folder_id:
        try:
            folder = BookmarkFolder.objects.get(id=folder_id, profile=profile)
            queryset = queryset.filter(folder=folder)
        except BookmarkFolder.DoesNotExist:
            return 400, {"message": "Folder not found"}

    if content_type:
        queryset = Bookmark.get_bookmarks_by_content_type(profile, content_type)
        if folder_id:
            queryset = queryset.filter(folder_id=folder_id)

    # Paginate
    from django.core.paginator import Paginator

    paginator = Paginator(queryset.order_by("-created_at"), page_size)
    bookmarks_page = paginator.get_page(page)

    # Format response
    bookmarks_data = []
    for bookmark in bookmarks_page:
        bookmark_data = {
            "id": bookmark.id,
            "content_type": bookmark.content_type.model,
            "object_id": bookmark.object_id,
            "notes": bookmark.notes,
            "created_at": bookmark.created_at.isoformat(),
            "content_summary": bookmark.content_summary,
            "folder": None,
        }

        if bookmark.folder:
            bookmark_data["folder"] = {
                "id": bookmark.folder.id,
                "name": bookmark.folder.name,
                "color": bookmark.folder.color,
            }

        bookmarks_data.append(bookmark_data)

    return {
        "bookmarks": bookmarks_data,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": paginator.count,
            "pages": paginator.num_pages,
            "has_next": bookmarks_page.has_next(),
            "has_previous": bookmarks_page.has_previous(),
        },
    }


@router.get(
    "/{content_type}/{object_id}/bookmark-status",
    response={200: dict, 404: Message, 401: Message},
    auth=PseudonymousJWTAuth(),
)
def get_bookmark_status(
    request: HttpRequest,
    content_type: ContentTypeEnum,
    object_id: int,
):
    """Check if content is bookmarked by the current user"""
    profile = request.auth

    if not profile:
        return 401, {"message": "Authentication required"}

    try:
        content_obj = get_content_object(content_type, object_id)
    except ObjectDoesNotExist as e:
        return 404, {"message": str(e)}

    is_bookmarked = Bookmark.is_bookmarked(profile, content_obj)

    bookmark_info = None
    if is_bookmarked:
        try:
            bookmark = Bookmark.objects.get(
                profile=profile,
                content_type__model=content_type.value,
                object_id=object_id,
            )
            bookmark_info = {
                "id": bookmark.id,
                "notes": bookmark.notes,
                "created_at": bookmark.created_at.isoformat(),
                "folder": None,
            }
            if bookmark.folder:
                bookmark_info["folder"] = {
                    "id": bookmark.folder.id,
                    "name": bookmark.folder.name,
                    "color": bookmark.folder.color,
                }
        except Bookmark.DoesNotExist:
            pass

    return {
        "bookmarked": is_bookmarked,
        "bookmark": bookmark_info,
    }


@router.delete(
    "/folders/{folder_id}",
    response={200: dict, 400: Message, 401: Message, 404: Message},
    auth=PseudonymousJWTAuth(),
)
def delete_bookmark_folder(request: HttpRequest, folder_id: int):
    """Delete a bookmark folder (bookmarks will be moved to no folder)"""
    profile = request.auth

    if not profile:
        return 401, {"message": "Authentication required"}

    try:
        folder = BookmarkFolder.objects.get(id=folder_id, profile=profile)
    except BookmarkFolder.DoesNotExist:
        return 404, {"message": "Folder not found"}

    # Count bookmarks that will be affected
    bookmark_count = folder.bookmarks.count()

    # Move bookmarks to no folder before deleting
    folder.bookmarks.update(folder=None)

    # Delete the folder
    folder.delete()

    return {
        "message": "Folder deleted successfully",
        "bookmarks_moved": bookmark_count,
    }
