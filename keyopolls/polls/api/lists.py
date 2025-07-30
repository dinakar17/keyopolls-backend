from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.paginator import Paginator
from django.db.models import Max, Prefetch, Q
from django.http import HttpRequest
from ninja import File, Query, Router, UploadedFile

from keyopolls.common.schemas import Message
from keyopolls.communities.models import Community
from keyopolls.polls.models import Poll, PollList

# You'll need to create these schemas in your schemas file
from keyopolls.polls.schemas import (
    ManagePollInListResponseSchema,
    ManagePollInListSchema,
    PollListCreateSchema,
    PollListDetailsSchema,
    PollListQueryParams,
    PollListsListResponseSchema,
    PollListUpdateSchema,
)
from keyopolls.profile.middleware import PseudonymousJWTAuth

router = Router(tags=["Poll Lists"])


@router.post(
    "/lists",
    response={200: PollListDetailsSchema, 400: Message, 401: Message},
    auth=PseudonymousJWTAuth(),
)
def create_poll_list(
    request: HttpRequest, data: PollListCreateSchema, image: UploadedFile = File(None)
):
    """Create a new poll list or folder"""
    profile = request.auth

    if not profile:
        return 401, {"message": "Authentication required"}

    # Validate required fields
    title = data.title.strip() if data.title else ""
    if not title:
        return 400, {"message": "List title is required"}

    if len(title) > 200:
        return 400, {"message": "List title must be 200 characters or less"}

    # if image size is greater than 10 MB, return error
    if image and image.size > 10 * 1024 * 1024:
        return 400, {"message": "Image size must be 10 MB or less"}

    # Get community
    try:
        community = Community.objects.get(slug=data.community_slug)
    except ObjectDoesNotExist:
        return 400, {"message": "Community not found"}

    # Check if user is a member of the community
    try:
        membership = community.memberships.get(profile=profile)
        if not membership:
            return 400, {"message": "You must be an active member of this community"}
    except ObjectDoesNotExist:
        return 400, {"message": "You are not a member of this community"}

    # Get parent if specified
    parent = None
    if data.parent_id:
        try:
            parent = PollList.objects.get(
                id=data.parent_id, community=community, is_deleted=False
            )
            # Check if user can add to this parent
            if parent.profile != profile and not parent.is_collaborative:
                return 400, {
                    "message": "You don't have permission to add to this folder"
                }
        except PollList.DoesNotExist:
            return 400, {"message": "Parent folder not found"}

    # Validate list type
    list_type = data.list_type if hasattr(data, "list_type") else "list"
    if list_type not in ["folder", "list"]:
        return 400, {"message": "Invalid list type. Must be 'folder' or 'list'"}

    # Validate visibility
    visibility = data.visibility if hasattr(data, "visibility") else "public"
    if visibility not in ["public", "unlisted", "private"]:
        return 400, {
            "message": (
                "Invalid visibility. Must be 'public', 'unlisted', or 'private'"
            )
        }

    try:
        # Calculate the next order value for this parent
        # Find the maximum order value for items with the same parent
        max_order_result = PollList.objects.filter(
            parent=parent, community=community, is_deleted=False
        ).aggregate(max_order=Max("order"))

        max_order = max_order_result["max_order"] or 0
        next_order = max_order + 1

        # Create the poll list
        poll_list = PollList.objects.create(
            title=title,
            image=image if image else None,
            description=(
                data.description.strip()
                if hasattr(data, "description") and data.description
                else ""
            ),
            list_type=list_type,
            visibility=visibility,
            profile=profile,
            community=community,
            parent=parent,
            order=next_order,  # Set the calculated order
            is_collaborative=(
                data.is_collaborative if hasattr(data, "is_collaborative") else False
            ),
            max_polls=(
                data.max_polls
                if hasattr(data, "max_polls") and data.max_polls
                else None
            ),
        )

        return PollListDetailsSchema.resolve_details(poll_list)

    except ValidationError as e:
        return 400, {"message": str(e)}
    except Exception as e:
        return 400, {"message": f"Failed to create list: {str(e)}"}


@router.post(
    "/lists/{list_id}/polls",
    response={
        200: ManagePollInListResponseSchema,
        400: Message,
        401: Message,
        403: Message,
        404: Message,
    },
    auth=PseudonymousJWTAuth(),
)
def manage_poll_in_list(
    request: HttpRequest, list_id: int, data: ManagePollInListSchema
):
    """Add, remove, or toggle a poll in a poll list"""
    profile = request.auth

    if not profile:
        return 401, {"message": "Authentication required"}

    # Get the poll list
    try:
        poll_list = PollList.objects.get(id=list_id, is_deleted=False)
    except PollList.DoesNotExist:
        return 404, {"message": "Poll list not found"}

    # Check permissions
    if not poll_list.can_add_polls(profile):
        return 403, {"message": "You don't have permission to modify this list"}

    # Folders cannot contain polls directly
    if poll_list.list_type == "folder":
        return 400, {
            "message": "Cannot add polls to folders. Add polls to lists instead."
        }

    # Get the poll
    try:
        poll = Poll.objects.get(id=data.poll_id, is_deleted=False)
    except Poll.DoesNotExist:
        return 404, {"message": "Poll not found"}

    # Validate same community
    if poll.community != poll_list.community:
        return 400, {"message": "Poll and list must be in the same community"}

    # Check if poll is currently in the list
    poll_in_list = poll.poll_list_id == poll_list.id

    # Handle the action
    if data.action == "add":
        if poll_in_list:
            return 400, {"message": "Poll is already in this list"}

        # Check if poll is already in another list
        if poll.poll_list_id is not None:
            return 400, {"message": "Poll is already in another list"}

        # Check max polls limit
        if poll_list.max_polls:
            # Count polls in this list using direct query
            current_count = Poll.objects.filter(
                poll_list=poll_list, is_deleted=False
            ).count()
            if current_count >= poll_list.max_polls:
                return 400, {
                    "message": (
                        f"List has reached maximum capacity of "
                        f"{poll_list.max_polls} polls"
                    )
                }

        try:
            # Add poll to the list
            poll.poll_list = poll_list
            poll.save(update_fields=["poll_list"])

            # Update list counts
            poll_list.update_counts()

            return {
                "success": True,
                "action": "added",
                "message": "Poll added to list successfully",
                "list_item_id": poll.id,  # Using poll id for consistency
                "poll_id": poll.id,
                "list_id": poll_list.id,
                # Order functionality would need to be implemented separately
                "order": None,
                "in_list": True,
            }

        except ValidationError as e:
            return 400, {"message": str(e)}
        except Exception as e:
            return 400, {"message": f"Failed to add poll to list: {str(e)}"}

    elif data.action == "remove":
        if not poll_in_list:
            return 400, {"message": "Poll is not in this list"}

        try:
            # Remove poll from the list
            poll.poll_list = None
            poll.save(update_fields=["poll_list"])

            # Update list counts
            poll_list.update_counts()

            return {
                "success": True,
                "action": "removed",
                "message": "Poll removed from list successfully",
                "list_item_id": None,
                "poll_id": poll.id,
                "list_id": poll_list.id,
                "order": None,
                "in_list": False,
            }

        except Exception as e:
            return 400, {"message": f"Failed to remove poll from list: {str(e)}"}

    elif data.action == "toggle":
        # Toggle behavior: add if not in list, remove if in list
        if poll_in_list:
            # Remove from list
            try:
                poll.poll_list = None
                poll.save(update_fields=["poll_list"])

                poll_list.update_counts()

                return {
                    "success": True,
                    "action": "removed",
                    "message": "Poll removed from list",
                    "list_item_id": None,
                    "poll_id": poll.id,
                    "list_id": poll_list.id,
                    "order": None,
                    "in_list": False,
                }
            except Exception as e:
                return 400, {"message": f"Failed to remove poll from list: {str(e)}"}
        else:
            # Add to list
            # Check if poll is already in another list
            if poll.poll_list_id is not None:
                return 400, {"message": "Poll is already in another list"}

            # Check max polls limit
            if poll_list.max_polls:
                # Count polls in this list using direct query
                current_count = Poll.objects.filter(
                    poll_list=poll_list, is_deleted=False
                ).count()
                if current_count >= poll_list.max_polls:
                    return 400, {
                        "message": (
                            f"List has reached maximum capacity of "
                            f"{poll_list.max_polls} polls"
                        )
                    }

            try:
                poll.poll_list = poll_list
                poll.save(update_fields=["poll_list"])

                poll_list.update_counts()

                return {
                    "success": True,
                    "action": "added",
                    "message": "Poll added to list",
                    "list_item_id": poll.id,
                    "poll_id": poll.id,
                    "list_id": poll_list.id,
                    "order": None,
                    "in_list": True,
                }
            except ValidationError as e:
                return 400, {"message": str(e)}
            except Exception as e:
                return 400, {"message": f"Failed to add poll to list: {str(e)}"}

    else:
        return 400, {"message": "Invalid action. Must be 'add', 'remove', or 'toggle'"}


@router.post(
    "/lists/update-poll/{list_id}",
    response={
        200: PollListDetailsSchema,
        400: Message,
        401: Message,
        403: Message,
        404: Message,
    },
    auth=PseudonymousJWTAuth(),
)
def update_poll_list(
    request: HttpRequest,
    list_id: int,
    data: PollListUpdateSchema,
    image: UploadedFile = File(None),
):
    """Update a poll list or folder"""
    profile = request.auth

    if not profile:
        return 401, {"message": "Authentication required"}

    # Get the poll list
    try:
        poll_list = PollList.objects.get(id=list_id, is_deleted=False)
    except PollList.DoesNotExist:
        return 404, {"message": "Poll list not found"}

    # Check permissions - only owner or admin collaborators can update
    is_owner = poll_list.profile == profile
    is_admin_collaborator = False

    if not is_owner:
        try:
            collaborator = poll_list.collaborators.get(profile=profile)
            is_admin_collaborator = collaborator.can_edit_list()
        except Exception:
            pass

    if not (is_owner or is_admin_collaborator):
        return 403, {"message": "You don't have permission to update this list"}

    # Update fields if provided
    updated_fields = []

    if hasattr(data, "title") and data.title is not None:
        title = data.title.strip()
        if not title:
            return 400, {"message": "List title cannot be empty"}
        if len(title) > 200:
            return 400, {"message": "List title must be 200 characters or less"}
        poll_list.title = title
        updated_fields.append("title")

    if image:
        # Validate image size
        if image.size > 10 * 1024 * 1024:
            return 400, {"message": "Image size must be 10 MB or less"}
        poll_list.image = image
        updated_fields.append("image")

    if hasattr(data, "description") and data.description is not None:
        poll_list.description = data.description.strip()
        updated_fields.append("description")

    if hasattr(data, "visibility") and data.visibility is not None:
        if data.visibility not in ["public", "unlisted", "private"]:
            return 400, {
                "message": (
                    "Invalid visibility. Must be 'public', 'unlisted', or 'private'"
                )
            }
        poll_list.visibility = data.visibility
        updated_fields.append("visibility")

    if hasattr(data, "is_collaborative") and data.is_collaborative is not None:
        poll_list.is_collaborative = data.is_collaborative
        updated_fields.append("is_collaborative")

    if hasattr(data, "max_polls") and data.max_polls is not None:
        # Validate max_polls doesn't conflict with current poll count
        if data.max_polls > 0:
            current_count = poll_list.poll_items.filter(is_deleted=False).count()
            if current_count > data.max_polls:
                return 400, {
                    "message": (
                        f"Cannot set max polls to {data.max_polls}. "
                        f"List currently has {current_count} polls."
                    )
                }
        poll_list.max_polls = data.max_polls if data.max_polls > 0 else None
        updated_fields.append("max_polls")

    if hasattr(data, "is_featured") and data.is_featured is not None:
        # Only owners can change featured status
        if not is_owner:
            return 403, {"message": "Only the owner can change featured status"}
        poll_list.is_featured = data.is_featured
        updated_fields.append("is_featured")

    # Handle parent change (moving to different folder)
    if hasattr(data, "parent_id") and data.parent_id is not None:
        if data.parent_id == 0:
            # Move to root level
            poll_list.parent = None
            updated_fields.extend(["parent", "path", "depth"])
        else:
            try:
                new_parent = PollList.objects.get(
                    id=data.parent_id,
                    community=poll_list.community,
                    list_type="folder",  # Can only move into folders
                    is_deleted=False,
                )
                # Prevent circular references
                if new_parent.path.startswith(f"{poll_list.path}{poll_list.id}/"):
                    return 400, {"message": "Cannot move list into its own descendant"}

                poll_list.parent = new_parent
                updated_fields.extend(["parent", "path", "depth"])
            except PollList.DoesNotExist:
                return 400, {"message": "Parent folder not found"}

    # Handle order change within parent
    if hasattr(data, "order") and data.order is not None:
        poll_list.order = data.order
        updated_fields.append("order")

    try:
        if updated_fields:
            poll_list.save(update_fields=updated_fields + ["updated_at"])

        return PollListDetailsSchema.resolve_details(poll_list)

    except ValidationError as e:
        return 400, {"message": str(e)}
    except Exception as e:
        return 400, {"message": f"Failed to update list: {str(e)}"}


@router.get(
    "/lists",
    response={200: PollListsListResponseSchema, 400: Message, 401: Message},
    auth=PseudonymousJWTAuth(),
)
def get_poll_lists(
    request: HttpRequest, query_params: PollListQueryParams = Query(...)
):
    """
    Get poll lists for the authenticated user with filtering and pagination

    Features:
    - Pagination with customizable page size
    - Filter by list type, visibility, community, parent folder
    - Search in title and description
    - Multiple ordering options
    - Includes user's own lists + collaborative lists they have access to
    - Hierarchical filtering (show only root level or specific parent)
    """
    profile = request.auth

    if not profile:
        return 401, {"message": "Authentication required"}

    # Base query: User's own lists OR lists they can collaborate on
    base_query = Q(profile=profile) | Q(
        collaborators__profile=profile,
        collaborators__permission_level__in=["view", "add", "edit", "admin"],
    )

    # Include public and unlisted lists from communities user is part of
    user_communities = Community.objects.filter(
        memberships__profile=profile, memberships__status="active"
    ).values_list("id", flat=True)

    public_lists_query = Q(
        community_id__in=user_communities,
        visibility__in=["public", "unlisted"],
        is_deleted=False,
    )

    # Combine queries
    base_query = base_query | public_lists_query

    queryset = PollList.objects.filter(base_query, is_deleted=False).distinct()

    # Apply filters
    if query_params.list_type:
        if query_params.list_type not in ["folder", "list"]:
            return 400, {"message": "Invalid list type. Must be 'folder' or 'list'"}
        queryset = queryset.filter(list_type=query_params.list_type)

    if query_params.visibility:
        if query_params.visibility not in ["public", "unlisted", "private"]:
            return 400, {
                "message": (
                    "Invalid visibility. Must be 'public', 'unlisted', or 'private'"
                )
            }
        queryset = queryset.filter(visibility=query_params.visibility)

    # Filter by community
    if query_params.community_id is not None:
        try:
            Community.objects.get(id=query_params.community_id)
            queryset = queryset.filter(community_id=query_params.community_id)
        except Community.DoesNotExist:
            return 400, {"message": "Community not found"}

    if query_params.community_slug:
        try:
            community = Community.objects.get(slug=query_params.community_slug)
            queryset = queryset.filter(community=community)
        except Community.DoesNotExist:
            return 400, {"message": "Community not found"}

    # Filter by parent (hierarchical filtering)
    if hasattr(query_params, "parent_id") and query_params.parent_id is not None:
        if query_params.parent_id == 0:
            # Show only root level items
            queryset = queryset.filter(parent=None)
        else:
            # Show items under specific parent
            try:
                parent = PollList.objects.get(
                    id=query_params.parent_id, is_deleted=False
                )
                queryset = queryset.filter(parent=parent)
            except PollList.DoesNotExist:
                return 400, {"message": "Parent folder not found"}

    # Filter by owner
    if hasattr(query_params, "owner_only") and query_params.owner_only:
        queryset = queryset.filter(profile=profile)

    # Filter by collaborative status
    if (
        hasattr(query_params, "is_collaborative")
        and query_params.is_collaborative is not None
    ):
        queryset = queryset.filter(is_collaborative=query_params.is_collaborative)

    # Filter by featured status
    if hasattr(query_params, "is_featured") and query_params.is_featured is not None:
        queryset = queryset.filter(is_featured=query_params.is_featured)

    # Filter by depth (for hierarchical views)
    if hasattr(query_params, "max_depth") and query_params.max_depth is not None:
        if query_params.max_depth >= 0:
            queryset = queryset.filter(depth__lte=query_params.max_depth)

    # Apply search
    if query_params.search:
        search_term = query_params.search.strip()
        if search_term:
            queryset = queryset.filter(
                Q(title__icontains=search_term) | Q(description__icontains=search_term)
            )

    # Apply ordering
    valid_orderings = [
        "title",
        "-title",
        "created_at",
        "-created_at",
        "updated_at",
        "-updated_at",
        "order",
        "-order",
        "total_polls_count",
        "-total_polls_count",
        "direct_polls_count",
        "-direct_polls_count",
        "view_count",
        "-view_count",
        "like_count",
        "-like_count",
        "depth",
        "-depth",
    ]

    ordering = query_params.ordering or "-created_at"
    if ordering not in valid_orderings:
        return 400, {
            "message": f"Invalid ordering. Valid options: {', '.join(valid_orderings)}"
        }

    # Special handling for hierarchical ordering
    if hasattr(query_params, "hierarchical_order") and query_params.hierarchical_order:
        # Order by depth first, then by order within each level
        queryset = queryset.order_by("depth", "order", "created_at")
    else:
        queryset = queryset.order_by(ordering)

    # Optimize queries with prefetch_related for better performance
    # Since polls are linked directly to lists via poll_list FK,
    # we prefetch the reverse relation
    queryset = queryset.select_related(
        "profile", "community", "parent"
    ).prefetch_related(
        Prefetch(
            "poll_list",  # This is the reverse relation from Poll to PollList
            queryset=Poll.objects.filter(is_deleted=False).select_related("profile"),
        ),
        "collaborators__profile",
        "children",
    )

    # Pagination
    page_size = min(max(1, query_params.page_size or 20), 100)  # Limit between 1-100
    page_number = max(1, query_params.page or 1)

    paginator = Paginator(queryset, page_size)

    # Handle invalid page numbers
    if page_number > paginator.num_pages and paginator.num_pages > 0:
        page_number = paginator.num_pages

    page_obj = paginator.get_page(page_number)

    # Resolve list details using custom method
    lists_data = [
        PollListDetailsSchema.resolve_details(poll_list, profile)
        for poll_list in page_obj.object_list
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

    # Add hierarchy information if showing hierarchical view
    hierarchy_info = {}
    if hasattr(query_params, "parent_id") and query_params.parent_id is not None:
        if query_params.parent_id > 0:
            try:
                parent = PollList.objects.get(id=query_params.parent_id)
                hierarchy_info = {
                    "parent": {
                        "id": parent.id,
                        "title": parent.title,
                        "depth": parent.depth,
                    },
                    "breadcrumbs": [
                        {
                            "id": ancestor.id,
                            "title": ancestor.title,
                            "depth": ancestor.depth,
                        }
                        for ancestor in parent.get_breadcrumbs()
                    ],
                }
            except PollList.DoesNotExist:
                pass

    response_data = {"lists": lists_data, "pagination": pagination_data}

    if hierarchy_info:
        response_data["hierarchy"] = hierarchy_info

    return response_data
