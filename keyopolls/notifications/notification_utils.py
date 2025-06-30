"""
Notification utilities for easy integration across the application.

This module provides simple functions that automatically handle both synchronous
and asynchronous notification delivery based on your application's configuration.

Usage Examples:
    # Basic usage (async by default)
    from keyoconnect.connect_notifications.utils import notify_post_comment
    notify_post_comment(post, comment, actor)

    # Force synchronous execution
    notify_post_comment(post, comment, actor, use_async=False)

    # Disable push notifications
    notify_post_comment(post, comment, actor, send_push=False)
"""

from django.conf import settings
from keyoconnect.connect_notifications.models import NotificationType
from keyoconnect.connect_notifications.services import AsyncNotificationService

# Global setting to enable/disable async notifications
USE_ASYNC_NOTIFICATIONS = settings.USE_ASYNC_NOTIFICATIONS


# === POST OWNER NOTIFICATIONS ===


def notify_post_comment(post, comment, actor, send_push=True, use_async=None):
    """
    Notify post owner when someone comments on their post.

    Args:
        post: The post that was commented on
        comment: The new comment
        actor: The user who made the comment
        send_push: Whether to send push notification
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, Notification object if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    return AsyncNotificationService.notify_post_comment(
        post, comment, actor, send_push, use_async
    )


def notify_post_milestone(post, milestone_type, count, send_push=True, use_async=None):
    """
    Notify post owner when their post reaches a milestone.

    Args:
        post: The post that reached the milestone
        milestone_type: Type of milestone (likes, shares, etc.)
        count: The milestone count reached
        send_push: Whether to send push notification
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, Notification object if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    return AsyncNotificationService.notify_post_milestone(
        post, milestone_type, count, send_push, use_async
    )


# === COMMENT OWNER NOTIFICATIONS ===


def notify_comment_reply(comment, reply, actor, send_push=True, use_async=None):
    """
    Notify comment owner when someone replies to their comment.

    Args:
        comment: The comment that was replied to
        reply: The new reply
        actor: The user who made the reply
        send_push: Whether to send push notification
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, Notification object if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    return AsyncNotificationService.notify_comment_reply(
        comment, reply, actor, send_push, use_async
    )


def notify_comment_milestone(
    comment, milestone_type, count, send_push=True, use_async=None
):
    """
    Notify comment owner when their comment reaches a milestone.

    Args:
        comment: The comment that reached the milestone
        milestone_type: Type of milestone (usually likes)
        count: The milestone count reached
        send_push: Whether to send push notification
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, Notification object if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    return AsyncNotificationService.notify_comment_milestone(
        comment, milestone_type, count, send_push, use_async
    )


# === SOCIAL NOTIFICATIONS ===


def notify_follow(follower, followee, send_push=True, use_async=None):
    """
    Notify user when someone follows them.

    Args:
        follower: The user who started following
        followee: The user being followed
        send_push: Whether to send push notification
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, Notification object if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    return AsyncNotificationService.notify_follow(
        follower, followee, send_push, use_async
    )


def notify_follower_milestone(user, count, send_push=True, use_async=None):
    """
    Notify user when they reach a follower milestone.

    Args:
        user: The user who reached the milestone
        count: The follower count reached
        send_push: Whether to send push notification
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, Notification object if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    return AsyncNotificationService.notify_follower_milestone(
        user, count, send_push, use_async
    )


def notify_mention(mentioned_user, actor, target, send_push=True, use_async=None):
    """
    Notify user when they are mentioned in a post or comment.

    Args:
        mentioned_user: The user who was mentioned
        actor: The user who made the mention
        target: The post or comment containing the mention
        send_push: Whether to send push notification
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, Notification object if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    return AsyncNotificationService.notify_mention(
        mentioned_user, actor, target, send_push, use_async
    )


# === FOLLOW-BASED NOTIFICATIONS ===


def notify_followed_user_post(post, send_push=False, use_async=None):
    """
    Notify all followers when someone they follow creates a new post.

    Args:
        post: The new post
        send_push: Whether to send push notifications (default False for feeds)
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, list of Notification objects if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    return AsyncNotificationService.notify_followed_user_post(
        post, send_push, use_async
    )


def notify_followed_post_comment(post, comment, actor, send_push=False, use_async=None):
    """
    Notify users who follow a post when someone comments on it.

    Args:
        post: The post that was commented on
        comment: The new comment
        actor: The user who made the comment
        send_push: Whether to send push notifications (default False for feeds)
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, list of Notification objects if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    return AsyncNotificationService.notify_followed_post_comment(
        post, comment, actor, send_push, use_async
    )


def notify_followed_comment_reply(
    comment, reply, actor, send_push=False, use_async=None
):
    """
    Notify users who follow a comment when someone replies to it.

    Args:
        comment: The comment that was replied to
        reply: The new reply
        actor: The user who made the reply
        send_push: Whether to send push notifications (default False for feeds)
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, list of Notification objects if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    return AsyncNotificationService.notify_followed_comment_reply(
        comment, reply, actor, send_push, use_async
    )


# === AUTO-FOLLOW UTILITIES ===


def auto_follow_post(user, post, interaction_type="comment", use_async=None):
    """
    Automatically follow a post when user interacts with it.

    Args:
        user: The user who interacted with the post
        post: The post that was interacted with
        interaction_type: Type of interaction (comment, like, etc.)
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, PostFollow object if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    return AsyncNotificationService.auto_follow_post(
        user, post, interaction_type, use_async
    )


def auto_follow_comment(user, comment, use_async=None):
    """
    Automatically follow a comment when user replies to it.

    Args:
        user: The user who replied to the comment
        comment: The comment that was replied to
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, CommentFollow object if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    return AsyncNotificationService.auto_follow_comment(user, comment, use_async)


def unfollow_post(user, post):
    """
    Unfollow a post (always synchronous).

    Args:
        user: The user who wants to unfollow
        post: The post to unfollow

    Returns:
        bool: True if unfollowed successfully, False if not following
    """
    return AsyncNotificationService.unfollow_post(user, post)


def unfollow_comment(user, comment):
    """
    Unfollow a comment (always synchronous).

    Args:
        user: The user who wants to unfollow
        comment: The comment to unfollow

    Returns:
        bool: True if unfollowed successfully, False if not following
    """
    return AsyncNotificationService.unfollow_comment(user, comment)


# === BATCH OPERATIONS ===


def send_notification_batch(notifications_data, send_push=True, send_email=True):
    """
    Send multiple notifications in batch using Celery.

    Args:
        notifications_data: List of dicts containing notification parameters
        send_push: Whether to send push notifications
        send_email: Whether to send email notifications

    Returns:
        Celery task result

    Example:
        notifications_data = [
            {
                'recipient': user1,
                'notification_type': 'comment',
                'title': 'New Comment',
                'message': 'Someone commented on your post',
                'actor': commenter,
                'target': post
            },
            # ... more notifications
        ]
        send_notification_batch(notifications_data)
    """
    from keyoconnect.connect_notifications.tasks import batch_send_notifications_task

    # Create notifications first
    notification_ids = []
    for data in notifications_data:
        notification = AsyncNotificationService.send_notification(
            use_async=False,  # Create notification synchronously
            send_push=False,  # Don't send immediately
            send_email=False,  # Don't send immediately
            **data,
        )
        notification_ids.append(notification.id)

    # Send all notifications asynchronously
    return batch_send_notifications_task.delay(notification_ids, send_push, send_email)


# === CLEANUP UTILITIES ===


def cleanup_old_notifications(days_old=30):
    """
    Clean up old read notifications.

    Args:
        days_old: Number of days old to consider for cleanup

    Returns:
        Celery task result
    """
    from keyoconnect.connect_notifications.tasks import cleanup_old_notifications_task

    return cleanup_old_notifications_task.delay(days_old)


# === CONFIGURATION UTILITIES ===


def enable_async_notifications():
    """Enable async notifications globally (runtime setting)."""
    global USE_ASYNC_NOTIFICATIONS
    USE_ASYNC_NOTIFICATIONS = True


def disable_async_notifications():
    """Disable async notifications globally (runtime setting)."""
    global USE_ASYNC_NOTIFICATIONS
    USE_ASYNC_NOTIFICATIONS = False


def is_async_enabled():
    """Check if async notifications are currently enabled."""
    return USE_ASYNC_NOTIFICATIONS


# === NOTIFICATION PREFERENCE UTILITIES ===


def update_notification_preferences(
    user,
    notification_type,
    enabled=True,
    push_enabled=True,
    email_enabled=True,
    custom_thresholds=None,
):
    """
    Update notification preferences for a user.

    Args:
        user: The user to update preferences for
        notification_type: Type of notification
        enabled: Whether notifications are enabled
        push_enabled: Whether push notifications are enabled
        email_enabled: Whether email notifications are enabled
        custom_thresholds: Custom milestone thresholds (for milestone notifications)

    Returns:
        NotificationPreference object
    """
    from django.contrib.contenttypes.models import ContentType
    from keyoconnect.connect_notifications.models import NotificationPreference

    preference, created = NotificationPreference.objects.update_or_create(
        profile_content_type=ContentType.objects.get_for_model(user),
        profile_object_id=user.id,
        notification_type=notification_type,
        defaults={
            "is_enabled": enabled,
            "push_enabled": push_enabled,
            "email_enabled": email_enabled,
            "custom_thresholds": custom_thresholds,
        },
    )

    return preference


def get_notification_preferences(user, notification_type=None):
    """
    Get notification preferences for a user.

    Args:
        user: The user to get preferences for
        notification_type: Specific notification type (None for all)

    Returns:
        QuerySet of NotificationPreference objects
    """
    from django.contrib.contenttypes.models import ContentType
    from keyoconnect.connect_notifications.models import NotificationPreference

    queryset = NotificationPreference.objects.filter(
        profile_content_type=ContentType.objects.get_for_model(user),
        profile_object_id=user.id,
    )

    if notification_type:
        queryset = queryset.filter(notification_type=notification_type)

    return queryset


def notify_replies_milestone(target, count, send_push=True, use_async=None):
    """
    Notify target owner (post or comment) when they reach a replies milestone.

    Args:
        target: The post or comment that reached the replies milestone
        count: The replies count reached
        send_push: Whether to send push notification
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, Notification object if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    # Determine if it's a post or comment milestone
    from keyoconnect.posts.models import Post

    if isinstance(target, Post):
        return AsyncNotificationService.notify_post_milestone(
            target, NotificationType.REPLIES_MILESTONE, count, send_push, use_async
        )
    else:
        # It's a comment
        return AsyncNotificationService.notify_comment_milestone(
            target, NotificationType.REPLIES_MILESTONE, count, send_push, use_async
        )


# === DEBUGGING UTILITIES ===


def get_notification_stats():
    """
    Get statistics about notifications in the system.

    Returns:
        dict: Statistics about notifications
    """
    from datetime import timedelta

    from django.db.models import Count
    from django.utils import timezone
    from keyoconnect.connect_notifications.models import Notification

    now = timezone.now()
    last_24h = now - timedelta(hours=24)
    last_7d = now - timedelta(days=7)

    stats = {
        "total_notifications": Notification.objects.count(),
        "unread_notifications": Notification.objects.filter(is_read=False).count(),
        "notifications_last_24h": Notification.objects.filter(
            created_at__gte=last_24h
        ).count(),
        "notifications_last_7d": Notification.objects.filter(
            created_at__gte=last_7d
        ).count(),
        "push_sent": Notification.objects.filter(push_sent=True).count(),
        "email_sent": Notification.objects.filter(email_sent=True).count(),
        "by_type": dict(
            Notification.objects.values("notification_type")
            .annotate(count=Count("id"))
            .values_list("notification_type", "count")
        ),
        "by_priority": dict(
            Notification.objects.values("priority")
            .annotate(count=Count("id"))
            .values_list("priority", "count")
        ),
    }

    return stats


def test_notification_delivery(user, notification_type="test"):
    """
    Send a test notification to verify delivery is working.

    Args:
        user: User to send test notification to
        notification_type: Type of test notification

    Returns:
        Notification object or Celery task result
    """
    return AsyncNotificationService.send_notification(
        recipient=user,
        notification_type=notification_type,
        title="Test Notification",
        message="This is a test notification to verify delivery is working.",
        send_push=True,
        send_email=True,
        use_async=USE_ASYNC_NOTIFICATIONS,
    )
