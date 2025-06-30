# api.py
import logging

from django.conf import settings
from google.auth.transport import requests
from google.oauth2 import id_token
from ninja import Router

from keyopolls.profile.middleware import (
    PseudonymousJWTAuth,
    generate_pseudonymous_access_token,
)
from keyopolls.profile.models import PseudonymousProfile
from keyopolls.profile.schemas import (
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


@router.post("/google", response=GoogleSignInResponseSchema)
def google_signin(request, payload: GoogleSignInSchema):
    """Handle Google Sign-In"""
    try:
        # Verify Google token
        idinfo = id_token.verify_oauth2_token(
            payload.credential, requests.Request(), settings.GOOGLE_CLIENT_ID
        )

        email = idinfo["email"]
        google_id = idinfo["sub"]
        name = idinfo.get("name", "")

        # Check if profile exists
        profile = PseudonymousProfile.objects.filter(email=email).first()

        if profile:
            # Update existing profile with Google ID if not set
            if not profile.google_id:
                profile.google_id = google_id
                profile.is_email_verified = True
                profile.save()
            profile.update_last_login()
        else:
            # Create new profile with Google data
            # Generate username from email or name
            base_username = email.split("@")[0] or name.replace(" ", "").lower()
            username = base_username
            counter = 1
            while PseudonymousProfile.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1

            profile = PseudonymousProfile.objects.create(
                username=username,
                display_name=name or username,
                email=email,
                google_id=google_id,
                is_email_verified=True,
                password_hash="",  # No password for Google users
            )
            profile.update_last_login()

        # Generate JWT token
        token = generate_pseudonymous_access_token(profile.id)

        return {
            "success": True,
            "token": token,
            "user": ProfileDetailsSchema.resolve(profile),
        }

    except ValueError as e:
        logger.error(f"Google token verification failed: {str(e)}")
        return {"success": False, "error": "Invalid Google token"}
    except Exception as e:
        logger.error(f"Google signin error: {str(e)}")
        return {"success": False, "error": "Google sign-in failed"}


@router.post("/send-otp", response=SendOTPResponseSchema)
def send_otp(request, payload: SendOTPSchema):
    """Send OTP for email verification"""
    email = payload.email.lower().strip()

    # Check if profile already exists and is verified
    existing_profile = PseudonymousProfile.objects.filter(email=email).first()
    if existing_profile and existing_profile.is_email_verified:
        return {"success": False, "error": "Email already registered and verified"}

    # Create temporary profile or update existing unverified one
    if existing_profile:
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
            "expires_in": 600,  # OTP valid for 10 minutes
        }
    else:
        return {"success": False, "error": "Failed to send OTP"}


@router.post("/verify-otp", response=VerifyOTPResponseSchema)
def verify_otp(request, payload: VerifyOTPSchema):
    """Verify OTP"""
    email = payload.email.lower().strip()

    try:
        profile = PseudonymousProfile.objects.get(email=email)
        success, message = profile.verify_otp(payload.otp)

        if success:
            return {"success": True, "message": message, "email_verified": True}
        else:
            return {"success": False, "error": message}

    except PseudonymousProfile.DoesNotExist:
        return {"success": False, "error": "Email not found"}


@router.post("/complete-registration", response=CompleteRegistrationResponseSchema)
def complete_registration(request, payload: CompleteRegistrationSchema):
    """Complete registration after OTP verification"""
    email = payload.email.lower().strip()
    username = payload.username.strip()

    try:
        profile = PseudonymousProfile.objects.get(email=email)

        # Complete profile setup
        profile.username = username
        profile.display_name = payload.display_name.strip()
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
        return {"success": False, "error": "Email not found"}


@router.post("/login", response=LoginResponseSchema)
def login(request, payload: LoginSchema):
    """Login with email and password"""
    email = payload.email.lower().strip()

    try:
        profile = PseudonymousProfile.objects.get(email=email)

        # Check if account was created via Google (no password)
        if profile.google_id and not profile.password_hash:
            return {"success": False, "error": "Please sign in with Google"}

        # Check password
        if not profile.check_password(payload.password):
            return {"success": False, "error": "Invalid credentials"}

        profile.update_last_login()

        # Generate JWT token
        token = generate_pseudonymous_access_token(profile.id)

        return {
            "success": True,
            "token": token,
            "user": ProfileDetailsSchema.resolve(profile),
        }

    except PseudonymousProfile.DoesNotExist:
        return {"success": False, "error": "Invalid credentials"}


@router.get("/check-username/{username}", response=UsernameAvailabilitySchema)
def check_username_availability(request, username: str):
    """Check if username is available"""
    username = username.strip().lower()

    if len(username) < 3:
        return {
            "available": False,
            "error": "Username must be at least 3 characters",
            "error_code": "USERNAME_TOO_SHORT",
        }

    if len(username) > 50:
        return {
            "available": False,
            "error": "Username must be less than 50 characters",
            "error_code": "USERNAME_TOO_LONG",
        }

    # Check for invalid characters (allow alphanumeric and underscores)
    if not username.replace("_", "").isalnum():
        return {
            "available": False,
            "error": "Username can only contain letters, numbers, and underscores",
            "error_code": "USERNAME_INVALID_CHARACTERS",
        }

    exists = PseudonymousProfile.objects.filter(username=username).exists()
    return {"available": not exists}
