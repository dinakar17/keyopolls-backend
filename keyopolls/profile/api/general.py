from ninja import File, Router, UploadedFile

from keyopolls.common.schemas import Message
from keyopolls.profile.middleware import (
    OptionalPseudonymousJWTAuth,
    PseudonymousJWTAuth,
)
from keyopolls.profile.models import PseudonymousProfile
from keyopolls.profile.schemas import ProfileDetailsSchema, ProfileUpdateSchema

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
