import logging
from typing import List

from django.db import models, transaction
from django.http import HttpRequest
from django.utils import timezone
from ninja import File, Router, UploadedFile
from ninja.errors import ValidationError

from keyopolls.common.schemas import Message
from keyopolls.communities.models import Community, CommunityMembership
from keyopolls.polls.models import Poll, PollOption
from keyopolls.polls.schemas import (
    PollCreateError,
    PollCreateSchema,
    PollDetails,
    PollUpdateSchema,
)
from keyopolls.polls.services.content_moderation import ContentModerationService
from keyopolls.profile.middleware import PseudonymousJWTAuth
from keyopolls.utils.contentUtils import increment_aura

logger = logging.getLogger(__name__)
router = Router(tags=["Polls"], auth=PseudonymousJWTAuth())


@router.post(
    "/polls",
    response={
        201: PollDetails,
        400: PollCreateError,
        403: PollCreateError,
    },
)
def create_poll(
    request: HttpRequest,
    data: PollCreateSchema,
    option_images: List[UploadedFile] = File(None),
):
    """Create a new poll in a community"""
    profile = request.auth

    try:
        # Validate community exists and user can post
        try:
            community = Community.objects.get(id=data.community_id, is_active=True)
        except Community.DoesNotExist:
            return 400, {"message": "Community not found"}

        # Handle membership logic based on community type
        membership = None
        if community.community_type == "public":
            # For public communities, check if user can post directly
            if not community.can_post(profile):
                return 403, {
                    "message": f"You need at least {community.requires_aura_to_post} "
                    "aura to post in this community"
                }

            # Check if user is already a member
            try:
                membership: CommunityMembership = community.memberships.get(
                    profile=profile
                )
                if not membership.is_active_member:
                    # User exists but not active (banned/left), they cannot post
                    return 403, {
                        "message": "You are not allowed to post in this community"
                    }
            except CommunityMembership.DoesNotExist:
                # Will create membership after poll creation
                pass

        else:
            # For private/restricted communities, membership is required
            try:
                membership = community.memberships.get(profile=profile)
                if not membership.is_active_member:
                    return 403, {
                        "message": "You must be an active member to create polls"
                    }
            except CommunityMembership.DoesNotExist:
                return 403, {
                    "message": "You must be a member of this community to create polls"
                }

            # Check if user can post in community
            if not community.can_post(profile):
                return 403, {
                    "message": f"You need at least {community.requires_aura_to_post} "
                    "aura to post in this community"
                }

        # Validate poll data
        if data.poll_type not in ["single", "multiple", "ranking", "text_input"]:
            return 400, {"message": "Invalid poll type"}

        # Validate options based on poll type
        if data.poll_type == "text_input":
            if data.options:
                return 400, {
                    "message": "Text input polls cannot have predefined options"
                }
            # Don't validate multiple votes settings for text input - we'll ignore them
        else:
            # Option-based polls
            if len(data.options) < 2:
                return 400, {"message": "Poll must have at least 2 options"}
            if len(data.options) > 10:  # Increased limit
                return 400, {"message": "Poll cannot have more than 10 options"}

        # Validate multiple choice settings
        if data.poll_type == "multiple":
            if data.max_choices and data.max_choices > len(data.options):
                return 400, {"message": "max_choices cannot exceed number of options"}

        # Validate correct answers
        if data.has_correct_answer:
            if data.poll_type == "text_input":
                if not data.correct_text_answer:
                    return 400, {
                        "message": (
                            "Text input polls with correct answers must specify "
                            "correct_text_answer"
                        )
                    }
                if " " in data.correct_text_answer.strip():
                    return 400, {"message": "Correct text answer cannot contain spaces"}

            elif data.poll_type == "ranking":
                if not data.correct_ranking_order:
                    return 400, {
                        "message": (
                            "Ranking polls with correct answers must specify "
                            "correct_ranking_order"
                        )
                    }
                if len(data.correct_ranking_order) != len(data.options):
                    return 400, {
                        "message": "Correct ranking order must include all options"
                    }
                # Validate that all option orders are included
                option_orders = {opt.order for opt in data.options}
                if set(data.correct_ranking_order) != option_orders:
                    return 400, {
                        "message": (
                            "Correct ranking order must include all option orders "
                            "exactly once"
                        )
                    }

            elif data.poll_type in ["single", "multiple"]:
                correct_options = [opt for opt in data.options if opt.is_correct]
                if not correct_options:
                    return 400, {
                        "message": (
                            f"{data.poll_type.title()} choice polls with correct "
                            "answers must have at least one correct option"
                        )
                    }
                if data.poll_type == "single" and len(correct_options) > 1:
                    return 400, {
                        "message": (
                            "Single choice polls can only have one correct option"
                        )
                    }

        # Validate option images
        if option_images:
            if data.poll_type == "text_input":
                if len(option_images) > 1:
                    return 400, {"message": "Text input polls can only have one image"}
            else:
                if len(option_images) > len(data.options):
                    return 400, {"message": "Too many images provided for options"}

        # Check daily poll limit (10 polls per day per community).
        # This now includes all attempts.
        today = timezone.now().date()
        daily_poll_count = Poll.objects.filter(
            profile=profile, community=community, created_at__date=today
        ).count()  # This now includes rejected polls

        if daily_poll_count >= 3:
            return 400, {
                "message": "You can only create 3 polls per day in this community"
            }

        # Use database transaction
        with transaction.atomic():
            # For public communities, auto-join user if they're not already a member
            if community.community_type == "public" and membership is None:
                membership = CommunityMembership.objects.create(
                    community=community, profile=profile, role="member", status="active"
                )
                # Update community member count
                community.member_count = models.F("member_count") + 1
                community.save(update_fields=["member_count"])

            # Prepare poll creation data based on poll type
            poll_data = {
                "title": data.title.strip(),
                "description": data.description.strip() if data.description else "",
                "poll_type": data.poll_type,
                "community": community,
                "profile": profile,
                "requires_aura": data.requires_aura,
                "expires_at": data.expires_at,
                "has_correct_answer": data.has_correct_answer,
                "option_count": (
                    len(data.options) if data.poll_type != "text_input" else 0
                ),
                "status": "pending_moderation",  # NEW: Start with pending status
            }

            # Add poll-type-specific fields
            if data.poll_type == "text_input":
                # For text input polls, only add relevant fields
                if data.has_correct_answer and data.correct_text_answer:
                    poll_data["correct_text_answer"] = data.correct_text_answer.strip()
            elif data.poll_type == "multiple":
                # For multiple choice polls
                poll_data["allow_multiple_votes"] = data.allow_multiple_votes
                poll_data["max_choices"] = data.max_choices
            elif data.poll_type == "ranking":
                # For ranking polls
                if data.has_correct_answer and data.correct_ranking_order:
                    poll_data["correct_ranking_order"] = data.correct_ranking_order

            # Create the poll (with pending_moderation status)
            poll = Poll.objects.create(**poll_data)

            # Handle images for text input polls
            if data.poll_type == "text_input" and option_images:
                # For text input polls, store the image in the poll's description
                # or a separate field (assuming you have a poll.image field)
                # For now, we'll assume you have a poll.image field
                poll.image = option_images[0]
                poll.save()

            # Create poll options (only for non-text-input polls)
            if data.poll_type != "text_input":
                for i, option_data in enumerate(data.options):
                    option = PollOption.objects.create(
                        poll=poll,
                        text=option_data.text.strip(),
                        order=option_data.order,
                        is_correct=(
                            option_data.is_correct if data.has_correct_answer else False
                        ),
                    )

                    # Add image if provided
                    if option_images and i < len(option_images):
                        option.image = option_images[i]
                        option.save()

            # NEW: CONTENT MODERATION AFTER POLL CREATION
            try:
                # Initialize content moderation service
                moderation_service = ContentModerationService()

                # Get community rules and category information
                community_rules = getattr(community, "rules", []) or []
                category_name = (
                    community.category.name if community.category else "General"
                )
                category_description = (
                    community.category.description
                    if community.category
                    else "General category"
                )

                # Run content moderation
                is_approved, reason, detailed_analysis = (
                    moderation_service.evaluate_poll_content(
                        poll_title=poll.title,
                        poll_description=poll.description,
                        community_name=community.name,
                        community_description=community.description,
                        community_rules=community_rules,
                        category_name=category_name,
                        category_description=category_description,
                        community_type=community.community_type,
                        option_images=option_images,
                    )
                )

                if is_approved:
                    # Approve the poll
                    poll.approve_poll()

                    # Update community poll count only for approved polls
                    community.poll_count = models.F("poll_count") + 1
                    community.save(update_fields=["poll_count"])

                    # NEW: Increment user's poll aura by 1 point for successful
                    #  poll creation
                    try:
                        aura_result = increment_aura(profile, "polls", 1)
                        logger.info(
                            f"Aura incremented for user {profile.id} after poll "
                            f"creation: {aura_result}"
                        )
                    except Exception as aura_error:
                        # Log the error but don't fail the poll creation
                        logger.error(
                            f"Failed to increment aura for user {profile.id}: "
                            f"{str(aura_error)}"
                        )

                    # Refresh poll with options
                    poll.refresh_from_db()

                    return 201, PollDetails.resolve(poll, profile)
                else:
                    # Reject the poll but keep it in database
                    poll.reject_poll(reason)

                    # Log the rejection for audit
                    logger.info(
                        f"Poll {poll.id} rejected by moderation: {reason}",
                        extra={
                            "poll_id": poll.id,
                            "profile_id": profile.id,
                            "community_id": community.id,
                            "detailed_analysis": detailed_analysis,
                        },
                    )

                    return 400, {
                        "message": f"Poll content not approved: {reason}",
                        "poll_id": poll.id,  # For audit purposes
                    }

            except Exception as moderation_error:
                # If moderation service fails, reject the poll
                logger.error(
                    (
                        f"Content moderation failed for poll {poll.id}: "
                        f"{str(moderation_error)}"
                    ),
                    exc_info=True,
                )
                poll.reject_poll(f"Moderation service error: {str(moderation_error)}")

                return 400, {
                    "message": "Content moderation failed. Please try again later.",
                    "poll_id": poll.id,
                }

    except ValidationError as e:
        logger.error(f"Validation error: {str(e)}")
        return 400, {"message": str(e)}
    except Exception as e:
        logger.error(f"Error creating poll: {str(e)}", exc_info=True)
        return 400, {
            "message": "An error occurred while creating the poll",
        }


@router.put(
    "/polls/{poll_id}",
    response={
        200: PollDetails,
        400: Message,
        403: Message,
        404: Message,
    },
)
def update_poll(request: HttpRequest, poll_id: int, data: PollUpdateSchema):
    """Update poll title and description only"""
    profile = request.auth

    try:
        # Get the poll
        try:
            poll = Poll.objects.get(id=poll_id, is_deleted=False)
        except Poll.DoesNotExist:
            return 404, {"message": "Poll not found"}

        # Check if user is the author
        if poll.profile.id != profile.id:
            return 403, {"message": "You can only edit your own polls"}

        # Validate title
        if not data.title.strip():
            return 400, {"message": "Title cannot be empty"}

        # Update only title and description
        poll.title = data.title.strip()
        poll.description = data.description.strip()
        poll.save(update_fields=["title", "description", "updated_at"])

        return 200, PollDetails.resolve(poll, profile)

    except Exception as e:
        logger.error(f"Error updating poll {poll_id}: {str(e)}", exc_info=True)
        return 400, {
            "success": False,
            "error": "An error occurred while updating the poll",
        }


@router.delete(
    "/polls/{poll_id}",
    response={
        200: Message,
        400: Message,
        403: Message,
        404: Message,
    },
)
def delete_poll(request: HttpRequest, poll_id: int):
    """Soft delete a poll"""
    profile = request.auth

    try:
        # Get the poll
        try:
            poll = Poll.objects.get(id=poll_id, is_deleted=False)
        except Poll.DoesNotExist:
            return 404, {"message": "Poll not found"}

        # Check if user is the author or community moderator
        is_author = poll.profile.id == profile.id
        is_moderator = False

        try:
            membership = poll.community.memberships.get(profile=profile)
            is_moderator = membership.can_moderate
        except CommunityMembership.DoesNotExist:
            pass

        if not (is_author or is_moderator):
            return 403, {
                "message": "You can only delete your own polls or moderate "
                "community polls",
            }

        # Soft delete the poll
        poll.is_deleted = True
        poll.status = "archived"
        poll.save(update_fields=["is_deleted", "status", "updated_at"])

        # Decrement community poll count
        poll.community.poll_count = models.F("poll_count") - 1
        poll.community.save(update_fields=["poll_count"])

        return 200, {"message": "Poll deleted successfully"}

    except Exception as e:
        logger.error(f"Error deleting poll {poll_id}: {str(e)}", exc_info=True)
        return 400, {
            "message": "An error occurred while deleting the poll",
        }


# Helper function to check poll ownership
def check_poll_ownership(poll: Poll, profile) -> bool:
    """Check if profile owns the poll"""
    return poll.profile.id == profile.id


# Validation helpers
def validate_poll_images(images: List[UploadedFile]) -> tuple[bool, str]:
    """Validate uploaded images for poll options"""
    if not images:
        return True, ""

    # Check file size (max 5MB per image)
    MAX_SIZE = 5 * 1024 * 1024  # 5MB
    for image in images:
        if image.size > MAX_SIZE:
            return False, f"Image {image.name} is too large. Maximum size is 5MB"

    # Check file type
    ALLOWED_TYPES = ["image/jpeg", "image/png", "image/gif", "image/webp"]
    for image in images:
        if image.content_type not in ALLOWED_TYPES:
            return (
                False,
                f"Invalid image type for {image.name}. Allowed: JPEG, PNG, GIF, WebP",
            )

    return True, ""
