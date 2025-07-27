from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest
from django.utils import timezone
from ninja import Query, Router

from keyopolls.common.models import Bookmark, BookmarkFolder
from keyopolls.common.schemas import (
    BookmarkFolderCreateSchema,
    BookmarkFolderDetailsSchema,
    BookmarkFolderQueryParams,
    BookmarkFoldersListResponseSchema,
    ContentTypeEnum,
    Message,
    TodoBookmarkStatusListResponseSchema,
    TodoBookmarkStatusSchema,
    ToggleBookmarkResponseSchema,
    ToggleBookmarkSchema,
    UpdateBookmarkFolderSchema,
)
from keyopolls.communities.models import Community
from keyopolls.profile.middleware import PseudonymousJWTAuth

router = Router(tags=["Bookmarks"])


def get_content_object(content_type: ContentTypeEnum, object_id: int):
    """Helper to get content object"""
    content_type_map = {
        ContentTypeEnum.POLL: "Poll",
        ContentTypeEnum.COMMENT: "GenericComment",
        ContentTypeEnum.POLL_TODO: "PollTodo",
        ContentTypeEnum.ARTICLE: "Article",
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
        403: Message,  # Added for paid folder restrictions
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

    Note: Paid bookmark folders can only contain Poll objects created by
    the folder author.
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

    # Get folder if specified, otherwise use/create default folder
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

        # Check if it's a paid folder and enforce author-only Poll content rule
        if folder.is_paid:
            # Paid folders can only contain Poll objects
            if content_type != ContentTypeEnum.POLL:
                return 403, {"message": "Paid folders can only contain Poll bookmarks"}

            # Check if the Poll was created by the folder author
            if not hasattr(content_obj, "profile"):
                return 400, {
                    "message": "Cannot determine poll author for paid folder validation"
                }

            # For paid folders, only allow bookmarking Polls created by the folder owner
            if content_obj.profile != profile:
                return 403, {
                    "message": (
                        "Paid folders can only contain bookmarks of Polls "
                        "created by the folder author"
                    )
                }

        # Validate folder content type consistency
        existing_bookmarks = folder.bookmarks.exclude(
            content_type=ContentType.objects.get_for_model(content_obj)
        )
        if existing_bookmarks.exists():
            existing_type = existing_bookmarks.first().content_type.model
            return 400, {
                "message": (
                    f"This folder already contains {existing_type} bookmarks. "
                    "Each folder can only contain one content type."
                )
            }

        # Validate todo type consistency
        if data.is_todo != folder.is_todo_folder:
            folder_type = "todo" if folder.is_todo_folder else "regular"
            bookmark_type = "todo" if data.is_todo else "regular"
            return 400, {
                "message": (
                    f"Cannot add {bookmark_type} bookmark to {folder_type} folder"
                )
            }

    else:
        # No folder specified - use or create appropriate default folder
        if data.is_todo:
            # Create/get default todo folder for this content type
            folder_name = f"Default {content_type.value} Todos"
            folder, created = BookmarkFolder.objects.get_or_create(
                profile=profile,
                name=folder_name,
                defaults={
                    "description": (
                        f"Default folder for {content_type.value} todo items"
                    ),
                    "color": "#F59E0B",  # Orange for todos
                    "access_level": BookmarkFolder.ACCESS_PRIVATE,
                    "is_todo_folder": True,
                    "content_type": content_type.value,
                },
            )
        else:
            # Create/get default regular folder for this content type
            folder_name = f"Default {content_type.value}"
            folder, created = BookmarkFolder.objects.get_or_create(
                profile=profile,
                name=folder_name,
                defaults={
                    "description": f"Default folder for {content_type.value} bookmarks",
                    "color": "#3B82F6",  # Blue for regular bookmarks
                    "access_level": BookmarkFolder.ACCESS_PRIVATE,
                    "is_todo_folder": False,
                    "content_type": content_type.value,
                },
            )

    # Toggle bookmark using pseudonymous profile
    created, bookmark = Bookmark.toggle_bookmark(
        profile=profile,
        content_obj=content_obj,
        folder=folder,
        notes=data.notes or "",
        is_todo=data.is_todo,
        todo_due_date=data.todo_due_date if data.todo_due_date else None,
    )

    # Update bookmark_count on content object if it has this field
    if hasattr(content_obj, "bookmark_count") and data.is_todo is False:
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


@router.post(
    "/folders",
    response={200: BookmarkFolderDetailsSchema, 400: Message, 401: Message},
    auth=PseudonymousJWTAuth(),
)
def create_bookmark_folder(request: HttpRequest, data: BookmarkFolderCreateSchema):
    """Create a new bookmark folder"""
    profile = request.auth

    if not profile:
        return 401, {"message": "Authentication required"}

    # Validate required fields
    name = data.name.strip() if data.name else ""
    if not name:
        return 400, {"message": "Folder name is required"}

    if len(name) > 100:
        return 400, {"message": "Folder name must be 100 characters or less"}

    # Check for duplicate folder names
    if BookmarkFolder.objects.filter(profile=profile, name=name).exists():
        return 400, {"message": "A folder with this name already exists"}

    # Validate access level
    access_level = (
        data.access_level
        if hasattr(data, "access_level")
        else BookmarkFolder.ACCESS_PRIVATE
    )
    if access_level not in [choice[0] for choice in BookmarkFolder.ACCESS_CHOICES]:
        return 400, {"message": "Invalid access level"}

    # Validate price for paid folders
    price = data.price if hasattr(data, "price") else None
    if access_level == BookmarkFolder.ACCESS_PAID:
        if not price:
            return 400, {"message": "Price is required for paid folders"}
        try:
            price = float(price)
            if price <= 0:
                return 400, {"message": "Price must be greater than 0"}
        except (ValueError, TypeError):
            return 400, {"message": "Invalid price format"}
    else:
        # Clear price for non-paid folders
        price = None

    # Validate color format (basic hex validation)
    color = data.color if hasattr(data, "color") and data.color else "#3B82F6"
    if not color.startswith("#") or len(color) != 7:
        return 400, {"message": "Color must be a valid hex code (e.g., #3B82F6)"}

    # Validate content type if provided
    content_type = data.content_type if hasattr(data, "content_type") else None
    if content_type:
        valid_content_types = [ct.value for ct in ContentTypeEnum]
        if content_type not in valid_content_types:
            return 400, {
                "message": (
                    "Invalid content type. Valid options: "
                    f"{', '.join(valid_content_types)}"
                )
            }

    try:
        # Create the folder
        folder = BookmarkFolder.objects.create(
            profile=profile,
            name=name,
            description=(
                data.description.strip()
                if hasattr(data, "description") and data.description
                else ""
            ),
            color=color,
            access_level=access_level,
            price=price,
            is_todo_folder=(
                data.is_todo_folder if hasattr(data, "is_todo_folder") else False
            ),
            content_type=content_type,
        )

        return BookmarkFolderDetailsSchema.resolve_details(folder)

    except ValueError as e:
        # Handle validation errors from the model's save method
        return 400, {"message": str(e)}
    except Exception:
        # Handle any unexpected errors
        return 400, {"message": "Failed to create folder"}


@router.get(
    "/folders",
    response={200: BookmarkFoldersListResponseSchema, 400: Message, 401: Message},
    auth=PseudonymousJWTAuth(),
)
def get_bookmark_folders(
    request: HttpRequest, query_params: BookmarkFolderQueryParams = Query(...)
):
    """
    Get bookmark folders for the authenticated user with filtering and pagination

    Features:
    - Pagination with customizable page size
    - Filter by access level, content type, todo status, community
    - Search in name and description
    - Multiple ordering options
    - Includes user's own folders + saved public folders + paid subscriptions
    """
    profile = request.auth

    if not profile:
        return 401, {"message": "Authentication required"}

    # Base query: User's own folders OR folders they have access to
    base_query = Q(profile=profile) | Q(
        folder_accesses__profile=profile, folder_accesses__is_active=True
    )

    # Exclude expired subscriptions
    base_query &= ~Q(
        folder_accesses__access_type="subscribed",
        folder_accesses__expires_at__lt=timezone.now(),
    )

    queryset = BookmarkFolder.objects.filter(base_query).distinct()

    # Apply filters
    if query_params.access_level:
        if query_params.access_level not in [
            choice[0] for choice in BookmarkFolder.ACCESS_CHOICES
        ]:
            return 400, {"message": "Invalid access level"}
        queryset = queryset.filter(access_level=query_params.access_level)

    if query_params.content_type:
        valid_content_types = [ct.value for ct in ContentTypeEnum]
        if query_params.content_type not in valid_content_types:
            return 400, {
                "message": (
                    f"Invalid content type. Valid options: "
                    f"{', '.join(valid_content_types)}"
                )
            }
        queryset = queryset.filter(content_type=query_params.content_type)

    if query_params.is_todo_folder is not None:
        queryset = queryset.filter(is_todo_folder=query_params.is_todo_folder)

    # Filter by community
    if query_params.community_id is not None:
        try:
            Community.objects.get(id=query_params.community_id)
            # Add any community access validation here if needed
            queryset = queryset.filter(community_id=query_params.community_id)
        except Community.DoesNotExist:
            return 400, {"message": "Community not found"}

    # Apply search
    if query_params.search:
        search_term = query_params.search.strip()
        if search_term:
            queryset = queryset.filter(
                Q(name__icontains=search_term) | Q(description__icontains=search_term)
            )

    # Apply ordering
    valid_orderings = [
        "name",
        "-name",
        "created_at",
        "-created_at",
        "updated_at",
        "-updated_at",
        "bookmark_count",
        "-bookmark_count",
        "access_level",
        "-access_level",
    ]

    ordering = query_params.ordering or "name"
    if ordering not in valid_orderings:
        return 400, {
            "message": f"Invalid ordering. Valid options: {', '.join(valid_orderings)}"
        }

    # Special handling for bookmark_count ordering (requires annotation)
    if "bookmark_count" in ordering:
        from django.db.models import Count

        queryset = queryset.annotate(bookmark_count_actual=Count("bookmarks")).order_by(
            ordering.replace("bookmark_count", "bookmark_count_actual")
        )
    else:
        queryset = queryset.order_by(ordering)

    # Pagination
    page_size = min(max(1, query_params.page_size or 20), 100)  # Limit between 1-100
    page_number = max(1, query_params.page or 1)

    paginator = Paginator(queryset, page_size)

    # Handle invalid page numbers
    if page_number > paginator.num_pages and paginator.num_pages > 0:
        page_number = paginator.num_pages

    page_obj = paginator.get_page(page_number)

    # Resolve folder details using custom method
    folders_data = [
        BookmarkFolderDetailsSchema.resolve_details(folder)
        for folder in page_obj.object_list
    ]

    # Build pagination info
    pagination_data = {
        "current_page": page_obj.number,
        "total_pages": paginator.num_pages,
        "total_count": paginator.count,
        "has_next": page_obj.has_next(),
        "has_previous": page_obj.has_previous(),
        "page_size": page_size,
        "next_page": page_obj.next_page_number() if page_obj.has_next() else None,
        "previous_page": (
            page_obj.previous_page_number() if page_obj.has_previous() else None
        ),
    }

    return {"folders": folders_data, "pagination": pagination_data}


@router.put(
    "/folders/{folder_id}",
    response={
        200: BookmarkFolderDetailsSchema,
        400: Message,
        401: Message,
        403: Message,
        404: Message,
    },
    auth=PseudonymousJWTAuth(),
)
def update_bookmark_folder(
    request: HttpRequest, folder_id: int, data: UpdateBookmarkFolderSchema
):
    """
    Update an existing bookmark folder

    Note: Paid folders cannot change their access level or content type
    """
    profile = request.auth

    if not profile:
        return 401, {"message": "Authentication required"}

    try:
        # Get the folder
        folder = BookmarkFolder.objects.get(id=folder_id, profile=profile)
    except BookmarkFolder.DoesNotExist:
        return 404, {"message": "Folder not found or does not belong to you"}

    # Validate that paid folders cannot change access level
    if (
        folder.is_paid
        and data.access_level
        and data.access_level != folder.access_level
    ):
        return 403, {"message": "Cannot change access level of paid folders"}

    # Validate that paid folders cannot change content type
    if (
        folder.is_paid
        and data.content_type
        and data.content_type != folder.content_type
    ):
        return 403, {"message": "Cannot change content type of paid folders"}

    # Validate name if provided
    if data.name is not None:
        name = data.name.strip()
        if not name:
            return 400, {"message": "Folder name cannot be empty"}

        if len(name) > 100:
            return 400, {"message": "Folder name must be 100 characters or less"}

        # Check for duplicate names (excluding current folder)
        if (
            BookmarkFolder.objects.filter(profile=profile, name=name)
            .exclude(id=folder_id)
            .exists()
        ):
            return 400, {"message": "A folder with this name already exists"}

    # Validate access level if provided
    if data.access_level is not None:
        if data.access_level not in [
            choice[0] for choice in BookmarkFolder.ACCESS_CHOICES
        ]:
            return 400, {"message": "Invalid access level"}

    # Validate content type if provided
    if data.content_type is not None:
        valid_content_types = [ct.value for ct in ContentTypeEnum]
        if data.content_type not in valid_content_types:
            return 400, {
                "message": (
                    f"Invalid content type. Valid options: "
                    f"{', '.join(valid_content_types)}"
                )
            }

    # Validate price for paid folders
    if data.access_level == BookmarkFolder.ACCESS_PAID:
        if data.price is None or data.price <= 0:
            return 400, {
                "message": (
                    "Price is required and must be greater than 0 for paid folders"
                )
            }
    elif data.access_level in [
        BookmarkFolder.ACCESS_PRIVATE,
        BookmarkFolder.ACCESS_PUBLIC,
    ]:
        # Clear price for non-paid folders
        data.price = None

    # Validate color format if provided
    if data.color is not None:
        if not data.color.startswith("#") or len(data.color) != 7:
            return 400, {"message": "Color must be a valid hex code (e.g., #3B82F6)"}

    try:
        # Update fields that are provided
        update_fields = []

        if data.name is not None:
            folder.name = data.name.strip()
            update_fields.append("name")

        if data.description is not None:
            folder.description = data.description.strip()
            update_fields.append("description")

        if data.color is not None:
            folder.color = data.color
            update_fields.append("color")

        if data.access_level is not None:
            folder.access_level = data.access_level
            update_fields.append("access_level")

        if data.price is not None:
            folder.price = data.price
            update_fields.append("price")
        elif data.access_level in [
            BookmarkFolder.ACCESS_PRIVATE,
            BookmarkFolder.ACCESS_PUBLIC,
        ]:
            folder.price = None
            update_fields.append("price")

        if data.is_todo_folder is not None:
            folder.is_todo_folder = data.is_todo_folder
            update_fields.append("is_todo_folder")

        if data.content_type is not None:
            folder.content_type = data.content_type
            update_fields.append("content_type")

        # Add updated_at to update fields
        update_fields.append("updated_at")

        # Save with specific fields
        folder.save(update_fields=update_fields)

        return BookmarkFolderDetailsSchema.resolve_details(folder)
    except ValueError as e:
        return 400, {"message": str(e)}
    except Exception:
        return 400, {"message": "Failed to update folder"}


@router.post(
    "/todos/bookmark-status",
    response={200: TodoBookmarkStatusListResponseSchema, 400: Message, 401: Message},
    auth=PseudonymousJWTAuth(),
)
def check_todos_bookmark_status(request: HttpRequest, data: TodoBookmarkStatusSchema):
    """
    Check bookmark status for multiple todos

    Returns which todos are bookmarked and in which folders
    """
    profile = request.auth

    if not profile:
        return 401, {"message": "Authentication required"}

    if not data.todo_ids:
        return 400, {"message": "At least one todo_id is required"}

    if len(data.todo_ids) > 50:
        return 400, {"message": "Maximum 50 todo_ids allowed per request"}

    try:
        # Get all bookmarks for the user that contain PollTodo objects
        from django.contrib.contenttypes.models import ContentType

        polltodo_content_type = ContentType.objects.get(model="polltodo")

        # Find all bookmarked todos for this user
        bookmarked_todos = Bookmark.objects.filter(
            profile=profile,
            content_type=polltodo_content_type,
            object_id__in=data.todo_ids,
        ).select_related("folder")

        # Create a mapping of todo_id -> bookmark info
        bookmark_map = {}
        for bookmark in bookmarked_todos:
            bookmark_map[bookmark.object_id] = {
                "folder_id": bookmark.folder.id if bookmark.folder else None,
                "folder_name": bookmark.folder.name if bookmark.folder else None,
            }

        # Build response for all requested todos
        statuses = []
        for todo_id in data.todo_ids:
            if todo_id in bookmark_map:
                bookmark_info = bookmark_map[todo_id]
                statuses.append(
                    {
                        "todo_id": todo_id,
                        "is_bookmarked": True,
                        "folder_id": bookmark_info["folder_id"],
                        "folder_name": bookmark_info["folder_name"],
                    }
                )
            else:
                statuses.append(
                    {
                        "todo_id": todo_id,
                        "is_bookmarked": False,
                        "folder_id": None,
                        "folder_name": None,
                    }
                )

        return {"statuses": statuses}

    except ContentType.DoesNotExist:
        return 400, {"message": "PollTodo content type not found"}
    except Exception:
        return 400, {"message": "Failed to check bookmark status"}
