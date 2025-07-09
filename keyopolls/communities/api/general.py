import logging
from typing import Optional

from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.db import models
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Query, Router, Schema

from keyopolls.common.models import TaggedItem
from keyopolls.common.schemas import Message
from keyopolls.communities.models import Community, CommunityMembership
from keyopolls.communities.schemas import CommunityDetails, CommunityListResponse
from keyopolls.profile.middleware import OptionalPseudonymousJWTAuth

logger = logging.getLogger(__name__)


router = Router(tags=["Communities General"])


# Query parameters for list endpoint
class CommunityListQuery(Schema):
    # Pagination
    page: int = 1
    page_size: int = 20

    # Filtering
    search: Optional[str] = None
    category_id: Optional[int] = None
    community_type: Optional[str] = None  # public, private, restricted
    tag: Optional[str] = None
    creator_id: Optional[int] = None

    # User-specific filters (requires auth)
    my_communities: bool = False  # Show only communities user is member of
    my_role: Optional[str] = (
        None  # Filter by user's role: member, moderator, admin, creator
    )
    my_status: Optional[str] = (
        None  # Filter by user's status: active, pending, banned, left
    )

    # Sorting
    sort_by: str = (
        "created_at"  # created_at, updated_at, member_count, poll_count, name
    )
    order: str = "desc"  # asc, desc

    # Admin options
    include_inactive: bool = False


# Response schemas


@router.get(
    "/communities/{community_slug}",
    auth=OptionalPseudonymousJWTAuth,
    response={
        200: CommunityDetails,
        404: Message,
    },
)
def get_community(request: HttpRequest, community_slug: str):
    """
    Get a single community by ID.
    Handles all visibility rules and user-specific data.
    """
    user_profile = getattr(request, "auth", None)

    try:
        # Get community with optimized queries
        community = get_object_or_404(
            Community.objects.select_related("creator", "category"), slug=community_slug
        )

        # Visibility checks

        # 1. Inactive communities - only creator/admin can view
        if not community.is_active:
            if not user_profile or not _user_can_view_inactive_community(
                user_profile, community
            ):
                return 404, {"message": "Community not found"}

        # 2. Private communities - only members can view
        elif community.community_type == "private":
            if not user_profile:
                return 404, {"message": "Community not found"}

            try:
                membership: CommunityMembership = community.memberships.get(
                    profile=user_profile
                )
                if not membership.is_active_member:
                    return 404, {"message": "Community not found"}
            except CommunityMembership.DoesNotExist:
                return 404, {"message": "Community not found"}

        # 3. Public and restricted communities are viewable by all
        return 200, CommunityDetails.resolve(community, user_profile)

    except Exception as e:
        logger.error(
            f"Error getting community {community_slug}: {str(e)}", exc_info=True
        )
        return 404, {"message": "Community not found"}


@router.get(
    "/communities",
    auth=OptionalPseudonymousJWTAuth,
    response={
        200: CommunityListResponse,
        400: Message,
    },
)
def list_communities(request: HttpRequest, filters: CommunityListQuery = Query()):
    """
    List communities with comprehensive filtering, searching, and pagination.
    Handles all possible use cases in a single endpoint.
    """
    user_profile = getattr(request, "auth", None)

    try:
        # Validate parameters
        if filters.page < 1:
            return 400, {"message": "Page must be >= 1"}

        if filters.page_size < 1 or filters.page_size > 100:
            return 400, {"message": "Page size must be between 1 and 100"}

        valid_sort_fields = [
            "created_at",
            "updated_at",
            "member_count",
            "poll_count",
            "name",
        ]
        if filters.sort_by not in valid_sort_fields:
            return 400, {
                "message": (
                    (
                        f"Invalid sort field. Must be one of: "
                        f"{', '.join(valid_sort_fields)}"
                    )
                )
            }

        if filters.order not in ["asc", "desc"]:
            return 400, {"message": "Order must be 'asc' or 'desc'"}

        # Validate user-specific filters
        if filters.my_communities or filters.my_role or filters.my_status:
            if not user_profile:
                return 400, {
                    "message": "Authentication required for user-specific filters"
                }

        valid_roles = ["member", "moderator", "admin", "creator"]
        if filters.my_role and filters.my_role not in valid_roles:
            return 400, {
                "message": f"Invalid role. Must be one of: {', '.join(valid_roles)}"
            }

        valid_statuses = ["active", "pending", "banned", "left"]
        if filters.my_status and filters.my_status not in valid_statuses:
            return 400, {
                "message": (
                    f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
                )
            }

        # Build base queryset
        queryset = Community.objects.select_related("creator", "category")

        # Track applied filters for response
        applied_filters = {}

        # === CORE FILTERING ===

        # 1. Active status filter
        if not filters.include_inactive:
            queryset = queryset.filter(is_active=True)
            applied_filters["active_only"] = True

        # 2. Handle my_communities filter first (affects base queryset)
        if filters.my_communities and user_profile:
            membership_filters = {"profile": user_profile}

            if filters.my_role:
                membership_filters["role"] = filters.my_role
                applied_filters["my_role"] = filters.my_role

            if filters.my_status:
                membership_filters["status"] = filters.my_status
                applied_filters["my_status"] = filters.my_status
            else:
                membership_filters["status"] = "active"  # Default to active

            user_community_ids = CommunityMembership.objects.filter(
                **membership_filters
            ).values_list("community_id", flat=True)

            queryset = queryset.filter(id__in=user_community_ids)
            applied_filters["my_communities"] = True

        # 3. Privacy filtering (if not showing user's communities)
        elif not filters.my_communities:
            if not user_profile:
                # Non-authenticated users see only public communities
                queryset = queryset.filter(community_type="public")
                applied_filters["public_only"] = True
            else:
                # Authenticated users see public + restricted
                # + their private communities
                if filters.community_type:
                    queryset = queryset.filter(community_type=filters.community_type)
                    applied_filters["community_type"] = filters.community_type
                else:
                    user_private_community_ids = CommunityMembership.objects.filter(
                        profile=user_profile,
                        status="active",
                        community__community_type="private",
                    ).values_list("community_id", flat=True)

                    queryset = queryset.filter(
                        models.Q(community_type__in=["public", "restricted"])
                        | models.Q(id__in=user_private_community_ids)
                    )

        # 4. Additional filters
        if filters.category_id:
            queryset = queryset.filter(category_id=filters.category_id)
            applied_filters["category_id"] = filters.category_id

        if filters.community_type and not filters.my_communities:
            if filters.community_type not in ["public", "private", "restricted"]:
                return 400, {"message": "Invalid community type"}
            queryset = queryset.filter(community_type=filters.community_type)
            applied_filters["community_type"] = filters.community_type

        if filters.creator_id:
            queryset = queryset.filter(creator_id=filters.creator_id)
            applied_filters["creator_id"] = filters.creator_id

        # 5. Tag filter
        if filters.tag:
            community_content_type = ContentType.objects.get_for_model(Community)
            tagged_community_ids = TaggedItem.objects.filter(
                content_type=community_content_type, tag__name__icontains=filters.tag
            ).values_list("object_id", flat=True)
            queryset = queryset.filter(id__in=tagged_community_ids)
            applied_filters["tag"] = filters.tag

        # 6. Search functionality
        if filters.search:
            search_term = filters.search.strip()
            queryset = queryset.filter(
                models.Q(name__icontains=search_term)
                | models.Q(description__icontains=search_term)
            )
            applied_filters["search"] = search_term

        # === SORTING ===
        sort_field = filters.sort_by
        if filters.order == "desc":
            sort_field = f"-{sort_field}"
        queryset = queryset.order_by(sort_field)
        applied_filters["sort_by"] = filters.sort_by
        applied_filters["order"] = filters.order

        # === PAGINATION ===
        paginator = Paginator(queryset, filters.page_size)
        page_obj = paginator.get_page(filters.page)

        # === RESOLVE COMMUNITIES ===
        communities = [
            CommunityDetails.resolve_minimal(community, user_profile)
            for community in page_obj.object_list
        ]

        # === PAGINATION INFO ===
        pagination = {
            "current_page": page_obj.number,
            "total_pages": paginator.num_pages,
            "total_items": paginator.count,
            "page_size": filters.page_size,
            "has_next": page_obj.has_next(),
            "has_previous": page_obj.has_previous(),
        }

        return 200, CommunityListResponse(
            communities=communities,
            pagination=pagination,
            filters_applied=applied_filters,
        )

    except Exception as e:
        logger.error(f"Error listing communities: {str(e)}", exc_info=True)
        return 400, {"message": "An error occurred while fetching communities"}


def _user_can_view_inactive_community(user_profile, community):
    """Check if user can view inactive communities (creator/admin only)"""
    try:
        membership = community.memberships.get(profile=user_profile)
        return membership.role in ["creator", "admin"] and membership.is_active_member
    except CommunityMembership.DoesNotExist:
        return False
