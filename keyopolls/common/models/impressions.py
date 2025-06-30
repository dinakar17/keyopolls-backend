import hashlib
from datetime import timedelta

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class ImpressionTrackingMixin:
    """
    Mixin to add impression tracking to any model.
    Just inherit from this class along with models.Model

    NOTE: Your model should have its own impressions_count field:
    impressions_count = models.PositiveIntegerField(default=0, db_index=True)
    """

    def record_impression(self, request):
        """
        Record an impression for this object
        Returns True if impression was recorded, False if duplicate
        """
        return Impression.record_for_object(self, request)

    def get_impressions_data(self, days=30):
        """Get impression analytics for the last N days"""
        return Impression.get_analytics_for_object(self, days)

    @classmethod
    def record_bulk_impressions(cls, objects_list, request):
        """
        Record impressions for multiple objects of this model type in bulk
        Returns dict with statistics about impressions recorded
        """
        return Impression.record_bulk_impressions(objects_list, request)

    @property
    def live_impressions_count(self):
        """Get real-time impressions count from database (accurate but slower)"""
        return Impression.objects.filter(
            content_type=ContentType.objects.get_for_model(self), object_id=self.pk
        ).count()

    def sync_impressions_count(self):
        """
        Sync denormalized impressions_count field with actual database count
        Your model must have an impressions_count field for this to work
        """
        if not hasattr(self, "impressions_count"):
            raise AttributeError(
                f"{self.__class__.__name__} must have an 'impressions_count' field "
                "to use sync_impressions_count()."
                " Add: impressions_count = "
                "models.PositiveIntegerField(default=0, db_index=True)"
            )

        actual_count = self.live_impressions_count
        if self.impressions_count != actual_count:
            old_count = self.impressions_count
            self.impressions_count = actual_count
            self.save(update_fields=["impressions_count"])
            print(
                f"Synced {self.__class__.__name__} {self.pk} impressions: "
                f"{old_count} → {actual_count}"
            )
            return True
        return False


class Impression(models.Model):
    """Generic impression tracking model for public profiles only"""

    # Generic foreign key to track impressions for any model
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    # Profile-based authentication info (only public profiles)
    profile_id = models.PositiveIntegerField(null=True, blank=True)

    # Session/device info for anonymous users
    ip_address = models.GenericIPAddressField()
    session_key = models.CharField(max_length=40, null=True, blank=True)

    # Metadata
    user_agent_hash = models.CharField(max_length=32, null=True, blank=True)
    referrer = models.URLField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    country_code = models.CharField(max_length=2, null=True, blank=True, db_index=True)

    # Todo: Create this later
    # def save(self, *args, **kwargs):
    #     if self.ip_address and not self.country_code:
    #         self.country_code = get_country_from_ip(self.ip_address)
    #     super().save(*args, **kwargs)

    class Meta:
        indexes = [
            models.Index(fields=["content_type", "object_id", "created_at"]),
            models.Index(fields=["ip_address", "created_at"]),
            models.Index(fields=["profile_id", "created_at"]),
            models.Index(fields=["session_key", "created_at"]),
        ]

    @classmethod
    def record_for_object(cls, obj, request):
        """
        Record an impression for any object with automatic counter update
        Returns True if recorded, False if duplicate
        """
        from django.db import transaction
        from django.db.models import F

        # Get request info
        ip_address = cls._get_client_ip(request)
        session_key = (
            request.session.session_key if hasattr(request, "session") else None
        )
        user_agent = request.META.get("HTTP_USER_AGENT", "")
        referrer = request.META.get("HTTP_REFERER", "")

        # Extract profile info from request.auth (simplified)
        profile_id = cls._extract_profile_id(request)

        # Check if we should record this impression
        if cls._should_record_impression(obj, profile_id, ip_address, session_key):
            with transaction.atomic():
                # Create the impression record
                cls.objects.create(
                    content_object=obj,
                    profile_id=profile_id,
                    ip_address=ip_address,
                    session_key=session_key,
                    user_agent_hash=(
                        hashlib.md5(user_agent.encode()).hexdigest()[:32]
                        if user_agent
                        else None
                    ),
                    referrer=referrer[:200] if referrer else None,  # Truncate long URLs
                )

                # 🚀 AUTO-INCREMENT THE DENORMALIZED COUNTER!
                if hasattr(obj, "impressions_count"):
                    obj.impressions_count = F("impressions_count") + 1
                    obj.save(update_fields=["impressions_count"])
            return True
        return False

    @classmethod
    def record_bulk_impressions(cls, objects_list, request):
        """
        Record impressions for multiple objects in bulk with automatic counter updates
        Returns dict with statistics about impressions recorded
        """
        from django.db import transaction
        from django.db.models import F

        stats = {
            "total_objects": len(objects_list),
            "impressions_recorded": 0,
            "impressions_skipped": 0,
        }

        if not objects_list:
            return stats

        # Extract request info once for all objects
        profile_id = cls._extract_profile_id(request)
        ip_address = cls._get_client_ip(request)
        session_key = (
            request.session.session_key if hasattr(request, "session") else None
        )
        user_agent = request.META.get("HTTP_USER_AGENT", "")
        referrer = request.META.get("HTTP_REFERER", "")

        # Prepare impression records and track object IDs that need counter updates
        impressions_to_create = []
        object_ids_to_update = []  # Store IDs instead of objects

        for obj in objects_list:
            # Check if we should record impression for this object
            if cls._should_record_impression(obj, profile_id, ip_address, session_key):
                impression = cls(
                    content_object=obj,
                    profile_id=profile_id,
                    ip_address=ip_address,
                    session_key=session_key,
                    user_agent_hash=(
                        hashlib.md5(user_agent.encode()).hexdigest()[:32]
                        if user_agent
                        else None
                    ),
                    referrer=referrer[:200] if referrer else None,
                )
                impressions_to_create.append(impression)

                # Track object IDs that need counter updates
                if hasattr(obj, "impressions_count"):
                    object_ids_to_update.append(obj.id)

                stats["impressions_recorded"] += 1
            else:
                stats["impressions_skipped"] += 1

        # Bulk create impressions and update counters
        if impressions_to_create and object_ids_to_update:
            try:
                with transaction.atomic():
                    # Create all impressions
                    cls.objects.bulk_create(impressions_to_create, batch_size=100)

                    # 🚀 BULK UPDATE COUNTERS USING QUERYSET (NOT INDIVIDUAL OBJECTS)
                    # This updates the database directly without creating F()
                    # expressions on objects
                    if object_ids_to_update:
                        # Get the model class from the first object
                        model_class = objects_list[0].__class__
                        model_class.objects.filter(id__in=object_ids_to_update).update(
                            impressions_count=F("impressions_count") + 1
                        )

            except Exception as e:
                # Log error and reset stats
                print(f"Failed to bulk create impressions: {e}")
                stats["impressions_recorded"] = 0
                stats["impressions_skipped"] = stats["total_objects"]

        return stats

    @classmethod
    def _extract_profile_id(cls, request):
        """Extract profile ID from request.auth - only public profiles"""
        if not hasattr(request, "auth") or request.auth is None:
            return None

        # Handle public profile object directly (from PublicJWTAuth or
        # OptionalPublicJWTAuth)
        if hasattr(request.auth, "id"):
            return request.auth.id

        return None

    @classmethod
    def _should_record_impression(cls, obj, profile_id, ip_address, session_key):
        """Determine if we should record this impression"""
        now = timezone.now()
        content_type = ContentType.objects.get_for_model(obj)

        # Rule 1: Authenticated users (public profile) - max 1 impression per day
        if profile_id:
            today = now.date()
            return not cls.objects.filter(
                content_type=content_type,
                object_id=obj.pk,
                profile_id=profile_id,
                created_at__date=today,
            ).exists()

        # Rule 2: Anonymous/unauthenticated users - max 1 per session+IP combo per hour
        one_hour_ago = now - timedelta(hours=1)
        return not cls.objects.filter(
            content_type=content_type,
            object_id=obj.pk,
            profile_id__isnull=True,
            ip_address=ip_address,
            session_key=session_key,
            created_at__gte=one_hour_ago,
        ).exists()

    @classmethod
    def _get_client_ip(cls, request):
        """Extract client IP from request"""
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0].strip()
        else:
            ip = request.META.get("REMOTE_ADDR")
        return ip

    @classmethod
    def get_analytics_for_object(cls, obj, days=30):
        """Get impression analytics for an object"""
        since = timezone.now() - timedelta(days=days)
        content_type = ContentType.objects.get_for_model(obj)

        impressions = cls.objects.filter(
            content_type=content_type, object_id=obj.pk, created_at__gte=since
        )

        # Calculate unique profiles (authenticated users)
        unique_profiles = (
            impressions.filter(profile_id__isnull=False)
            .values("profile_id")
            .distinct()
            .count()
        )

        return {
            "total_impressions": impressions.count(),
            "unique_profiles": unique_profiles,
            "unique_ips": impressions.values("ip_address").distinct().count(),
            "anonymous_impressions": impressions.filter(
                profile_id__isnull=True
            ).count(),
            "authenticated_impressions": impressions.filter(
                profile_id__isnull=False
            ).count(),
            "daily_breakdown": cls._get_daily_breakdown(impressions, days),
        }

    @classmethod
    def _get_daily_breakdown(cls, impressions_qs, days):
        """Get daily impression breakdown"""
        from django.db.models import Count
        from django.db.models.functions import TruncDate

        daily_data = (
            impressions_qs.annotate(date=TruncDate("created_at"))
            .values("date")
            .annotate(count=Count("id"))
            .order_by("date")
        )

        return list(daily_data)


# Utility function for list impression tracking
def record_list_impressions(request, objects_list):
    """
    Convenience function to record impressions for a list of objects.
    Can be used in any view that displays multiple objects.

    Usage:
        # In your list view
        record_list_impressions(request, page_obj.object_list)
    """
    if objects_list:
        # Use the first object's class to call the bulk recording method
        first_object = objects_list[0]
        if hasattr(first_object, "record_bulk_impressions"):
            return first_object.__class__.record_bulk_impressions(objects_list, request)
        else:
            # Fallback: record individually (less efficient)
            stats = {
                "total_objects": len(objects_list),
                "impressions_recorded": 0,
                "impressions_skipped": 0,
            }
            for obj in objects_list:
                if hasattr(obj, "record_impression"):
                    recorded = obj.record_impression(request)
                    if recorded:
                        stats["impressions_recorded"] += 1
                    else:
                        stats["impressions_skipped"] += 1
            return stats

    return {
        "total_objects": 0,
        "impressions_recorded": 0,
        "impressions_skipped": 0,
    }
