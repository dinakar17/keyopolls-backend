from datetime import datetime
from typing import List, Optional

from ninja import Schema

from keyopolls.communities.models import CommunityMembership
from keyopolls.profile.models import PseudonymousProfile


# Schemas
class GoogleSignInSchema(Schema):
    credential: str


class SendOTPSchema(Schema):
    email: str


class VerifyOTPSchema(Schema):
    email: str
    otp: str


class CompleteRegistrationSchema(Schema):
    email: str
    username: str
    display_name: Optional[str] = None
    password: str


class LoginSchema(Schema):
    email_or_username: str
    password: str


class ProfileUpdateSchema(Schema):
    display_name: Optional[str] = None
    about: Optional[str] = None


class ProfileDetailsSchema(Schema):
    id: int
    username: str
    display_name: str
    about: Optional[str] = None
    avatar: Optional[str] = None
    banner: Optional[str] = None
    email: str
    aura_polls: int
    aura_comments: int
    total_aura: int
    is_email_verified: bool
    created_at: datetime

    is_owner: Optional[bool] = None

    @staticmethod
    def resolve(profile: PseudonymousProfile, profile_id: Optional[int] = None):
        return {
            "id": profile.id,
            "username": profile.username,
            "display_name": profile.display_name,
            "about": profile.about,
            "email": profile.email,
            "aura_polls": profile.aura_polls,
            "aura_comments": profile.aura_comments,
            "total_aura": profile.total_aura,
            "is_email_verified": profile.is_email_verified,
            "created_at": profile.created_at,
            "avatar": profile.avatar.url if profile.avatar else None,
            "banner": profile.banner.url if profile.banner else None,
            "is_owner": profile.id == profile_id if profile_id is not None else None,
        }


class GoogleDataSchema(Schema):
    google_id: str
    email: str
    name: str
    suggested_username: str
    suggested_display_name: str


class GoogleSignInResponseSchema(Schema):
    success: bool
    token: str = None
    user: ProfileDetailsSchema = None
    requires_completion: bool = None
    google_data: GoogleDataSchema = None
    error: str = None


class SendOTPResponseSchema(Schema):
    success: bool
    message: str = None
    expires_in: int = None
    error: str = None


class VerifyOTPResponseSchema(Schema):
    success: bool
    message: str = None
    email_verified: bool = None
    error: str = None


class CompleteRegistrationResponseSchema(Schema):
    success: bool
    token: str = None
    user: ProfileDetailsSchema = None
    error: str = None


class CompleteGoogleRegistrationSchema(Schema):
    google_id: str
    username: str
    display_name: Optional[str] = None


class LoginResponseSchema(Schema):
    success: bool
    token: str = None
    user: ProfileDetailsSchema = None
    error: str = None


class UsernameAvailabilitySchema(Schema):
    available: bool
    error: str = None
    error_code: str = None


class AuthorSchema(Schema):
    id: int
    username: str
    display_name: str
    total_aura: int
    avatar: Optional[str] = None

    @staticmethod
    def resolve(profile):
        return {
            "id": profile.id,
            "username": profile.username,
            "display_name": profile.display_name,
            "avatar": profile.avatar.url if profile.avatar else None,
            "total_aura": profile.total_aura,
        }


class CompleteGoogleRegistrationResponseSchema(Schema):
    success: bool
    token: str = None
    user: ProfileDetailsSchema = None
    error: str = None


# Schemas
class UserListItemSchema(Schema):
    id: int
    username: str
    display_name: str
    avatar: Optional[str] = None
    total_aura: int
    created_at: datetime

    # Community-specific fields (only when filtering by community)
    role: Optional[str] = None
    joined_at: Optional[datetime] = None
    is_active_member: Optional[bool] = None

    @staticmethod
    def resolve(
        profile: PseudonymousProfile, membership: Optional[CommunityMembership] = None
    ):
        data = {
            "id": profile.id,
            "username": profile.username,
            "display_name": profile.display_name,
            "avatar": profile.avatar.url if profile.avatar else None,
            "total_aura": profile.total_aura,
            "created_at": profile.created_at,
        }

        # Add membership details if provided
        if membership:
            data.update(
                {
                    "role": membership.role,
                    "joined_at": membership.joined_at,
                    "is_active_member": membership.is_active_member,
                }
            )

        return data


class UsersListResponseSchema(Schema):
    users: List[UserListItemSchema]
    total_count: int
    page: int
    per_page: int
    total_pages: int
    has_next: bool
    has_previous: bool


class UsersListFiltersSchema(Schema):
    search: Optional[str] = None
    community_id: Optional[int] = None
    role: Optional[str] = None
    page: int = 1
    per_page: int = 20
    # Options: created_at, -created_at, username, -username, total_aura, -total_aura
    order_by: str = "-created_at"

    class Config:
        schema_extra = {
            "example": {
                "search": "john",
                "community_id": 123,
                "role": "member",
                "page": 1,
                "per_page": 20,
                "order_by": "-created_at",
            }
        }
