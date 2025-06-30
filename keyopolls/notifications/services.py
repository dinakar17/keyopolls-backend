from typing import Dict, Optional

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from keyoconnect.common.models import Follow
from keyoconnect.connect_notifications.models import (
    CommentFollow,
    Notification,
    NotificationPreference,
    NotificationPriority,
    NotificationType,
    PostFollow,
)


class URLBuilder:
    """Helper class to build URLs and deep links for different notification types"""

    @staticmethod
    def build_post_url(post_id: int, profile_type: str = "public") -> str:
        """Build URL for post-related notifications"""
        return f"/posts/{post_id}?type={profile_type}"

    @staticmethod
    def build_comment_url(
        post_id: int, comment_id: int, profile_type: str = "public"
    ) -> str:
        """Build URL for comment-related notifications"""
        return (
            f"/posts/{post_id}?view=thread&commentId={comment_id}&type={profile_type}"
        )

    @staticmethod
    def build_profile_url(profile_handle: str, profile_type: str = "public") -> str:
        """Build URL for profile-related notifications"""
        if profile_type == "public":
            return f"/profile/{profile_handle}"
        else:
            return f"/profile/{profile_handle}?type={profile_type}"

    @staticmethod
    def build_followers_url(profile_handle: str) -> str:
        """Build URL for follower-related notifications"""
        return f"/profile/{profile_handle}/followers"

    @staticmethod
    def build_deep_link_data(screen: str, params: dict = None) -> dict:
        """Build deep link data for mobile apps"""
        return {"screen": screen, "params": params or {}}


class AsyncNotificationService:
    """Async notification service that uses Celery tasks for delivery"""

    # Default milestone thresholds
    DEFAULT_THRESHOLDS = {
        NotificationType.LIKE_MILESTONE: [1, 10, 50, 100, 500, 1000],
        NotificationType.SHARE_MILESTONE: [10, 50, 100, 500, 1000],
        NotificationType.BOOKMARK_MILESTONE: [10, 30, 100, 500],
        NotificationType.IMPRESSION_MILESTONE: [100, 500, 1000, 5000, 10000],
        NotificationType.FOLLOWER_MILESTONE: [10, 50, 100, 200, 500, 1000],
        NotificationType.REPLIES_MILESTONE: [5, 10, 25, 50, 100, 250, 500],
    }

    @classmethod
    def send_notification(
        cls,
        recipient,
        notification_type: str,
        title: str,
        message: str,
        actor=None,
        target=None,
        click_url: str = None,
        deep_link_data: dict = None,
        extra_data: Optional[Dict] = None,
        priority: str = NotificationPriority.NORMAL,
        send_push: bool = False,
        send_email: bool = False,
        expires_at=None,
        use_async: bool = True,
    ) -> Notification:
        """Main method to create and send notifications"""

        notification = Notification.objects.create(
            recipient_content_type=ContentType.objects.get_for_model(recipient),
            recipient_object_id=recipient.id,
            actor_content_type=(
                ContentType.objects.get_for_model(actor) if actor else None
            ),
            actor_object_id=actor.id if actor else None,
            target_content_type=(
                ContentType.objects.get_for_model(target) if target else None
            ),
            target_object_id=target.id if target else None,
            notification_type=notification_type,
            title=title,
            message=message,
            click_url=click_url,
            deep_link_data=deep_link_data or {},
            extra_data=extra_data or {},
            priority=priority,
            expires_at=expires_at,
        )

        cls._handle_delivery(notification, send_push, send_email, use_async)
        return notification

    # === POST OWNER NOTIFICATIONS ===

    @classmethod
    def notify_post_comment(cls, post, comment, actor, send_push=True, use_async=True):
        """Notify post owner when someone comments on their post"""
        if use_async:
            from keyoconnect.connect_notifications.tasks import notify_post_comment_task

            actor_type = actor._meta.model_name
            return notify_post_comment_task.delay(
                post.id, comment.id, actor.id, actor_type, send_push
            )

        # Fallback to synchronous execution
        return cls._notify_post_comment_sync(post, comment, actor, send_push)

    @classmethod
    def _notify_post_comment_sync(cls, post, comment, actor, send_push=True):
        """Synchronous version of post comment notification"""
        post_owner = cls._get_post_owner(post)
        if not post_owner or post_owner.id == actor.id:
            return None

        actor_name = cls._get_actor_name(actor)
        profile_type = cls._get_profile_type(actor)

        click_url = URLBuilder.build_comment_url(post.id, comment.id, profile_type)
        deep_link_data = URLBuilder.build_deep_link_data(
            "post", {"post_id": post.id, "comment_id": comment.id}
        )

        return cls.send_notification(
            recipient=post_owner,
            notification_type=NotificationType.COMMENT,
            title="New Comment!",
            message=f"{actor_name} commented on your post",
            actor=actor,
            target=post,
            click_url=click_url,
            deep_link_data=deep_link_data,
            send_push=send_push,
            use_async=False,  # Already async at this level
        )

    @classmethod
    def notify_post_milestone(
        cls, post, milestone_type: str, count: int, send_push=True, use_async=True
    ):
        """Notify post owner when their post reaches a milestone"""
        if use_async:
            from keyoconnect.connect_notifications.tasks import (
                notify_post_milestone_task,
            )

            return notify_post_milestone_task.delay(
                post.id, milestone_type, count, send_push
            )

        # Fallback to synchronous execution
        return cls._notify_post_milestone_sync(post, milestone_type, count, send_push)

    @classmethod
    def _notify_post_milestone_sync(
        cls, post, milestone_type: str, count: int, send_push=True
    ):
        """Synchronous version of post milestone notification"""
        post_owner = cls._get_post_owner(post)
        if not post_owner:
            return None

        if not cls._should_send_milestone(post_owner, milestone_type, count):
            return None

        milestone_messages = {
            NotificationType.LIKE_MILESTONE: f"🎉 Your post reached {count} likes!",
            NotificationType.SHARE_MILESTONE: f"🚀 Your post was shared {count} times!",
            NotificationType.BOOKMARK_MILESTONE: (
                f"📚 Your post was bookmarked {count} times!"
            ),
            NotificationType.IMPRESSION_MILESTONE: (
                f"👀 Your post reached {count} impressions!"
            ),
            NotificationType.REPLIES_MILESTONE: (
                f"💬 Your post received {count} replies!"
            ),
        }

        click_url = URLBuilder.build_post_url(post.id)
        deep_link_data = URLBuilder.build_deep_link_data("post", {"post_id": post.id})

        return cls.send_notification(
            recipient=post_owner,
            notification_type=milestone_type,
            title="Milestone Reached!",
            message=milestone_messages.get(
                milestone_type, f"Your post reached {count}!"
            ),
            target=post,
            click_url=click_url,
            deep_link_data=deep_link_data,
            extra_data={"milestone_count": count},
            priority=NotificationPriority.HIGH,
            send_push=send_push,
            use_async=False,
        )

    # === COMMENT OWNER NOTIFICATIONS ===

    @classmethod
    def notify_comment_reply(
        cls, comment, reply, actor, send_push=True, use_async=True
    ):
        """Notify comment owner when someone replies to their comment"""
        if use_async:
            from keyoconnect.connect_notifications.tasks import (
                notify_comment_reply_task,
            )

            actor_type = actor._meta.model_name
            return notify_comment_reply_task.delay(
                comment.id, reply.id, actor.id, actor_type, send_push
            )

        return cls._notify_comment_reply_sync(comment, reply, actor, send_push)

    @classmethod
    def _notify_comment_reply_sync(cls, comment, reply, actor, send_push=True):
        """Synchronous version of comment reply notification"""
        comment_owner = cls._get_comment_owner(comment)
        if not comment_owner or comment_owner.id == actor.id:
            return None

        actor_name = cls._get_actor_name(actor)
        profile_type = cls._get_profile_type(actor)

        # Get the post this comment belongs to
        post = cls._get_comment_post(comment)
        if not post:
            return None

        click_url = URLBuilder.build_comment_url(post.id, reply.id, profile_type)
        deep_link_data = URLBuilder.build_deep_link_data(
            "post",
            {
                "post_id": post.id,
                "comment_id": reply.id,
                "parent_comment_id": comment.id,
            },
        )

        return cls.send_notification(
            recipient=comment_owner,
            notification_type=NotificationType.REPLY,
            title="New Reply!",
            message=f"{actor_name} replied to your comment",
            actor=actor,
            target=comment,
            click_url=click_url,
            deep_link_data=deep_link_data,
            send_push=send_push,
            use_async=False,
        )

    @classmethod
    def notify_comment_milestone(
        cls, comment, milestone_type: str, count: int, send_push=True, use_async=True
    ):
        """Notify comment owner when their comment reaches a milestone"""
        if use_async:
            from keyoconnect.connect_notifications.tasks import (
                notify_comment_milestone_task,
            )

            return notify_comment_milestone_task.delay(
                comment.id, milestone_type, count, send_push
            )

        return cls._notify_comment_milestone_sync(
            comment, milestone_type, count, send_push
        )

    @classmethod
    def _notify_comment_milestone_sync(
        cls, comment, milestone_type: str, count: int, send_push=True
    ):
        """Synchronous version of comment milestone notification"""
        comment_owner = cls._get_comment_owner(comment)
        if not comment_owner:
            return None

        if not cls._should_send_milestone(comment_owner, milestone_type, count):
            return None

        post = cls._get_comment_post(comment)
        if not post:
            return None

        click_url = URLBuilder.build_comment_url(post.id, comment.id)
        deep_link_data = URLBuilder.build_deep_link_data(
            "post", {"post_id": post.id, "comment_id": comment.id}
        )

        milestone_messages = {
            NotificationType.LIKE_MILESTONE: f"🎉 Your comment reached {count} likes!",
            NotificationType.REPLIES_MILESTONE: (
                f"💬 Your comment received {count} replies!"
            ),
        }

        return cls.send_notification(
            recipient=comment_owner,
            notification_type=milestone_type,
            title="Milestone Reached!",
            message=milestone_messages.get(
                milestone_type, f"Your comment reached {count}!"
            ),
            target=comment,
            click_url=click_url,
            deep_link_data=deep_link_data,
            extra_data={"milestone_count": count},
            priority=NotificationPriority.HIGH,
            send_push=send_push,
            use_async=False,
        )

    # === SOCIAL NOTIFICATIONS ===

    @classmethod
    def notify_follow(cls, follower, followee, send_push=True, use_async=True):
        """Notify user when someone follows them"""
        if use_async:
            from keyoconnect.connect_notifications.tasks import notify_follow_task

            follower_type = follower._meta.model_name
            followee_type = followee._meta.model_name
            return notify_follow_task.delay(
                follower.id, follower_type, followee.id, followee_type, send_push
            )

        return cls._notify_follow_sync(follower, followee, send_push)

    @classmethod
    def _notify_follow_sync(cls, follower, followee, send_push=True):
        """Synchronous version of follow notification"""
        if follower.id == followee.id:
            return None

        actor_name = cls._get_actor_name(follower)
        profile_type = cls._get_profile_type(follower)

        actor_handle = cls._get_profile_handle(follower)
        click_url = URLBuilder.build_profile_url(actor_handle, profile_type)
        deep_link_data = URLBuilder.build_deep_link_data(
            "profile", {"profile_handle": actor_handle, "profile_type": profile_type}
        )

        return cls.send_notification(
            recipient=followee,
            notification_type=NotificationType.FOLLOW,
            title="New Follower!",
            message=f"{actor_name} started following you",
            actor=follower,
            click_url=click_url,
            deep_link_data=deep_link_data,
            send_push=send_push,
            use_async=False,
        )

    @classmethod
    def notify_follower_milestone(
        cls, user, count: int, send_push=True, use_async=True
    ):
        """Notify user when they reach a follower milestone"""
        if use_async:
            from keyoconnect.connect_notifications.tasks import (
                notify_follower_milestone_task,
            )

            user_type = user._meta.model_name
            return notify_follower_milestone_task.delay(
                user.id, user_type, count, send_push
            )

        return cls._notify_follower_milestone_sync(user, count, send_push)

    @classmethod
    def _notify_follower_milestone_sync(cls, user, count: int, send_push=True):
        """Synchronous version of follower milestone notification"""
        if not cls._should_send_milestone(
            user, NotificationType.FOLLOWER_MILESTONE, count
        ):
            return None

        user_handle = cls._get_profile_handle(user)
        click_url = URLBuilder.build_followers_url(user_handle)
        deep_link_data = URLBuilder.build_deep_link_data(
            "followers", {"profile_handle": user_handle}
        )

        return cls.send_notification(
            recipient=user,
            notification_type=NotificationType.FOLLOWER_MILESTONE,
            title="Milestone Reached!",
            message=f"🌟 You reached {count} followers!",
            click_url=click_url,
            deep_link_data=deep_link_data,
            extra_data={"milestone_count": count},
            priority=NotificationPriority.HIGH,
            send_push=send_push,
            use_async=False,
        )

    @classmethod
    def notify_mention(
        cls, mentioned_user, actor, target, send_push=True, use_async=True
    ):
        """Notify user when they are mentioned in a post or comment"""
        if use_async:
            from keyoconnect.connect_notifications.tasks import notify_mention_task

            mentioned_user_type = mentioned_user._meta.model_name
            actor_type = actor._meta.model_name
            target_type = target._meta.model_name
            return notify_mention_task.delay(
                mentioned_user.id,
                mentioned_user_type,
                actor.id,
                actor_type,
                target.id,
                target_type,
                send_push,
            )

        return cls._notify_mention_sync(mentioned_user, actor, target, send_push)

    @classmethod
    def _notify_mention_sync(cls, mentioned_user, actor, target, send_push=True):
        """Synchronous version of mention notification"""
        if mentioned_user.id == actor.id:
            return None

        actor_name = cls._get_actor_name(actor)
        profile_type = cls._get_profile_type(actor)

        # Determine if it's a post or comment mention
        if hasattr(target, "content") and hasattr(target, "profile_type"):
            # It's a post
            target_type = "post"
            click_url = URLBuilder.build_post_url(target.id, profile_type)
            deep_link_data = URLBuilder.build_deep_link_data(
                "post", {"post_id": target.id, "highlight": "mention"}
            )
            message = f"{actor_name} mentioned you in a post"
        else:
            # It's a comment
            target_type = "comment"
            post = cls._get_comment_post(target)
            if not post:
                return None
            click_url = URLBuilder.build_comment_url(post.id, target.id, profile_type)
            deep_link_data = URLBuilder.build_deep_link_data(
                "post",
                {"post_id": post.id, "comment_id": target.id, "highlight": "mention"},
            )
            message = f"{actor_name} mentioned you in a comment"

        return cls.send_notification(
            recipient=mentioned_user,
            notification_type=NotificationType.MENTION,
            title="You were mentioned!",
            message=message,
            actor=actor,
            target=target,
            click_url=click_url,
            deep_link_data=deep_link_data,
            extra_data={"target_type": target_type},
            priority=NotificationPriority.HIGH,
            send_push=send_push,
            use_async=False,
        )

    # === FOLLOW-BASED NOTIFICATIONS ===

    @classmethod
    def notify_followed_user_post(cls, post, send_push=False, use_async=True):
        """Notify all followers when someone they follow creates a new post"""
        if use_async:
            from keyoconnect.connect_notifications.tasks import (
                notify_followed_user_post_task,
            )

            return notify_followed_user_post_task.delay(post.id, send_push)

        return cls._notify_followed_user_post_sync(post, send_push)

    @classmethod
    def _notify_followed_user_post_sync(cls, post, send_push=False):
        """Synchronous version of followed user post notification"""
        post_author = cls._get_post_owner(post)
        if not post_author:
            return []

        followers = Follow.objects.filter(
            followee=post_author, is_active=True
        ).select_related("follower")

        notifications_sent = []
        actor_name = cls._get_actor_name(post_author)
        profile_type = cls._get_profile_type(post_author)

        for follow_relationship in followers:
            follower = follow_relationship.follower

            if follower.id == post_author.id:
                continue

            click_url = URLBuilder.build_post_url(post.id, profile_type)
            deep_link_data = URLBuilder.build_deep_link_data(
                "post", {"post_id": post.id, "source": "followed_user"}
            )

            notification = cls.send_notification(
                recipient=follower,
                notification_type=NotificationType.FOLLOWED_USER_POST,
                title="New Post from Someone You Follow",
                message=f"{actor_name} just posted something new",
                actor=post_author,
                target=post,
                click_url=click_url,
                deep_link_data=deep_link_data,
                send_push=send_push,
                use_async=False,
            )

            notifications_sent.append(notification)

        return notifications_sent

    @classmethod
    def notify_followed_post_comment(
        cls, post, comment, actor, send_push=False, use_async=True
    ):
        """Notify users who follow a post when someone comments on it"""
        if use_async:
            from keyoconnect.connect_notifications.tasks import (
                notify_followed_post_comment_task,
            )

            actor_type = actor._meta.model_name
            return notify_followed_post_comment_task.delay(
                post.id, comment.id, actor.id, actor_type, send_push
            )

        return cls._notify_followed_post_comment_sync(post, comment, actor, send_push)

    @classmethod
    def _notify_followed_post_comment_sync(cls, post, comment, actor, send_push=False):
        """Synchronous version of followed post comment notification"""
        post_followers = PostFollow.objects.filter(
            post=post, is_active=True
        ).select_related()

        if not post_followers.exists():
            return []

        notifications_sent = []
        actor_name = cls._get_actor_name(actor)
        profile_type = cls._get_profile_type(actor)

        for post_follow in post_followers:
            follower = post_follow.follower

            # Don't notify the actor or post owner
            if follower.id == actor.id:
                continue

            post_owner = cls._get_post_owner(post)
            if post_owner and follower.id == post_owner.id:
                continue

            click_url = URLBuilder.build_comment_url(post.id, comment.id, profile_type)
            deep_link_data = URLBuilder.build_deep_link_data(
                "post",
                {
                    "post_id": post.id,
                    "comment_id": comment.id,
                    "source": "followed_post",
                },
            )

            notification = cls.send_notification(
                recipient=follower,
                notification_type=NotificationType.FOLLOWED_POST_COMMENT,
                title="New Comment on Followed Post",
                message=f"{actor_name} commented on a post you're following",
                actor=actor,
                target=post,
                click_url=click_url,
                deep_link_data=deep_link_data,
                send_push=send_push,
                use_async=False,
            )

            notifications_sent.append(notification)

        return notifications_sent

    @classmethod
    def notify_followed_comment_reply(
        cls, comment, reply, actor, send_push=False, use_async=True
    ):
        """Notify users who follow a comment when someone replies to it"""
        if use_async:
            from keyoconnect.connect_notifications.tasks import (
                notify_followed_comment_reply_task,
            )

            actor_type = actor._meta.model_name
            return notify_followed_comment_reply_task.delay(
                comment.id, reply.id, actor.id, actor_type, send_push
            )

        return cls._notify_followed_comment_reply_sync(comment, reply, actor, send_push)

    @classmethod
    def _notify_followed_comment_reply_sync(
        cls, comment, reply, actor, send_push=False
    ):
        """Synchronous version of followed comment reply notification"""
        comment_followers = CommentFollow.objects.filter(
            comment=comment, is_active=True
        ).select_related()

        if not comment_followers.exists():
            return []

        notifications_sent = []
        actor_name = cls._get_actor_name(actor)
        profile_type = cls._get_profile_type(actor)

        for comment_follow in comment_followers:
            follower = comment_follow.follower

            # Don't notify the actor or comment owner
            if follower.id == actor.id:
                continue

            comment_owner = cls._get_comment_owner(comment)
            if comment_owner and follower.id == comment_owner.id:
                continue

            post = cls._get_comment_post(comment)
            if not post:
                continue

            click_url = URLBuilder.build_comment_url(post.id, reply.id, profile_type)
            deep_link_data = URLBuilder.build_deep_link_data(
                "post",
                {
                    "post_id": post.id,
                    "comment_id": reply.id,
                    "parent_comment_id": comment.id,
                    "source": "followed_comment",
                },
            )

            notification = cls.send_notification(
                recipient=follower,
                notification_type=NotificationType.FOLLOWED_COMMENT_REPLY,
                title="New Reply on Followed Comment",
                message=f"{actor_name} replied to a comment you're following",
                actor=actor,
                target=comment,
                click_url=click_url,
                deep_link_data=deep_link_data,
                extra_data={"reply_id": reply.id},
                send_push=send_push,
                use_async=False,
            )

            notifications_sent.append(notification)

        return notifications_sent

    # === AUTO-FOLLOW METHODS ===

    @classmethod
    def auto_follow_post(cls, user, post, interaction_type="comment", use_async=True):
        """Automatically follow a post when user interacts with it"""
        if use_async:
            from keyoconnect.connect_notifications.tasks import auto_follow_post_task

            user_type = user._meta.model_name
            return auto_follow_post_task.delay(
                user.id, user_type, post.id, interaction_type
            )

        return cls._auto_follow_post_sync(user, post, interaction_type)

    @classmethod
    def _auto_follow_post_sync(cls, user, post, interaction_type="comment"):
        """Synchronous version of auto follow post"""
        post_owner = cls._get_post_owner(post)
        if post_owner and user.id == post_owner.id:
            return None

        post_follow, created = PostFollow.objects.get_or_create(
            follower_content_type=ContentType.objects.get_for_model(user),
            follower_object_id=user.id,
            post=post,
            defaults={"auto_followed": True},
        )

        if not created and not post_follow.is_active:
            post_follow.is_active = True
            post_follow.save()

        return post_follow

    @classmethod
    def auto_follow_comment(cls, user, comment, use_async=True):
        """Automatically follow a comment when user replies to it"""
        if use_async:
            from keyoconnect.connect_notifications.tasks import auto_follow_comment_task

            user_type = user._meta.model_name
            return auto_follow_comment_task.delay(user.id, user_type, comment.id)

        return cls._auto_follow_comment_sync(user, comment)

    @classmethod
    def _auto_follow_comment_sync(cls, user, comment):
        """Synchronous version of auto follow comment"""
        comment_owner = cls._get_comment_owner(comment)
        if comment_owner and user.id == comment_owner.id:
            return None

        comment_follow, created = CommentFollow.objects.get_or_create(
            follower_content_type=ContentType.objects.get_for_model(user),
            follower_object_id=user.id,
            comment=comment,
            defaults={"auto_followed": True},
        )

        if not created and not comment_follow.is_active:
            comment_follow.is_active = True
            comment_follow.save()

        return comment_follow

    @classmethod
    def unfollow_post(cls, user, post):
        """Unfollow a post"""
        try:
            post_follow = PostFollow.objects.get(
                follower_content_type=ContentType.objects.get_for_model(user),
                follower_object_id=user.id,
                post=post,
            )
            post_follow.is_active = False
            post_follow.save()
            return True
        except PostFollow.DoesNotExist:
            return False

    @classmethod
    def unfollow_comment(cls, user, comment):
        """Unfollow a comment"""
        try:
            comment_follow = CommentFollow.objects.get(
                follower_content_type=ContentType.objects.get_for_model(user),
                follower_object_id=user.id,
                comment=comment,
            )
            comment_follow.is_active = False
            comment_follow.save()
            return True
        except CommentFollow.DoesNotExist:
            return False

    # === HELPER METHODS ===

    @classmethod
    def _get_post_owner(cls, post):
        """Get the owner of a post"""
        if post.profile_type == "public" and post.public_profile:
            return post.public_profile
        elif post.profile_type == "anonymous" and post.anonymous_profile:
            return post.anonymous_profile
        return None

    @classmethod
    def _get_comment_owner(cls, comment):
        """Get the owner of a comment"""
        from keyoconnect.profiles.models import AnonymousProfile, PublicProfile

        if comment.profile_type == "public":
            return PublicProfile.objects.filter(id=comment.profile_id).first()
        elif comment.profile_type == "anonymous":
            return AnonymousProfile.objects.filter(id=comment.profile_id).first()
        return None

    @classmethod
    def _get_comment_post(cls, comment):
        """Get the post that a comment belongs to"""
        from keyoconnect.posts.models import Post

        # Check if the comment's content_object is a Post
        if isinstance(comment.content_object, Post):
            return comment.content_object
        return None

    @classmethod
    def _get_actor_name(cls, actor):
        """Get display name for actor"""
        if hasattr(actor, "display_name") and actor.display_name:
            return actor.display_name
        elif hasattr(actor, "handle") and actor.handle:
            return f"@{actor.handle}"
        elif hasattr(actor, "anonymous_post_identifier"):
            return actor.anonymous_post_identifier
        else:
            return "Someone"

    @classmethod
    def _get_profile_type(cls, profile):
        """Get profile type string"""
        from keyoconnect.profiles.models import AnonymousProfile, PublicProfile

        if isinstance(profile, PublicProfile):
            return "public"
        elif isinstance(profile, AnonymousProfile):
            return "anonymous"
        else:
            return "public"  # default fallback

    @classmethod
    def _get_profile_handle(cls, profile):
        """Get profile handle for URL building"""
        return getattr(profile, "handle", None) or getattr(
            profile, "user_name", str(profile.id)
        )

    @classmethod
    def _should_send_milestone(cls, recipient, milestone_type: str, count: int) -> bool:
        """Check if milestone notification should be sent based on user preferences"""
        try:
            preference = NotificationPreference.objects.get(
                profile_content_type=ContentType.objects.get_for_model(recipient),
                profile_object_id=recipient.id,
                notification_type=milestone_type,
            )

            if not preference.is_enabled:
                return False

            thresholds = preference.custom_thresholds or cls.DEFAULT_THRESHOLDS.get(
                milestone_type, []
            )

        except NotificationPreference.DoesNotExist:
            thresholds = cls.DEFAULT_THRESHOLDS.get(milestone_type, [])

        return count in thresholds

    @classmethod
    def _handle_delivery(
        cls,
        notification: Notification,
        send_push: bool,
        send_email: bool,
        use_async: bool = True,
    ):
        """Handle push and email delivery"""
        from keyoconnect.profiles.models import PublicProfile

        # Only send push/email to Public profiles (Anonymous profiles are in-app only)
        if isinstance(notification.recipient, PublicProfile):
            try:
                preference = NotificationPreference.objects.get(
                    profile_content_type=notification.recipient_content_type,
                    profile_object_id=notification.recipient_object_id,
                    notification_type=notification.notification_type,
                )

                push_enabled = preference.push_enabled
                email_enabled = preference.email_enabled

            except NotificationPreference.DoesNotExist:
                push_enabled = True
                email_enabled = True

            if send_push and push_enabled:
                if use_async:
                    from keyoconnect.connect_notifications.tasks import (
                        send_push_notification_task,
                    )

                    send_push_notification_task.delay(notification.id)
                else:
                    cls._send_push_notification(notification)

            if send_email and email_enabled:
                if use_async:
                    from keyoconnect.connect_notifications.tasks import (
                        send_email_notification_task,
                    )

                    send_email_notification_task.delay(notification.id)
                else:
                    cls._send_email_notification(notification)

    @classmethod
    def _send_push_notification(cls, notification: Notification):
        """Send push notification using FCM service"""
        try:
            import logging

            from keyoconnect.connect_notifications.fcm_services import FCMService
            from keyoconnect.profiles.models import PublicProfile

            logger = logging.getLogger(__name__)

            # Only send push notifications to Public profiles
            if not isinstance(notification.recipient, PublicProfile):
                logger.info(
                    f"Skipping push notification for non-public profile: "
                    f"{type(notification.recipient)}"
                )
                return

            # Prepare notification data for FCM
            notification_data = {
                "notification_id": str(notification.id),
                "notification_type": notification.notification_type,
                "click_url": notification.click_url or "",
                "priority": notification.priority,
            }

            # Add deep link data
            if notification.deep_link_data:
                notification_data.update(notification.deep_link_data)

            # Add extra data (convert to string for FCM compatibility)
            if notification.extra_data:
                notification_data["extra_data"] = str(notification.extra_data)

            # Send push notification using FCM service
            result = FCMService.notify_profile(
                profile=notification.recipient,
                title=notification.title,
                body=notification.message,
                data=notification_data,
                notification_type=notification.notification_type,
            )

            # Update notification status based on FCM result
            if result["success"]:
                notification.push_sent = True
                notification.push_sent_at = timezone.now()
                notification.save(update_fields=["push_sent", "push_sent_at"])
                logger.info(
                    f"Push notification sent successfully to "
                    f"{notification.recipient.handle}: {result['message']}"
                )
            else:
                logger.warning(
                    f"Push notification failed for "
                    f"{notification.recipient.handle}: {result['message']}"
                )

        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(
                f"Failed to send push notification for notification "
                f"{notification.id}: {str(e)}"
            )

    @classmethod
    def _send_email_notification(cls, notification: Notification):
        """Send email notification using ZeptoMail service"""
        try:
            import logging

            from keyoconnect.profiles.models import PublicProfile
            from shared.member.services.send_otp import (
                NotificationService as EmailService,
            )

            logger = logging.getLogger(__name__)

            # Only send email notifications to Public profiles with email addresses
            if not isinstance(notification.recipient, PublicProfile):
                logger.info(
                    f"Skipping email notification for non-public profile: "
                    f"{type(notification.recipient)}"
                )
                return

            # Check if recipient has an email address
            if not notification.recipient.email:
                logger.info(
                    f"Skipping email notification for profile "
                    f"{notification.recipient.handle} - no email address"
                )
                return

            # Get recipient info
            recipient_email = notification.recipient.email
            recipient_name = (
                notification.recipient.display_name
                or f"@{notification.recipient.handle}"
            )

            # Prepare email subject based on notification type
            subject_map = {
                "comment": "💬 New comment on your post",
                "reply": "↩️ New reply to your comment",
                "follow": "👋 You have a new follower",
                "mention": "📢 You were mentioned",
                "like_milestone": "🎉 Milestone reached!",
                "share_milestone": "🚀 Your post is trending!",
                "bookmark_milestone": "📚 People love your content!",
                "impression_milestone": "👀 Your post is getting views!",
                "follower_milestone": "🌟 Congratulations on your followers!",
                "followed_user_post": "📝 New post from someone you follow",
                "verification": "✅ Verification complete",
                "welcome": "🎊 Welcome!",
            }

            email_subject = subject_map.get(
                notification.notification_type, f"🔔 {notification.title}"
            )

            # Send email using the NotificationService
            success = EmailService.send_notification_email(
                email=recipient_email,
                subject=email_subject,
                title=notification.title,
                message=notification.message,
                click_url=notification.click_url,
                recipient_name=recipient_name,
                notification_type=notification.notification_type,
            )

            # Update notification status based on email result
            if success:
                notification.email_sent = True
                notification.email_sent_at = timezone.now()
                notification.save(update_fields=["email_sent", "email_sent_at"])
                logger.info(
                    f"Email notification sent successfully to {recipient_email}"
                )
            else:
                logger.warning(
                    f"Failed to send email notification to {recipient_email}"
                )

        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(
                f"Failed to send email notification for notification "
                f"{notification.id}: {str(e)}"
            )
