from datetime import datetime
from typing import List, Optional

from django.core.paginator import Paginator
from django.http import HttpRequest
from ninja import Query, Router, Schema

from keyopolls.common.models import Bookmark, BookmarkFolder, FolderAccess
from keyopolls.common.schemas import Message, PaginationSchema
from keyopolls.polls.models import PollTodo
from keyopolls.profile.middleware import PseudonymousJWTAuth

router = Router(tags=["Todos"])


class BookmarkedTodoItemSchema(Schema):
    """Schema for individual todo items in the list"""

    id: int
    text: str
    todo_completed: bool
    todo_due_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        schema_extra = {
            "example": {
                "id": 123,
                "text": "Research poll methodology for climate survey",
                "todo_completed": False,
                "todo_due_date": "2025-08-01T10:00:00Z",
                "created_at": "2025-07-27T10:30:00Z",
                "updated_at": "2025-07-27T10:30:00Z",
            }
        }


class TodoListDetailSchema(Schema):
    """Schema for todo list details"""

    id: int
    folder_id: str
    slug: str
    name: str
    description: str
    color: str
    access_level: str
    access_level_display: str
    price: Optional[str] = None
    is_owner: bool
    total_todos: int
    completed_todos: int
    completion_percentage: float
    created_at: datetime
    updated_at: datetime

    class Config:
        schema_extra = {
            "example": {
                "id": 123,
                "folder_id": "dQw4w9WgXcQ",
                "slug": "my-poll-research-todos",
                "name": "My Poll Research Todos",
                "description": "Important tasks for poll research project",
                "color": "#F59E0B",
                "access_level": "public",
                "access_level_display": "Public",
                "price": None,
                "is_owner": True,
                "total_todos": 10,
                "completed_todos": 3,
                "completion_percentage": 30.0,
                "created_at": "2025-07-20T10:30:00Z",
                "updated_at": "2025-07-27T10:30:00Z",
            }
        }


class TodoListQueryParams(Schema):
    """Query parameters for todo list"""

    page: Optional[int] = 1
    page_size: Optional[int] = 20
    completed: Optional[bool] = None  # Filter by completion status
    overdue: Optional[bool] = None  # Filter by overdue status
    search: Optional[str] = None  # Search in todo text
    ordering: Optional[str] = (
        "-created_at"  # created_at, -created_at, due_date, -due_date
    )

    class Config:
        schema_extra = {
            "example": {
                "page": 1,
                "page_size": 20,
                "completed": False,
                "overdue": True,
                "search": "research",
                "ordering": "todo_due_date",
            }
        }


class TodoListResponseSchema(Schema):
    """Response schema for todo list with todos"""

    folder: TodoListDetailSchema
    todos: List[BookmarkedTodoItemSchema]
    pagination: PaginationSchema

    class Config:
        schema_extra = {
            "example": {
                "folder": {
                    "id": 123,
                    "folder_id": "dQw4w9WgXcQ",
                    "slug": "my-poll-research-todos",
                    "name": "My Poll Research Todos",
                    "description": "Important tasks for poll research project",
                    "color": "#F59E0B",
                    "access_level": "public",
                    "access_level_display": "Public",
                    "price": None,
                    "is_owner": True,
                    "total_todos": 10,
                    "completed_todos": 3,
                    "completion_percentage": 30.0,
                    "created_at": "2025-07-20T10:30:00Z",
                    "updated_at": "2025-07-27T10:30:00Z",
                },
                "todos": [],
                "pagination": {
                    "current_page": 1,
                    "total_pages": 2,
                    "total_count": 25,
                    "has_next": True,
                    "has_previous": False,
                    "page_size": 20,
                    "next_page": 2,
                    "previous_page": None,
                },
            }
        }


class UpdateTodoSchema(Schema):
    """Schema for updating individual todo items"""

    todo_completed: Optional[bool] = None
    todo_due_date: Optional[datetime] = None

    class Config:
        schema_extra = {
            "example": {"todo_completed": True, "todo_due_date": "2025-08-15T14:30:00Z"}
        }


@router.get(
    "/todos/{slug}",
    response={
        200: TodoListResponseSchema,
        400: Message,
        401: Message,
        403: Message,
        404: Message,
    },
    auth=PseudonymousJWTAuth(),
)
def list_todos(
    request: HttpRequest, slug: str, query_params: TodoListQueryParams = Query(...)
):
    """
    Get todos from a specific todo folder by slug

    Features:
    - Pagination with customizable page size
    - Filter by completion status and overdue status
    - Search in todo text
    - Multiple ordering options
    - Access control for public/paid folders
    """
    profile = request.auth

    if not profile:
        return 401, {"message": "Authentication required"}

    try:
        # Get the todo folder
        folder = BookmarkFolder.objects.get(
            slug=slug, is_todo_folder=True, content_type="PollTodo"
        )
    except BookmarkFolder.DoesNotExist:
        return 404, {"message": "Todo list not found"}

    # Check access permissions
    if folder.profile != profile:
        # For non-owners, check if they have access
        if folder.access_level == BookmarkFolder.ACCESS_PRIVATE:
            return 403, {"message": "This todo list is private"}
        elif folder.access_level == BookmarkFolder.ACCESS_PAID:
            # Check if user has paid access
            if not FolderAccess.has_folder_access(profile, folder):
                return 403, {"message": "This todo list requires payment to access"}

    # Build queryset for todos in this folder
    from django.contrib.contenttypes.models import ContentType
    from django.utils import timezone

    polltodo_content_type = ContentType.objects.get(model="polltodo")

    queryset = (
        Bookmark.objects.filter(
            folder=folder, content_type=polltodo_content_type, is_todo=True
        )
        .select_related("content_type")
        .prefetch_related("content_object")
    )

    # Apply filters
    if query_params.completed is not None:
        queryset = queryset.filter(todo_completed=query_params.completed)

    if query_params.overdue is not None:
        now = timezone.now()
        if query_params.overdue:
            # Show overdue items (due date passed and not completed)
            queryset = queryset.filter(todo_due_date__lt=now, todo_completed=False)
        else:
            # Show non-overdue items
            queryset = queryset.exclude(todo_due_date__lt=now, todo_completed=False)

    # Apply search - search in PollTodo text field
    if query_params.search:
        search_term = query_params.search.strip()
        if search_term:
            matching_polltodos = PollTodo.objects.filter(
                text__icontains=search_term
            ).values_list("id", flat=True)

            queryset = queryset.filter(object_id__in=matching_polltodos)

    # Apply ordering
    valid_orderings = [
        "created_at",
        "-created_at",
        "updated_at",
        "-updated_at",
        "todo_due_date",
        "-todo_due_date",
        "todo_completed",
        "-todo_completed",
    ]

    ordering = query_params.ordering or "-created_at"
    if ordering not in valid_orderings:
        return 400, {
            "message": f"Invalid ordering. Valid options: {', '.join(valid_orderings)}"
        }

    queryset = queryset.order_by(ordering)

    # Pagination
    page_size = min(max(1, query_params.page_size or 20), 100)
    page_number = max(1, query_params.page or 1)

    paginator = Paginator(queryset, page_size)

    if page_number > paginator.num_pages and paginator.num_pages > 0:
        page_number = paginator.num_pages

    page_obj = paginator.get_page(page_number)

    # Build todo items data
    todos_data = []
    for bookmark in page_obj.object_list:
        # Get the PollTodo object
        polltodo = bookmark.content_object

        todos_data.append(
            {
                "id": bookmark.id,
                "text": polltodo.text if polltodo else "Deleted todo",
                "todo_completed": bookmark.todo_completed,
                "todo_due_date": bookmark.todo_due_date,
                "created_at": bookmark.created_at,
                "updated_at": bookmark.updated_at,
            }
        )

    # Calculate completion stats
    total_todos = folder.bookmarks.filter(is_todo=True).count()
    completed_todos = folder.bookmarks.filter(is_todo=True, todo_completed=True).count()
    completion_percentage = (
        (completed_todos / total_todos * 100) if total_todos > 0 else 0
    )

    # Build folder details
    folder_data = {
        "id": folder.id,
        "folder_id": folder.folder_id,
        "slug": folder.slug,
        "name": folder.name,
        "description": folder.description,
        "color": folder.color,
        "access_level": folder.access_level,
        "access_level_display": folder.get_access_level_display(),
        "price": str(folder.price) if folder.price else None,
        "is_owner": folder.profile == profile,
        "total_todos": total_todos,
        "completed_todos": completed_todos,
        "completion_percentage": round(completion_percentage, 1),
        "created_at": folder.created_at,
        "updated_at": folder.updated_at,
    }

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

    return {"folder": folder_data, "todos": todos_data, "pagination": pagination_data}


@router.patch(
    "/todos/{slug}/items/{todo_id}",
    response={
        200: BookmarkedTodoItemSchema,
        400: Message,
        401: Message,
        403: Message,
        404: Message,
    },
    auth=PseudonymousJWTAuth(),
)
def update_todo_item(
    request: HttpRequest, slug: str, todo_id: int, data: UpdateTodoSchema
):
    """
    Update a specific todo item's completion status and due date
    Only the folder owner can update todos
    """
    profile = request.auth

    if not profile:
        return 401, {"message": "Authentication required"}

    try:
        # Get the todo folder
        folder = BookmarkFolder.objects.get(
            slug=slug, is_todo_folder=True, content_type="PollTodo"
        )
    except BookmarkFolder.DoesNotExist:
        return 404, {"message": "Todo list not found"}

    # Only folder owner can update todos
    if folder.profile != profile:
        return 403, {"message": "Only the todo list owner can update items"}

    try:
        # Get the specific todo item
        todo = Bookmark.objects.get(id=todo_id, folder=folder, is_todo=True)
    except Bookmark.DoesNotExist:
        return 404, {"message": "Todo item not found"}

    # Update the allowed fields
    updated_fields = []

    if data.todo_completed is not None:
        todo.todo_completed = data.todo_completed
        updated_fields.append("todo_completed")

    if data.todo_due_date is not None:
        todo.todo_due_date = data.todo_due_date
        updated_fields.append("todo_due_date")

    if updated_fields:
        updated_fields.append("updated_at")
        todo.save(update_fields=updated_fields)

    # Get the PollTodo object for the text
    polltodo = todo.content_object

    # Return updated todo item
    return {
        "id": todo.id,
        "text": polltodo.text if polltodo else "Deleted todo",
        "todo_completed": todo.todo_completed,
        "todo_due_date": todo.todo_due_date,
        "created_at": todo.created_at,
        "updated_at": todo.updated_at,
    }
