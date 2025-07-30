import logging
from typing import List

from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.http import HttpRequest
from django.utils import timezone
from django.utils.text import slugify
from ninja import File, Router, UploadedFile
from ninja.errors import ValidationError

from keyopolls.common.models import Tag, TaggedItem
from keyopolls.common.schemas import Message
from keyopolls.communities.models import Community, CommunityMembership
from keyopolls.polls.models import Poll, PollList, PollOption, PollTodo
from keyopolls.polls.schemas import (
    PollCreateError,
    PollCreateSchema,
    PollDetails,
    PollUpdateSchema,
)
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

        # Validate folder if provided
        folder = None
        if data.folder_id:
            try:
                folder = PollList.objects.get(
                    id=data.folder_id,
                    community=community,
                    list_type="folder",
                    is_deleted=False,
                )
            except PollList.DoesNotExist:
                return 400, {"message": "Folder not found or invalid"}

            # Check if user can add polls to this folder
            if not folder.can_add_polls(profile):
                return 403, {
                    "message": "You don't have permission to add polls to this folder"
                }

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

        # Validate explanation field (mandatory)
        if not data.explanation or len(data.explanation.strip()) < 250:
            return 400, {"message": "Explanation must be at least 250 characters"}

        # Validate todos
        if hasattr(data, "todos") and data.todos:
            if len(data.todos) > 5:
                return 400, {"message": "Cannot create more than 5 todos per poll"}

            for todo in data.todos:
                if not todo.text or len(todo.text.strip()) == 0:
                    return 400, {"message": "Todo text cannot be empty"}
                if len(todo.text.strip()) > 400:
                    return 400, {"message": "Todo text cannot exceed 400 characters"}

        # Validate option images
        if option_images:
            if data.poll_type == "text_input":
                if len(option_images) > 1:
                    return 400, {"message": "Text input polls can only have one image"}
            else:
                if len(option_images) > len(data.options):
                    return 400, {"message": "Too many images provided for options"}

        # Validate tags
        if hasattr(data, "tags") and data.tags:
            if len(data.tags) > 5:  # Limit to 5 tags max
                return 400, {"message": "Poll cannot have more than 5 tags"}

            # Validate each tag
            for tag_name in data.tags:
                if not tag_name or len(tag_name.strip()) == 0:
                    return 400, {"message": "Tag name cannot be empty"}
                if len(tag_name.strip()) > 50:
                    return 400, {"message": "Tag name cannot exceed 50 characters"}
                # Check for valid characters (letters, numbers, hyphens, underscores)
                if (
                    not tag_name.replace("-", "")
                    .replace("_", "")
                    .replace(" ", "")
                    .isalnum()
                ):
                    return 400, {
                        "message": f"Tag '{tag_name}' contains invalid characters"
                    }

        # Check daily poll limit (3 polls per day per community)
        today = timezone.now().date()
        daily_poll_count = Poll.objects.filter(
            profile=profile, community=community, created_at__date=today
        ).count()

        if daily_poll_count >= 100:
            return 400, {
                "message": "You can only create 100 polls per day in this community"
            }

        # Check if user is creator or moderator
        is_creator = community.memberships.filter(
            profile=profile, role="creator", status="active"
        ).exists()
        is_moderator = False

        if membership:
            is_moderator = membership.can_moderate

        if not (is_creator or is_moderator):
            return 403, {
                "message": "Only community creators and moderators can create polls"
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

            # Prepare poll creation data
            poll_data = {
                "title": data.title.strip(),
                "description": data.description.strip() if data.description else "",
                "explanation": data.explanation.strip(),
                "poll_type": data.poll_type,
                "community": community,
                "profile": profile,
                "requires_aura": data.requires_aura,
                "has_correct_answer": data.has_correct_answer,
                "option_count": (
                    len(data.options) if data.poll_type != "text_input" else 0
                ),
                "status": "active",  # Direct approval without moderation
            }

            # Add poll-type-specific fields
            if data.poll_type == "text_input":
                # For text input polls, only add relevant fields
                if data.correct_text_answer:
                    poll_data["correct_text_answer"] = data.correct_text_answer.strip()
            elif data.poll_type == "multiple":
                # For multiple choice polls
                poll_data["allow_multiple_votes"] = data.allow_multiple_votes
                poll_data["max_choices"] = data.max_choices
            elif data.poll_type == "ranking":
                # For ranking polls
                if data.correct_ranking_order:
                    poll_data["correct_ranking_order"] = data.correct_ranking_order

            # Create the poll (with active status)
            poll = Poll.objects.create(**poll_data)

            # Handle images for text input polls
            if data.poll_type == "text_input" and option_images:
                # For text input polls, store the image in the poll's image field
                poll.image = option_images[0]
                poll.save()

            # Create poll options (only for non-text-input polls)
            if data.poll_type != "text_input":
                for i, option_data in enumerate(data.options):
                    option = PollOption.objects.create(
                        poll=poll,
                        text=option_data.text.strip(),
                        order=option_data.order,
                        is_correct=(option_data.is_correct),
                    )

                    # Add image if provided
                    if option_images and i < len(option_images):
                        option.image = option_images[i]
                        option.save()

            # Add poll to folder if specified
            if folder:
                # Assign poll to the folder directly
                poll.poll_list = folder
                poll.save(update_fields=["poll_list"])

                # Update folder counts
                folder.update_counts()

            # Create todos
            if hasattr(data, "todos") and data.todos:
                for todo in data.todos:
                    todo_text = todo.text.strip()
                    if todo_text:  # Skip empty todos
                        PollTodo.objects.create(
                            poll=poll, profile=profile, text=todo_text
                        )

            # Handle tags
            if hasattr(data, "tags") and data.tags:
                poll_content_type = ContentType.objects.get_for_model(Poll)

                for tag_name in data.tags:
                    tag_name = tag_name.strip().lower()  # Normalize tag name
                    if tag_name:  # Skip empty tags
                        # Generate slug
                        tag_slug = slugify(tag_name)

                        # Get or create the tag
                        tag, created = Tag.objects.get_or_create(
                            name=tag_name, defaults={"slug": tag_slug}
                        )

                        # Create the TaggedItem relationship
                        TaggedItem.objects.get_or_create(
                            tag=tag,
                            content_type=poll_content_type,
                            object_id=poll.id,
                            community=community,
                        )

            # Update community poll count
            community.poll_count = models.F("poll_count") + 1
            community.save(update_fields=["poll_count"])

            # Increment user's poll aura by 1 point for successful poll creation
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
    """Update poll title, description, explanation, and tags"""
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

        # Validate explanation if provided
        if hasattr(data, "explanation") and data.explanation is not None:
            if len(data.explanation.strip()) < 250:
                return 400, {"message": "Explanation must be at least 250 characters"}

        # Validate tags if provided
        if hasattr(data, "tags") and data.tags:
            if len(data.tags) > 5:
                return 400, {"message": "Poll cannot have more than 5 tags"}

            for tag_name in data.tags:
                if not tag_name or len(tag_name.strip()) == 0:
                    return 400, {"message": "Tag name cannot be empty"}
                if len(tag_name.strip()) > 50:
                    return 400, {"message": "Tag name cannot exceed 50 characters"}
                if (
                    not tag_name.replace("-", "")
                    .replace("_", "")
                    .replace(" ", "")
                    .isalnum()
                ):
                    return 400, {
                        "message": f"Tag '{tag_name}' contains invalid characters"
                    }

        with transaction.atomic():
            # Update basic fields
            poll.title = data.title.strip()
            poll.description = data.description.strip()

            update_fields = ["title", "description", "updated_at"]

            # Update explanation if provided
            if hasattr(data, "explanation") and data.explanation is not None:
                poll.explanation = data.explanation.strip()
                update_fields.append("explanation")

            poll.save(update_fields=update_fields)

            # Handle tags if provided
            if hasattr(data, "tags") and data.tags is not None:
                poll_content_type = ContentType.objects.get_for_model(Poll)

                # Remove existing tags
                TaggedItem.objects.filter(
                    content_type=poll_content_type, object_id=poll.id
                ).delete()

                # Add new tags
                for tag_name in data.tags:
                    tag_name = tag_name.strip().lower()
                    if tag_name:
                        tag_slug = slugify(tag_name)
                        tag, created = Tag.objects.get_or_create(
                            name=tag_name, defaults={"slug": tag_slug}
                        )
                        TaggedItem.objects.get_or_create(
                            tag=tag,
                            content_type=poll_content_type,
                            object_id=poll.id,
                            community=poll.community,
                        )

        return 200, PollDetails.resolve(poll, profile)

    except Exception as e:
        logger.error(f"Error updating poll {poll_id}: {str(e)}", exc_info=True)
        return 400, {
            "message": "An error occurred while updating the poll",
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
