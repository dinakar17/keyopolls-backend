from typing import List, Optional

from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest
from keyoconnect.connect_notifications.fcm_services import FCMService
from keyoconnect.connect_notifications.models import (
    NotificationPreference,
    NotificationType,
)
from keyoconnect.connect_notifications.schemas import (
    BulkNotificationPreferenceUpdateIn,
    FCMResponse,
    NotificationPreferenceResponse,
    NotificationPreferenceUpdateIn,
    RegisterDeviceIn,
    UnregisterDeviceIn,
)
from keyoconnect.profiles.middleware import PublicJWTAuth
from keyoconnect.profiles.models import PublicProfile
from ninja import Query, Router
from shared.schemas import Message

router = Router(tags=["FCM Notifications"])


@router.post(
    "/register-device/", response={200: FCMResponse, 400: Message}, auth=PublicJWTAuth()
)
def register_device(request: HttpRequest, data: RegisterDeviceIn):
    """
    Register FCM device token for push notifications
    Only available for Public profiles
    """
    # Get public profile from authenticated request
    public_profile: PublicProfile = request.auth

    return FCMService.register_device(
        token=data.token,
        device_type=data.device_type,
        profile=public_profile,
        device_info=data.device_info,
    )


@router.post(
    "/unregister-device/",
    response={200: FCMResponse, 400: Message},
    auth=PublicJWTAuth(),
)
def unregister_device(request: HttpRequest, data: UnregisterDeviceIn):
    """
    Unregister FCM device token
    """
    return FCMService.unregister_device(token=data.token)


# Get all devices for the authenticated profile
@router.get(
    "/devices/", response={200: FCMResponse, 400: Message}, auth=PublicJWTAuth()
)
def get_my_devices(request: HttpRequest):
    """
    Get all FCM devices for the authenticated profile
    """
    public_profile: PublicProfile = request.auth
    return FCMService.get_profile_devices(public_profile)


# Get notification preferences for the authenticated profile
@router.get(
    "/preferences/",
    response={200: List[NotificationPreferenceResponse], 400: Message},
    auth=PublicJWTAuth(),
)
def get_notification_preferences(request: HttpRequest):
    """
    Get notification preferences for the authenticated profile
    """
    public_profile: PublicProfile = request.auth

    # Get existing preferences
    existing_preferences = NotificationPreference.objects.filter(
        profile_content_type=ContentType.objects.get_for_model(public_profile),
        profile_object_id=public_profile.id,
    )

    # Convert to dict for easy lookup
    existing_prefs_dict = {
        pref.notification_type: pref for pref in existing_preferences
    }

    # Get all notification types
    all_notification_types = [choice[0] for choice in NotificationType.choices]

    preference_data = []

    for notification_type in all_notification_types:
        if notification_type in existing_prefs_dict:
            # Use existing preference
            preference = existing_prefs_dict[notification_type]
        else:
            # Create a virtual preference with defaults (don't save to DB)
            preference = NotificationPreference._create_default_preference_object(
                public_profile, notification_type
            )

        preference_data.append(
            NotificationPreferenceResponse(
                notification_type=preference.notification_type,
                in_app_enabled=preference.in_app_enabled,
                push_enabled=preference.push_enabled,
                email_enabled=preference.email_enabled,
                is_enabled=preference.is_enabled,
                custom_thresholds=preference.custom_thresholds,
                can_receive_push=preference.can_receive_push(),
            )
        )

    return preference_data


@router.post(
    "/preferences/bulk-update/",
    response={200: List[NotificationPreferenceResponse], 400: Message},
    auth=PublicJWTAuth(),
)
def bulk_update_notification_preferences(
    request: HttpRequest, data: BulkNotificationPreferenceUpdateIn
):
    """
    Bulk update notification preferences for all notification types
    """
    public_profile: PublicProfile = request.auth

    # Get all notification types
    all_notification_types = [choice[0] for choice in NotificationType.choices]

    updated_preferences = []
    errors = []

    for notification_type in all_notification_types:
        try:
            # Determine what to update based on the bulk operation
            update_data = {}

            if hasattr(data, "push_enabled") and data.push_enabled is not None:
                update_data["push_enabled"] = data.push_enabled
            if hasattr(data, "email_enabled") and data.email_enabled is not None:
                update_data["email_enabled"] = data.email_enabled
            if hasattr(data, "in_app_enabled") and data.in_app_enabled is not None:
                update_data["in_app_enabled"] = data.in_app_enabled

            # Get or create the preference
            preference = NotificationPreference.get_or_create_for_type(
                public_profile, notification_type
            )

            # Update the preference
            for field, value in update_data.items():
                setattr(preference, field, value)

            # Update is_enabled based on any enabled channel
            preference.is_enabled = (
                preference.push_enabled
                or preference.email_enabled
                or preference.in_app_enabled
            )

            preference.save()
            updated_preferences.append(preference)

        except Exception as e:
            errors.append(f"Error updating {notification_type}: {str(e)}")

    if errors:
        return 400, {"message": f"Some updates failed: {'; '.join(errors)}"}

    # Return updated preferences
    return [
        NotificationPreferenceResponse(
            notification_type=pref.notification_type,
            in_app_enabled=pref.in_app_enabled,
            push_enabled=pref.push_enabled,
            email_enabled=pref.email_enabled,
            is_enabled=pref.is_enabled,
            custom_thresholds=pref.custom_thresholds,
            can_receive_push=pref.can_receive_push(),
        )
        for pref in updated_preferences
    ]


# Update notification preferences for a specific notification type
@router.post(
    "/preferences/{notification_type}/",
    response={200: NotificationPreferenceResponse, 400: Message},
    auth=PublicJWTAuth(),
)
def update_notification_preference(
    request: HttpRequest, notification_type: str, data: NotificationPreferenceUpdateIn
):
    """
    Update notification preferences for a specific notification type
    """
    public_profile: PublicProfile = request.auth

    # Validate notification type
    if notification_type not in [choice[0] for choice in NotificationType.choices]:
        return 400, {"message": f"Invalid notification_type: {notification_type}"}

    # Update preferences
    result = FCMService.update_notification_preferences(
        profile=public_profile,
        notification_type=notification_type,
        push_enabled=data.push_enabled,
        email_enabled=data.email_enabled,
        in_app_enabled=data.in_app_enabled,
        is_enabled=data.is_enabled,
    )

    if not result["success"]:
        return 400, {"message": result["message"]}

    # Get updated preference
    try:
        from django.contrib.contenttypes.models import ContentType

        preference = NotificationPreference.objects.get(
            profile_content_type=ContentType.objects.get_for_model(public_profile),
            profile_object_id=public_profile.id,
            notification_type=notification_type,
        )

        return NotificationPreferenceResponse(
            notification_type=preference.notification_type,
            in_app_enabled=preference.in_app_enabled,
            push_enabled=preference.push_enabled,
            email_enabled=preference.email_enabled,
            is_enabled=preference.is_enabled,
            custom_thresholds=preference.custom_thresholds,
            can_receive_push=preference.can_receive_push(),
        )
    except NotificationPreference.DoesNotExist:
        return 400, {"message": "Preference not found"}


# Toggle all push notifications for the authenticated profile
@router.post("/preferences/push/{status}/", response=FCMResponse, auth=PublicJWTAuth())
def toggle_all_push_notifications(request: HttpRequest, status: str):
    """
    Enable or disable push notifications for all notification types
    Status should be 'enable' or 'disable'
    """
    public_profile: PublicProfile = request.auth

    if status not in ["enable", "disable"]:
        return 400, {"message": "Status must be 'enable' or 'disable'"}

    push_enabled = status == "enable"

    try:
        from django.contrib.contenttypes.models import ContentType

        # Update all notification preferences for this profile
        updated_count = NotificationPreference.objects.filter(
            profile_content_type=ContentType.objects.get_for_model(public_profile),
            profile_object_id=public_profile.id,
        ).update(push_enabled=push_enabled)

        # If no preferences exist, create them
        if updated_count == 0:
            NotificationPreference.get_or_create_default_preferences(public_profile)
            # Update them after creation
            NotificationPreference.objects.filter(
                profile_content_type=ContentType.objects.get_for_model(public_profile),
                profile_object_id=public_profile.id,
            ).update(push_enabled=push_enabled)
            updated_count = NotificationType.choices.__len__()

        return {
            "success": True,
            "message": (
                f"Push notifications {status}d for {updated_count} notification types"
            ),
            "updated_count": updated_count,
        }

    except Exception as e:
        return 400, {"message": f"Error updating preferences: {str(e)}"}


# Toggle all email notifications for the authenticated profile
@router.post("/preferences/email/{status}/", response=FCMResponse, auth=PublicJWTAuth())
def toggle_all_email_notifications(request: HttpRequest, status: str):
    """
    Enable or disable email notifications for all notification types
    Status should be 'enable' or 'disable'
    """
    public_profile: PublicProfile = request.auth

    if status not in ["enable", "disable"]:
        return 400, {"message": "Status must be 'enable' or 'disable'"}

    email_enabled = status == "enable"

    try:
        from django.contrib.contenttypes.models import ContentType

        # Update all notification preferences for this profile
        updated_count = NotificationPreference.objects.filter(
            profile_content_type=ContentType.objects.get_for_model(public_profile),
            profile_object_id=public_profile.id,
        ).update(email_enabled=email_enabled)

        # If no preferences exist, create them
        if updated_count == 0:
            NotificationPreference.get_or_create_default_preferences(public_profile)
            # Update them after creation
            NotificationPreference.objects.filter(
                profile_content_type=ContentType.objects.get_for_model(public_profile),
                profile_object_id=public_profile.id,
            ).update(email_enabled=email_enabled)
            updated_count = NotificationType.choices.__len__()

        return {
            "success": True,
            "message": (
                f"Email notifications {status}d for {updated_count} notification types"
            ),
            "updated_count": updated_count,
        }

    except Exception as e:
        return 400, {"message": f"Error updating preferences: {str(e)}"}


# Admin/Testing endpoints (you might want to restrict these)
@router.post("/test/send-to-profile/", response=FCMResponse, auth=PublicJWTAuth())
def test_send_notification(
    request: HttpRequest,
    title: str = Query(..., description="Notification title"),
    body: str = Query(..., description="Notification body"),
    notification_type: Optional[str] = Query(None, description="Notification type"),
):
    """
    Test sending a notification to the authenticated profile
    """
    public_profile: PublicProfile = request.auth

    return FCMService.notify_profile(
        profile=public_profile,
        title=title,
        body=body,
        data={"test": True},
        notification_type=notification_type,
    )
