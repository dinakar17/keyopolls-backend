import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest
from django.utils.text import slugify
from ninja import File, Router, UploadedFile

from keyopolls.common.schemas import Message
from keyopolls.communities.models import Community, CommunityMembership
from keyopolls.communities.schemas import (
    CommunityCreateSchema,
    CommunityDetails,
    CommunityMembershipResponseSchema,
    CommunityMembershipSchema,
    CommunityUpdateSchema,
)
from keyopolls.profile.middleware import PseudonymousJWTAuth

logger = logging.getLogger(__name__)

router = Router(tags=["Communities"], auth=PseudonymousJWTAuth())


@router.post(
    "/communities",
    response={
        201: CommunityDetails,
        400: Message,
        403: Message,
    },
)
def create_community(
    request: HttpRequest,
    data: CommunityCreateSchema,
    avatar: UploadedFile = File(None),
    banner: UploadedFile = File(None),
):
    """Create a new community"""
    profile = request.auth

    try:
        # Validate community type
        valid_types = ["public", "private", "restricted"]
        if data.community_type not in valid_types:
            return 400, {
                "message": (
                    f"Invalid community type. Must be one of: "
                    f"{', '.join(valid_types)}"
                )
            }

        # Check if community name already exists (case-insensitive) or slug exists
        name_slug = slugify(data.name.strip())
        if Community.objects.filter(name__iexact=data.name.strip()).exists():
            return 400, {"message": "A community with this name already exists"}

        if Community.objects.filter(slug=name_slug).exists():
            return 400, {"message": "A community with this name already exists"}

        # # Validate category exists
        # try:
        #     category = Category.objects.get(id=data.category_id)
        # except Category.DoesNotExist:
        #     return 400, {"message": "Category not found"}

        # # Validate tags (max 3)
        # if len(data.tag_names) > 3:
        #     return 400, {"message": "Community cannot have more than 3 tags"}

        # Validate and prepare tags
        # tag_names = [name.strip().lower() for name in data.tag_names if name.strip()]
        # if len(set(tag_names)) != len(tag_names):
        #     return 400, {"message": "Duplicate tags are not allowed"}

        # # Validate tag names
        # for tag_name in tag_names:
        #     if len(tag_name) < 2:
        #         return 400, {"message": "Tag names must be at least 2
        # characters long"}
        #     if len(tag_name) > 50:
        #         return 400, {"message": "Tag names cannot exceed 50 characters"}

        # validate media files
        if avatar and avatar.size > 5 * 1024 * 1024:
            return 400, {"message": "Avatar image cannot exceed 5MB"}

        if banner and banner.size > 10 * 1024 * 1024:
            return 400, {"message": "Banner image cannot exceed 10MB"}

        # Use database transaction
        with transaction.atomic():
            # Create the community
            community = Community.objects.create(
                name=data.name.strip(),
                description=data.description.strip() if data.description else "",
                community_type=data.community_type,
                # category=category,
                creator=profile,
                avatar=avatar,
                banner=banner,
                member_count=1,  # Creator is the first member
            )

            # Create creator membership
            CommunityMembership.objects.create(
                community=community, profile=profile, role="creator", status="active"
            )

            # Create/get tags and associate them with the community
            # community_content_type = ContentType.objects.get_for_model(Community)

            # for tag_name in tag_names:
            #     # Get or create tag
            #     tag, created = Tag.objects.get_or_create(
            #         name=tag_name,
            #         defaults={"slug": slugify(tag_name), "usage_count": 0},
            #     )

            #     # Create tagged item (this will increment usage_count via save method)
            #     TaggedItem.objects.create(
            #         tag=tag, content_type=community_content_type,
            # object_id=community.id
            #     )

            # Refresh community with related data
            community.refresh_from_db()

            return 201, CommunityDetails.resolve(community, profile=profile)

    except ValidationError as e:
        return 400, {"message": str(e)}
    except Exception as e:
        logger.error(f"Error creating community: {str(e)}", exc_info=True)
        return 400, {
            "message": "An error occurred while creating the community",
        }


@router.post(
    "/communities/{community_id}",
    response={
        200: CommunityDetails,
        400: Message,
        403: Message,
        404: Message,
    },
)
def update_community(
    request: HttpRequest,
    community_id: int,
    data: CommunityUpdateSchema,
    avatar: UploadedFile = File(None),
    banner: UploadedFile = File(None),
):
    """Update community details"""
    profile = request.auth

    # Fetch the community
    community = Community.objects.filter(id=community_id).first()
    if not community:
        return 404, {"message": "Community not found"}

    # Check if the user is a member of the community
    membership = CommunityMembership.objects.filter(
        community=community, profile=profile
    ).first()
    if not membership or membership.role not in ["creator"]:
        return 403, {"message": "You do not have permission to update this community"}

    if data.description:
        community.description = data.description.strip()

    if data.rules:
        community.rules = data.rules

    if avatar:
        if avatar.size > 5 * 1024 * 1024:  # Limit to 5MB
            return 400, {"message": "Avatar image cannot exceed 5MB"}
        community.avatar = avatar

    if banner:
        if banner.size > 10 * 1024 * 1024:  # Limit to 10MB
            return 400, {"message": "Banner image cannot exceed 10MB"}
        community.banner = banner

    # Save the updated community
    community.save()

    # Refresh and return the updated community details
    community.refresh_from_db()

    return CommunityDetails.resolve(community, profile=profile)


@router.post(
    "/communities/{community_id}/membership",
    auth=PseudonymousJWTAuth(),
    response={200: CommunityMembershipResponseSchema, 400: Message, 404: Message},
)
def toggle_community_membership(
    request, community_id: int, payload: CommunityMembershipSchema
):
    """Join or leave a community"""
    profile = request.auth
    community = Community.objects.filter(id=community_id).first()

    # Check if community is active
    if not community.is_active:
        return 400, {"message": "Community is not active"}

    # Handle different community types
    if community.community_type == "public":
        return _handle_public_community_membership(profile, community, payload.action)
    elif community.community_type == "restricted":
        # TODO: Implement restricted community logic
        # For now, return not implemented
        return 400, {"message": "Restricted communities not yet implemented"}
    elif community.community_type == "private":
        # TODO: Implement private community logic
        # For now, return not implemented
        return 400, {"message": "Private communities not yet implemented"}
    else:
        return 400, {"message": "Invalid community type"}


def _handle_public_community_membership(profile, community, action: str):
    """Handle membership for public communities"""

    # Check if user meets aura requirements to join
    if action == "join" and not community.can_join(profile):
        return 400, {
            "message": (
                f"You need at least {community.requires_aura_to_join} aura "
                "to join this community"
            )
        }

    # Check if user is the creator (creators cannot leave their own communities)
    if action == "leave" and community.creator_id == profile.id:
        return 400, {"message": "Community creators cannot leave their own communities"}

    try:
        with transaction.atomic():
            # Get or create membership
            membership, created = CommunityMembership.objects.get_or_create(
                community=community,
                profile=profile,
                defaults={
                    "role": (
                        "creator" if community.creator_id == profile.id else "member"
                    ),
                    "status": "active",
                },
            )

            if action == "join":
                if created:
                    # New membership created
                    community.member_count += 1
                    community.save(update_fields=["member_count"])

                    return 200, {
                        "success": True,
                        "message": f"Successfully joined {community.name}",
                        "is_member": True,
                        "member_count": community.member_count,
                    }
                elif membership.status == "left":
                    # Rejoining - reactivate membership
                    membership.status = "active"
                    membership.save(update_fields=["status", "updated_at"])

                    community.member_count += 1
                    community.save(update_fields=["member_count"])

                    return 200, {
                        "success": True,
                        "message": f"Successfully rejoined {community.name}",
                        "is_member": True,
                        "member_count": community.member_count,
                    }
                elif membership.status == "banned":
                    return 400, {"message": "You are banned from this community"}
                else:
                    # Already an active member
                    return 400, {
                        "message": "You are already a member of this community"
                    }

            elif action == "leave":
                if not created and membership.status == "active":
                    # Leave community
                    membership.status = "left"
                    membership.save(update_fields=["status", "updated_at"])

                    community.member_count = max(0, community.member_count - 1)
                    community.save(update_fields=["member_count"])

                    return 200, {
                        "success": True,
                        "message": f"Successfully left {community.name}",
                        "is_member": False,
                        "member_count": community.member_count,
                    }
                else:
                    # Not a member or already left
                    return 400, {"message": "You are not a member of this community"}

    except Exception as e:
        logger.error(f"Error toggling community membership: {str(e)}")
        return 400, {"message": "An error occurred while processing your request"}
