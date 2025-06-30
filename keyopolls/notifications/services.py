from typing import Dict, Optional

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from keyopolls.notifications.models import (
    CommentFollow,
    Notification,
    NotificationPreference,
    NotificationPriority,
    NotificationType,
    PollFollow,
    ProfileFollow,
)


class URLBuilder:
    """Helper class to build URLs and deep links for different notification types"""

    @staticmethod
    def build_poll_url(poll_id: int) -> str:
        """Build URL for poll-related notifications"""
        return f"/polls/{poll_id}"

    @staticmethod
    def build_comment_url(poll_id: int, comment_id: int) -> str:
        """Build URL for comment-related notifications"""
        return f"/polls/{poll_id}?view=thread&commentId={comment_id}"

    @staticmethod
    def build_profile_url(username: str) -> str:
        """Build URL for profile-related notifications"""
        return f"/profile/{username}"

    @staticmethod
    def build_followers_url(username: str) -> str:
        """Build URL for follower-related notifications"""
        return f"/profile/{username}/followers"

    @staticmethod
    def build_community_url(community_id: int) -> str:
        """Build URL for community-related notifications"""
        return f"/communities/{community_id}"

    @staticmethod
    def build_deep_link_data(screen: str, params: dict = None) -> dict:
        """Build deep link data for mobile apps"""
        return {"screen": screen, "params": params or {}}


class AsyncNotificationService:
    """Async notification service that uses Celery tasks for delivery"""

    # Default milestone thresholds
    DEFAULT_THRESHOLDS = {
        NotificationType.VOTE_MILESTONE: [10, 25, 50, 100, 250, 500, 1000],
        NotificationType.LIKE_MILESTONE: [1, 10, 50, 100, 500, 1000],
        NotificationType.SHARE_MILESTONE: [10, 50, 100, 500, 1000],
        NotificationType.BOOKMARK_MILESTONE: [10, 30, 100, 500],
        NotificationType.VIEW_MILESTONE: [100, 500, 1000, 5000, 10000],
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
            recipient=recipient,
            actor=actor,
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

    # === POLL OWNER NOTIFICATIONS ===

    @classmethod
    def notify_poll_comment(cls, poll, comment, actor, send_push=True, use_async=True):
        """Notify poll owner when someone comments on their poll"""
        if use_async:
            from keyopolls.notifications.tasks import notify_poll_comment_task

            return notify_poll_comment_task.delay(
                poll.id, comment.id, actor.id, send_push
            )

        # Fallback to synchronous execution
        return cls._notify_poll_comment_sync(poll, comment, actor, send_push)

    @classmethod
    def _notify_poll_comment_sync(cls, poll, comment, actor, send_push=True):
        """Synchronous version of poll comment notification"""
        poll_owner = poll.profile
        if not poll_owner or poll_owner.id == actor.id:
            return None

        actor_name = cls._get_actor_name(actor)

        click_url = URLBuilder.build_comment_url(poll.id, comment.id)
        deep_link_data = URLBuilder.build_deep_link_data(
            "poll", {"poll_id": poll.id, "comment_id": comment.id}
        )

        return cls.send_notification(
            recipient=poll_owner,
            notification_type=NotificationType.POLL_COMMENT,
            title="New Comment!",
            message=f"{actor_name} commented on your poll",
            actor=actor,
            target=poll,
            click_url=click_url,
            deep_link_data=deep_link_data,
            send_push=send_push,
            use_async=False,
        )

    @classmethod
    def notify_poll_vote(cls, poll, voter, option, send_push=True, use_async=True):
        """Notify poll owner when someone votes on their poll"""
        if use_async:
            from keyopolls.notifications.tasks import notify_poll_vote_task

            return notify_poll_vote_task.delay(poll.id, voter.id, option.id, send_push)

        return cls._notify_poll_vote_sync(poll, voter, option, send_push)

    @classmethod
    def _notify_poll_vote_sync(cls, poll, voter, option, send_push=True):
        """Synchronous version of poll vote notification"""
        poll_owner = poll.profile
        if not poll_owner or poll_owner.id == voter.id:
            return None

        actor_name = cls._get_actor_name(voter)

        click_url = URLBuilder.build_poll_url(poll.id)
        deep_link_data = URLBuilder.build_deep_link_data("poll", {"poll_id": poll.id})

        return cls.send_notification(
            recipient=poll_owner,
            notification_type=NotificationType.POLL_VOTE,
            title="New Vote!",
            message=f"{actor_name} voted on your poll",
            actor=voter,
            target=poll,
            click_url=click_url,
            deep_link_data=deep_link_data,
            extra_data={"option_id": option.id, "option_text": option.text},
            send_push=send_push,
            use_async=False,
        )

    @classmethod
    def notify_poll_milestone(
        cls, poll, milestone_type: str, count: int, send_push=True, use_async=True
    ):
        """Notify poll owner when their poll reaches a milestone"""
        if use_async:
            from keyopolls.notifications.tasks import notify_poll_milestone_task

            return notify_poll_milestone_task.delay(
                poll.id, milestone_type, count, send_push
            )

        return cls._notify_poll_milestone_sync(poll, milestone_type, count, send_push)

    @classmethod
    def _notify_poll_milestone_sync(
        cls, poll, milestone_type: str, count: int, send_push=True
    ):
        """Synchronous version of poll milestone notification"""
        poll_owner = poll.profile
        if not poll_owner:
            return None

        if not cls._should_send_milestone(poll_owner, milestone_type, count):
            return None

        milestone_messages = {
            NotificationType.VOTE_MILESTONE: f"🗳️ Your poll reached {count} votes!",
            NotificationType.LIKE_MILESTONE: f"🎉 Your poll reached {count} likes!",
            NotificationType.SHARE_MILESTONE: f"🚀 Your poll was shared {count} times!",
            NotificationType.BOOKMARK_MILESTONE: (
                f"📚 Your poll was bookmarked {count} times!"
            ),
            NotificationType.VIEW_MILESTONE: f"👀 Your poll reached {count} views!",
            NotificationType.REPLIES_MILESTONE: (
                f"💬 Your poll received {count} comments!"
            ),
        }

        click_url = URLBuilder.build_poll_url(poll.id)
        deep_link_data = URLBuilder.build_deep_link_data("poll", {"poll_id": poll.id})

        return cls.send_notification(
            recipient=poll_owner,
            notification_type=milestone_type,
            title="Milestone Reached!",
            message=milestone_messages.get(
                milestone_type, f"Your poll reached {count}!"
            ),
            target=poll,
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
            from keyopolls.notifications.tasks import notify_comment_reply_task

            return notify_comment_reply_task.delay(
                comment.id, reply.id, actor.id, send_push
            )

        return cls._notify_comment_reply_sync(comment, reply, actor, send_push)

    @classmethod
    def _notify_comment_reply_sync(cls, comment, reply, actor, send_push=True):
        """Synchronous version of comment reply notification"""
        comment_owner = comment.profile
        if not comment_owner or comment_owner.id == actor.id:
            return None

        actor_name = cls._get_actor_name(actor)

        # Get the poll this comment belongs to
        poll = cls._get_comment_poll(comment)
        if not poll:
            return None

        click_url = URLBuilder.build_comment_url(poll.id, reply.id)
        deep_link_data = URLBuilder.build_deep_link_data(
            "poll",
            {
                "poll_id": poll.id,
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
            from keyopolls.notifications.tasks import notify_comment_milestone_task

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
        comment_owner = comment.profile
        if not comment_owner:
            return None

        if not cls._should_send_milestone(comment_owner, milestone_type, count):
            return None

        poll = cls._get_comment_poll(comment)
        if not poll:
            return None

        click_url = URLBuilder.build_comment_url(poll.id, comment.id)
        deep_link_data = URLBuilder.build_deep_link_data(
            "poll", {"poll_id": poll.id, "comment_id": comment.id}
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
            from keyopolls.notifications.tasks import notify_follow_task

            return notify_follow_task.delay(follower.id, followee.id, send_push)

        return cls._notify_follow_sync(follower, followee, send_push)

    @classmethod
    def _notify_follow_sync(cls, follower, followee, send_push=True):
        """Synchronous version of follow notification"""
        if follower.id == followee.id:
            return None

        actor_name = cls._get_actor_name(follower)

        click_url = URLBuilder.build_profile_url(follower.username)
        deep_link_data = URLBuilder.build_deep_link_data(
            "profile", {"username": follower.username}
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
            from keyopolls.notifications.tasks import notify_follower_milestone_task

            return notify_follower_milestone_task.delay(user.id, count, send_push)

        return cls._notify_follower_milestone_sync(user, count, send_push)

    @classmethod
    def _notify_follower_milestone_sync(cls, user, count: int, send_push=True):
        """Synchronous version of follower milestone notification"""
        if not cls._should_send_milestone(
            user, NotificationType.FOLLOWER_MILESTONE, count
        ):
            return None

        click_url = URLBuilder.build_followers_url(user.username)
        deep_link_data = URLBuilder.build_deep_link_data(
            "followers", {"username": user.username}
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
        """Notify user when they are mentioned in a poll or comment"""
        if use_async:
            from keyopolls.notifications.tasks import notify_mention_task

            target_type = target._meta.model_name
            return notify_mention_task.delay(
                mentioned_user.id,
                actor.id,
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

        # Determine if it's a poll or comment mention
        if hasattr(target, "title") and hasattr(target, "poll_type"):
            # It's a poll
            target_type = "poll"
            click_url = URLBuilder.build_poll_url(target.id)
            deep_link_data = URLBuilder.build_deep_link_data(
                "poll", {"poll_id": target.id, "highlight": "mention"}
            )
            message = f"{actor_name} mentioned you in a poll"
        else:
            # It's a comment
            target_type = "comment"
            poll = cls._get_comment_poll(target)
            if not poll:
                return None
            click_url = URLBuilder.build_comment_url(poll.id, target.id)
            deep_link_data = URLBuilder.build_deep_link_data(
                "poll",
                {"poll_id": poll.id, "comment_id": target.id, "highlight": "mention"},
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

    # === COMMUNITY NOTIFICATIONS ===

    @classmethod
    def notify_community_new_poll(
        cls, community, poll, send_push=False, use_async=True
    ):
        """Notify community members when a new poll is created"""
        if use_async:
            from keyopolls.notifications.tasks import notify_community_new_poll_task

            return notify_community_new_poll_task.delay(
                community.id, poll.id, send_push
            )

        return cls._notify_community_new_poll_sync(community, poll, send_push)

    @classmethod
    def _notify_community_new_poll_sync(cls, community, poll, send_push=False):
        """Synchronous version of community new poll notification"""
        from keyopolls.communities.models import CommunityMembership

        members = (
            CommunityMembership.objects.filter(community=community, status="active")
            .exclude(profile=poll.profile)
            .select_related("profile")
        )

        notifications_sent = []
        poll_author_name = cls._get_actor_name(poll.profile)

        for membership in members:
            member = membership.profile

            click_url = URLBuilder.build_poll_url(poll.id)
            deep_link_data = URLBuilder.build_deep_link_data(
                "poll", {"poll_id": poll.id, "source": "community"}
            )

            notification = cls.send_notification(
                recipient=member,
                notification_type=NotificationType.COMMUNITY_NEW_POLL,
                title=f"New Poll in {community.name}",
                message=f"{poll_author_name} created a new poll: {poll.title}",
                actor=poll.profile,
                target=poll,
                click_url=click_url,
                deep_link_data=deep_link_data,
                extra_data={
                    "community_id": community.id,
                    "community_name": community.name,
                },
                send_push=send_push,
                use_async=False,
            )

            notifications_sent.append(notification)

        return notifications_sent

    @classmethod
    def notify_community_invite(
        cls, community, inviter, invitee, send_push=True, use_async=True
    ):
        """Notify user when they are invited to join a community"""
        if use_async:
            from keyopolls.notifications.tasks import notify_community_invite_task

            return notify_community_invite_task.delay(
                community.id, inviter.id, invitee.id, send_push
            )

        return cls._notify_community_invite_sync(community, inviter, invitee, send_push)

    @classmethod
    def _notify_community_invite_sync(cls, community, inviter, invitee, send_push=True):
        """Synchronous version of community invite notification"""
        if inviter.id == invitee.id:
            return None

        inviter_name = cls._get_actor_name(inviter)

        click_url = URLBuilder.build_community_url(community.id)
        deep_link_data = URLBuilder.build_deep_link_data(
            "community", {"community_id": community.id, "action": "join"}
        )

        return cls.send_notification(
            recipient=invitee,
            notification_type=NotificationType.COMMUNITY_INVITE,
            title="Community Invitation",
            message=f"{inviter_name} invited you to join {community.name}",
            actor=inviter,
            target=community,
            click_url=click_url,
            deep_link_data=deep_link_data,
            priority=NotificationPriority.HIGH,
            send_push=send_push,
            use_async=False,
        )

    # === FOLLOW-BASED NOTIFICATIONS ===

    @classmethod
    def notify_followed_user_poll(cls, poll, send_push=False, use_async=True):
        """Notify all followers when someone they follow creates a new poll"""
        if use_async:
            from keyopolls.notifications.tasks import notify_followed_user_poll_task

            return notify_followed_user_poll_task.delay(poll.id, send_push)

        return cls._notify_followed_user_poll_sync(poll, send_push)

    @classmethod
    def _notify_followed_user_poll_sync(cls, poll, send_push=False):
        """Synchronous version of followed user poll notification"""
        poll_author = poll.profile
        if not poll_author:
            return []

        followers = ProfileFollow.objects.filter(
            following=poll_author, is_active=True
        ).select_related("follower")

        notifications_sent = []
        actor_name = cls._get_actor_name(poll_author)

        for follow_relationship in followers:
            follower = follow_relationship.follower

            if follower.id == poll_author.id:
                continue

            click_url = URLBuilder.build_poll_url(poll.id)
            deep_link_data = URLBuilder.build_deep_link_data(
                "poll", {"poll_id": poll.id, "source": "followed_user"}
            )

            notification = cls.send_notification(
                recipient=follower,
                notification_type=NotificationType.FOLLOWED_USER_POLL,
                title="New Poll from Someone You Follow",
                message=f"{actor_name} created a new poll: {poll.title}",
                actor=poll_author,
                target=poll,
                click_url=click_url,
                deep_link_data=deep_link_data,
                send_push=send_push,
                use_async=False,
            )

            notifications_sent.append(notification)

        return notifications_sent

    @classmethod
    def notify_followed_poll_comment(
        cls, poll, comment, actor, send_push=False, use_async=True
    ):
        """Notify users who follow a poll when someone comments on it"""
        if use_async:
            from keyopolls.notifications.tasks import notify_followed_poll_comment_task

            return notify_followed_poll_comment_task.delay(
                poll.id, comment.id, actor.id, send_push
            )

        return cls._notify_followed_poll_comment_sync(poll, comment, actor, send_push)

    @classmethod
    def _notify_followed_poll_comment_sync(cls, poll, comment, actor, send_push=False):
        """Synchronous version of followed poll comment notification"""
        poll_followers = PollFollow.objects.filter(
            poll=poll, is_active=True
        ).select_related("follower")

        if not poll_followers.exists():
            return []

        notifications_sent = []
        actor_name = cls._get_actor_name(actor)

        for poll_follow in poll_followers:
            follower = poll_follow.follower

            # Don't notify the actor or poll owner
            if follower.id == actor.id or follower.id == poll.profile.id:
                continue

            click_url = URLBuilder.build_comment_url(poll.id, comment.id)
            deep_link_data = URLBuilder.build_deep_link_data(
                "poll",
                {
                    "poll_id": poll.id,
                    "comment_id": comment.id,
                    "source": "followed_poll",
                },
            )

            notification = cls.send_notification(
                recipient=follower,
                notification_type=NotificationType.FOLLOWED_POLL_COMMENT,
                title="New Comment on Followed Poll",
                message=f"{actor_name} commented on a poll you're following",
                actor=actor,
                target=poll,
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
            from keyopolls.notifications.tasks import notify_followed_comment_reply_task

            return notify_followed_comment_reply_task.delay(
                comment.id, reply.id, actor.id, send_push
            )

        return cls._notify_followed_comment_reply_sync(comment, reply, actor, send_push)

    @classmethod
    def _notify_followed_comment_reply_sync(
        cls, comment, reply, actor, send_push=False
    ):
        """Synchronous version of followed comment reply notification"""
        comment_followers = CommentFollow.objects.filter(
            comment=comment, is_active=True
        ).select_related("follower")

        if not comment_followers.exists():
            return []

        notifications_sent = []
        actor_name = cls._get_actor_name(actor)

        for comment_follow in comment_followers:
            follower = comment_follow.follower

            # Don't notify the actor or comment owner
            if follower.id == actor.id or follower.id == comment.profile.id:
                continue

            poll = cls._get_comment_poll(comment)
            if not poll:
                continue

            click_url = URLBuilder.build_comment_url(poll.id, reply.id)
            deep_link_data = URLBuilder.build_deep_link_data(
                "poll",
                {
                    "poll_id": poll.id,
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
    def auto_follow_poll(cls, user, poll, interaction_type="comment", use_async=True):
        """Automatically follow a poll when user interacts with it"""
        if use_async:
            from keyopolls.notifications.tasks import auto_follow_poll_task

            return auto_follow_poll_task.delay(user.id, poll.id, interaction_type)

        return cls._auto_follow_poll_sync(user, poll, interaction_type)

    @classmethod
    def _auto_follow_poll_sync(cls, user, poll, interaction_type="comment"):
        """Synchronous version of auto follow poll"""
        if user.id == poll.profile.id:
            return None

        poll_follow, created = PollFollow.objects.get_or_create(
            follower=user,
            poll=poll,
            defaults={"auto_followed": True},
        )

        if not created and not poll_follow.is_active:
            poll_follow.is_active = True
            poll_follow.save()

        return poll_follow

    @classmethod
    def auto_follow_comment(cls, user, comment, use_async=True):
        """Automatically follow a comment when user replies to it"""
        if use_async:
            from keyopolls.notifications.tasks import auto_follow_comment_task

            return auto_follow_comment_task.delay(user.id, comment.id)

        return cls._auto_follow_comment_sync(user, comment)

    @classmethod
    def _auto_follow_comment_sync(cls, user, comment):
        """Synchronous version of auto follow comment"""
        if user.id == comment.profile.id:
            return None

        comment_follow, created = CommentFollow.objects.get_or_create(
            follower=user,
            comment=comment,
            defaults={"auto_followed": True},
        )

        if not created and not comment_follow.is_active:
            comment_follow.is_active = True
            comment_follow.save()

        return comment_follow

    @classmethod
    def unfollow_poll(cls, user, poll):
        """Unfollow a poll"""
        try:
            poll_follow = PollFollow.objects.get(
                follower=user,
                poll=poll,
            )
            poll_follow.is_active = False
            poll_follow.save()
            return True
        except PollFollow.DoesNotExist:
            return False

    @classmethod
    def unfollow_comment(cls, user, comment):
        """Unfollow a comment"""
        try:
            comment_follow = CommentFollow.objects.get(
                follower=user,
                comment=comment,
            )
            comment_follow.is_active = False
            comment_follow.save()
            return True
        except CommentFollow.DoesNotExist:
            return False

    # === HELPER METHODS ===

    @classmethod
    def _get_comment_poll(cls, comment):
        """Get the poll that a comment belongs to"""
        from keyopolls.models import Poll

        # Check if the comment's content_object is a Poll
        if isinstance(comment.content_object, Poll):
            return comment.content_object
        return None

    @classmethod
    def _get_actor_name(cls, actor):
        """Get display name for actor"""
        if hasattr(actor, "display_name") and actor.display_name:
            return actor.display_name
        elif hasattr(actor, "username") and actor.username:
            return f"@{actor.username}"
        else:
            return "Someone"

    @classmethod
    def _should_send_milestone(cls, recipient, milestone_type: str, count: int) -> bool:
        """Check if milestone notification should be sent based on user preferences"""
        try:
            preference = NotificationPreference.objects.get(
                profile=recipient,
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
        try:
            preference = NotificationPreference.objects.get(
                profile=notification.recipient,
                notification_type=notification.notification_type,
            )

            push_enabled = preference.push_enabled
            email_enabled = preference.email_enabled

        except NotificationPreference.DoesNotExist:
            push_enabled = True
            email_enabled = True

        if send_push and push_enabled:
            if use_async:
                from keyopolls.notifications.tasks import send_push_notification_task

                send_push_notification_task.delay(notification.id)
            else:
                cls._send_push_notification(notification)

        if send_email and email_enabled:
            if use_async:
                from keyopolls.notifications.tasks import send_email_notification_task

                send_email_notification_task.delay(notification.id)
            else:
                cls._send_email_notification(notification)

    @classmethod
    def _send_push_notification(cls, notification: Notification):
        """Send push notification using FCM service"""
        try:
            import logging

            from keyopolls.notifications.fcm_services import FCMService

            logger = logging.getLogger(__name__)

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
                    f"{notification.recipient.username}: {result['message']}"
                )
            else:
                logger.warning(
                    f"Push notification failed for "
                    f"{notification.recipient.username}: {result['message']}"
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
        """Send email notification using communication service"""
        try:
            import logging

            from keyopolls.profile.services import CommunicationService

            logger = logging.getLogger(__name__)

            # Check if recipient has an email address
            if not notification.recipient.email:
                logger.info(
                    f"Skipping email notification for profile "
                    f"{notification.recipient.username} - no email address"
                )
                return

            # Get recipient info
            recipient_email = notification.recipient.email
            recipient_name = (
                notification.recipient.display_name
                or f"@{notification.recipient.username}"
            )

            # Prepare email subject based on notification type
            subject_map = {
                "poll_comment": "💬 New comment on your poll",
                "poll_vote": "🗳️ Someone voted on your poll",
                "reply": "↩️ New reply to your comment",
                "follow": "👋 You have a new follower",
                "mention": "📢 You were mentioned",
                "vote_milestone": "🗳️ Your poll is getting votes!",
                "like_milestone": "🎉 Milestone reached!",
                "share_milestone": "🚀 Your poll is trending!",
                "bookmark_milestone": "📚 People love your content!",
                "view_milestone": "👀 Your poll is getting views!",
                "follower_milestone": "🌟 Congratulations on your followers!",
                "community_new_poll": "📊 New poll in your community",
                "community_invite": "🏘️ Community invitation",
                "followed_user_poll": "📊 New poll from someone you follow",
                "verification": "✅ Verification complete",
                "welcome": "🎊 Welcome!",
            }

            email_subject = subject_map.get(
                notification.notification_type, f"🔔 {notification.title}"
            )

            # Send email using the CommunicationService
            success = CommunicationService.send_notification_email(
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


# Convenience wrapper functions for easy usage
def notify_poll_comment(poll, comment, actor, send_push=True):
    """Convenience function for poll comment notifications"""
    return AsyncNotificationService.notify_poll_comment(poll, comment, actor, send_push)


def notify_poll_vote(poll, voter, option, send_push=True):
    """Convenience function for poll vote notifications"""
    return AsyncNotificationService.notify_poll_vote(poll, voter, option, send_push)


def notify_comment_reply(comment, reply, actor, send_push=True):
    """Convenience function for comment reply notifications"""
    return AsyncNotificationService.notify_comment_reply(
        comment, reply, actor, send_push
    )


def notify_follow(follower, followee, send_push=True):
    """Convenience function for follow notifications"""
    return AsyncNotificationService.notify_follow(follower, followee, send_push)


def notify_mention(mentioned_user, actor, target, send_push=True):
    """Convenience function for mention notifications"""
    return AsyncNotificationService.notify_mention(
        mentioned_user, actor, target, send_push
    )


def notify_community_new_poll(community, poll, send_push=False):
    """Convenience function for community new poll notifications"""
    return AsyncNotificationService.notify_community_new_poll(
        community, poll, send_push
    )


def notify_community_invite(community, inviter, invitee, send_push=True):
    """Convenience function for community invite notifications"""
    return AsyncNotificationService.notify_community_invite(
        community, inviter, invitee, send_push
    )


def auto_follow_poll(user, poll, interaction_type="comment"):
    """Convenience function for auto-following polls"""
    return AsyncNotificationService.auto_follow_poll(user, poll, interaction_type)


def auto_follow_comment(user, comment):
    """Convenience function for auto-following comments"""
    return AsyncNotificationService.auto_follow_comment(user, comment)


def notify_milestone(target, milestone_type, count, send_push=True):
    """Convenience function for milestone notifications"""
    if hasattr(target, "title"):  # It's a poll
        return AsyncNotificationService.notify_poll_milestone(
            target, milestone_type, count, send_push
        )
    else:  # It's a comment
        return AsyncNotificationService.notify_comment_milestone(
            target, milestone_type, count, send_push
        )
