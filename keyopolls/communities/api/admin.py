from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from keyopolls.common.schemas import Message
from keyopolls.communities.models import Community, CommunityMembership
from keyopolls.profile.middleware import PseudonymousJWTAuth
from keyopolls.profile.models import PseudonymousProfile

router = Router()


class ChangeRoleRequestSchema(Schema):
    user_id: int
    new_role: str

    class Config:
        schema_extra = {"example": {"user_id": 123, "new_role": "moderator"}}


@router.patch(
    "/communities/{community_id}/members/role",
    response={200: Message, 400: Message, 403: Message, 404: Message},
    auth=PseudonymousJWTAuth(),
)
def change_member_role(request, community_id: int, data: ChangeRoleRequestSchema):
    """
    Change the role of a community member.
    Only the community creator can change member roles.

    Available roles:
    - member: Regular community member
    - moderator: Can moderate content and manage members
    - recruiter: Can invite new members
    - creator: Cannot be assigned (only one creator per community)

    Restrictions:
    - Only community creator can change roles
    - Cannot change creator role
    - Cannot assign creator role to others
    - Cannot change your own role
    - Target user must be an active member of the community
    """

    # Get the community
    community = get_object_or_404(Community, id=community_id, is_active=True)

    # Check if the requester is the creator
    requester_membership = get_object_or_404(
        CommunityMembership, community=community, profile=request.auth, status="active"
    )

    if requester_membership.role != "creator":
        return 403, {"message": "Only the community creator can change member roles"}

    # Validate the new role
    valid_roles = dict(CommunityMembership.ROLE_CHOICES).keys()
    if data.new_role not in valid_roles:
        return 400, {"message": f"Invalid role. Valid roles: {', '.join(valid_roles)}"}

    # Cannot assign creator role
    if data.new_role == "creator":
        return 400, {"message": "Creator role cannot be assigned to other members"}

    # Get the target user
    try:
        target_user = PseudonymousProfile.objects.get(id=data.user_id)
    except PseudonymousProfile.DoesNotExist:
        return 404, {"message": "User not found"}

    # Check if user is trying to change their own role
    if target_user.id == request.auth.id:
        return 400, {"message": "You cannot change your own role"}

    # Get the target member's membership
    try:
        target_membership = CommunityMembership.objects.get(
            community=community, profile=target_user, status="active"
        )
    except CommunityMembership.DoesNotExist:
        return 404, {"message": "User is not an active member of this community"}

    # Cannot change creator's role
    if target_membership.role == "creator":
        return 400, {"message": "Cannot change the creator's role"}

    # Check if role is already the same
    if target_membership.role == data.new_role:
        return 400, {"message": f"User is already a {data.new_role}"}

    # Store old role for response
    old_role = target_membership.role

    # Update the role
    target_membership.role = data.new_role
    target_membership.save()

    return {
        "message": f"Successfully changed {target_user.username}'s role from "
        f"{old_role} to {data.new_role}",
    }
