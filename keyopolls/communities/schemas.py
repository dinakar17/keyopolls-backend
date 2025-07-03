from typing import List, Literal, Optional

from django.contrib.contenttypes.models import ContentType
from ninja import Schema

from keyopolls.common.models import TaggedItem
from keyopolls.communities.models import Community, CommunityMembership
from keyopolls.profile.models import PseudonymousProfile


# Request Schemas
class CommunityCreateSchema(Schema):
    name: str
    description: Optional[str] = ""
    community_type: str = "public"  # public, private, restricted
    category_id: int
    tag_names: List[str] = []  # List of tag names (max 3)


class CommunityUpdateSchema(Schema):
    """Schema for updating community details"""

    description: Optional[str] = None
    rules: Optional[List[str]] = None


# Response Schemas
class CategoryResponseSchema(Schema):
    id: int
    name: str
    slug: str
    description: str
    category_type: str


class TagResponseSchema(Schema):
    id: int
    name: str
    slug: str
    usage_count: int


class MembershipDetailsSchema(Schema):
    """Schema for user's membership details in the community"""

    role: str  # member, moderator, admin, creator
    status: str  # active, pending, banned, left
    joined_at: str
    is_active: bool
    can_moderate: bool


class UserPermissionsSchema(Schema):
    """Schema for user's permissions in the community"""

    can_join: bool
    can_post: bool
    can_view: bool


class CommunityDetails(Schema):
    id: int
    name: str
    description: str
    rules: Optional[List[str]] = None  # List of community rules
    avatar: Optional[str] = None
    banner: Optional[str] = None
    community_type: str
    creator_id: int
    category: CategoryResponseSchema
    tags: List[TagResponseSchema]
    member_count: int
    poll_count: int
    requires_aura_to_join: int
    requires_aura_to_post: int
    created_at: str
    is_active: bool

    # Member-specific fields (only present when profile is provided)
    membership_details: Optional[MembershipDetailsSchema] = None
    user_permissions: Optional[UserPermissionsSchema] = None

    @staticmethod
    def resolve_minimal(community: Community, profile=None):
        """
        Resolve minimal community details for list views.
        Returns only essential fields, leaves others empty for performance.
        """
        # Basic category data (minimal)
        category_data = CategoryResponseSchema(
            id=community.category.id,
            name=community.category.name,
            slug=community.category.slug,
            description="",  # Empty for minimal
            category_type=community.category.category_type,
        )

        # Basic membership status if user is authenticated
        membership_details = None
        user_permissions = None

        if profile:
            # Simple membership check
            try:
                membership = community.memberships.get(profile=profile, status="active")
                membership_details = MembershipDetailsSchema(
                    role=membership.role,
                    status=membership.status,
                    joined_at=membership.joined_at.isoformat(),
                    is_active=membership.is_active_member,
                    can_moderate=membership.can_moderate,
                )
            except CommunityMembership.DoesNotExist:
                pass

            # Basic permissions
            user_permissions = UserPermissionsSchema(
                can_join=community.can_join(profile),
                can_post=False,  # Skip expensive permission check for lists
                can_view=True,  # Simplified since they can see it in the list
            )

        return CommunityDetails(
            id=community.id,
            name=community.name,
            description=community.description,
            rules=community.rules if community.rules else [],  # Include rules if any
            avatar=community.avatar.url if community.avatar else None,
            banner=None,  # Skip banner for list views
            community_type=community.community_type,
            creator_id=community.creator.id,
            category=category_data,
            tags=[],  # Empty tags list for performance
            member_count=community.member_count,
            poll_count=community.poll_count,
            requires_aura_to_join=community.requires_aura_to_join,
            requires_aura_to_post=community.requires_aura_to_post,
            created_at=community.created_at.isoformat(),
            is_active=community.is_active,
            membership_details=membership_details,
            user_permissions=user_permissions,
        )

    @staticmethod
    def resolve(community: Community, profile=None):
        """
        Resolve full community details for detailed views.
        """
        # Get category data
        category_data = CategoryResponseSchema(
            id=community.category.id,
            name=community.category.name,
            slug=community.category.slug,
            description=community.category.description,
            category_type=community.category.category_type,
        )

        # Get tags data
        community_content_type = ContentType.objects.get_for_model(Community)
        tagged_items = TaggedItem.objects.filter(
            content_type=community_content_type, object_id=community.id
        ).select_related("tag")

        tags_data = [
            TagResponseSchema(
                id=item.tag.id,
                name=item.tag.name,
                slug=item.tag.slug,
                usage_count=item.tag.usage_count,
            )
            for item in tagged_items
        ]

        # Initialize member-specific data
        membership_details = None
        user_permissions = None

        # If profile is provided, get membership and permission details
        if profile:
            # Get membership details
            try:
                membership: CommunityMembership = community.memberships.get(
                    profile=profile
                )
                membership_details = MembershipDetailsSchema(
                    role=membership.role,
                    status=membership.status,
                    joined_at=membership.joined_at.isoformat(),
                    is_active=membership.is_active_member,
                    can_moderate=membership.can_moderate,
                )
            except CommunityMembership.DoesNotExist:
                membership_details = None

            # Get user permissions
            user_permissions = UserPermissionsSchema(
                can_join=community.can_join(profile),
                can_post=community.can_post(profile),
                can_view=_can_view_community(community, profile),
            )

        return CommunityDetails(
            id=community.id,
            name=community.name,
            description=community.description,
            avatar=community.avatar.url if community.avatar else None,
            banner=community.banner.url if community.banner else None,
            community_type=community.community_type,
            creator_id=community.creator.id,
            category=category_data,
            tags=tags_data,
            member_count=community.member_count,
            poll_count=community.poll_count,
            requires_aura_to_join=community.requires_aura_to_join,
            requires_aura_to_post=community.requires_aura_to_post,
            created_at=community.created_at.isoformat(),
            is_active=community.is_active,
            membership_details=membership_details,
            user_permissions=user_permissions,
        )


class CommunityListResponse(Schema):
    communities: List[CommunityDetails]
    pagination: dict
    filters_applied: dict


def _can_view_community(community: Community, profile: PseudonymousProfile):
    """Helper function to check if user can view the community"""
    # Public and restricted communities are viewable by all
    if community.community_type in ["public", "restricted"]:
        return True

    # Private communities require membership
    if community.community_type == "private":
        try:
            membership = community.memberships.get(profile=profile)
            return membership.is_active_member
        except CommunityMembership.DoesNotExist:
            return False

    # Inactive communities - only creator/admin can view
    if not community.is_active:
        try:
            membership = community.memberships.get(profile=profile)
            return (
                membership.role in ["creator", "admin"] and membership.is_active_member
            )
        except CommunityMembership.DoesNotExist:
            return False

    return True


class CommunityMembershipSchema(Schema):
    action: Literal["join", "leave"]


class CommunityMembershipResponseSchema(Schema):
    success: bool
    message: str
    is_member: bool
    member_count: int
