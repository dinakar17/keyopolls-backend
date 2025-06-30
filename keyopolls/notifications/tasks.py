import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from keyopolls.comments.models import GenericComment
from keyopolls.communities.models import Community
from keyopolls.notifications.models import Notification
from keyopolls.notifications.services import AsyncNotificationService
from keyopolls.polls.models import Poll, PollOption
from keyopolls.profile.models import PseudonymousProfile

logger = logging.getLogger(__name__)


# === CORE NOTIFICATION TASKS ===


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_push_notification_task(self, notification_id):
    """Async task to send push notification"""
    try:
        notification = Notification.objects.get(id=notification_id)
        AsyncNotificationService._send_push_notification(notification)
        return {"success": True, "notification_id": notification_id}
    except Notification.DoesNotExist:
        logger.error(f"Notification {notification_id} does not exist")
        return {"success": False, "error": "Notification not found"}
    except Exception as exc:
        logger.error(f"Push notification task failed for {notification_id}: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=60 * (2**self.request.retries), exc=exc)
        return {"success": False, "error": str(exc)}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_email_notification_task(self, notification_id):
    """Async task to send email notification"""
    try:
        notification = Notification.objects.get(id=notification_id)
        AsyncNotificationService._send_email_notification(notification)
        return {"success": True, "notification_id": notification_id}
    except Notification.DoesNotExist:
        logger.error(f"Notification {notification_id} does not exist")
        return {"success": False, "error": "Notification not found"}
    except Exception as exc:
        logger.error(
            f"Email notification task failed for {notification_id}: {str(exc)}"
        )
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=60 * (2**self.request.retries), exc=exc)
        return {"success": False, "error": str(exc)}


# === POLL OWNER NOTIFICATION TASKS ===


@shared_task(bind=True, max_retries=2)
def notify_poll_comment_task(self, poll_id, comment_id, actor_id, send_push=True):
    """Async task to notify poll owner about new comment"""
    try:
        poll = Poll.objects.get(id=poll_id)
        comment = GenericComment.objects.get(id=comment_id)
        actor = PseudonymousProfile.objects.get(id=actor_id)

        result = AsyncNotificationService.notify_poll_comment(
            poll, comment, actor, send_push, use_async=False
        )
        return {"success": True, "notification_id": result.id if result else None}
    except Exception as exc:
        logger.error(f"Poll comment notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


@shared_task(bind=True, max_retries=2)
def notify_poll_vote_task(self, poll_id, voter_id, option_id, send_push=True):
    """Async task to notify poll owner about new vote"""
    try:
        poll = Poll.objects.get(id=poll_id)
        voter = PseudonymousProfile.objects.get(id=voter_id)
        option = PollOption.objects.get(id=option_id)

        result = AsyncNotificationService.notify_poll_vote(
            poll, voter, option, send_push, use_async=False
        )
        return {"success": True, "notification_id": result.id if result else None}
    except Exception as exc:
        logger.error(f"Poll vote notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


@shared_task(bind=True, max_retries=2)
def notify_poll_milestone_task(self, poll_id, milestone_type, count, send_push=True):
    """Async task to notify poll owner about milestone"""
    try:
        poll = Poll.objects.get(id=poll_id)
        result = AsyncNotificationService.notify_poll_milestone(
            poll, milestone_type, count, send_push, use_async=False
        )
        return {"success": True, "notification_id": result.id if result else None}
    except Exception as exc:
        logger.error(f"Poll milestone notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


# === COMMENT OWNER NOTIFICATION TASKS ===


@shared_task(bind=True, max_retries=2)
def notify_comment_reply_task(self, comment_id, reply_id, actor_id, send_push=True):
    """Async task to notify comment owner about new reply"""
    try:
        comment = GenericComment.objects.get(id=comment_id)
        reply = GenericComment.objects.get(id=reply_id)
        actor = PseudonymousProfile.objects.get(id=actor_id)

        result = AsyncNotificationService.notify_comment_reply(
            comment, reply, actor, send_push, use_async=False
        )
        return {"success": True, "notification_id": result.id if result else None}
    except Exception as exc:
        logger.error(f"Comment reply notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


@shared_task(bind=True, max_retries=2)
def notify_comment_milestone_task(
    self, comment_id, milestone_type, count, send_push=True
):
    """Async task to notify comment owner about milestone"""
    try:
        comment = GenericComment.objects.get(id=comment_id)
        result = AsyncNotificationService.notify_comment_milestone(
            comment, milestone_type, count, send_push, use_async=False
        )
        return {"success": True, "notification_id": result.id if result else None}
    except Exception as exc:
        logger.error(f"Comment milestone notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


# === SOCIAL NOTIFICATION TASKS ===


@shared_task(bind=True, max_retries=2)
def notify_follow_task(self, follower_id, followee_id, send_push=True):
    """Async task to notify user about new follower"""
    try:
        follower = PseudonymousProfile.objects.get(id=follower_id)
        followee = PseudonymousProfile.objects.get(id=followee_id)

        result = AsyncNotificationService.notify_follow(
            follower, followee, send_push, use_async=False
        )
        return {"success": True, "notification_id": result.id if result else None}
    except Exception as exc:
        logger.error(f"Follow notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


@shared_task(bind=True, max_retries=2)
def notify_follower_milestone_task(self, user_id, count, send_push=True):
    """Async task to notify user about follower milestone"""
    try:
        user = PseudonymousProfile.objects.get(id=user_id)

        result = AsyncNotificationService.notify_follower_milestone(
            user, count, send_push, use_async=False
        )
        return {"success": True, "notification_id": result.id if result else None}
    except Exception as exc:
        logger.error(f"Follower milestone notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


@shared_task(bind=True, max_retries=2)
def notify_mention_task(
    self,
    mentioned_user_id,
    actor_id,
    target_id,
    target_type,
    send_push=True,
):
    """Async task to notify user about mention"""
    try:
        mentioned_user = PseudonymousProfile.objects.get(id=mentioned_user_id)
        actor = PseudonymousProfile.objects.get(id=actor_id)

        # Get target (poll or comment)
        if target_type == "poll":
            target = Poll.objects.get(id=target_id)
        elif target_type == "genericcomment":
            target = GenericComment.objects.get(id=target_id)
        else:
            raise ValueError(f"Unsupported target type: {target_type}")

        result = AsyncNotificationService.notify_mention(
            mentioned_user, actor, target, send_push, use_async=False
        )
        return {"success": True, "notification_id": result.id if result else None}
    except Exception as exc:
        logger.error(f"Mention notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


# === COMMUNITY NOTIFICATION TASKS ===


@shared_task(bind=True, max_retries=2)
def notify_community_new_poll_task(self, community_id, poll_id, send_push=False):
    """Async task to notify community members about new poll"""
    try:
        community = Community.objects.get(id=community_id)
        poll = Poll.objects.get(id=poll_id)

        results = AsyncNotificationService.notify_community_new_poll(
            community, poll, send_push, use_async=False
        )
        return {
            "success": True,
            "notifications_sent": len(results),
            "notification_ids": [n.id for n in results if n],
        }
    except Exception as exc:
        logger.error(f"Community new poll notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


@shared_task(bind=True, max_retries=2)
def notify_community_invite_task(
    self, community_id, inviter_id, invitee_id, send_push=True
):
    """Async task to notify user about community invitation"""
    try:
        community = Community.objects.get(id=community_id)
        inviter = PseudonymousProfile.objects.get(id=inviter_id)
        invitee = PseudonymousProfile.objects.get(id=invitee_id)

        result = AsyncNotificationService.notify_community_invite(
            community, inviter, invitee, send_push, use_async=False
        )
        return {"success": True, "notification_id": result.id if result else None}
    except Exception as exc:
        logger.error(f"Community invite notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


# === FOLLOW-BASED NOTIFICATION TASKS ===


@shared_task(bind=True, max_retries=2)
def notify_followed_user_poll_task(self, poll_id, send_push=False):
    """Async task to notify followers about new poll from followed user"""
    try:
        poll = Poll.objects.get(id=poll_id)
        results = AsyncNotificationService.notify_followed_user_poll(
            poll, send_push, use_async=False
        )
        return {
            "success": True,
            "notifications_sent": len(results),
            "notification_ids": [n.id for n in results if n],
        }
    except Exception as exc:
        logger.error(f"Followed user poll notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


@shared_task(bind=True, max_retries=2)
def notify_followed_poll_comment_task(
    self, poll_id, comment_id, actor_id, send_push=False
):
    """Async task to notify poll followers about new comment"""
    try:
        poll = Poll.objects.get(id=poll_id)
        comment = GenericComment.objects.get(id=comment_id)
        actor = PseudonymousProfile.objects.get(id=actor_id)

        results = AsyncNotificationService.notify_followed_poll_comment(
            poll, comment, actor, send_push, use_async=False
        )
        return {
            "success": True,
            "notifications_sent": len(results),
            "notification_ids": [n.id for n in results if n],
        }
    except Exception as exc:
        logger.error(f"Followed poll comment notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


@shared_task(bind=True, max_retries=2)
def notify_followed_comment_reply_task(
    self, comment_id, reply_id, actor_id, send_push=False
):
    """Async task to notify comment followers about new reply"""
    try:
        comment = GenericComment.objects.get(id=comment_id)
        reply = GenericComment.objects.get(id=reply_id)
        actor = PseudonymousProfile.objects.get(id=actor_id)

        results = AsyncNotificationService.notify_followed_comment_reply(
            comment, reply, actor, send_push, use_async=False
        )
        return {
            "success": True,
            "notifications_sent": len(results),
            "notification_ids": [n.id for n in results if n],
        }
    except Exception as exc:
        logger.error(f"Followed comment reply notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


# === AUTO-FOLLOW TASKS ===


@shared_task(bind=True, max_retries=2)
def auto_follow_poll_task(self, user_id, poll_id, interaction_type="comment"):
    """Async task to auto-follow a poll"""
    try:
        user = PseudonymousProfile.objects.get(id=user_id)
        poll = Poll.objects.get(id=poll_id)

        result = AsyncNotificationService.auto_follow_poll(
            user, poll, interaction_type, use_async=False
        )
        return {"success": True, "follow_created": result is not None}
    except Exception as exc:
        logger.error(f"Auto follow poll task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


@shared_task(bind=True, max_retries=2)
def auto_follow_comment_task(self, user_id, comment_id):
    """Async task to auto-follow a comment"""
    try:
        user = PseudonymousProfile.objects.get(id=user_id)
        comment = GenericComment.objects.get(id=comment_id)

        result = AsyncNotificationService.auto_follow_comment(
            user, comment, use_async=False
        )
        return {"success": True, "follow_created": result is not None}
    except Exception as exc:
        logger.error(f"Auto follow comment task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


# === MILESTONE NOTIFICATION TASKS ===


@shared_task(bind=True, max_retries=2)
def notify_replies_milestone_task(self, target_id, target_type, count, send_push=True):
    """Async task to notify target owner about replies milestone"""
    try:
        # Get target (poll or comment)
        if target_type == "poll":
            target = Poll.objects.get(id=target_id)
            result = AsyncNotificationService.notify_poll_milestone(
                target, "replies_milestone", count, send_push, use_async=False
            )
        elif target_type == "genericcomment":
            target = GenericComment.objects.get(id=target_id)
            result = AsyncNotificationService.notify_comment_milestone(
                target, "replies_milestone", count, send_push, use_async=False
            )
        else:
            raise ValueError(f"Unsupported target type: {target_type}")

        return {"success": True, "notification_id": result.id if result else None}
    except Exception as exc:
        logger.error(f"Replies milestone notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


@shared_task(bind=True, max_retries=2)
def notify_vote_milestone_task(self, poll_id, count, send_push=True):
    """Async task to notify poll owner about vote milestone"""
    try:
        poll = Poll.objects.get(id=poll_id)
        result = AsyncNotificationService.notify_poll_milestone(
            poll, "vote_milestone", count, send_push, use_async=False
        )
        return {"success": True, "notification_id": result.id if result else None}
    except Exception as exc:
        logger.error(f"Vote milestone notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


@shared_task(bind=True, max_retries=2)
def notify_like_milestone_task(self, target_id, target_type, count, send_push=True):
    """Async task to notify target owner about like milestone"""
    try:
        # Get target (poll or comment)
        if target_type == "poll":
            target = Poll.objects.get(id=target_id)
            result = AsyncNotificationService.notify_poll_milestone(
                target, "like_milestone", count, send_push, use_async=False
            )
        elif target_type == "genericcomment":
            target = GenericComment.objects.get(id=target_id)
            result = AsyncNotificationService.notify_comment_milestone(
                target, "like_milestone", count, send_push, use_async=False
            )
        else:
            raise ValueError(f"Unsupported target type: {target_type}")

        return {"success": True, "notification_id": result.id if result else None}
    except Exception as exc:
        logger.error(f"Like milestone notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


# === BATCH NOTIFICATION TASKS ===


@shared_task(bind=True, max_retries=2)
def batch_send_notifications_task(
    self, notification_ids, send_push=True, send_email=True
):
    """Async task to send multiple notifications in batch"""
    try:
        notifications = Notification.objects.filter(id__in=notification_ids)
        results = []

        for notification in notifications:
            try:
                if send_push:
                    send_push_notification_task.delay(notification.id)
                if send_email:
                    send_email_notification_task.delay(notification.id)
                results.append({"notification_id": notification.id, "success": True})
            except Exception as e:
                logger.error(
                    f"Failed to queue notification {notification.id}: {str(e)}"
                )
                results.append(
                    {
                        "notification_id": notification.id,
                        "success": False,
                        "error": str(e),
                    }
                )

        return {"success": True, "results": results}
    except Exception as exc:
        logger.error(f"Batch send notifications task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


# === COMMUNITY-SPECIFIC TASKS ===


@shared_task(bind=True, max_retries=2)
def notify_community_role_change_task(
    self, community_id, member_id, old_role, new_role, actor_id, send_push=True
):
    """Async task to notify user about community role change"""
    try:
        community = Community.objects.get(id=community_id)
        member = PseudonymousProfile.objects.get(id=member_id)
        actor = PseudonymousProfile.objects.get(id=actor_id)

        actor_name = AsyncNotificationService._get_actor_name(actor)

        click_url = AsyncNotificationService.URLBuilder.build_community_url(
            community.id
        )
        deep_link_data = AsyncNotificationService.URLBuilder.build_deep_link_data(
            "community", {"community_id": community.id}
        )

        result = AsyncNotificationService.send_notification(
            recipient=member,
            notification_type="community_role_change",
            title="Role Updated",
            message=f"{actor_name} changed your role in {community.name} to {new_role}",
            actor=actor,
            target=community,
            click_url=click_url,
            deep_link_data=deep_link_data,
            extra_data={
                "old_role": old_role,
                "new_role": new_role,
                "community_id": community.id,
                "community_name": community.name,
            },
            send_push=send_push,
            use_async=False,
        )
        return {"success": True, "notification_id": result.id if result else None}
    except Exception as exc:
        logger.error(f"Community role change notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


# === CLEANUP TASKS ===


@shared_task
def cleanup_old_notifications_task(days_old=30):
    """Async task to cleanup old notifications"""
    try:
        cutoff_date = timezone.now() - timedelta(days=days_old)
        deleted_count = Notification.objects.filter(
            created_at__lt=cutoff_date, is_read=True
        ).delete()[0]

        logger.info(f"Cleaned up {deleted_count} old notifications")
        return {"success": True, "deleted_count": deleted_count}
    except Exception as exc:
        logger.error(f"Cleanup notifications task failed: {str(exc)}")
        return {"success": False, "error": str(exc)}


@shared_task
def cleanup_expired_notifications_task():
    """Async task to cleanup expired notifications"""
    try:
        now = timezone.now()
        deleted_count = Notification.objects.filter(expires_at__lt=now).delete()[0]

        logger.info(f"Cleaned up {deleted_count} expired notifications")
        return {"success": True, "deleted_count": deleted_count}
    except Exception as exc:
        logger.error(f"Cleanup expired notifications task failed: {str(exc)}")
        return {"success": False, "error": str(exc)}


# === BULK COMMUNITY NOTIFICATION TASKS ===


@shared_task(bind=True, max_retries=2)
def bulk_notify_community_members_task(
    self, community_id, title, message, notification_type="system", send_push=False
):
    """Async task to send bulk notifications to all community members"""
    try:
        from keyopolls.notifications.fcm_services import FCMService

        community = Community.objects.get(id=community_id)

        result = FCMService.notify_community_members(
            community=community,
            title=title,
            body=message,
            notification_type=notification_type,
            exclude_profile=None,
        )

        return {
            "success": result["success"],
            "message": result["message"],
            "sent": result.get("sent", 0),
            "total": result.get("total", 0),
        }
    except Exception as exc:
        logger.error(f"Bulk community notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}
