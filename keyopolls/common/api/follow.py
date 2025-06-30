import logging
from datetime import datetime, timedelta
from typing import List, Literal, Optional

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest
from django.utils import timezone
from keyoconnect.common.models import Follow
from keyoconnect.common.schemas import FollowResponse
from keyoconnect.connect_notifications.notification_utils import (
    notify_follow,
    notify_follower_milestone,
)
from keyoconnect.profiles.middleware import PublicJWTAuth
from keyoconnect.profiles.models import PublicProfile
from ninja import Router, Schema
from shared.schemas import Message, PaginationSchema

logger = logging.getLogger(__name__)


router = Router(tags=["Connect Follow Profiles"])


def get_public_profile(profile_id: int):
    """Get a public profile by ID"""
    try:
        return PublicProfile.objects.get(id=profile_id)
    except PublicProfile.DoesNotExist:
        raise ObjectDoesNotExist(f"Public profile with ID {profile_id} not found")


def validate_follow_relationship(follower_profile, followee_profile):
    """Validate if the follow relationship is allowed"""
    # Prevent self-following
    if follower_profile.id == followee_profile.id:
        raise ValidationError("A profile cannot follow itself")

    # Note: Since we're using standalone PublicProfiles now,
    # we don't need to check for same member relationships


def get_follow_relationship(follower_profile, followee_profile):
    """Get existing follow relationship if it exists"""
    try:
        return Follow.objects.get(
            follower=follower_profile,
            followee=followee_profile,
        )
    except Follow.DoesNotExist:
        return None


@router.post(
    "/follow",
    response={200: FollowResponse, 400: Message, 404: Message},
    auth=PublicJWTAuth(),
)
def follow_unfollow_profile(
    request: HttpRequest,
    action: Literal["follow", "unfollow"],
    followee_profile_id: int,
):
    """
    Follow or unfollow a public profile.

    Parameters:
    - action: "follow" or "unfollow"
    - followee_profile_id: ID of the public profile to follow/unfollow
    """
    # Get the authenticated public profile directly
    follower_profile: PublicProfile = request.auth

    try:
        # Get the profile to follow/unfollow
        followee_profile = get_public_profile(followee_profile_id)

        # Validate the follow relationship
        validate_follow_relationship(follower_profile, followee_profile)

        # Get existing follow relationship
        existing_follow = get_follow_relationship(follower_profile, followee_profile)

        with transaction.atomic():
            if action == "follow":
                if existing_follow:
                    if existing_follow.is_active:
                        return 400, {
                            "message": "You are already following this profile"
                        }
                    else:
                        # Reactivate the follow relationship
                        existing_follow.is_active = True
                        existing_follow.save()
                        message = "Successfully resumed following this profile"
                else:
                    # Create new follow relationship
                    Follow.objects.create(
                        follower=follower_profile,
                        followee=followee_profile,
                        is_active=True,
                        notify_on_posts=True,
                    )
                    message = "Successfully followed this profile"

                is_following = True

                # === NOTIFICATION TRIGGERS FOR FOLLOW ===
                # 1. Follow notification: Notify the followee about new follower
                notify_follow(follower_profile, followee_profile, send_push=True)

                # 2. Update and check follower milestone for followee
                # First refresh the followee's follower count
                followee_profile.refresh_from_db()
                current_follower_count = followee_profile.follower_count

                # Check if they reached a follower milestone
                notify_follower_milestone(
                    followee_profile, current_follower_count, send_push=True
                )

                # === END NOTIFICATION TRIGGERS ===

            elif action == "unfollow":
                if not existing_follow or not existing_follow.is_active:
                    return 400, {"message": "You are not following this profile"}

                # Soft delete - set is_active to False
                existing_follow.is_active = False
                existing_follow.save()
                message = "Successfully unfollowed this profile"
                is_following = False

                # Note: No notifications needed for unfollow action

            else:
                return 400, {
                    "message": "Invalid action. Must be 'follow' or 'unfollow'"
                }

        return 200, {
            "success": True,
            "message": message,
            "is_following": is_following,
            "follower_count": follower_profile.follower_count,
            "following_count": follower_profile.following_count,
        }

    except ObjectDoesNotExist as e:
        return 404, {"message": str(e)}
    except ValidationError as e:
        return 400, {"message": str(e)}
    except Exception as e:
        logger.error(f"Error in follow/unfollow operation: {str(e)}", exc_info=True)
        return 400, {
            "message": "An error occurred while processing the follow/unfollow request"
        }


@router.get(
    "/follow/status/{profile_id}",
    response={200: dict, 404: Message},
    auth=PublicJWTAuth(),
)
def get_follow_status(
    request: HttpRequest,
    profile_id: int,
):
    """
    Check if the authenticated user is following a specific public profile.

    Parameters:
    - profile_id: ID of the public profile to check
    """
    # Get the authenticated public profile directly
    follower_profile: PublicProfile = request.auth

    try:
        # Get the profile to check
        target_profile = get_public_profile(profile_id)

        # Check if follow relationship exists and is active
        existing_follow = get_follow_relationship(follower_profile, target_profile)
        is_following = existing_follow and existing_follow.is_active

        return 200, {
            "is_following": is_following,
            "follower_profile_counts": {
                "follower_count": follower_profile.follower_count,
                "following_count": follower_profile.following_count,
            },
            "target_profile_counts": {
                "follower_count": target_profile.follower_count,
            },
        }

    except ObjectDoesNotExist as e:
        return 404, {"message": str(e)}
    except Exception as e:
        logger.error(f"Error checking follow status: {str(e)}", exc_info=True)
        return 400, {"message": "An error occurred while checking follow status"}


class FollowerProfileSchema(Schema):
    """Schema for follower profile data"""

    profile_id: int
    display_name: str
    handle: str
    bio: Optional[str]
    follower_count: int
    following_count: int
    is_real_human: bool
    profile_picture: Optional[str]
    followed_at: str
    days_following: int


class FollowingProfileSchema(Schema):
    """Schema for following profile data"""

    profile_id: int
    display_name: str
    handle: str
    bio: Optional[str]
    follower_count: int
    following_count: int
    is_real_human: bool
    profile_picture: Optional[str]
    followed_at: str
    days_following: int
    is_mutual: bool


class ProfileInfoSchema(Schema):
    """Schema for profile info in response"""

    profile_id: int
    display_name: str
    handle: str
    total_followers: Optional[int] = None
    total_following: Optional[int] = None


class FollowersPaginationSchema(Schema):
    """Schema for followers pagination"""

    current_page: int
    page_size: int
    total_followers: int
    total_pages: int
    has_next: bool
    has_previous: bool


class FollowingPaginationSchema(Schema):
    """Schema for following pagination"""

    current_page: int
    page_size: int
    total_following: int
    total_pages: int
    has_next: bool
    has_previous: bool


class FollowersMetaSchema(Schema):
    """Schema for followers metadata"""

    filters_applied: dict
    filtered_count: int


class FollowersResponseSchema(Schema):
    """Response schema for followers list"""

    followers: List[FollowerProfileSchema]
    pagination: PaginationSchema
    profile_info: ProfileInfoSchema
    meta: Optional[FollowersMetaSchema] = None


class FollowingResponseSchema(Schema):
    """Response schema for following list"""

    following: List[FollowingProfileSchema]
    pagination: PaginationSchema
    profile_info: ProfileInfoSchema
    meta: Optional[FollowersMetaSchema] = None


@router.get(
    "/followers/{handle}",
    response=FollowersResponseSchema,
    auth=PublicJWTAuth(),
)
def get_followers(
    request: HttpRequest,
    handle: str,
    # === SEARCH & FILTERING ===
    search: Optional[str] = None,
    verified_only: Optional[bool] = None,
    has_bio: Optional[bool] = None,
    min_followers: Optional[int] = None,
    # === TIME-BASED FILTERS ===
    followed_after: Optional[str] = None,
    followed_before: Optional[str] = None,
    recent_followers: Optional[bool] = None,
    # === SORTING & PAGINATION ===
    sort_by: Optional[str] = "followed_at",
    sort_order: Optional[str] = "desc",
    page: int = 1,
    page_size: int = 20,
):
    """
    Get followers of a specific public profile with advanced filtering.

    Examples:
    - ?search=john&verified_only=true
    - ?min_followers=100&sort_by=follower_count
    - ?recent_followers=true&sort_by=followed_at
    - ?followed_after=2024-01-01&has_bio=true
    """
    try:
        # Get the target profile
        target_profile = PublicProfile.objects.get(handle=handle)

        # Base queryset with followers
        queryset = Follow.objects.filter(
            followee=target_profile,
            is_active=True,
        ).select_related("follower")

        # === SEARCH FILTERS ===
        if search:
            search_query = Q(follower__display_name__icontains=search) | Q(
                follower__handle__icontains=search
            )
            queryset = queryset.filter(search_query)

        # === PROFILE QUALITY FILTERS ===
        if verified_only is not None:
            queryset = queryset.filter(follower__is_real_human=verified_only)

        if has_bio is not None:
            if has_bio:
                queryset = queryset.exclude(
                    Q(follower__bio__isnull=True) | Q(follower__bio__exact="")
                )
            else:
                queryset = queryset.filter(
                    Q(follower__bio__isnull=True) | Q(follower__bio__exact="")
                )

        if min_followers is not None:
            queryset = queryset.filter(follower__follower_count__gte=min_followers)

        # === TIME-BASED FILTERS ===
        if followed_after:
            try:
                date_after = datetime.strptime(followed_after, "%Y-%m-%d").date()
                queryset = queryset.filter(created_at__date__gte=date_after)
            except ValueError:
                return 400, {
                    "message": "Invalid followed_after date format. Use YYYY-MM-DD"
                }

        if followed_before:
            try:
                date_before = datetime.strptime(followed_before, "%Y-%m-%d").date()
                queryset = queryset.filter(created_at__date__lte=date_before)
            except ValueError:
                return 400, {
                    "message": "Invalid followed_before date format. Use YYYY-MM-DD"
                }

        if recent_followers:
            seven_days_ago = timezone.now() - timedelta(days=7)
            if recent_followers:
                queryset = queryset.filter(created_at__gte=seven_days_ago)
            else:
                queryset = queryset.filter(created_at__lt=seven_days_ago)

        # === SORTING ===
        valid_sort_fields = {
            "followed_at": "created_at",
            "display_name": "follower__display_name",
            "follower_count": "follower__follower_count",
            "following_count": "follower__following_count",
        }

        sort_field = valid_sort_fields.get(sort_by, "created_at")
        order_prefix = "-" if sort_order == "desc" else ""
        queryset = queryset.order_by(f"{order_prefix}{sort_field}")

        # === PAGINATION ===
        total_followers = queryset.count()
        offset = (page - 1) * page_size
        follows_page = queryset[offset : offset + page_size]

        # === FORMAT RESPONSE DATA ===
        followers_data = []
        for follow in follows_page:
            follower_profile = follow.follower
            followers_data.append(
                {
                    "profile_id": follower_profile.id,
                    "display_name": follower_profile.display_name,
                    "handle": follower_profile.handle,
                    "bio": follower_profile.bio,
                    "follower_count": follower_profile.follower_count,
                    "following_count": follower_profile.following_count,
                    "is_real_human": follower_profile.is_real_human,
                    "profile_picture": (
                        follower_profile.profile_picture.url
                        if follower_profile.profile_picture
                        else None
                    ),
                    "followed_at": follow.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "days_following": (
                        timezone.now().date() - follow.created_at.date()
                    ).days,
                }
            )

        # === PAGINATION INFO ===
        total_pages = (total_followers + page_size - 1) // page_size

        response_data = {
            "followers": followers_data,
            "pagination": {
                "current_page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "total_count": total_followers,
                "has_next": page < total_pages,
                "has_previous": page > 1,
                "next_page": page + 1 if page < total_pages else None,
                "previous_page": page - 1 if page > 1 else None,
            },
            "profile_info": {
                "profile_id": target_profile.id,
                "display_name": target_profile.display_name,
                "handle": target_profile.handle,
                "total_followers": target_profile.follower_count,
            },
        }

        # Add filter metadata if any filters were applied
        filters_applied = {
            "search": search,
            "verified_only": verified_only,
            "has_bio": has_bio,
            "min_followers": min_followers,
            "recent_followers": recent_followers,
        }

        if any(v is not None for v in filters_applied.values()):
            response_data["meta"] = {
                "filters_applied": {
                    k: v for k, v in filters_applied.items() if v is not None
                },
                "filtered_count": total_followers,
            }

        return response_data

    except ObjectDoesNotExist:
        return 404, {"message": "Profile not found"}
    except Exception as e:
        logger.error(f"Error getting followers: {str(e)}", exc_info=True)
        return 400, {"message": "An error occurred while getting followers"}


@router.get(
    "/following/{handle}",
    response=FollowingResponseSchema,
    auth=PublicJWTAuth(),
)
def get_following(
    request: HttpRequest,
    handle: str,
    # === SEARCH & FILTERING ===
    search: Optional[str] = None,
    verified_only: Optional[bool] = None,
    has_bio: Optional[bool] = None,
    min_followers: Optional[int] = None,
    mutual_followers: Optional[bool] = None,
    # === TIME-BASED FILTERS ===
    followed_after: Optional[str] = None,
    followed_before: Optional[str] = None,
    recent_following: Optional[bool] = None,
    # === SORTING & PAGINATION ===
    sort_by: Optional[str] = "followed_at",
    sort_order: Optional[str] = "desc",
    page: int = 1,
    page_size: int = 20,
):
    """
    Get profiles that a specific profile is following with advanced filtering.

    Examples:
    - ?search=tech&verified_only=true
    - ?min_followers=1000&sort_by=follower_count
    - ?mutual_followers=true&recent_following=false
    - ?followed_after=2024-01-01&has_bio=true
    """
    try:
        # Get the target profile
        target_profile = PublicProfile.objects.get(handle=handle)

        # Base queryset with following
        queryset = Follow.objects.filter(
            follower=target_profile,
            is_active=True,
        ).select_related("followee")

        # === SEARCH FILTERS ===
        if search:
            search_query = Q(followee__display_name__icontains=search) | Q(
                followee__handle__icontains=search
            )
            queryset = queryset.filter(search_query)

        # === PROFILE QUALITY FILTERS ===
        if verified_only is not None:
            queryset = queryset.filter(followee__is_real_human=verified_only)

        if has_bio is not None:
            if has_bio:
                queryset = queryset.exclude(
                    Q(followee__bio__isnull=True) | Q(followee__bio__exact="")
                )
            else:
                queryset = queryset.filter(
                    Q(followee__bio__isnull=True) | Q(followee__bio__exact="")
                )

        if min_followers is not None:
            queryset = queryset.filter(followee__follower_count__gte=min_followers)

        # === MUTUAL FOLLOWERS FILTER ===
        if mutual_followers is not None:
            # Get IDs of profiles that follow back
            mutual_follow_ids = Follow.objects.filter(
                follower__in=queryset.values_list("followee", flat=True),
                followee=target_profile,
                is_active=True,
            ).values_list("follower_id", flat=True)

            if mutual_followers:
                queryset = queryset.filter(followee_id__in=mutual_follow_ids)
            else:
                queryset = queryset.exclude(followee_id__in=mutual_follow_ids)

        # === TIME-BASED FILTERS ===
        if followed_after:
            try:
                date_after = datetime.strptime(followed_after, "%Y-%m-%d").date()
                queryset = queryset.filter(created_at__date__gte=date_after)
            except ValueError:
                return 400, {
                    "message": "Invalid followed_after date format. Use YYYY-MM-DD"
                }

        if followed_before:
            try:
                date_before = datetime.strptime(followed_before, "%Y-%m-%d").date()
                queryset = queryset.filter(created_at__date__lte=date_before)
            except ValueError:
                return 400, {
                    "message": "Invalid followed_before date format. Use YYYY-MM-DD"
                }

        if recent_following is not None:
            seven_days_ago = timezone.now() - timedelta(days=7)
            if recent_following:
                queryset = queryset.filter(created_at__gte=seven_days_ago)
            else:
                queryset = queryset.filter(created_at__lt=seven_days_ago)

        # === SORTING ===
        valid_sort_fields = {
            "followed_at": "created_at",
            "display_name": "followee__display_name",
            "follower_count": "followee__follower_count",
            "following_count": "followee__following_count",
        }

        sort_field = valid_sort_fields.get(sort_by, "created_at")
        order_prefix = "-" if sort_order == "desc" else ""
        queryset = queryset.order_by(f"{order_prefix}{sort_field}")

        # === PAGINATION ===
        total_following = queryset.count()
        offset = (page - 1) * page_size
        follows_page = queryset[offset : offset + page_size]

        # === CHECK MUTUAL FOLLOWS FOR RESPONSE ===
        # Get all mutual follow relationships for the current page
        followee_ids = [follow.followee_id for follow in follows_page]
        mutual_follow_ids = set(
            Follow.objects.filter(
                follower_id__in=followee_ids, followee=target_profile, is_active=True
            ).values_list("follower_id", flat=True)
        )

        # === FORMAT RESPONSE DATA ===
        following_data = []
        for follow in follows_page:
            followee_profile = follow.followee
            is_mutual = followee_profile.id in mutual_follow_ids

            following_data.append(
                {
                    "profile_id": followee_profile.id,
                    "display_name": followee_profile.display_name,
                    "handle": followee_profile.handle,
                    "bio": followee_profile.bio,
                    "follower_count": followee_profile.follower_count,
                    "following_count": followee_profile.following_count,
                    "is_real_human": followee_profile.is_real_human,
                    "profile_picture": (
                        followee_profile.profile_picture.url
                        if followee_profile.profile_picture
                        else None
                    ),
                    "followed_at": follow.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "days_following": (
                        timezone.now().date() - follow.created_at.date()
                    ).days,
                    "is_mutual": is_mutual,  # Whether they follow back
                }
            )

        # === PAGINATION INFO ===
        total_pages = (total_following + page_size - 1) // page_size

        response_data = {
            "following": following_data,
            "pagination": {
                "current_page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "total_count": total_following,
                "has_next": page < total_pages,
                "has_previous": page > 1,
                "next_page": page + 1 if page < total_pages else None,
                "previous_page": page - 1 if page > 1 else None,
            },
            "profile_info": {
                "profile_id": target_profile.id,
                "display_name": target_profile.display_name,
                "handle": target_profile.handle,
                "total_following": target_profile.following_count,
            },
        }

        # Add filter metadata if any filters were applied
        filters_applied = {
            "search": search,
            "verified_only": verified_only,
            "has_bio": has_bio,
            "min_followers": min_followers,
            "mutual_followers": mutual_followers,
            "recent_following": recent_following,
        }

        if any(v is not None for v in filters_applied.values()):
            response_data["meta"] = {
                "filters_applied": {
                    k: v for k, v in filters_applied.items() if v is not None
                },
                "filtered_count": total_following,
            }

        return response_data

    except ObjectDoesNotExist:
        return 404, {"message": "Profile not found"}
    except Exception as e:
        logger.error(f"Error getting following: {str(e)}", exc_info=True)
        return 400, {"message": "An error occurred while getting following"}
