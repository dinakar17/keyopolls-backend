import logging
from typing import Dict, List, Optional

from django.contrib.contenttypes.models import ContentType
from keyoconnect.connect_notifications.models import FCMDevice, NotificationPreference
from keyoconnect.profiles.models import PublicProfile
from shared.notifications.firebase import FirebaseService

logger = logging.getLogger(__name__)


class FCMService:
    """FCM service for device registration and notification sending using profiles"""

    @classmethod
    def register_device(
        cls,
        token: str,
        device_type: str,
        profile: PublicProfile,
        device_info: Optional[Dict] = None,
    ) -> Dict:
        """Register FCM device token for a Public profile"""
        try:
            if not isinstance(profile, PublicProfile):
                return {
                    "success": False,
                    "message": "Only Public profiles can register for push "
                    "notifications",
                }

            # Extra device info
            device_info = device_info or {}

            # Create or update device
            device, created = FCMDevice.objects.update_or_create(
                token=token,
                defaults={
                    "profile": profile,
                    "device_type": device_type,
                    "active": True,
                    "device_id": device_info.get("device_id"),
                    "device_name": device_info.get("device_name"),
                },
            )

            # Ensure the profile has notification preferences
            NotificationPreference.get_or_create_default_preferences(profile)

            return {
                "success": True,
                "message": "Device registered successfully",
                "created": created,
                "device_id": device.id,
            }
        except Exception as e:
            logger.error(f"Error registering FCM device: {str(e)}")
            return {"success": False, "message": str(e)}

    @classmethod
    def unregister_device(cls, token: str) -> Dict:
        """Unregister FCM device token"""
        try:
            device = FCMDevice.objects.get(token=token)
            device.active = False
            device.save()

            return {"success": True, "message": "Device unregistered successfully"}
        except FCMDevice.DoesNotExist:
            return {"success": False, "message": "Device not found"}
        except Exception as e:
            logger.error(f"Error unregistering FCM device: {str(e)}")
            return {"success": False, "message": str(e)}

    @classmethod
    def notify_profile(
        cls,
        profile: PublicProfile,
        title: str,
        body: str,
        data: Optional[Dict] = None,
        notification_type: Optional[str] = None,
    ) -> Dict:
        """Send notification to a Public profile"""
        try:
            if not isinstance(profile, PublicProfile):
                return {
                    "success": False,
                    "message": "Only Public profiles can receive push notifications",
                    "sent": 0,
                    "total": 0,
                }

            # Check if push notifications are enabled for this profile and
            # notification type
            if notification_type:
                try:
                    preference = NotificationPreference.objects.get(
                        profile_content_type=ContentType.objects.get_for_model(profile),
                        profile_object_id=profile.id,
                        notification_type=notification_type,
                    )
                    if not preference.push_enabled:
                        return {
                            "success": False,
                            "message": (
                                f"Push notifications disabled for {notification_type}"
                            ),
                            "sent": 0,
                            "total": 0,
                        }
                except NotificationPreference.DoesNotExist:
                    # Create default preferences if they don't exist
                    NotificationPreference.get_or_create_default_preferences(profile)
                    # For safety, don't send if preferences don't exist
                    return {
                        "success": False,
                        "message": "Notification preferences not found",
                        "sent": 0,
                        "total": 0,
                    }

            # Get active devices for the profile
            devices = FCMDevice.objects.filter(profile=profile, active=True)

            if not devices.exists():
                return {
                    "success": False,
                    "message": "No active devices found for this profile",
                    "sent": 0,
                    "total": 0,
                }

            # Get tokens
            tokens = list(devices.values_list("token", flat=True))

            # Add notification metadata to data
            notification_data = data or {}
            notification_data.update(
                {
                    "profile_id": str(profile.id),
                    "profile_type": "public",
                    "notification_type": notification_type or "general",
                }
            )

            # Send notification
            result = FirebaseService.send_multicast(
                tokens=tokens, title=title, body=body, data=notification_data
            )

            # Update last_used_at for successful tokens
            if result["success"] > 0:
                from django.utils import timezone

                devices.update(last_used_at=timezone.now())

            return {
                "success": result["success"] > 0,
                "message": (
                    f"Sent to {result['success']} devices "
                    f"with {result['failure']} failures"
                ),
                "sent": result["success"],
                "total": len(tokens),
            }
        except Exception as e:
            logger.error(f"Error sending notification to profile: {str(e)}")
            return {"success": False, "message": str(e), "sent": 0, "total": 0}

    @classmethod
    def notify_profiles(
        cls,
        profiles: List[PublicProfile],
        title: str,
        body: str,
        data: Optional[Dict] = None,
        notification_type: Optional[str] = None,
    ) -> Dict:
        """Send notification to multiple Public profiles"""
        try:
            # Filter to only Public profiles
            public_profiles = [p for p in profiles if isinstance(p, PublicProfile)]

            if not public_profiles:
                return {
                    "success": False,
                    "message": "No Public profiles found",
                    "sent": 0,
                    "total": 0,
                }

            profile_ids = [p.id for p in public_profiles]

            # Get profiles with push enabled for this notification type
            enabled_profile_ids = profile_ids
            if notification_type:
                enabled_preferences = NotificationPreference.objects.filter(
                    profile_content_type=ContentType.objects.get_for_model(
                        PublicProfile
                    ),
                    profile_object_id__in=profile_ids,
                    notification_type=notification_type,
                    push_enabled=True,
                    is_enabled=True,
                )
                enabled_profile_ids = list(
                    enabled_preferences.values_list("profile_object_id", flat=True)
                )

            if not enabled_profile_ids:
                return {
                    "success": False,
                    "message": (
                        "No profiles have push notifications enabled for this type"
                    ),
                    "sent": 0,
                    "total": 0,
                }

            # Get active devices for the enabled profiles
            devices = FCMDevice.objects.filter(
                profile_id__in=enabled_profile_ids, active=True
            )

            if not devices.exists():
                return {
                    "success": False,
                    "message": "No active devices found for these profiles",
                    "sent": 0,
                    "total": 0,
                }

            # Get tokens
            tokens = list(devices.values_list("token", flat=True))

            # Add notification metadata to data
            notification_data = data or {}
            notification_data.update(
                {
                    "notification_type": notification_type or "general",
                    "target_profiles": len(enabled_profile_ids),
                }
            )

            # Send notification
            result = FirebaseService.send_multicast(
                tokens=tokens, title=title, body=body, data=notification_data
            )

            # Update last_used_at for successful devices
            if result["success"] > 0:
                from django.utils import timezone

                devices.update(last_used_at=timezone.now())

            return {
                "success": result["success"] > 0,
                "message": (
                    f"Sent to {result['success']} devices across "
                    f"{len(enabled_profile_ids)} profiles with "
                    f"{result['failure']} failures"
                ),
                "sent": result["success"],
                "total": len(tokens),
                "profiles_notified": len(enabled_profile_ids),
            }
        except Exception as e:
            logger.error(f"Error sending notification to profiles: {str(e)}")
            return {"success": False, "message": str(e), "sent": 0, "total": 0}

    @classmethod
    def broadcast(
        cls,
        title: str,
        body: str,
        data: Optional[Dict] = None,
        notification_type: Optional[str] = None,
    ) -> Dict:
        """Broadcast notification to all active devices with push enabled"""
        try:
            # Get all profiles with push enabled for this notification type
            enabled_profile_ids = []
            if notification_type:
                enabled_preferences = NotificationPreference.objects.filter(
                    profile_content_type=ContentType.objects.get_for_model(
                        PublicProfile
                    ),
                    notification_type=notification_type,
                    push_enabled=True,
                    is_enabled=True,
                )
                enabled_profile_ids = list(
                    enabled_preferences.values_list("profile_object_id", flat=True)
                )
            else:
                # If no specific type, get all public profiles with any push enabled
                enabled_profile_ids = list(
                    NotificationPreference.objects.filter(
                        profile_content_type=ContentType.objects.get_for_model(
                            PublicProfile
                        ),
                        push_enabled=True,
                        is_enabled=True,
                    )
                    .values_list("profile_object_id", flat=True)
                    .distinct()
                )

            if not enabled_profile_ids:
                return {
                    "success": False,
                    "message": "No profiles have push notifications enabled",
                    "sent": 0,
                    "total": 0,
                }

            # Get active devices for enabled profiles
            devices = FCMDevice.objects.filter(
                profile_id__in=enabled_profile_ids, active=True
            )

            if not devices.exists():
                return {
                    "success": False,
                    "message": "No active devices found",
                    "sent": 0,
                    "total": 0,
                }

            # Get tokens
            tokens = list(devices.values_list("token", flat=True))

            # Add broadcast metadata to data
            notification_data = data or {}
            notification_data.update(
                {
                    "notification_type": notification_type or "broadcast",
                    "is_broadcast": True,
                }
            )

            # Send notification
            result = FirebaseService.send_multicast(
                tokens=tokens, title=title, body=body, data=notification_data
            )

            # Update last_used_at for successful devices
            if result["success"] > 0:
                from django.utils import timezone

                devices.update(last_used_at=timezone.now())

            return {
                "success": result["success"] > 0,
                "message": (
                    f"Broadcast sent to {result['success']} devices "
                    f"with {result['failure']} failures"
                ),
                "sent": result["success"],
                "total": len(tokens),
            }
        except Exception as e:
            logger.error(f"Error broadcasting notification: {str(e)}")
            return {"success": False, "message": str(e), "sent": 0, "total": 0}

    @classmethod
    def get_profile_devices(cls, profile: PublicProfile) -> Dict:
        """Get all devices for a profile"""
        try:
            devices = FCMDevice.objects.filter(profile=profile)
            device_data = []

            for device in devices:
                device_data.append(
                    {
                        "id": device.id,
                        "device_type": device.device_type,
                        "device_name": device.device_name,
                        "active": device.active,
                        "created_at": device.created_at.isoformat(),
                        "last_used_at": (
                            device.last_used_at.isoformat()
                            if device.last_used_at
                            else None
                        ),
                    }
                )

            return {
                "success": True,
                "devices": device_data,
                "total": len(device_data),
                "active": len([d for d in device_data if d["active"]]),
            }
        except Exception as e:
            logger.error(f"Error getting profile devices: {str(e)}")
            return {"success": False, "message": str(e), "devices": [], "total": 0}

    @classmethod
    def update_notification_preferences(
        cls,
        profile,
        notification_type: str,
        push_enabled: Optional[bool] = None,
        email_enabled: Optional[bool] = None,
        in_app_enabled: Optional[bool] = None,
        is_enabled: Optional[bool] = None,
    ) -> Dict:
        """Update notification preferences for a profile"""
        try:
            preference, created = NotificationPreference.objects.get_or_create(
                profile_content_type=ContentType.objects.get_for_model(profile),
                profile_object_id=profile.id,
                notification_type=notification_type,
            )

            # Update fields if provided
            if push_enabled is not None:
                # Only allow push notifications for Public profiles
                if isinstance(profile, PublicProfile):
                    preference.push_enabled = push_enabled
                else:
                    preference.push_enabled = False

            if email_enabled is not None:
                preference.email_enabled = email_enabled

            if in_app_enabled is not None:
                preference.in_app_enabled = in_app_enabled

            if is_enabled is not None:
                preference.is_enabled = is_enabled

            preference.save()

            return {
                "success": True,
                "message": "Notification preferences updated successfully",
                "created": created,
            }
        except Exception as e:
            logger.error(f"Error updating notification preferences: {str(e)}")
            return {"success": False, "message": str(e)}
