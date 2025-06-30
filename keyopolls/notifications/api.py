from datetime import datetime, timedelta
from typing import Optional, Tuple

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Q
from django.http import HttpRequest
from django.utils import timezone
from ninja import Query, Router
from shared.schemas import Message

from keyopolls.notifications.models import (
    Notification,
    NotificationPriority,
    NotificationType,
)
from keyopolls.notifications.schemas import (
    NotificationActionResponse,
    NotificationSchema,
    NotificationsListResponse,
    NotificationSummaryResponse,
)
from keyopolls.profile.middleware import OptionalPseudonymousJWTAuth
from keyopolls.profile.models import PseudonymousProfile
from keyopolls.utils import get_author_info

router = Router(tags=["Notifications"])


# Helper Functions
def get_actor_info(notification: Notification) -> Optional[dict]:
    """Extract actor information from notification using get_author_info"""
    if not notification.actor:
        return None

    actor = notification.actor

    # For PseudonymousProfile
    if isinstance(actor, PseudonymousProfile):
        return get_author_info(
            profile=actor,
        )

    # Fallback for unknown profile types
    return {
        "id": actor.id if hasattr(actor, "id") else None,
        "display_name": str(actor),
        "username": getattr(actor, "username", None),
        "profile_picture": None,
        "followers": 0,
        "following": 0,
        "is_verified": False,
    }


def get_target_info(notification: Notification) -> Optional[dict]:
    """Extract target information from notification"""
    if not notification.target:
        return None

    target = notification.target
    target_type = notification.target_content_type.model

    # Handle different target types
    if target_type == "poll":
        # Get poll author info
        poll_author_info = None
        if hasattr(target, "profile") and target.profile:
            poll_author_info = get_author_info(
                profile=target.profile, anonymous_identifier=None
            )

        return {
            "type": "poll",
            "id": target.id,
            "title": target.title,
            "description": (
                target.description[:100] + "..."
                if target.description and len(target.description) > 100
                else target.description or ""
            ),
            "poll_type": getattr(target, "poll_type", "unknown"),
            "total_votes": getattr(target, "total_votes", 0),
            "author": (
                poll_author_info.get("display_name", "Unknown")
                if poll_author_info
                else "Unknown"
            ),
            "author_info": poll_author_info,
        }

    elif target_type == "genericcomment":
        # Get comment author info
        comment_author_info = None
        if hasattr(target, "profile") and target.profile:
            comment_author_info = get_author_info(
                profile=target.profile,
            )

        # Get poll info if comment belongs to a poll
        poll_info = None
        if hasattr(target, "content_object") and target.content_object:
            content_obj = target.content_object
            if hasattr(content_obj, "id") and hasattr(content_obj, "title"):
                poll_info = {
                    "id": content_obj.id,
                    "title": content_obj.title,
                    "poll_type": getattr(content_obj, "poll_type", "unknown"),
                }

        return {
            "type": "comment",
            "id": target.id,
            "content": (
                target.content[:100] + "..."
                if len(target.content) > 100
                else target.content
            ),
            "depth": getattr(target, "depth", 0),
            "author": (
                comment_author_info.get("display_name", "Unknown")
                if comment_author_info
                else "Unknown"
            ),
            "author_info": comment_author_info,
            "poll_info": poll_info,
        }

    elif target_type == "pseudonymousprofile":
        # For profile targets, use get_author_info directly
        profile_info = get_author_info(profile=target, anonymous_identifier=None)

        return {
            "type": "profile",
            "id": target.id,
            "username": target.username,
            "display_name": target.display_name,
            "total_aura": target.total_aura,
            "profile_info": profile_info,
        }

    elif target_type == "community":
        # For community targets
        return {
            "type": "community",
            "id": target.id,
            "name": getattr(target, "name", "Unknown Community"),
            "member_count": getattr(target, "member_count", 0),
            "community_type": getattr(target, "community_type", "public"),
        }

    # Fallback for unknown target types
    return {
        "type": target_type,
        "id": target.id if hasattr(target, "id") else None,
        "title": str(target),
    }


def format_notification(notification: Notification) -> NotificationSchema:
    """Format notification for API response"""
    return NotificationSchema(
        id=notification.id,
        notification_type=notification.notification_type,
        title=notification.title,
        message=notification.message,
        priority=notification.priority,
        click_url=notification.click_url,
        deep_link_data=notification.deep_link_data,
        is_read=notification.is_read,
        is_clicked=notification.is_clicked,
        actor_info=get_actor_info(notification),
        target_info=get_target_info(notification),
        extra_data=notification.extra_data,
        created_at=notification.created_at.isoformat(),
        read_at=notification.read_at.isoformat() if notification.read_at else None,
        clicked_at=(
            notification.clicked_at.isoformat() if notification.clicked_at else None
        ),
        push_sent=notification.push_sent,
        email_sent=notification.email_sent,
    )


# API Endpoints
@router.get(
    "/notifications",
    response={200: NotificationsListResponse, 400: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def get_notifications(
    request: HttpRequest,
    # Pagination
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    # Filters
    notification_type: Optional[str] = Query(
        None, description="Filter by notification type"
    ),
    priority: Optional[str] = Query(
        None, description="Filter by priority (low, normal, high, urgent)"
    ),
    is_read: Optional[bool] = Query(None, description="Filter by read status"),
    is_clicked: Optional[bool] = Query(None, description="Filter by clicked status"),
    # Actor filters
    actor_id: Optional[int] = Query(None, description="Filter by specific actor ID"),
    # Target filters
    target_type: Optional[str] = Query(
        None, description="Filter by target type (poll, comment, profile, community)"
    ),
    target_id: Optional[int] = Query(None, description="Filter by specific target ID"),
    # Date filters
    date_from: Optional[str] = Query(
        None, description="Filter from date (ISO format: 2024-01-01)"
    ),
    date_to: Optional[str] = Query(
        None, description="Filter to date (ISO format: 2024-01-31)"
    ),
    days_ago: Optional[int] = Query(
        None, description="Filter by days ago (e.g., 7 for last week)"
    ),
    # Content filters
    search: Optional[str] = Query(None, description="Search in title and message"),
    # Special filters
    unread_only: bool = Query(False, description="Show only unread notifications"),
    recent_only: bool = Query(
        False, description="Show only recent notifications (last 24h)"
    ),
    exclude_expired: bool = Query(True, description="Exclude expired notifications"),
    # Sorting
    sort_by: str = Query(
        "created_at", description="Sort by: created_at, read_at, priority"
    ),
    sort_order: str = Query("desc", description="Sort order: asc or desc"),
    # Response options
    include_summary: bool = Query(True, description="Include summary statistics"),
) -> Tuple[int, NotificationsListResponse]:
    """
    Get notifications for authenticated user with comprehensive filtering options.
    """

    # Get authenticated profile
    profile = request.auth

    if not profile:
        return 400, {"message": "Authentication required"}

    # Start with base queryset for user's notifications
    queryset = Notification.objects.filter(recipient=profile).select_related(
        "actor", "target_content_type"
    )

    # Applied filters tracking
    applied_filters = {}

    # Apply filters
    if notification_type:
        if notification_type in [choice[0] for choice in NotificationType.choices]:
            queryset = queryset.filter(notification_type=notification_type)
            applied_filters["notification_type"] = notification_type
        else:
            return 400, {"message": f"Invalid notification_type: {notification_type}"}

    if priority:
        if priority in [choice[0] for choice in NotificationPriority.choices]:
            queryset = queryset.filter(priority=priority)
            applied_filters["priority"] = priority
        else:
            return 400, {"message": f"Invalid priority: {priority}"}

    if is_read is not None:
        queryset = queryset.filter(is_read=is_read)
        applied_filters["is_read"] = is_read

    if is_clicked is not None:
        queryset = queryset.filter(is_clicked=is_clicked)
        applied_filters["is_clicked"] = is_clicked

    # Actor filters
    if actor_id:
        queryset = queryset.filter(actor_id=actor_id)
        applied_filters["actor_id"] = actor_id

    # Target filters
    if target_type:
        # Map target type to content type
        target_model_map = {
            "poll": "poll",
            "comment": "genericcomment",
            "profile": "pseudonymousprofile",
            "community": "community",
        }

        if target_type in target_model_map:
            try:
                ct = ContentType.objects.get(model=target_model_map[target_type])
                queryset = queryset.filter(target_content_type=ct)
                applied_filters["target_type"] = target_type
            except ContentType.DoesNotExist:
                return 400, {"message": f"Invalid target_type: {target_type}"}
        else:
            return 400, {"message": f"Invalid target_type: {target_type}"}

    if target_id:
        queryset = queryset.filter(target_object_id=target_id)
        applied_filters["target_id"] = target_id

    # Date filters
    if days_ago:
        date_threshold = timezone.now() - timedelta(days=days_ago)
        queryset = queryset.filter(created_at__gte=date_threshold)
        applied_filters["days_ago"] = days_ago

    if date_from:
        try:
            from_date = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
            queryset = queryset.filter(created_at__gte=from_date)
            applied_filters["date_from"] = date_from
        except ValueError:
            return 400, {
                "message": "Invalid date_from format. Use ISO format: 2024-01-01"
            }

    if date_to:
        try:
            to_date = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
            queryset = queryset.filter(created_at__lte=to_date)
            applied_filters["date_to"] = date_to
        except ValueError:
            return 400, {
                "message": "Invalid date_to format. Use ISO format: 2024-01-31"
            }

    # Content search
    if search:
        search_query = Q(title__icontains=search) | Q(message__icontains=search)
        queryset = queryset.filter(search_query)
        applied_filters["search"] = search

    # Special filters
    if unread_only:
        queryset = queryset.filter(is_read=False)
        applied_filters["unread_only"] = True

    if recent_only:
        recent_threshold = timezone.now() - timedelta(hours=24)
        queryset = queryset.filter(created_at__gte=recent_threshold)
        applied_filters["recent_only"] = True

    if exclude_expired:
        now = timezone.now()
        queryset = queryset.filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        applied_filters["exclude_expired"] = True

    # Sorting
    valid_sort_fields = {
        "created_at": "created_at",
        "read_at": "read_at",
        "priority": "priority",
    }

    sort_field = valid_sort_fields.get(sort_by, "created_at")
    if sort_order == "asc":
        order_by = sort_field
    else:
        order_by = f"-{sort_field}"

    queryset = queryset.order_by(order_by)
    applied_filters["sort_by"] = sort_by
    applied_filters["sort_order"] = sort_order

    # Calculate summary statistics (before pagination)
    summary = {}
    if include_summary:
        total_count = queryset.count()
        unread_count = queryset.filter(is_read=False).count()

        # Unread count by type
        unread_by_type = {}
        if unread_count > 0:
            unread_types = (
                queryset.filter(is_read=False)
                .values("notification_type")
                .annotate(count=Count("notification_type"))
            )
            unread_by_type = {
                item["notification_type"]: item["count"] for item in unread_types
            }

        # Recent count (last 24 hours)
        recent_threshold = timezone.now() - timedelta(hours=24)
        recent_count = queryset.filter(created_at__gte=recent_threshold).count()

        summary = {
            "total_count": total_count,
            "unread_count": unread_count,
            "unread_by_type": unread_by_type,
            "recent_count": recent_count,
        }

    # Apply pagination
    total_count = queryset.count()
    offset = (page - 1) * page_size
    notifications_page = queryset[offset : offset + page_size]

    # Format notifications
    notifications_data = [format_notification(notif) for notif in notifications_page]

    # Pagination info
    total_pages = (total_count + page_size - 1) // page_size
    pagination = {
        "current_page": page,
        "total_pages": total_pages,
        "total_count": total_count,
        "page_size": page_size,
        "has_next": page < total_pages,
        "has_previous": page > 1,
    }

    response = NotificationsListResponse(
        notifications=notifications_data,
        pagination=pagination,
        summary=summary,
        applied_filters=applied_filters,
    )

    return 200, response


@router.patch(
    "/notifications/{notification_id}/read",
    response={200: NotificationActionResponse, 400: Message, 404: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def mark_notification_read(
    request: HttpRequest,
    notification_id: int,
) -> Tuple[int, NotificationActionResponse]:
    """Mark a specific notification as read"""

    profile = request.auth

    if not profile:
        return 400, {"message": "Authentication required"}

    try:
        notification = Notification.objects.filter(
            id=notification_id, recipient=profile
        ).first()

        if not notification:
            return 404, {"message": "Notification not found"}

        notification.mark_as_read()

        return 200, NotificationActionResponse(
            success=True, message="Notification marked as read"
        )

    except Exception as e:
        return 400, {"message": f"Error marking notification as read: {str(e)}"}


@router.patch(
    "/notifications/{notification_id}/clicked",
    response={200: NotificationActionResponse, 400: Message, 404: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def mark_notification_clicked(
    request: HttpRequest,
    notification_id: int,
) -> Tuple[int, NotificationActionResponse]:
    """Mark a specific notification as clicked"""

    profile = request.auth

    if not profile:
        return 400, {"message": "Authentication required"}

    try:
        notification = Notification.objects.filter(
            id=notification_id, recipient=profile
        ).first()

        if not notification:
            return 404, {"message": "Notification not found"}

        notification.mark_as_clicked()

        return 200, NotificationActionResponse(
            success=True, message="Notification marked as clicked"
        )

    except Exception as e:
        return 400, {"message": f"Error marking notification as clicked: {str(e)}"}


@router.patch(
    "/notifications/read-all",
    response={200: NotificationActionResponse, 400: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def mark_all_notifications_read(
    request: HttpRequest,
    notification_type: Optional[str] = Query(
        None, description="Mark only specific type as read"
    ),
) -> Tuple[int, NotificationActionResponse]:
    """Mark all notifications as read for the authenticated user"""

    profile = request.auth

    if not profile:
        return 400, {"message": "Authentication required"}

    # Get unread notifications
    queryset = Notification.objects.filter(recipient=profile, is_read=False)

    # Apply type filter if specified
    if notification_type:
        queryset = queryset.filter(notification_type=notification_type)

    # Mark all as read
    updated_count = queryset.update(is_read=True, read_at=timezone.now())

    message = f"Marked {updated_count} notification(s) as read"
    if notification_type:
        message += f" for type '{notification_type}'"

    return 200, NotificationActionResponse(
        success=True, message=message, updated_count=updated_count
    )


@router.delete(
    "/notifications/{notification_id}",
    response={200: NotificationActionResponse, 400: Message, 404: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def delete_notification(
    request: HttpRequest,
    notification_id: int,
) -> Tuple[int, NotificationActionResponse]:
    """Delete a specific notification"""

    profile = request.auth

    if not profile:
        return 400, {"message": "Authentication required"}

    try:
        notification = Notification.objects.filter(
            id=notification_id, recipient=profile
        ).first()

        if not notification:
            return 404, {"message": "Notification not found"}

        notification.delete()

        return 200, NotificationActionResponse(
            success=True, message="Notification deleted successfully"
        )

    except Exception as e:
        return 400, {"message": f"Error deleting notification: {str(e)}"}


@router.delete(
    "/notifications/clear-all",
    response={200: NotificationActionResponse, 400: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def clear_all_notifications(
    request: HttpRequest,
    notification_type: Optional[str] = Query(
        None, description="Clear only specific type"
    ),
    read_only: bool = Query(False, description="Clear only read notifications"),
) -> Tuple[int, NotificationActionResponse]:
    """Clear all notifications for the authenticated user"""

    profile = request.auth

    if not profile:
        return 400, {"message": "Authentication required"}

    try:
        # Start with user's notifications
        queryset = Notification.objects.filter(recipient=profile)

        # Apply filters
        if notification_type:
            queryset = queryset.filter(notification_type=notification_type)

        if read_only:
            queryset = queryset.filter(is_read=True)

        # Delete notifications
        deleted_count, _ = queryset.delete()

        message = f"Cleared {deleted_count} notification(s)"
        if notification_type:
            message += f" of type '{notification_type}'"
        if read_only:
            message += " (read only)"

        return 200, NotificationActionResponse(
            success=True, message=message, updated_count=deleted_count
        )

    except Exception as e:
        return 400, {"message": f"Error clearing notifications: {str(e)}"}


@router.get(
    "/notifications/summary",
    response={200: NotificationSummaryResponse, 400: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def get_notifications_summary(
    request: HttpRequest,
) -> Tuple[int, NotificationSummaryResponse]:
    """Get summary statistics for user's notifications"""

    profile = request.auth

    if not profile:
        return 400, {"message": "Authentication required"}

    queryset = Notification.objects.filter(recipient=profile)

    # Calculate various statistics
    total_count = queryset.count()
    unread_count = queryset.filter(is_read=False).count()

    # Recent notifications (last 24 hours)
    recent_threshold = timezone.now() - timedelta(hours=24)
    recent_count = queryset.filter(created_at__gte=recent_threshold).count()
    recent_unread_count = queryset.filter(
        created_at__gte=recent_threshold, is_read=False
    ).count()

    # Unread by type
    unread_by_type = {}
    if unread_count > 0:
        unread_types = (
            queryset.filter(is_read=False)
            .values("notification_type")
            .annotate(count=Count("notification_type"))
        )
        unread_by_type = {
            item["notification_type"]: item["count"] for item in unread_types
        }

    # Unread by priority
    unread_by_priority = {}
    if unread_count > 0:
        unread_priorities = (
            queryset.filter(is_read=False)
            .values("priority")
            .annotate(count=Count("priority"))
        )
        unread_by_priority = {
            item["priority"]: item["count"] for item in unread_priorities
        }

    summary = NotificationSummaryResponse(
        total_count=total_count,
        unread_count=unread_count,
        recent_count=recent_count,
        recent_unread_count=recent_unread_count,
        unread_by_type=unread_by_type,
        unread_by_priority=unread_by_priority,
        read_percentage=(
            round((total_count - unread_count) / total_count * 100, 1)
            if total_count > 0
            else 0
        ),
    )

    return 200, summary


@router.get(
    "/notifications/unread-count",
    response={200: dict, 400: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def get_unread_count(
    request: HttpRequest,
) -> Tuple[int, dict]:
    """Get quick unread count for badges/indicators"""

    profile = request.auth

    if not profile:
        return 400, {"message": "Authentication required"}

    unread_count = Notification.objects.filter(recipient=profile, is_read=False).count()

    # Get unread count by type for detailed badges
    unread_by_type = {}
    if unread_count > 0:
        unread_types = (
            Notification.objects.filter(recipient=profile, is_read=False)
            .values("notification_type")
            .annotate(count=Count("notification_type"))
        )
        unread_by_type = {
            item["notification_type"]: item["count"] for item in unread_types
        }

    return 200, {
        "unread_count": unread_count,
        "unread_by_type": unread_by_type,
        "has_unread": unread_count > 0,
    }
