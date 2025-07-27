from datetime import datetime, timedelta, timezone
from enum import Enum

import jwt
from django.conf import settings
from django.http import HttpRequest
from ninja.security import HttpBearer

from keyopolls.profile.models import PseudonymousProfile


# Custom Exception Classes for Authentication
class AuthErrorType(Enum):
    """Enumeration of authentication error types"""

    TOKEN_EXPIRED = ("Your session has expired. Please log in again.", 401)
    INVALID_TOKEN = ("Invalid authentication token", 401)
    PROFILE_NOT_FOUND = ("Profile not found", 403)
    MISSING_HEADER = ("Missing required header", 400)
    AUTHENTICATION_FAILED = ("Authentication failed", 401)


class AuthError(Exception):
    """
    Unified authentication exception class.

    Usage:
        raise AuthError(AuthErrorType.TOKEN_EXPIRED)
        raise AuthError(AuthErrorType.PROFILE_NOT_FOUND, "Custom message")
    """

    def __init__(self, error_type: AuthErrorType, custom_message: str = None):
        self.error_type = error_type
        self.message = custom_message or error_type.value[0]
        self.status_code = error_type.value[1]
        super().__init__(self.message)

    def __str__(self):
        return self.message

    @property
    def error_name(self):
        """Returns the error type name for logging/debugging"""
        return self.error_type.name


def generate_pseudonymous_access_token(pseudonymous_profile_id: int) -> str:
    """
    Generate JWT access token for pseudonymous profile.

    Args:
        pseudonymous_profile_id: ID of the pseudonymous profile

    Returns:
        JWT token string
    """
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": pseudonymous_profile_id,
        "iat": now,  # Issued at timestamp
        "exp": now + timedelta(days=30),  # Expires in 7 days
    }

    # Generate JWT token
    token = jwt.encode(payload, settings.PSEUDONYMOUS_SECRET_KEY, algorithm="HS256")

    return token


class PseudonymousJWTAuth(HttpBearer):
    """JWT Authentication for pseudonymous profiles"""

    def authenticate(self, request: HttpRequest, token: str):
        try:
            # Decode and validate the JWT token
            payload = jwt.decode(
                token, settings.PSEUDONYMOUS_SECRET_KEY, algorithms=["HS256"]
            )

            # Get the pseudonymous profile from the database
            pseudonymous_profile = PseudonymousProfile.objects.get(
                id=payload["user_id"]
            )

            # Update last login timestamp
            pseudonymous_profile.update_last_login()

            return pseudonymous_profile

        except jwt.ExpiredSignatureError:
            raise AuthError(AuthErrorType.TOKEN_EXPIRED)
        except jwt.InvalidTokenError:
            raise AuthError(AuthErrorType.INVALID_TOKEN)
        except PseudonymousProfile.DoesNotExist:
            raise AuthError(
                AuthErrorType.PROFILE_NOT_FOUND, "Pseudonymous profile not found"
            )
        except Exception as e:
            raise AuthError(AuthErrorType.AUTHENTICATION_FAILED, str(e))


def OptionalPseudonymousJWTAuth(request: HttpRequest):
    """
    Optional pseudonymous profile authentication

    Args:
        request: HttpRequest object
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        request.auth = None
        return True

    if not auth_header.startswith("Bearer "):
        request.auth = None
        return True

    token_part = auth_header.split("Bearer ", 1)
    if len(token_part) < 2:
        request.auth = None
        return True

    token = token_part[1].strip()

    if not token or token == "null" or token == "undefined":
        request.auth = None
        return True

    try:
        payload = jwt.decode(
            token, settings.PSEUDONYMOUS_SECRET_KEY, algorithms=["HS256"]
        )
        pseudonymous_profile = PseudonymousProfile.objects.get(id=payload["user_id"])

        # Update last login timestamp
        pseudonymous_profile.update_last_login()

        request.auth = pseudonymous_profile
        return pseudonymous_profile

    except jwt.ExpiredSignatureError:
        raise AuthError(AuthErrorType.TOKEN_EXPIRED)
    except jwt.InvalidTokenError:
        raise AuthError(AuthErrorType.INVALID_TOKEN)
    except PseudonymousProfile.DoesNotExist:
        raise AuthError(
            AuthErrorType.PROFILE_NOT_FOUND, "Pseudonymous profile not found"
        )
    except Exception as e:
        raise AuthError(AuthErrorType.AUTHENTICATION_FAILED, str(e))
