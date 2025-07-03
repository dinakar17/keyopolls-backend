import logging

from django.apps import apps
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router
from shared.schemas import Message

from keyopolls.common.models import Reaction, Share
from keyopolls.common.schemas import (
    ContentTypeEnum,
    ReactionRequest,
    ReactionResponse,
    ShareRequestSchema,
    ShareResponseSchema,
)
from keyopolls.profile.middleware import OptionalPseudonymousJWTAuth
from keyopolls.profile.models import PseudonymousProfile

logger = logging.getLogger(__name__)

router = Router(tags=["Reactions"])


def get_model_class(content_type_str):
    """Get the model class based on content type string"""
    # Map of content type strings to model paths
    content_type_map = {
        ContentTypeEnum.POLL: "Poll",
        ContentTypeEnum.COMMENT: "GenericComment",
        # Add other content types as needed
    }

    if content_type_str not in content_type_map:
        raise ValueError(f"Invalid content type: {content_type_str}")

    model_name = content_type_map[content_type_str]

    # Find the model class in any app
    model_class = None
    for app_config in apps.get_app_configs():
        try:
            model_class = apps.get_model(app_config.label, model_name)
            break
        except LookupError:
            continue

    if model_class is None:
        raise ValueError(f"Model {model_name} not found")

    return model_class


def build_content_filters(content_type, object_id, model_class):
    """Build filters for getting the content object based on type and model"""
    filters = {"id": object_id}

    # Add visibility filters based on model type
    if hasattr(model_class, "is_deleted"):
        filters["is_deleted"] = False

    # For comment models, add additional visibility filters
    if model_class.__name__ == "GenericComment":
        filters["is_taken_down"] = False
        filters["moderation_status"] = "approved"

    # For poll models, add status filter
    if model_class.__name__ == "Poll":
        filters["status"] = "active"

    return filters


def validate_reaction_type(reaction_type):
    """Validate if the reaction type is supported"""
    valid_reactions = dict(Reaction.REACTION_TYPES)
    if reaction_type not in valid_reactions:
        raise ValueError(
            f"Invalid reaction type: {reaction_type}. "
            f"Valid types are: {list(valid_reactions.keys())}"
        )


def get_singular_content_type(content_type):
    """Convert plural content type to singular for response"""
    if content_type.endswith("s") and content_type != "messages":
        return content_type[:-1]
    return content_type


@router.post(
    "/{content_type}/{object_id}/react",
    response={200: ReactionResponse, 404: Message, 401: Message, 400: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def toggle_reaction(
    request: HttpRequest, content_type: str, object_id: int, data: ReactionRequest
):
    """
    Toggle a reaction on any content type using pseudonymous profile.

    All reactions are made using the authenticated user's pseudonymous profile.

    Like and dislike reactions are mutually exclusive:
    - If user likes content that they previously disliked, the dislike is removed
    - If user dislikes content that they previously liked, the like is removed
    - If user clicks the same reaction twice, it gets toggled (removed then added back)

    content_type can be one of:
    - polls
    - comments

    Parameters:
    - content_type: The type of content to react to
    - object_id: The ID of the content object
    - data: ReactionRequest containing reaction_type ("like" or "dislike")
    """
    # Get the authenticated pseudonymous profile
    profile = request.auth if isinstance(request.auth, PseudonymousProfile) else None

    if not profile:
        return 401, {"message": "Authentication required"}

    reaction_type = data.reaction_type

    try:
        # Validate reaction type
        validate_reaction_type(reaction_type)

        # Get the model class for the content type
        model_class = get_model_class(content_type)

        # Build filters for getting the content object
        filters = build_content_filters(content_type, object_id, model_class)

        # Get the content object
        content_obj = model_class.objects.get(**filters)

        # For polls, check if user can vote/react
        if model_class.__name__ == "Poll":
            if not content_obj.can_vote(profile):
                return 400, {"message": "You are not allowed to react to this poll"}

        # Get current user reactions before any changes
        current_user_reactions = Reaction.get_user_reactions(profile, content_obj)

        # Determine the opposite reaction type
        opposite_reaction = "dislike" if reaction_type == "like" else "like"

        # Check if user has the current reaction type
        has_current_reaction = current_user_reactions.get(reaction_type, False)

        # Check if user has the opposite reaction type
        has_opposite_reaction = current_user_reactions.get(opposite_reaction, False)

        # Handle mutually exclusive logic
        if has_current_reaction:
            # User already has this reaction, so remove it (normal toggle)
            action, counts = Reaction.toggle_reaction(
                profile, content_obj, reaction_type
            )
        elif has_opposite_reaction:
            # User has opposite reaction, remove it first, then add new reaction
            # Remove opposite reaction
            Reaction.toggle_reaction(profile, content_obj, opposite_reaction)
            # Add new reaction
            action, counts = Reaction.toggle_reaction(
                profile, content_obj, reaction_type
            )
            # Action should be "added" since we're adding the new reaction
            action = "added"
        else:
            # User has no reaction, simply add the new one
            action, counts = Reaction.toggle_reaction(
                profile, content_obj, reaction_type
            )

        # === NOTIFICATION TRIGGERS FOR LIKE MILESTONES ===
        # Commented out for now - will be updated when notification system is ready
        # if reaction_type == "like" and action == "added":
        #     from keyopolls.notifications.models import NotificationType
        #     from keyopolls.notifications.notification_utils import (
        #         notify_comment_milestone,
        #         notify_poll_milestone,
        #     )

        #     # Get the current like count from the updated counts
        #     current_like_count = counts.get("like", 0)

        #     # Determine if it's a poll or comment and trigger like milestone
        #     if model_class.__name__ == "Poll":
        #         # This is a poll like milestone
        #         notify_poll_milestone(
        #             content_obj,
        #             NotificationType.LIKE_MILESTONE,
        #             current_like_count,
        #             send_push=True,
        #         )
        #     elif model_class.__name__ == "GenericComment":
        #         # This is a comment like milestone
        #         notify_comment_milestone(
        #             content_obj,
        #             NotificationType.LIKE_MILESTONE,
        #             current_like_count,
        #             send_push=True,
        #         )

        # Get updated user reactions after all changes
        user_reactions = Reaction.get_user_reactions(profile, content_obj)

        # Get singular form of content type for response
        singular_content_type = get_singular_content_type(content_type)

        return 200, {
            "action": action,
            "counts": counts,
            "object_type": singular_content_type,
            "object_id": content_obj.id,
            "user_reactions": user_reactions,
        }

    except ValueError as e:
        return 400, {"message": str(e)}
    except ObjectDoesNotExist:
        # Content object not found
        singular = get_singular_content_type(content_type)
        return 404, {"message": f"{singular.replace('_', ' ').title()} not found"}
    except Exception as e:
        logger.error(
            f"Error toggling reaction on {content_type} {object_id}: {str(e)}",
            exc_info=True,
        )
        return 400, {"message": "An error occurred while processing the reaction"}


@router.get(
    "/{content_type}/{object_id}/reactions",
    response={200: dict, 404: Message, 400: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def get_reactions(
    request: HttpRequest,
    content_type: str,
    object_id: int,
):
    """
    Get reaction counts and user's reaction status for a content object.

    Returns reaction counts for all users and the authenticated user's reaction status
    (if authenticated with a pseudonymous profile).

    Parameters:
    - content_type: The type of content
    - object_id: The ID of the content object
    """
    # Get the authenticated pseudonymous profile (could be None for unauthenticated
    #  users)
    profile = request.auth

    try:
        # Get the model class for the content type
        model_class = get_model_class(content_type)

        # Build filters for getting the content object
        filters = build_content_filters(content_type, object_id, model_class)

        # Get the content object
        content_obj = model_class.objects.get(**filters)

        # Get reaction counts for the content object
        reaction_counts = Reaction.get_reaction_counts(content_obj)

        # Get user's reactions if authenticated
        user_reactions = {}
        if profile:
            user_reactions = Reaction.get_user_reactions(profile, content_obj)
        else:
            # User is not authenticated, return default reactions (all False)
            user_reactions = {r_type: False for r_type, _ in Reaction.REACTION_TYPES}

        # Get singular form of content type for response
        singular_content_type = get_singular_content_type(content_type)

        return 200, {
            "object_type": singular_content_type,
            "object_id": content_obj.id,
            "counts": reaction_counts,
            "user_reactions": user_reactions,
        }

    except ValueError as e:
        return 400, {"message": str(e)}
    except ObjectDoesNotExist:
        singular = get_singular_content_type(content_type)
        return 404, {"message": f"{singular.replace('_', ' ').title()} not found"}
    except Exception as e:
        logger.error(
            f"Error getting reactions for {content_type} {object_id}: {str(e)}",
            exc_info=True,
        )
        return 400, {"message": "An error occurred while getting reactions"}


# Helper function to get client IP
def get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0]
    else:
        ip = request.META.get("REMOTE_ADDR")
    return ip


def get_content_object(content_type: str, object_id: int):
    """Get content object by content type and ID"""
    try:
        # Map content type strings to model classes
        content_type_map = {
            "poll": "polls.Poll",
            "comment": "comments.GenericComment",
            # Add other content types as needed
        }

        if content_type not in content_type_map:
            raise ValueError(f"Invalid content type: {content_type}")

        model_class = apps.get_model(content_type_map[content_type])
        return get_object_or_404(model_class, id=object_id)
    except Exception as e:
        raise ValueError(f"Content object not found: {e}")


@router.post(
    "/share/{content_type}/{object_id}",
    response=ShareResponseSchema,
    auth=OptionalPseudonymousJWTAuth,
)
def share_content(
    request, content_type: ContentTypeEnum, object_id: int, data: ShareRequestSchema
):
    """Record a share event for any content type using pseudonymous profile"""

    # Get the content object
    content_object = get_content_object(content_type, object_id)

    # Get additional request info
    ip_address = get_client_ip(request)
    user_agent = request.META.get("HTTP_USER_AGENT", "")

    # Handle authentication - pseudonymous profile or unauthenticated
    profile = request.auth

    # Create share record and increment counter
    share, created = Share.increment_share_count(
        content_object=content_object,
        profile=profile,  # Can be None for unauthenticated users
        platform=data.platform,
        ip_address=ip_address,
        user_agent=user_agent,
        referrer=data.referrer or "",
    )

    return ShareResponseSchema(
        success=True,
        message=f"Share {'recorded' if created else 'already exists'} "
        f"for {data.platform}",
        total_shares=getattr(content_object, "share_count", 0),
        already_shared=not created,
    )
