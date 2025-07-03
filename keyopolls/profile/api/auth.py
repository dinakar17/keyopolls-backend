# api.py
import logging

from django.conf import settings
from django.db.models import Q
from google.auth.transport import requests
from google.oauth2 import id_token
from ninja import Router

from keyopolls.common.schemas import Message
from keyopolls.profile.middleware import (
    PseudonymousJWTAuth,
    generate_pseudonymous_access_token,
)
from keyopolls.profile.models import PseudonymousProfile
from keyopolls.profile.schemas import (
    CompleteGoogleRegistrationResponseSchema,
    CompleteGoogleRegistrationSchema,
    CompleteRegistrationResponseSchema,
    CompleteRegistrationSchema,
    GoogleSignInResponseSchema,
    GoogleSignInSchema,
    LoginResponseSchema,
    LoginSchema,
    ProfileDetailsSchema,
    SendOTPResponseSchema,
    SendOTPSchema,
    UsernameAvailabilitySchema,
    VerifyOTPResponseSchema,
    VerifyOTPSchema,
)
from keyopolls.profile.services import CommunicationService

logger = logging.getLogger(__name__)
router = Router()

# Initialize auth handlers
auth = PseudonymousJWTAuth()


@router.post("/google", response={200: GoogleSignInResponseSchema, 400: Message})
def google_signin(request, payload: GoogleSignInSchema):
    """Handle Google Sign-In - creates incomplete profile requiring completion"""
    # Verify Google token
    idinfo = id_token.verify_oauth2_token(
        payload.credential, requests.Request(), settings.GOOGLE_CLIENT_ID
    )

    email = idinfo["email"]
    google_id = idinfo["sub"]
    name = idinfo.get("name", "")

    # Check if profile already exists
    existing_profile = PseudonymousProfile.objects.filter(email=email).first()

    if existing_profile:
        # If profile exists and is complete, log them in
        if existing_profile.is_profile_complete:
            existing_profile.update_last_login()
            token = generate_pseudonymous_access_token(existing_profile.id)

            return {
                "success": True,
                "token": token,
                "user": ProfileDetailsSchema.resolve(existing_profile),
                "requires_completion": False,
            }
        else:
            # Profile exists but incomplete, update Google data and
            # require completion
            existing_profile.google_id = google_id
            existing_profile.is_email_verified = True
            existing_profile.save()

            return {
                "success": True,
                "requires_completion": True,
                "google_data": {
                    "google_id": google_id,
                    "email": email,
                    "name": name,
                    "suggested_username": email.split("@")[0],
                    "suggested_display_name": name,
                },
            }
    else:
        # Create new incomplete profile
        PseudonymousProfile.objects.create(
            username="",  # Empty - will be set during completion
            display_name="",  # Empty - will be set during completion
            email=email,
            google_id=google_id,
            is_email_verified=True,
            password_hash="",  # No password for Google users
        )

        return 200, {
            "success": True,
            "requires_completion": True,
            "google_data": {
                "google_id": google_id,
                "email": email,
                "name": name,
                "suggested_username": email.split("@")[0],
                "suggested_display_name": name,
            },
        }


@router.post("/send-otp", response={200: SendOTPResponseSchema, 400: Message})
def send_otp(request, payload: SendOTPSchema):
    """Send OTP for email verification"""
    email = payload.email.lower().strip()

    # Check if profile already exists
    existing_profile = PseudonymousProfile.objects.filter(email=email).first()

    if existing_profile:
        # If profile is complete (has username and password),
        # don't allow re-registration
        if existing_profile.is_profile_complete:
            return 400, {
                "message": "Email already registered and verified. Please log in."
            }

        # If profile exists but incomplete (no username), allow re-registration
        # This handles cases where user abandoned registration after OTP verification
        profile = existing_profile
    else:
        # Create temporary profile for OTP verification
        profile = PseudonymousProfile.objects.create(
            username="",  # Will be set during registration
            display_name="",  # Will be set during registration
            email=email,
            password_hash="",  # Will be set during registration
            is_email_verified=False,
        )

    # Generate and send OTP
    otp = profile.generate_otp()

    if CommunicationService.send_email_otp(email, otp):
        return {
            "success": True,
            "message": "OTP sent successfully",
            "expires_in": 600,  # 10 minutes
        }
    else:
        return 400, {"message": "Failed to send OTP. Please try again later."}


@router.post("/verify-otp", response={200: VerifyOTPResponseSchema, 400: Message})
def verify_otp(request, payload: VerifyOTPSchema):
    """Verify OTP"""
    email = payload.email.lower().strip()

    try:
        profile = PseudonymousProfile.objects.get(email=email)
        success, message = profile.verify_otp(payload.otp)

        if success:
            return {"success": True, "message": message, "email_verified": True}
        else:
            return 400, {"message": message}

    except PseudonymousProfile.DoesNotExist:
        return 400, {"message": "Email not found or OTP not generated"}


@router.post(
    "/complete-google-registration",
    response={200: CompleteGoogleRegistrationResponseSchema, 400: Message},
)
def complete_google_registration(request, payload: CompleteGoogleRegistrationSchema):
    """Complete Google registration after initial sign-in"""
    google_id = payload.google_id.strip()
    username = payload.username.strip()

    try:
        # Find profile by Google ID
        profile = PseudonymousProfile.objects.get(google_id=google_id)

        # Check if profile is already complete
        if profile.is_profile_complete:
            return 400, {"message": "Profile already completed. Please log in."}

        # Check if username is available
        if (
            PseudonymousProfile.objects.filter(username=username)
            .exclude(id=profile.id)
            .exists()
        ):
            return 400, {"message": "Username already taken"}

        # Complete profile setup
        profile.username = username

        # Handle optional display_name
        if payload.display_name:
            profile.display_name = payload.display_name.strip()

        profile.save()
        profile.update_last_login()

        # Generate JWT token
        token = generate_pseudonymous_access_token(profile.id)

        return {
            "success": True,
            "token": token,
            "user": ProfileDetailsSchema.resolve(profile),
        }

    except PseudonymousProfile.DoesNotExist:
        return 400, {"message": "Google profile not found"}


@router.post(
    "/complete-registration",
    response={200: CompleteRegistrationResponseSchema, 400: Message},
)
def complete_registration(request, payload: CompleteRegistrationSchema):
    """Complete registration after OTP verification"""
    email = payload.email.lower().strip()
    username = payload.username.strip()

    try:
        profile = PseudonymousProfile.objects.get(email=email)

        # Check if username is available (excluding current profile)
        if (
            PseudonymousProfile.objects.filter(username=username)
            .exclude(id=profile.id)
            .exists()
        ):
            return 400, {"message": "Username already taken"}

        # Complete profile setup
        profile.username = username
        # Remove display_name assignment since it's no longer submitted
        profile.set_password(payload.password)
        profile.save()
        profile.update_last_login()

        # Generate JWT token
        token = generate_pseudonymous_access_token(profile.id)

        return {
            "success": True,
            "token": token,
            "user": ProfileDetailsSchema.resolve(profile),
        }

    except PseudonymousProfile.DoesNotExist:
        return 400, {"message": "Email not found"}


@router.post("/login", response={200: LoginResponseSchema, 400: Message})
def login(request, payload: LoginSchema):
    """Login with email or username and password"""
    email_or_username = payload.email_or_username.lower().strip()

    try:
        # Try to find user by email or username
        profile = PseudonymousProfile.objects.get(
            Q(email=email_or_username) | Q(username=email_or_username)
        )

        # Check if account was created via Google (no password)
        if profile.google_id and not profile.password_hash:
            return 400, {"message": "Please sign in with Google"}

        # Check password
        if not profile.check_password(payload.password):
            return 400, {"message": "Invalid password"}

        profile.update_last_login()

        # Generate JWT token
        token = generate_pseudonymous_access_token(profile.id)

        return 200, {
            "success": True,
            "token": token,
            "user": ProfileDetailsSchema.resolve(profile),
        }

    except PseudonymousProfile.DoesNotExist:
        return 400, {
            "message": (
                "No account found with this email or username. "
                "Please register first."
            )
        }


@router.get(
    "/check-username/{username}",
    response={200: UsernameAvailabilitySchema, 400: Message},
)
def check_username_availability(request, username: str):
    """Check if username is available"""
    username = username.strip().lower()

    if len(username) < 3:
        return 400, {
            "message": "Username must be at least 3 characters",
        }

    if len(username) > 50:
        return 400, {
            "message": "Username must be less than 50 characters",
        }

    # Check for invalid characters (allow alphanumeric and underscores)
    if not username.replace("_", "").isalnum():
        return 400, {
            "message": "Username can only contain letters, numbers, and underscores",
        }

    exists = PseudonymousProfile.objects.filter(username=username).exists()
    return {"available": not exists}
