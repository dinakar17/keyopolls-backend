from typing import List, Optional

from django.core.paginator import Paginator
from django.db.models import Q
from ninja import Query, Router, Schema

from keyopolls.common.schemas import Message
from keyopolls.profile.middleware import OptionalPseudonymousJWTAuth

router = Router(tags=["Tags"])


# Schemas
class TagItemSchema(Schema):
    id: int
    name: str
    slug: str
    description: Optional[str] = None
    created_at: str
    usage_count: int = 0

    @classmethod
    def resolve(cls, tag):
        return cls(
            id=tag.id,
            name=tag.name,
            slug=tag.slug,
            description=tag.description,
            created_at=tag.created_at.isoformat(),
            usage_count=tag.usage_count,
        )


class TagsListFiltersSchema(Schema):
    search: Optional[str] = None
    page: int = 1
    per_page: int = 20
    order_by: str = "-created_at"


class TagsListResponseSchema(Schema):
    tags: List[TagItemSchema]
    total_count: int
    page: int
    per_page: int
    total_pages: int
    has_next: bool
    has_previous: bool


@router.get(
    "/tags",
    response={200: TagsListResponseSchema, 400: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def get_tags_list(request, filters: TagsListFiltersSchema = Query(...)):
    """
    Get a paginated list of tags with optional search functionality.

    Features:
    - Search by tag name or description
    - Pagination with configurable page size
    - Multiple sorting options
    - Returns usage count for each tag

    Query Parameters:
    - search: Search term for tag name or description
    - page: Page number (default: 1)
    - per_page: Items per page (default: 20, max: 100)
    - order_by: Sort field (created_at, name, usage_count with - for desc)
    """

    # Import Tag model (adjust the import path based on your project structure)
    from keyopolls.common.models import Tag  # Adjust this import path as needed

    # Validate per_page limit
    if filters.per_page > 100:
        filters.per_page = 100
    if filters.per_page < 1:
        filters.per_page = 20

    # Validate page
    if filters.page < 1:
        filters.page = 1

    # Validate order_by options
    valid_order_fields = [
        "created_at",
        "-created_at",
        "name",
        "-name",
        "usage_count",
        "-usage_count",
    ]
    if filters.order_by not in valid_order_fields:
        filters.order_by = "-created_at"

    # Start with base queryset
    queryset = Tag.objects.all()

    # Apply search
    if filters.search:
        search_term = filters.search.strip()
        if search_term:
            queryset = queryset.filter(
                Q(name__icontains=search_term) | Q(description__icontains=search_term)
            )

    # Handle ordering
    queryset = queryset.order_by(filters.order_by)

    # Get total count before pagination
    total_count = queryset.count()

    # Apply pagination
    paginator = Paginator(queryset, filters.per_page)

    if filters.page > paginator.num_pages and paginator.num_pages > 0:
        filters.page = paginator.num_pages

    try:
        page_obj = paginator.page(filters.page)
    except Exception:
        return 400, {"message": "Invalid page number"}

    # Build response
    tags_data = []
    for tag in page_obj.object_list:
        tag_data = TagItemSchema.resolve(tag)
        tags_data.append(tag_data)

    return {
        "tags": tags_data,
        "total_count": total_count,
        "page": filters.page,
        "per_page": filters.per_page,
        "total_pages": paginator.num_pages,
        "has_next": page_obj.has_next(),
        "has_previous": page_obj.has_previous(),
    }
