from typing import List, Optional

from django.http import HttpRequest
from django.utils import timezone
from ninja import Query, Router
from shared.schemas import Message

from keyopolls.notifications.fcm_services import FCMService
from keyopolls.notifications.models import NotificationPreference, NotificationType
from keyopolls.notifications.schemas import (
    BulkNotificationPreferenceUpdateIn,
    FCMResponse,
    NotificationPreferenceResponse,
    NotificationPreferenceUpdateIn,
    RegisterDeviceIn,
    UnregisterDeviceIn,
)
from keyopolls.profile.middleware import PseudonymousJWTAuth
from keyopolls.profile.models import PseudonymousProfile

router = Router(tags=["FCM Notifications"])


@router.post(
    "/register-device/",
    response={200: FCMResponse, 400: Message},
    auth=PseudonymousJWTAuth(),
)
def register_device(request: HttpRequest, data: RegisterDeviceIn):
    """
    Register FCM device token for push notifications
    Available for all PseudonymousProfiles
    """
    # Get pseudonymous profile from authenticated request
    profile: PseudonymousProfile = request.auth

    return FCMService.register_device(
        token=data.token,
        device_type=data.device_type,
        profile=profile,
        device_info=data.device_info,
    )


@router.post(
    "/unregister-device/",
    response={200: FCMResponse, 400: Message},
    auth=PseudonymousJWTAuth(),
)
def unregister_device(request: HttpRequest, data: UnregisterDeviceIn):
    """
    Unregister FCM device token
    """
    return FCMService.unregister_device(token=data.token)


# Get all devices for the authenticated profile
@router.get(
    "/devices/", response={200: FCMResponse, 400: Message}, auth=PseudonymousJWTAuth()
)
def get_my_devices(request: HttpRequest):
    """
    Get all FCM devices for the authenticated profile
    """
    profile: PseudonymousProfile = request.auth
    return FCMService.get_profile_devices(profile)


# Get notification preferences for the authenticated profile
@router.get(
    "/preferences/",
    response={200: List[NotificationPreferenceResponse], 400: Message},
    auth=PseudonymousJWTAuth(),
)
def get_notification_preferences(request: HttpRequest):
    """
    Get notification preferences for the authenticated profile
    """
    profile: PseudonymousProfile = request.auth

    # Get existing preferences
    existing_preferences = NotificationPreference.objects.filter(profile=profile)

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
                profile, notification_type
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
    auth=PseudonymousJWTAuth(),
)
def bulk_update_notification_preferences(
    request: HttpRequest, data: BulkNotificationPreferenceUpdateIn
):
    """
    Bulk update notification preferences for all notification types
    """
    profile: PseudonymousProfile = request.auth

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
                profile, notification_type
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
    auth=PseudonymousJWTAuth(),
)
def update_notification_preference(
    request: HttpRequest, notification_type: str, data: NotificationPreferenceUpdateIn
):
    """
    Update notification preferences for a specific notification type
    """
    profile: PseudonymousProfile = request.auth

    # Validate notification type
    if notification_type not in [choice[0] for choice in NotificationType.choices]:
        return 400, {"message": f"Invalid notification_type: {notification_type}"}

    # Update preferences
    result = FCMService.update_notification_preferences(
        profile=profile,
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
        preference = NotificationPreference.objects.get(
            profile=profile,
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
@router.post(
    "/preferences/push/{status}/", response=FCMResponse, auth=PseudonymousJWTAuth()
)
def toggle_all_push_notifications(request: HttpRequest, status: str):
    """
    Enable or disable push notifications for all notification types
    Status should be 'enable' or 'disable'
    """
    profile: PseudonymousProfile = request.auth

    if status not in ["enable", "disable"]:
        return {"success": False, "message": "Status must be 'enable' or 'disable'"}

    push_enabled = status == "enable"

    try:
        # Update all notification preferences for this profile
        updated_count = NotificationPreference.objects.filter(
            profile=profile,
        ).update(push_enabled=push_enabled)

        # If no preferences exist, create them
        if updated_count == 0:
            FCMService._ensure_default_preferences(profile)
            # Update them after creation
            updated_count = NotificationPreference.objects.filter(
                profile=profile,
            ).update(push_enabled=push_enabled)

        return {
            "success": True,
            "message": f"Push notifications {status}d for {updated_count} "
            "notification types",
            "updated_count": updated_count,
        }

    except Exception as e:
        return {"success": False, "message": f"Error updating preferences: {str(e)}"}


# Toggle all email notifications for the authenticated profile
@router.post(
    "/preferences/email/{status}/", response=FCMResponse, auth=PseudonymousJWTAuth()
)
def toggle_all_email_notifications(request: HttpRequest, status: str):
    """
    Enable or disable email notifications for all notification types
    Status should be 'enable' or 'disable'
    """
    profile: PseudonymousProfile = request.auth

    if status not in ["enable", "disable"]:
        return {"success": False, "message": "Status must be 'enable' or 'disable'"}

    email_enabled = status == "enable"

    try:
        # Update all notification preferences for this profile
        updated_count = NotificationPreference.objects.filter(
            profile=profile,
        ).update(email_enabled=email_enabled)

        # If no preferences exist, create them
        if updated_count == 0:
            FCMService._ensure_default_preferences(profile)
            # Update them after creation
            updated_count = NotificationPreference.objects.filter(
                profile=profile,
            ).update(email_enabled=email_enabled)

        return {
            "success": True,
            "message": f"Email notifications {status}d for {updated_count} "
            "notification types",
            "updated_count": updated_count,
        }

    except Exception as e:
        return {"success": False, "message": f"Error updating preferences: {str(e)}"}


# Toggle all in-app notifications for the authenticated profile
@router.post(
    "/preferences/in-app/{status}/", response=FCMResponse, auth=PseudonymousJWTAuth()
)
def toggle_all_in_app_notifications(request: HttpRequest, status: str):
    """
    Enable or disable in-app notifications for all notification types
    Status should be 'enable' or 'disable'
    """
    profile: PseudonymousProfile = request.auth

    if status not in ["enable", "disable"]:
        return {"success": False, "message": "Status must be 'enable' or 'disable'"}

    in_app_enabled = status == "enable"

    try:
        # Update all notification preferences for this profile
        updated_count = NotificationPreference.objects.filter(
            profile=profile,
        ).update(in_app_enabled=in_app_enabled)

        # If no preferences exist, create them
        if updated_count == 0:
            FCMService._ensure_default_preferences(profile)
            # Update them after creation
            updated_count = NotificationPreference.objects.filter(
                profile=profile,
            ).update(in_app_enabled=in_app_enabled)

        return {
            "success": True,
            "message": f"In-app notifications {status}d for {updated_count} "
            "notification types",
            "updated_count": updated_count,
        }

    except Exception as e:
        return {"success": False, "message": f"Error updating preferences: {str(e)}"}


# Get notification statistics for the authenticated profile
@router.get("/stats/", response={200: dict, 400: Message}, auth=PseudonymousJWTAuth())
def get_notification_stats(request: HttpRequest):
    """
    Get notification statistics for the authenticated profile
    """
    profile: PseudonymousProfile = request.auth

    try:
        from datetime import timedelta

        from django.utils import timezone

        from keyopolls.notifications.models import Notification

        # Get various statistics
        total_notifications = Notification.objects.filter(recipient=profile).count()
        unread_notifications = Notification.objects.filter(
            recipient=profile, is_read=False
        ).count()

        # Notifications from last 7 days
        week_ago = timezone.now() - timedelta(days=7)
        recent_notifications = Notification.objects.filter(
            recipient=profile, created_at__gte=week_ago
        ).count()

        # Most common notification types
        from django.db.models import Count

        notification_types = list(
            Notification.objects.filter(recipient=profile)
            .values("notification_type")
            .annotate(count=Count("notification_type"))
            .order_by("-count")[:5]
        )

        # Device count
        device_count = profile.fcm_devices.filter(active=True).count()

        # Notification preferences summary
        preferences = NotificationPreference.objects.filter(profile=profile)
        push_enabled_count = preferences.filter(
            push_enabled=True, is_enabled=True
        ).count()
        email_enabled_count = preferences.filter(
            email_enabled=True, is_enabled=True
        ).count()
        in_app_enabled_count = preferences.filter(
            in_app_enabled=True, is_enabled=True
        ).count()

        return {
            "success": True,
            "stats": {
                "total_notifications": total_notifications,
                "unread_notifications": unread_notifications,
                "recent_notifications": recent_notifications,
                "active_devices": device_count,
                "notification_types": notification_types,
                "preferences": {
                    "push_enabled_types": push_enabled_count,
                    "email_enabled_types": email_enabled_count,
                    "in_app_enabled_types": in_app_enabled_count,
                    "total_preference_types": len(NotificationType.choices),
                },
            },
        }

    except Exception as e:
        return 400, {"message": f"Error getting notification stats: {str(e)}"}


# Admin/Testing endpoints (you might want to restrict these)
@router.post("/test/send-to-profile/", response=FCMResponse, auth=PseudonymousJWTAuth())
def test_send_notification(
    request: HttpRequest,
    title: str = Query(..., description="Notification title"),
    body: str = Query(..., description="Notification body"),
    notification_type: Optional[str] = Query(None, description="Notification type"),
):
    """
    Test sending a notification to the authenticated profile
    """
    profile: PseudonymousProfile = request.auth

    return FCMService.notify_profile(
        profile=profile,
        title=title,
        body=body,
        data={"test": True, "sent_at": timezone.now().isoformat()},
        notification_type=notification_type,
    )


# Test community notification
@router.post(
    "/test/send-to-community/", response=FCMResponse, auth=PseudonymousJWTAuth()
)
def test_send_community_notification(
    request: HttpRequest,
    community_id: int = Query(..., description="Community ID"),
    title: str = Query(..., description="Notification title"),
    body: str = Query(..., description="Notification body"),
    notification_type: Optional[str] = Query(
        "community_new_poll", description="Notification type"
    ),
):
    """
    Test sending a notification to all members of a community
    """
    profile: PseudonymousProfile = request.auth

    try:
        from keyopolls.communities.models import Community

        community = Community.objects.get(id=community_id)

        # Check if user is a member of the community
        if not community.memberships.filter(profile=profile, status="active").exists():
            return {
                "success": False,
                "message": "You are not a member of this community",
            }

        return FCMService.notify_community_members(
            community=community,
            title=title,
            body=body,
            data={"test": True, "sent_at": timezone.now().isoformat()},
            notification_type=notification_type,
            exclude_profile=profile,  # Don't notify the sender
        )

    except Community.DoesNotExist:
        return {"success": False, "message": "Community not found"}
    except Exception as e:
        return {
            "success": False,
            "message": f"Error sending community notification: {str(e)}",
        }
