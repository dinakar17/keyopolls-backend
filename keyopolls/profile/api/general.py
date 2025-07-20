from django.core.paginator import Paginator
from django.db.models import F, Q
from ninja import File, Query, Router, UploadedFile

from keyopolls.common.schemas import Message
from keyopolls.communities.models import Community, CommunityMembership
from keyopolls.profile.middleware import (
    OptionalPseudonymousJWTAuth,
    PseudonymousJWTAuth,
)
from keyopolls.profile.models import PseudonymousProfile
from keyopolls.profile.schemas import (
    ProfileDetailsSchema,
    ProfileUpdateSchema,
    UserListItemSchema,
    UsersListFiltersSchema,
    UsersListResponseSchema,
)

router = Router(tags=["Profile General"])


# Get Profile Information
@router.get(
    "/profile/${name}",
    response={200: ProfileDetailsSchema, 404: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def get_profile_info(request, name: str):
    """
    Get the profile information of the authenticated user.
    If no user is authenticated, returns an empty profile.
    """

    profile = PseudonymousProfile.objects.filter(username=name).first()

    # If no user is authenticated, return an empty profile
    return ProfileDetailsSchema.resolve(
        profile,
        profile_id=(
            request.auth.id if isinstance(request.auth, PseudonymousProfile) else None
        ),
    )


@router.post(
    "/profile",
    response={200: ProfileDetailsSchema, 404: Message},
    auth=PseudonymousJWTAuth(),
)
def edit_profile_info(
    request,
    data: ProfileUpdateSchema,
    avatar: UploadedFile = File(None),
    banner: UploadedFile = File(None),
):
    """
    Edit the profile information of the authenticated user.
    """
    profile: PseudonymousProfile = request.auth

    if not profile:
        return 404, {"message": "Profile not found"}

    # Update profile fields
    profile.display_name = data.display_name
    profile.about = data.about
    if avatar:
        profile.avatar = avatar
    if banner:
        profile.banner = banner

    profile.save()

    return ProfileDetailsSchema.resolve(profile, request.auth.id)


@router.get(
    "/users",
    response={200: UsersListResponseSchema, 400: Message, 404: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def get_users_list(request, filters: UsersListFiltersSchema = Query(...)):
    """
    Get a paginated list of users with optional filtering and searching.

    Features:
    - Search by username, display_name, or email
    - Filter by community membership and role
    - Pagination with configurable page size
    - Multiple sorting options
    - Returns community-specific data when filtering by community

    Query Parameters:
    - search: Search term for username, display_name, or email
    - community_id: Filter users by community membership
    - role: Filter by role (only works with community_id)
    - page: Page number (default: 1)
    - per_page: Items per page (default: 20, max: 100)
    - order_by: Sort field (created_at, username, total_aura with - for desc)
    """

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
        "username",
        "-username",
        "total_aura",
        "-total_aura",
        "display_name",
        "-display_name",
    ]
    if filters.order_by not in valid_order_fields:
        filters.order_by = "-created_at"

    # Start with base queryset
    if filters.community_id:
        # If filtering by community, check if community exists
        try:
            Community.objects.get(id=filters.community_id, is_active=True)
        except Community.DoesNotExist:
            return 404, {"message": "Community not found"}

        # Get users through community membership
        membership_queryset = CommunityMembership.objects.filter(
            community_id=filters.community_id, status="active"
        ).select_related("profile")

        # Filter by role if specified
        if filters.role:
            # Validate role
            valid_roles = dict(CommunityMembership.ROLE_CHOICES).keys()
            if filters.role not in valid_roles:
                return 400, {
                    "message": f"Invalid role. Valid roles: {', '.join(valid_roles)}"
                }
            membership_queryset = membership_queryset.filter(role=filters.role)

        # Apply search to profile fields
        if filters.search:
            search_term = filters.search.strip()
            if search_term:
                membership_queryset = membership_queryset.filter(
                    Q(profile__username__icontains=search_term)
                    | Q(profile__display_name__icontains=search_term)
                    | Q(profile__email__icontains=search_term)
                )

        # Handle ordering when filtering by community
        if filters.order_by in ["total_aura", "-total_aura"]:
            # For total_aura, we need to calculate it
            membership_queryset = membership_queryset.annotate(
                calculated_total_aura=(
                    F("profile__aura_polls") + F("profile__aura_comments")
                )
            ).order_by(
                ("-" if filters.order_by.startswith("-") else "")
                + "calculated_total_aura"
            )
        elif filters.order_by in ["username", "-username"]:
            order_field = "profile__username"
            if filters.order_by.startswith("-"):
                order_field = f"-{order_field}"
            membership_queryset = membership_queryset.order_by(order_field)
        elif filters.order_by in ["display_name", "-display_name"]:
            order_field = "profile__display_name"
            if filters.order_by.startswith("-"):
                order_field = f"-{order_field}"
            membership_queryset = membership_queryset.order_by(order_field)
        elif filters.order_by in ["created_at", "-created_at"]:
            order_field = "profile__created_at"
            if filters.order_by.startswith("-"):
                order_field = f"-{order_field}"
            membership_queryset = membership_queryset.order_by(order_field)
        else:
            # Default ordering by joined_at for community members
            membership_queryset = membership_queryset.order_by("-joined_at")

        # Get total count before pagination
        total_count = membership_queryset.count()

        # Apply pagination
        paginator = Paginator(membership_queryset, filters.per_page)

        if filters.page > paginator.num_pages and paginator.num_pages > 0:
            filters.page = paginator.num_pages

        try:
            page_obj = paginator.page(filters.page)
        except Exception:
            return 400, {"message": "Invalid page number"}

        # Build response with membership data
        users_data = []
        for membership in page_obj.object_list:
            user_data = UserListItemSchema.resolve(membership.profile, membership)
            users_data.append(user_data)

    else:
        # General user search without community filtering
        queryset = PseudonymousProfile.objects.all()

        # Apply search
        if filters.search:
            search_term = filters.search.strip()
            if search_term:
                queryset = queryset.filter(
                    Q(username__icontains=search_term)
                    | Q(display_name__icontains=search_term)
                    | Q(email__icontains=search_term)
                )

        # Handle ordering for total_aura
        if filters.order_by in ["total_aura", "-total_aura"]:
            queryset = queryset.annotate(
                calculated_total_aura=F("aura_polls") + F("aura_comments")
            ).order_by(
                ("-" if filters.order_by.startswith("-") else "")
                + "calculated_total_aura"
            )

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

        # Build response without membership data
        users_data = []
        for profile in page_obj.object_list:
            user_data = UserListItemSchema.resolve(profile)
            users_data.append(user_data)

    # If role is specified but no community_id, return error
    if filters.role and not filters.community_id:
        return 400, {"message": "Role filtering requires community_id parameter"}

    return {
        "users": users_data,
        "total_count": total_count,
        "page": filters.page,
        "per_page": filters.per_page,
        "total_pages": paginator.num_pages,
        "has_next": page_obj.has_next(),
        "has_previous": page_obj.has_previous(),
    }
