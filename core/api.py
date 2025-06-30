import logging

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django_ratelimit.exceptions import Ratelimited
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, HttpError, HttpRequest, ValidationError
from ninja.throttling import AnonRateThrottle, AuthRateThrottle


api = NinjaAPI(
    docs_url="docs/",
    title="Keyo API",
    version="1.0.0",
    description="API for Keyo polls app",
    urls_namespace="api_v1",
    throttle=[
        AnonRateThrottle("60/m"),  # Unauthenticated: 60 requests per minute
        AuthRateThrottle("300/m"),  # Authenticated: 300 requests per minute
    ],
)

"""
Custom Exception Handlers
"""


# # Single exception handler for all authentication errors
# # We're overriding the default django-ninja authentication error handler
# @api.exception_handler(AuthError)
# def auth_error_handler(request, exc):
#     return api.create_response(
#         request, {"message": exc.message}, status=exc.status_code
#     )


"""
Global Exception Handlers (Error Handlers)
"""


@api.exception_handler(HttpError)
def custom_http_error_handler(request, exc):
    return api.create_response(
        request, {"message": exc.message}, status=exc.status_code
    )


@api.exception_handler(AuthenticationError)
def custom_authentication_error_handler(request, exc):
    logging.error(f"Authentication error: {exc}")

    if isinstance(exc, HttpError):
        return api.create_response(
            request,
            {"message": str(exc)},  # Use the original HttpError message
            status=exc.status_code,
        )

    return api.create_response(
        request,
        {"message": "You need to be logged in to perform this action."},
        status=401,
    )


@api.exception_handler(Ratelimited)
def ratelimit_exceeded_handler(request, exc):
    return api.create_response(
        request,
        {"message": "Too many requests. Please try again later."},
        status=429,
    )


@api.exception_handler(ValidationError)
def validation_error_handler(request: HttpRequest, exc: ValidationError):
    print(exc.errors)
    return api.create_response(request, {"message": exc.errors}, status=422)


@api.exception_handler(ObjectDoesNotExist)
def object_not_found_handler(request, exc):
    # Return a 404 response if the object is not found
    return api.create_response(request, {"message": exc.args[0]}, status=404)


@api.exception_handler(Exception)
def generic_error_handler(request: HttpRequest, exc: Exception):
    print(f"Unhandled exception: {exc}")
    if settings.DEBUG:
        error_message = str(exc)
    else:
        error_message = "Internal Server Error"

    return api.create_response(request, {"message": error_message}, status=500)


# api.add_router("/shared", shared_router)
# api.add_router("/connect", connect_router)
# api.add_router("/sparkle", sparkle_router)
# api.add_router("/keyorewards", keyorewards_router)
