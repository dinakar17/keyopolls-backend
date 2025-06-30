"""
Notification utilities for easy integration across the poll application.

This module provides simple functions that automatically handle both synchronous
and asynchronous notification delivery based on your application's configuration.

Usage Examples:
    # Basic usage (async by default)
    from keyopolls.notifications.utils import notify_poll_comment
    notify_poll_comment(poll, comment, actor)

    # Force synchronous execution
    notify_poll_comment(poll, comment, actor, use_async=False)

    # Disable push notifications
    notify_poll_comment(poll, comment, actor, send_push=False)
"""

from django.conf import settings

from keyopolls.notifications.models import NotificationType
from keyopolls.notifications.services import AsyncNotificationService

# Global setting to enable/disable async notifications
USE_ASYNC_NOTIFICATIONS = getattr(settings, "USE_ASYNC_NOTIFICATIONS", True)


# === POLL OWNER NOTIFICATIONS ===


def notify_poll_comment(poll, comment, actor, send_push=True, use_async=None):
    """
    Notify poll owner when someone comments on their poll.

    Args:
        poll: The poll that was commented on
        comment: The new comment
        actor: The user who made the comment
        send_push: Whether to send push notification
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, Notification object if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    return AsyncNotificationService.notify_poll_comment(
        poll, comment, actor, send_push, use_async
    )


def notify_poll_vote(poll, voter, option, send_push=True, use_async=None):
    """
    Notify poll owner when someone votes on their poll.

    Args:
        poll: The poll that was voted on
        voter: The user who voted
        option: The poll option that was selected
        send_push: Whether to send push notification
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, Notification object if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    return AsyncNotificationService.notify_poll_vote(
        poll, voter, option, send_push, use_async
    )


def notify_poll_milestone(poll, milestone_type, count, send_push=True, use_async=None):
    """
    Notify poll owner when their poll reaches a milestone.

    Args:
        poll: The poll that reached the milestone
        milestone_type: Type of milestone (votes, likes, shares, etc.)
        count: The milestone count reached
        send_push: Whether to send push notification
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, Notification object if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    return AsyncNotificationService.notify_poll_milestone(
        poll, milestone_type, count, send_push, use_async
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
        milestone_type: Type of milestone (usually likes or replies)
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
    Notify user when they are mentioned in a poll or comment.

    Args:
        mentioned_user: The user who was mentioned
        actor: The user who made the mention
        target: The poll or comment containing the mention
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


# === COMMUNITY NOTIFICATIONS ===


def notify_community_new_poll(community, poll, send_push=False, use_async=None):
    """
    Notify community members when a new poll is created.

    Args:
        community: The community where the poll was created
        poll: The new poll
        send_push: Whether to send push notifications (default False for feeds)
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, list of Notification objects if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    return AsyncNotificationService.notify_community_new_poll(
        community, poll, send_push, use_async
    )


def notify_community_invite(
    community, inviter, invitee, send_push=True, use_async=None
):
    """
    Notify user when they are invited to join a community.

    Args:
        community: The community they were invited to
        inviter: The user who sent the invitation
        invitee: The user who was invited
        send_push: Whether to send push notification
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, Notification object if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    return AsyncNotificationService.notify_community_invite(
        community, inviter, invitee, send_push, use_async
    )


# === FOLLOW-BASED NOTIFICATIONS ===


def notify_followed_user_poll(poll, send_push=False, use_async=None):
    """
    Notify all followers when someone they follow creates a new poll.

    Args:
        poll: The new poll
        send_push: Whether to send push notifications (default False for feeds)
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, list of Notification objects if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    return AsyncNotificationService.notify_followed_user_poll(
        poll, send_push, use_async
    )


def notify_followed_poll_comment(poll, comment, actor, send_push=False, use_async=None):
    """
    Notify users who follow a poll when someone comments on it.

    Args:
        poll: The poll that was commented on
        comment: The new comment
        actor: The user who made the comment
        send_push: Whether to send push notifications (default False for feeds)
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, list of Notification objects if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    return AsyncNotificationService.notify_followed_poll_comment(
        poll, comment, actor, send_push, use_async
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


def auto_follow_poll(user, poll, interaction_type="comment", use_async=None):
    """
    Automatically follow a poll when user interacts with it.

    Args:
        user: The user who interacted with the poll
        poll: The poll that was interacted with
        interaction_type: Type of interaction (comment, vote, etc.)
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, PollFollow object if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    return AsyncNotificationService.auto_follow_poll(
        user, poll, interaction_type, use_async
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


def unfollow_poll(user, poll):
    """
    Unfollow a poll (always synchronous).

    Args:
        user: The user who wants to unfollow
        poll: The poll to unfollow

    Returns:
        bool: True if unfollowed successfully, False if not following
    """
    return AsyncNotificationService.unfollow_poll(user, poll)


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


# === MILESTONE UTILITIES ===


def notify_replies_milestone(target, count, send_push=True, use_async=None):
    """
    Notify target owner (poll or comment) when they reach a replies milestone.

    Args:
        target: The poll or comment that reached the replies milestone
        count: The replies count reached
        send_push: Whether to send push notification
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, Notification object if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    # Determine if it's a poll or comment milestone
    from keyopolls.polls.models import Poll

    if isinstance(target, Poll):
        return AsyncNotificationService.notify_poll_milestone(
            target, NotificationType.REPLIES_MILESTONE, count, send_push, use_async
        )
    else:
        # It's a comment
        return AsyncNotificationService.notify_comment_milestone(
            target, NotificationType.REPLIES_MILESTONE, count, send_push, use_async
        )


def notify_vote_milestone(poll, count, send_push=True, use_async=None):
    """
    Notify poll owner when their poll reaches a vote milestone.

    Args:
        poll: The poll that reached the vote milestone
        count: The vote count reached
        send_push: Whether to send push notification
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, Notification object if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    return AsyncNotificationService.notify_poll_milestone(
        poll, NotificationType.VOTE_MILESTONE, count, send_push, use_async
    )


def notify_view_milestone(poll, count, send_push=True, use_async=None):
    """
    Notify poll owner when their poll reaches a view milestone.

    Args:
        poll: The poll that reached the view milestone
        count: The view count reached
        send_push: Whether to send push notification
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, Notification object if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    return AsyncNotificationService.notify_poll_milestone(
        poll, NotificationType.VIEW_MILESTONE, count, send_push, use_async
    )


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
                'notification_type': 'poll_comment',
                'title': 'New Comment',
                'message': 'Someone commented on your poll',
                'actor': commenter,
                'target': poll
            },
            # ... more notifications
        ]
        send_notification_batch(notifications_data)
    """
    from keyopolls.notifications.tasks import batch_send_notifications_task

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
    from keyopolls.notifications.tasks import cleanup_old_notifications_task

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
    from keyopolls.notifications.models import NotificationPreference

    preference, created = NotificationPreference.objects.update_or_create(
        profile=user,
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
    from keyopolls.notifications.models import NotificationPreference

    queryset = NotificationPreference.objects.filter(profile=user)

    if notification_type:
        queryset = queryset.filter(notification_type=notification_type)

    return queryset


# === COMMUNITY UTILITIES ===


def notify_community_role_change(
    community, member, new_role, changed_by, send_push=True, use_async=None
):
    """
    Notify user when their role in a community changes.

    Args:
        community: The community where the role changed
        member: The user whose role changed
        new_role: The new role assigned
        changed_by: The user who changed the role
        send_push: Whether to send push notification
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, Notification object if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    from keyopolls.notifications.utils import URLBuilder

    click_url = URLBuilder.build_community_url(community.id)
    deep_link_data = URLBuilder.build_deep_link_data(
        "community", {"community_id": community.id}
    )

    return AsyncNotificationService.send_notification(
        recipient=member,
        notification_type=NotificationType.COMMUNITY_ROLE_CHANGE,
        title="Role Updated",
        message=f"Your role in {community.name} has been changed to {new_role}",
        actor=changed_by,
        target=community,
        click_url=click_url,
        deep_link_data=deep_link_data,
        extra_data={"new_role": new_role, "community_name": community.name},
        # priority=NotificationPriority.HIGH,
        send_push=send_push,
        use_async=use_async,
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

    from keyopolls.notifications.models import Notification

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


def test_notification_delivery(user, notification_type="system"):
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


# === POLL-SPECIFIC UTILITIES ===


def notify_poll_closed(poll, send_push=True, use_async=None):
    """
    Notify poll followers when a poll is closed and results are available.

    Args:
        poll: The poll that was closed
        send_push: Whether to send push notification
        use_async: Override global async setting (None uses global setting)

    Returns:
        Celery task result if async, list of Notification objects if sync
    """
    if use_async is None:
        use_async = USE_ASYNC_NOTIFICATIONS

    from keyopolls.notifications.models import PollFollow
    from keyopolls.notifications.services import URLBuilder

    # Get all poll followers
    followers = PollFollow.objects.filter(poll=poll, is_active=True).select_related(
        "follower"
    )

    if not followers.exists():
        return []

    notifications_sent = []
    click_url = URLBuilder.build_poll_url(poll.id)
    deep_link_data = URLBuilder.build_deep_link_data(
        "poll", {"poll_id": poll.id, "view": "results"}
    )

    for poll_follow in followers:
        follower = poll_follow.follower

        # Don't notify the poll owner
        if follower.id == poll.profile.id:
            continue

        notification = AsyncNotificationService.send_notification(
            recipient=follower,
            notification_type=NotificationType.SYSTEM,
            title="Poll Results Available",
            message=f"Results are now available for: {poll.title}",
            target=poll,
            click_url=click_url,
            deep_link_data=deep_link_data,
            send_push=send_push,
            use_async=use_async,
        )

        notifications_sent.append(notification)

    return notifications_sent


def get_user_poll_activity_summary(user, days=7):
    """
    Get a summary of poll-related notifications for a user.

    Args:
        user: The user to get activity for
        days: Number of days to look back

    Returns:
        dict: Summary of poll activity
    """
    from datetime import timedelta

    from django.utils import timezone

    from keyopolls.notifications.models import Notification

    since = timezone.now() - timedelta(days=days)

    notifications = Notification.objects.filter(recipient=user, created_at__gte=since)

    summary = {
        "poll_comments": notifications.filter(
            notification_type=NotificationType.POLL_COMMENT
        ).count(),
        "poll_votes": notifications.filter(
            notification_type=NotificationType.POLL_VOTE
        ).count(),
        "comment_replies": notifications.filter(
            notification_type=NotificationType.REPLY
        ).count(),
        "new_followers": notifications.filter(
            notification_type=NotificationType.FOLLOW
        ).count(),
        "mentions": notifications.filter(
            notification_type=NotificationType.MENTION
        ).count(),
        "milestones": notifications.filter(
            notification_type__in=[
                NotificationType.VOTE_MILESTONE,
                NotificationType.LIKE_MILESTONE,
                NotificationType.FOLLOWER_MILESTONE,
                NotificationType.REPLIES_MILESTONE,
            ]
        ).count(),
        "community_notifications": notifications.filter(
            notification_type__in=[
                NotificationType.COMMUNITY_NEW_POLL,
                NotificationType.COMMUNITY_INVITE,
                NotificationType.COMMUNITY_ROLE_CHANGE,
            ]
        ).count(),
        "total_notifications": notifications.count(),
        "unread_notifications": notifications.filter(is_read=False).count(),
    }

    return summary
