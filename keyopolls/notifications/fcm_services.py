import logging
from typing import Dict, List, Optional

from shared.notifications.firebase import FirebaseService

from keyopolls.notifications.models import FCMDevice, NotificationPreference
from keyopolls.profile.models import PseudonymousProfile

logger = logging.getLogger(__name__)


class FCMService:
    """FCM service for device registration and notification sending using
    PseudonymousProfile"""

    @classmethod
    def register_device(
        cls,
        token: str,
        device_type: str,
        profile: PseudonymousProfile,
        device_info: Optional[Dict] = None,
    ) -> Dict:
        """Register FCM device token for a PseudonymousProfile"""
        try:
            if not isinstance(profile, PseudonymousProfile):
                return {
                    "success": False,
                    "message": "Invalid profile type for device registration",
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
            cls._ensure_default_preferences(profile)

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
        profile: PseudonymousProfile,
        title: str,
        body: str,
        data: Optional[Dict] = None,
        notification_type: Optional[str] = None,
    ) -> Dict:
        """Send notification to a PseudonymousProfile"""
        try:
            if not isinstance(profile, PseudonymousProfile):
                return {
                    "success": False,
                    "message": "Invalid profile type for notifications",
                    "sent": 0,
                    "total": 0,
                }

            # Check if push notifications are enabled for this profile and notification
            #  type
            if notification_type:
                try:
                    preference = NotificationPreference.objects.get(
                        profile=profile,
                        notification_type=notification_type,
                    )
                    if not preference.push_enabled or not preference.is_enabled:
                        return {
                            "success": False,
                            "message": (
                                f"Push notifications disabled for "
                                f"{notification_type}"
                            ),
                            "sent": 0,
                            "total": 0,
                        }
                except NotificationPreference.DoesNotExist:
                    # Create default preferences if they don't exist
                    cls._ensure_default_preferences(profile)
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
                    "profile_username": profile.username,
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
                    f"Sent to {result['success']} devices with "
                    f"{result['failure']} failures"
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
        profiles: List[PseudonymousProfile],
        title: str,
        body: str,
        data: Optional[Dict] = None,
        notification_type: Optional[str] = None,
    ) -> Dict:
        """Send notification to multiple PseudonymousProfiles"""
        try:
            # Filter to only PseudonymousProfile instances
            valid_profiles = [p for p in profiles if isinstance(p, PseudonymousProfile)]

            if not valid_profiles:
                return {
                    "success": False,
                    "message": "No valid profiles found",
                    "sent": 0,
                    "total": 0,
                }

            profile_ids = [p.id for p in valid_profiles]

            # Get profiles with push enabled for this notification type
            enabled_profile_ids = profile_ids
            if notification_type:
                enabled_preferences = NotificationPreference.objects.filter(
                    profile_id__in=profile_ids,
                    notification_type=notification_type,
                    push_enabled=True,
                    is_enabled=True,
                )
                enabled_profile_ids = list(
                    enabled_preferences.values_list("profile_id", flat=True)
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
                    notification_type=notification_type,
                    push_enabled=True,
                    is_enabled=True,
                )
                enabled_profile_ids = list(
                    enabled_preferences.values_list("profile_id", flat=True)
                )
            else:
                # If no specific type, get all profiles with any push enabled
                enabled_profile_ids = list(
                    NotificationPreference.objects.filter(
                        push_enabled=True,
                        is_enabled=True,
                    )
                    .values_list("profile_id", flat=True)
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
                    f"Broadcast sent to {result['success']} devices with "
                    f"{result['failure']} failures"
                ),
                "sent": result["success"],
                "total": len(tokens),
            }
        except Exception as e:
            logger.error(f"Error broadcasting notification: {str(e)}")
            return {"success": False, "message": str(e), "sent": 0, "total": 0}

    @classmethod
    def get_profile_devices(cls, profile: PseudonymousProfile) -> Dict:
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
        profile: PseudonymousProfile,
        notification_type: str,
        push_enabled: Optional[bool] = None,
        email_enabled: Optional[bool] = None,
        in_app_enabled: Optional[bool] = None,
        is_enabled: Optional[bool] = None,
    ) -> Dict:
        """Update notification preferences for a profile"""
        try:
            preference, created = NotificationPreference.objects.get_or_create(
                profile=profile,
                notification_type=notification_type,
            )

            # Update fields if provided
            if push_enabled is not None:
                preference.push_enabled = push_enabled

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

    @classmethod
    def get_notification_preferences(cls, profile: PseudonymousProfile) -> Dict:
        """Get all notification preferences for a profile"""
        try:
            preferences = NotificationPreference.objects.filter(profile=profile)

            pref_data = []
            for pref in preferences:
                pref_data.append(
                    {
                        "notification_type": pref.notification_type,
                        "in_app_enabled": pref.in_app_enabled,
                        "push_enabled": pref.push_enabled,
                        "email_enabled": pref.email_enabled,
                        "is_enabled": pref.is_enabled,
                        "custom_thresholds": pref.custom_thresholds,
                    }
                )

            return {
                "success": True,
                "preferences": pref_data,
                "total": len(pref_data),
            }
        except Exception as e:
            logger.error(f"Error getting notification preferences: {str(e)}")
            return {"success": False, "message": str(e), "preferences": []}

    @classmethod
    def _ensure_default_preferences(cls, profile: PseudonymousProfile):
        """Ensure profile has default notification preferences"""
        try:
            from keyopolls.notifications.models import NotificationType

            # Create default preferences for all notification types
            for notification_type, _ in NotificationType.choices:
                NotificationPreference.get_or_create_for_type(
                    profile, notification_type
                )

        except Exception as e:
            logger.error(f"Error creating default preferences: {str(e)}")

    @classmethod
    def notify_community_members(
        cls,
        community,
        title: str,
        body: str,
        data: Optional[Dict] = None,
        notification_type: Optional[str] = None,
        exclude_profile: Optional[PseudonymousProfile] = None,
    ) -> Dict:
        """Send notification to all members of a community"""
        try:
            # Get all active community members
            from keyopolls.communities.models import CommunityMembership

            memberships = CommunityMembership.objects.filter(
                community=community, status="active"
            ).select_related("profile")

            profiles = [m.profile for m in memberships]

            # Exclude specific profile if provided (e.g., the actor)
            if exclude_profile:
                profiles = [p for p in profiles if p.id != exclude_profile.id]

            if not profiles:
                return {
                    "success": False,
                    "message": "No community members found",
                    "sent": 0,
                    "total": 0,
                }

            # Add community context to data
            community_data = data or {}
            community_data.update(
                {
                    "community_id": str(community.id),
                    "community_name": community.name,
                }
            )

            return cls.notify_profiles(
                profiles=profiles,
                title=title,
                body=body,
                data=community_data,
                notification_type=notification_type,
            )

        except Exception as e:
            logger.error(f"Error notifying community members: {str(e)}")
            return {"success": False, "message": str(e), "sent": 0, "total": 0}

    @classmethod
    def notify_poll_followers(
        cls,
        poll,
        title: str,
        body: str,
        data: Optional[Dict] = None,
        notification_type: Optional[str] = None,
        exclude_profile: Optional[PseudonymousProfile] = None,
    ) -> Dict:
        """Send notification to all followers of a poll"""
        try:
            # Get all active poll followers
            from keyopolls.notifications.models import PollFollow

            follows = PollFollow.objects.filter(
                poll=poll, is_active=True
            ).select_related("follower")

            profiles = [f.follower for f in follows]

            # Exclude specific profile if provided (e.g., the actor)
            if exclude_profile:
                profiles = [p for p in profiles if p.id != exclude_profile.id]

            if not profiles:
                return {
                    "success": False,
                    "message": "No poll followers found",
                    "sent": 0,
                    "total": 0,
                }

            # Add poll context to data
            poll_data = data or {}
            poll_data.update(
                {
                    "poll_id": str(poll.id),
                    "poll_title": poll.title,
                }
            )

            return cls.notify_profiles(
                profiles=profiles,
                title=title,
                body=body,
                data=poll_data,
                notification_type=notification_type,
            )

        except Exception as e:
            logger.error(f"Error notifying poll followers: {str(e)}")
            return {"success": False, "message": str(e), "sent": 0, "total": 0}
