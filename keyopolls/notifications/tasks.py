import logging
from datetime import timedelta

from celery import shared_task
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from keyoconnect.comments.models import GenericComment
from keyoconnect.connect_notifications.models import Notification
from keyoconnect.connect_notifications.services import AsyncNotificationService
from keyoconnect.posts.models import Post

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


# === POST OWNER NOTIFICATION TASKS ===


@shared_task(bind=True, max_retries=2)
def notify_post_comment_task(
    self, post_id, comment_id, actor_id, actor_type, send_push=True
):
    """Async task to notify post owner about new comment"""
    try:
        post = Post.objects.get(id=post_id)
        comment = GenericComment.objects.get(id=comment_id)

        # Get actor based on type
        actor_content_type = ContentType.objects.get(model=actor_type)
        actor = actor_content_type.get_object_for_this_type(id=actor_id)

        result = AsyncNotificationService.notify_post_comment(
            post, comment, actor, send_push
        )
        return {"success": True, "notification_id": result.id if result else None}
    except Exception as exc:
        logger.error(f"Post comment notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


@shared_task(bind=True, max_retries=2)
def notify_post_milestone_task(self, post_id, milestone_type, count, send_push=True):
    """Async task to notify post owner about milestone"""
    try:
        post = Post.objects.get(id=post_id)
        result = AsyncNotificationService.notify_post_milestone(
            post, milestone_type, count, send_push
        )
        return {"success": True, "notification_id": result.id if result else None}
    except Exception as exc:
        logger.error(f"Post milestone notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


# === COMMENT OWNER NOTIFICATION TASKS ===


@shared_task(bind=True, max_retries=2)
def notify_comment_reply_task(
    self, comment_id, reply_id, actor_id, actor_type, send_push=True
):
    """Async task to notify comment owner about new reply"""
    try:
        comment = GenericComment.objects.get(id=comment_id)
        reply = GenericComment.objects.get(id=reply_id)

        # Get actor based on type
        actor_content_type = ContentType.objects.get(model=actor_type)
        actor = actor_content_type.get_object_for_this_type(id=actor_id)

        result = AsyncNotificationService.notify_comment_reply(
            comment, reply, actor, send_push
        )
        return {"success": True, "notification_id": result.id if result else None}
    except Exception as exc:
        logger.error(f"GenericComment reply notification task failed: {str(exc)}")
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
            comment, milestone_type, count, send_push
        )
        return {"success": True, "notification_id": result.id if result else None}
    except Exception as exc:
        logger.error(f"GenericComment milestone notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


# === SOCIAL NOTIFICATION TASKS ===


@shared_task(bind=True, max_retries=2)
def notify_follow_task(
    self, follower_id, follower_type, followee_id, followee_type, send_push=True
):
    """Async task to notify user about new follower"""
    try:
        # Get follower and followee based on types
        follower_content_type = ContentType.objects.get(model=follower_type)
        followee_content_type = ContentType.objects.get(model=followee_type)

        follower = follower_content_type.get_object_for_this_type(id=follower_id)
        followee = followee_content_type.get_object_for_this_type(id=followee_id)

        result = AsyncNotificationService.notify_follow(follower, followee, send_push)
        return {"success": True, "notification_id": result.id if result else None}
    except Exception as exc:
        logger.error(f"Follow notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


@shared_task(bind=True, max_retries=2)
def notify_follower_milestone_task(self, user_id, user_type, count, send_push=True):
    """Async task to notify user about follower milestone"""
    try:
        user_content_type = ContentType.objects.get(model=user_type)
        user = user_content_type.get_object_for_this_type(id=user_id)

        result = AsyncNotificationService.notify_follower_milestone(
            user, count, send_push
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
    mentioned_user_type,
    actor_id,
    actor_type,
    target_id,
    target_type,
    send_push=True,
):
    """Async task to notify user about mention"""
    try:
        # Get mentioned user
        mentioned_user_content_type = ContentType.objects.get(model=mentioned_user_type)
        mentioned_user = mentioned_user_content_type.get_object_for_this_type(
            id=mentioned_user_id
        )

        # Get actor
        actor_content_type = ContentType.objects.get(model=actor_type)
        actor = actor_content_type.get_object_for_this_type(id=actor_id)

        # Get target (post or comment)
        target_content_type = ContentType.objects.get(model=target_type)
        target = target_content_type.get_object_for_this_type(id=target_id)

        result = AsyncNotificationService.notify_mention(
            mentioned_user, actor, target, send_push
        )
        return {"success": True, "notification_id": result.id if result else None}
    except Exception as exc:
        logger.error(f"Mention notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


# === FOLLOW-BASED NOTIFICATION TASKS ===


@shared_task(bind=True, max_retries=2)
def notify_followed_user_post_task(self, post_id, send_push=False):
    """Async task to notify followers about new post from followed user"""
    try:
        post = Post.objects.get(id=post_id)
        results = AsyncNotificationService.notify_followed_user_post(post, send_push)
        return {
            "success": True,
            "notifications_sent": len(results),
            "notification_ids": [n.id for n in results if n],
        }
    except Exception as exc:
        logger.error(f"Followed user post notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


@shared_task(bind=True, max_retries=2)
def notify_followed_post_comment_task(
    self, post_id, comment_id, actor_id, actor_type, send_push=False
):
    """Async task to notify post followers about new comment"""
    try:
        post = Post.objects.get(id=post_id)
        comment = GenericComment.objects.get(id=comment_id)

        # Get actor
        actor_content_type = ContentType.objects.get(model=actor_type)
        actor = actor_content_type.get_object_for_this_type(id=actor_id)

        results = AsyncNotificationService.notify_followed_post_comment(
            post, comment, actor, send_push
        )
        return {
            "success": True,
            "notifications_sent": len(results),
            "notification_ids": [n.id for n in results if n],
        }
    except Exception as exc:
        logger.error(f"Followed post comment notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


@shared_task(bind=True, max_retries=2)
def notify_followed_comment_reply_task(
    self, comment_id, reply_id, actor_id, actor_type, send_push=False
):
    """Async task to notify comment followers about new reply"""
    try:
        comment = GenericComment.objects.get(id=comment_id)
        reply = GenericComment.objects.get(id=reply_id)

        # Get actor
        actor_content_type = ContentType.objects.get(model=actor_type)
        actor = actor_content_type.get_object_for_this_type(id=actor_id)

        results = AsyncNotificationService.notify_followed_comment_reply(
            comment, reply, actor, send_push
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
def auto_follow_post_task(
    self, user_id, user_type, post_id, interaction_type="comment"
):
    """Async task to auto-follow a post"""
    try:
        from keyoconnect.posts.models import Post

        user_content_type = ContentType.objects.get(model=user_type)
        user = user_content_type.get_object_for_this_type(id=user_id)
        post = Post.objects.get(id=post_id)

        result = AsyncNotificationService.auto_follow_post(user, post, interaction_type)
        return {"success": True, "follow_created": result is not None}
    except Exception as exc:
        logger.error(f"Auto follow post task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}


@shared_task(bind=True, max_retries=2)
def auto_follow_comment_task(self, user_id, user_type, comment_id):
    """Async task to auto-follow a comment"""
    try:
        user_content_type = ContentType.objects.get(model=user_type)
        user = user_content_type.get_object_for_this_type(id=user_id)
        comment = GenericComment.objects.get(id=comment_id)

        result = AsyncNotificationService.auto_follow_comment(user, comment)
        return {"success": True, "follow_created": result is not None}
    except Exception as exc:
        logger.error(f"Auto follow comment task failed: {str(exc)}")
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


@shared_task(bind=True, max_retries=2)
def notify_replies_milestone_task(self, target_id, target_type, count, send_push=True):
    """Async task to notify target owner about replies milestone"""
    try:
        # Get target (post or comment)
        target_content_type = ContentType.objects.get(model=target_type)
        target = target_content_type.get_object_for_this_type(id=target_id)

        from keyoconnect.posts.models import Post

        if isinstance(target, Post):
            result = AsyncNotificationService.notify_post_milestone(
                target, "replies_milestone", count, send_push
            )
        else:
            result = AsyncNotificationService.notify_comment_milestone(
                target, "replies_milestone", count, send_push
            )

        return {"success": True, "notification_id": result.id if result else None}
    except Exception as exc:
        logger.error(f"Replies milestone notification task failed: {str(exc)}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "error": str(exc)}
