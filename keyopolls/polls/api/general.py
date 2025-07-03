import logging
from typing import List, Optional

from django.core.paginator import Paginator
from django.db import models, transaction
from django.http import HttpRequest
from ninja import Query, Router

from keyopolls.common.models import Category
from keyopolls.common.models.impressions import record_list_impressions
from keyopolls.common.schemas import Message
from keyopolls.communities.models import Community, CommunityMembership
from keyopolls.polls.models import Poll, PollTextResponse, PollVote
from keyopolls.polls.schemas import CastVoteSchema, PollDetails, PollListResponseSchema
from keyopolls.polls.services import validate_vote_for_poll_type
from keyopolls.profile.middleware import (
    OptionalPseudonymousJWTAuth,
    PseudonymousJWTAuth,
)
from keyopolls.profile.models import PseudonymousProfile

logger = logging.getLogger(__name__)
router = Router(tags=["Polls"])


# Updated endpoint
@router.post(
    "/polls/vote",
    response={
        200: PollDetails,
        400: Message,
        403: Message,
        404: Message,
    },
    auth=PseudonymousJWTAuth(),
)
def cast_vote(request, data: CastVoteSchema):
    """Cast a vote on a poll - handles all poll types - cannot be changed once cast"""
    profile: PseudonymousProfile = request.auth

    try:
        # Get the poll with related data
        try:
            poll = (
                Poll.objects.select_related("community", "profile")
                .prefetch_related("options")
                .get(id=data.poll_id, is_deleted=False)
            )
        except Poll.DoesNotExist:
            return 404, {"message": "Poll not found"}

        # Check if poll is active
        if not poll.is_active:
            return 400, {"message": "Poll is not active or has expired"}

        # Check if user can vote
        if not poll.can_vote(profile):
            if poll.requires_aura > 0 and profile.total_aura < poll.requires_aura:
                return 403, {
                    "message": f"You need at least {poll.requires_aura} aura to vote",
                }
            return 403, {
                "message": "You are not authorized to vote on this poll",
            }

        # Check if user has already voted/responded
        if poll.poll_type == "text_input":
            existing_response = poll.text_responses.filter(profile=profile).first()
            if existing_response:
                return 400, {
                    "message": (
                        (
                            "You have already responded to this poll "
                            "and cannot change your response"
                        )
                    ),
                }
        else:
            existing_votes = poll.votes.filter(profile=profile)
            if existing_votes.exists():
                return 400, {
                    "message": (
                        (
                            "You have already voted on this poll "
                            "and cannot change your vote"
                        )
                    ),
                }

        # Handle text input polls
        if poll.poll_type == "text_input":
            if not data.text_value:
                return 400, {
                    "message": "Text response is required for text input polls"
                }

            # Validate text input
            text_value = data.text_value.strip()
            if not text_value:
                return 400, {"message": "Text response cannot be empty"}

            if " " in text_value:
                return 400, {"message": "Text response cannot contain spaces"}

            if len(text_value) > 50:
                return 400, {"message": "Text response cannot exceed 50 characters"}

            # Submit the text response using transaction
            with transaction.atomic():
                # Create the text response
                PollTextResponse.objects.create(
                    poll=poll,
                    profile=profile,
                    text_value=text_value,
                )

                # Update poll counts (new voter)
                poll.increment_vote_count(is_new_voter=True)

                # Update aggregates
                from keyopolls.polls.models import PollTextAggregate

                PollTextAggregate.update_aggregates_for_poll(poll)

                # Refresh poll data to get updated counts
                poll.refresh_from_db()

                return 200, PollDetails.resolve(poll, profile)

        # Handle option-based polls (single, multiple, ranking)
        else:
            # Validate vote data
            if not data.votes:
                return 400, {"message": "No votes provided"}

            # Get poll options for validation
            poll_options = {opt.id: opt for opt in poll.options.all()}

            # Validate all option IDs exist
            for vote in data.votes:
                if vote.option_id not in poll_options:
                    return 400, {
                        "message": f"Invalid option ID: {vote.option_id}",
                    }

            # Validate vote based on poll type
            validation_result = validate_vote_for_poll_type(
                poll, data.votes, poll_options
            )
            if not validation_result["valid"]:
                return 400, {"message": validation_result["error"]}

            # Cast the votes using transaction
            with transaction.atomic():
                # is_new_voter = True  # Since we checked they haven't voted before
                votes_created = []

                for vote_data in data.votes:
                    option = poll_options[vote_data.option_id]

                    # Create the vote
                    vote = PollVote.objects.create(
                        poll=poll, option=option, profile=profile, rank=vote_data.rank
                    )
                    votes_created.append(vote)

                    # Update option vote count
                    option.increment_vote_count()

                # Update poll vote counts
                if poll.poll_type == "ranking":
                    # For ranking polls: each user contributes 1 to total_voters
                    # and total_votes equals total_voters
                    # (since each user ranks all options)
                    poll.increment_vote_count(is_new_voter=True)
                else:
                    # For single/multiple choice: count each individual vote
                    total_vote_count = len(data.votes)
                    poll.increment_vote_count(is_new_voter=True)

                    # Add remaining votes if multiple votes were cast
                    if total_vote_count > 1:
                        poll.total_votes = models.F("total_votes") + (
                            total_vote_count - 1
                        )
                        poll.save(update_fields=["total_votes"])

                # Refresh poll data to get updated counts
                poll.refresh_from_db()

                return 200, PollDetails.resolve(poll, profile)

    except Exception as e:
        logger.error(
            f"Error casting vote on poll {data.poll_id}: {str(e)}", exc_info=True
        )
        return 400, {
            "message": "An error occurred while casting your vote",
        }


@router.get(
    "/polls/{poll_id}",
    response={200: PollDetails, 404: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def get_poll(request: HttpRequest, poll_id: int):
    """Get a specific poll by ID"""
    # Extract profile (can be None for unauthenticated users)
    profile = request.auth if isinstance(request.auth, PseudonymousProfile) else None

    try:
        # Get the poll with related data
        try:
            poll = (
                Poll.objects.select_related("community", "profile")
                .prefetch_related("options")
                .get(id=poll_id, is_deleted=False)
            )
        except Poll.DoesNotExist:
            return 404, {"message": "Poll not found"}

        # Todo: Include the impressions_count in here

        return 200, PollDetails.resolve(poll, profile)

    except Exception as e:
        logger.error(f"Error getting poll {poll_id}: {str(e)}", exc_info=True)
        return 400, {
            "message": "An error occurred while fetching the poll",
        }


@router.get(
    "/polls",
    response={200: PollListResponseSchema, 400: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def list_polls(
    request: HttpRequest,
    # Community & Category filtering
    community_id: Optional[int] = Query(None, description="Filter by community ID"),
    category_id: Optional[int] = Query(
        None, description="Filter by category ID (1 = for-you feed)"
    ),
    # Content filtering
    poll_type: Optional[str] = Query(
        None, description="Filter by poll type (single, multiple, ranking)"
    ),
    status: Optional[List[str]] = Query(
        ["active"],
        description=(
            "Filter by status (active, closed, archived, draft, "
            "pending_moderation, rejected). Can provide multiple values."
        ),
    ),
    author_id: Optional[int] = Query(None, description="Filter by author profile ID"),
    tag: Optional[str] = Query(None, description="Filter by tag name"),
    # Search
    search: Optional[str] = Query(
        None, description="Search in poll title and description"
    ),
    # User-specific filters (requires auth)
    my_polls: bool = Query(False, description="Show only user's polls"),
    my_communities: bool = Query(
        False, description="Show polls from user's communities only"
    ),
    voted: Optional[bool] = Query(
        None, description="Filter by voted status (true/false)"
    ),
    # Pagination
    page: int = Query(1, description="Page number"),
    page_size: int = Query(20, description="Items per page (max 100)"),
    # Sorting
    sort: str = Query(
        "newest", description="Sort: newest, oldest, most_votes, most_popular, trending"
    ),
    # Special filters
    include_expired: bool = Query(False, description="Include expired polls"),
    min_aura: Optional[int] = Query(None, description="Minimum aura requirement"),
):
    """
    List polls with comprehensive filtering, searching, and pagination.
    Handles all possible use cases including personalized feeds.
    """
    # Extract profile (can be None for unauthenticated users)
    profile = request.auth if isinstance(request.auth, PseudonymousProfile) else None

    try:
        # === PARAMETER VALIDATION ===
        if page_size < 1 or page_size > 100:
            return 400, {"message": "page_size must be between 1 and 100"}

        if page < 1:
            return 400, {"message": "page must be greater than 0"}

        valid_poll_types = ["single", "multiple", "ranking"]
        if poll_type and poll_type not in valid_poll_types:
            return 400, {
                "message": f"Invalid poll_type. Must be: {', '.join(valid_poll_types)}"
            }

        # UPDATED: Validate status list
        valid_statuses = [
            "active",
            "closed",
            "archived",
            "draft",
            "pending_moderation",
            "rejected",
        ]

        # Handle case where status might be None or empty
        if not status:
            status = ["active"]

        # Validate each status in the list
        invalid_statuses = [s for s in status if s not in valid_statuses]
        if invalid_statuses:
            return 400, {
                "message": (
                    f"Invalid status(es): {', '.join(invalid_statuses)}. "
                    f"Must be: {', '.join(valid_statuses)}"
                )
            }

        valid_sorts = ["newest", "oldest", "most_votes", "most_popular", "trending"]
        if sort not in valid_sorts:
            return 400, {"message": f"Invalid sort. Must be: {', '.join(valid_sorts)}"}

        # Validate auth-required filters
        auth_required_filters = [my_polls, my_communities, voted is not None]
        if any(auth_required_filters) and not profile:
            return 400, {"message": "Authentication required for user-specific filters"}

        # === BUILD BASE QUERYSET ===
        polls = (
            Poll.objects.select_related("community", "community__category", "profile")
            .prefetch_related("options")
            .filter(is_deleted=False)
        )

        # Track applied filters for debugging
        applied_filters = {}

        # === SPECIAL CATEGORY HANDLING ===
        if category_id == 1:  # "For You" personalized feed
            applied_filters["for_you_feed"] = True

            if not profile:
                # Unauthenticated users get popular public polls (ACTIVE + CLOSED)
                polls = (
                    polls.filter(
                        community__community_type="public",
                        community__is_active=True,
                        status__in=[
                            "active",
                            "closed",
                        ],  # Show active and closed polls in public feeds
                    )
                    .annotate(
                        popularity_score=models.F("total_votes")
                        + models.F("total_voters") * 2
                    )
                    .order_by("-popularity_score", "-created_at")
                )
                applied_filters["unauthenticated_feed"] = True
            else:
                # Authenticated users get personalized feed
                # Get user's communities
                user_community_ids = CommunityMembership.objects.filter(
                    profile=profile, status="active"
                ).values_list("community_id", flat=True)

                # Get categories user interacts with (from their community memberships)
                user_category_ids = Community.objects.filter(
                    id__in=user_community_ids
                ).values_list("category_id", flat=True)

                # Personalized algorithm:
                # user communities + similar categories + trending
                polls = (
                    polls.filter(
                        models.Q(
                            community_id__in=user_community_ids
                        )  # User's communities
                        | models.Q(
                            community__category_id__in=user_category_ids,
                            community__community_type="public",
                        )  # Similar categories
                        | models.Q(
                            community__community_type="public", total_votes__gte=10
                        )  # Trending public polls
                    )
                    .filter(
                        community__is_active=True, status__in=["active", "closed"]
                    )  # Active and closed polls
                    .distinct()
                )
                applied_filters["personalized_feed"] = True

        # === CORE FILTERING ===
        elif category_id and category_id != 1:
            # Filter by specific category
            try:
                category = Category.objects.get(id=category_id)
                polls = polls.filter(community__category=category)
                applied_filters["category_id"] = category_id
            except Category.DoesNotExist:
                return 400, {"message": "Category not found"}

        # Community filter
        if community_id:
            try:
                community = Community.objects.get(id=community_id, is_active=True)

                # Check if user can view this community's polls
                if community.community_type == "private" and profile:
                    try:
                        membership = community.memberships.get(profile=profile)
                        if not membership.is_active_member:
                            return 400, {
                                "message": "You don't have access to this community"
                            }
                    except CommunityMembership.DoesNotExist:
                        return 400, {
                            "message": "You don't have access to this community"
                        }
                elif community.community_type == "private" and not profile:
                    return 400, {
                        "message": "Authentication required to view this community"
                    }

                polls = polls.filter(community=community)
                applied_filters["community_id"] = community_id
            except Community.DoesNotExist:
                return 400, {"message": "Community not found"}

        # User-specific filters
        if my_polls and profile:
            polls = polls.filter(profile=profile)
            applied_filters["my_polls"] = True
            # UPDATED: When viewing own polls, use provided status filters
            # If only "active" is provided, show all statuses for own polls
            if status == ["active"]:
                # Default behavior: show all statuses for own polls
                status = [
                    "active",
                    "closed",
                    "pending_moderation",
                    "rejected",
                    "draft",
                    "archived",
                ]
                applied_filters["my_polls_all_statuses"] = True
        elif not my_polls and category_id != 1:
            # UPDATED: For non-personal feeds, use provided status
            # or default to active + closed
            if status == ["active"]:
                status = ["active", "closed"]
                applied_filters["default_active_and_closed"] = True

        if my_communities and profile:
            user_community_ids = CommunityMembership.objects.filter(
                profile=profile, status="active"
            ).values_list("community_id", flat=True)
            polls = polls.filter(community_id__in=user_community_ids)
            applied_filters["my_communities"] = True

        # Voting status filter
        if voted is not None and profile:
            if voted:
                # User has voted - get polls where user has votes
                voted_poll_ids = (
                    PollVote.objects.filter(profile=profile)
                    .values_list("poll_id", flat=True)
                    .distinct()
                )
                polls = polls.filter(id__in=voted_poll_ids)
                applied_filters["voted"] = True
            else:
                # User hasn't voted - exclude polls where user has votes
                voted_poll_ids = (
                    PollVote.objects.filter(profile=profile)
                    .values_list("poll_id", flat=True)
                    .distinct()
                )
                polls = polls.exclude(id__in=voted_poll_ids)
                applied_filters["not_voted"] = True

        # === ADDITIONAL FILTERS ===
        if poll_type:
            polls = polls.filter(poll_type=poll_type)
            applied_filters["poll_type"] = poll_type

        # UPDATED: Enhanced status filtering logic with multiple statuses
        if status and category_id != 1:  # For-you feed handles status internally
            # Check for sensitive statuses
            sensitive_statuses = ["pending_moderation", "rejected"]
            has_sensitive_status = any(s in sensitive_statuses for s in status)

            if has_sensitive_status:
                if not profile:
                    return 400, {
                        "message": "Authentication required to view moderation statuses"
                    }

                # Only allow users to see their own pending/rejected polls
                # Unless they're staff/moderators
                if not (hasattr(profile, "is_staff") and profile.is_staff):
                    # Filter out sensitive statuses for non-owners
                    if not my_polls:
                        status = [s for s in status if s not in sensitive_statuses]
                        applied_filters["filtered_sensitive_statuses"] = True
                    else:
                        applied_filters["own_moderation_polls"] = True

            # Apply status filter
            if status:  # Only apply if there are still statuses left after filtering
                polls = polls.filter(status__in=status)
                applied_filters["status"] = status

        if author_id:
            # UPDATED: When viewing specific author's polls, apply visibility rules
            if author_id != (profile.id if profile else None):
                # Viewing someone else's polls - filter out sensitive statuses
                # unless the viewer is staff
                if not (profile and hasattr(profile, "is_staff") and profile.is_staff):
                    # Remove sensitive statuses from the filter
                    safe_statuses = [
                        s
                        for s in status
                        if s not in ["pending_moderation", "rejected", "draft"]
                    ]
                    if not safe_statuses:
                        safe_statuses = ["active", "closed"]
                    polls = polls.filter(status__in=safe_statuses)
                    applied_filters["author_safe_statuses"] = safe_statuses

            polls = polls.filter(profile_id=author_id)
            applied_filters["author_id"] = author_id

        if tag:
            # If you have a tagging system for polls, update this section
            # For now, assuming polls might be tagged through their communities
            # You can remove this section if polls don't have direct tags
            pass  # Remove this filter if polls don't support tags directly
            # applied_filters["tag"] = tag

        if min_aura:
            polls = polls.filter(requires_aura__gte=min_aura)
            applied_filters["min_aura"] = min_aura

        # Expiration filter
        if not include_expired:
            from django.utils import timezone

            now = timezone.now()
            polls = polls.filter(
                models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now)
            )
            applied_filters["exclude_expired"] = True

        # === SEARCH FUNCTIONALITY ===
        if search:
            search_term = search.strip()
            polls = polls.filter(
                models.Q(title__icontains=search_term)
                | models.Q(description__icontains=search_term)
            )
            applied_filters["search"] = search_term

        # === PRIVACY FILTERING ===
        if not my_communities and category_id != 1:  # Skip for personalized feeds
            if not profile:
                # Non-authenticated users see only public community polls
                polls = polls.filter(community__community_type="public")
                applied_filters["public_only"] = True
            else:
                # Authenticated users see public + restricted + their private
                # community polls
                user_private_community_ids = CommunityMembership.objects.filter(
                    profile=profile,
                    status="active",
                    community__community_type="private",
                ).values_list("community_id", flat=True)

                polls = polls.filter(
                    models.Q(community__community_type__in=["public", "restricted"])
                    | models.Q(community_id__in=user_private_community_ids)
                )

        # === SORTING ===
        if category_id != 1:  # For-you feed has custom sorting
            sort_mapping = {
                "newest": "-created_at",
                "oldest": "created_at",
                "most_votes": "-total_votes",
                "most_popular": "-total_voters",
                "trending": None,  # Special handling below
            }

            if sort == "trending":
                # Trending algorithm: recent polls with high engagement
                from datetime import timedelta

                from django.utils import timezone

                recent_cutoff = timezone.now() - timedelta(days=7)
                polls = (
                    polls.filter(created_at__gte=recent_cutoff)
                    .annotate(
                        trending_score=(
                            models.F("total_votes") * 2
                            + models.F("total_voters") * 3
                            + models.Case(
                                models.When(
                                    created_at__gte=timezone.now()
                                    - timedelta(hours=24),
                                    then=10,
                                ),
                                models.When(
                                    created_at__gte=timezone.now() - timedelta(days=3),
                                    then=5,
                                ),
                                default=0,
                                output_field=models.IntegerField(),
                            )
                        )
                    )
                    .order_by("-trending_score", "-created_at")
                )
                applied_filters["trending_sort"] = True
            else:
                polls = polls.order_by(sort_mapping[sort])
                applied_filters["sort"] = sort

        # === PAGINATION ===
        paginator = Paginator(polls, page_size)

        try:
            page_obj = paginator.page(page)
        except Exception:
            # If page doesn't exist, return empty results
            page_obj = (
                paginator.page(paginator.num_pages) if paginator.num_pages > 0 else None
            )

        # === RESOLVE POLLS ===
        polls_data = []
        if page_obj:
            # Record impressions for the polls being displayed
            record_list_impressions(request, page_obj.object_list)

            for poll in page_obj.object_list:
                # UPDATED: Enhanced poll resolution with status-aware data
                poll_data = PollDetails.resolve(poll, profile)

                # Add moderation info for appropriate users
                if poll.status in ["pending_moderation", "rejected"] and profile:
                    if poll.profile == profile or (
                        hasattr(profile, "is_staff") and profile.is_staff
                    ):
                        poll_data["moderation_info"] = {
                            "status": poll.status,
                            "reason": poll.moderation_reason,
                            "moderated_at": (
                                poll.moderated_at.isoformat()
                                if poll.moderated_at
                                else None
                            ),
                        }

                polls_data.append(poll_data)

        return 200, {
            "items": polls_data,
            "total": paginator.count,
            "page": page_obj.number if page_obj else 1,
            "pages": paginator.num_pages,
            "page_size": page_size,
            "has_next": page_obj.has_next() if page_obj else False,
            "has_previous": page_obj.has_previous() if page_obj else False,
            "filters_applied": applied_filters,  # For debugging
            "feed_type": "for_you" if category_id == 1 else "standard",
        }

    except Exception as e:
        logger.error(f"Error listing polls: {str(e)}", exc_info=True)
        return 400, {
            "success": False,
            "message": "An error occurred while fetching polls",
        }
