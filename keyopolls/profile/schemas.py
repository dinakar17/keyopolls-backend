from datetime import datetime

from ninja import Schema


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
    display_name: str
    password: str


class LoginSchema(Schema):
    email: str
    password: str


class ProfileDetailsSchema(Schema):
    id: int
    username: str
    display_name: str
    email: str
    aura_polls: int
    aura_comments: int
    total_aura: int
    is_email_verified: bool
    created_at: datetime

    @staticmethod
    def resolve(profile):
        return {
            "id": profile.id,
            "username": profile.username,
            "display_name": profile.display_name,
            "email": profile.email,
            "aura_polls": profile.aura_polls,
            "aura_comments": profile.aura_comments,
            "total_aura": profile.total_aura,
            "is_email_verified": profile.is_email_verified,
            "created_at": profile.created_at,
        }


class GoogleSignInResponseSchema(Schema):
    success: bool
    token: str = None
    user: ProfileDetailsSchema = None
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

    @staticmethod
    def resolve(profile):
        return {
            "id": profile.id,
            "username": profile.username,
            "display_name": profile.display_name,
            "total_aura": profile.total_aura,
        }
