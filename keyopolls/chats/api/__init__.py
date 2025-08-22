from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from ninja import Query, Router

from keyopolls.chats.models import Chat, ChatParticipant
from keyopolls.chats.schemas import (
    ChatUsersFiltersSchema,
    ChatUsersResponseSchema,
    CreateChatRequestSchema,
    CreateChatResponseSchema,
)
from keyopolls.common.schemas import Message
from keyopolls.communities.models import Community, CommunityMembership
from keyopolls.profile.middleware import (
    OptionalPseudonymousJWTAuth,
    PseudonymousJWTAuth,
)
from keyopolls.profile.models import PseudonymousProfile

router = Router(tags=["Chats"])


@router.get(
    "/chat-users",
    response={200: ChatUsersResponseSchema, 400: Message, 404: Message},
    auth=OptionalPseudonymousJWTAuth,
)
def get_chat_users(request, filters: ChatUsersFiltersSchema = Query(...)):
    """
    Get a list of users the user can chat with in a community.

    For unauthenticated users: Shows only moderators (no chat data).
    For authenticated users: Shows moderators they can chat with + chat data.
    For moderators: Shows their existing chats + other moderators.

    Only displays users with "moderator" role.

    Returns users ordered by:
    1. Users they've chatted with (with latest message first) - authenticated only
    2. Remaining moderators (alphabetically)
    """

    profile = request.auth if isinstance(request.auth, PseudonymousProfile) else None

    # Validate community exists
    try:
        community = Community.objects.get(id=filters.community_id, is_active=True)
    except Community.DoesNotExist:
        return 404, {"message": "Community not found"}

    # For authenticated users, check community membership
    user_membership = None
    user_is_moderator = False

    if profile:
        try:
            user_membership = CommunityMembership.objects.get(
                community=community, profile=profile, status="active"
            )
            user_is_moderator = user_membership.role == "moderator"
        except CommunityMembership.DoesNotExist:
            # Authenticated user but not a member - treat like unauthenticated
            pass

    # Get community moderators only
    moderator_role = "moderator"

    if profile and user_membership and user_is_moderator:
        # For moderators, show:
        # 1. Users who have messaged them (any role)
        # 2. Other moderators they haven't chatted with

        # First get users who have existing chats
        existing_chats_user_ids = set()
        existing_chats = (
            Chat.objects.filter(community=community)
            .filter(Q(participant_1=profile) | Q(participant_2=profile))
            .select_related("participant_1", "participant_2")
        )

        for chat in existing_chats:
            other_user = (
                chat.participant_1
                if chat.participant_2 == profile
                else chat.participant_2
            )
            existing_chats_user_ids.add(other_user.id)

        # Get memberships for users with existing chats (any role) + all moderators
        target_memberships = (
            CommunityMembership.objects.filter(community=community, status="active")
            .filter(Q(profile_id__in=existing_chats_user_ids) | Q(role=moderator_role))
            .exclude(profile=profile)
            .select_related("profile")
            .distinct()
            .prefetch_related(
                Prefetch(
                    "profile__chats_as_participant_1",
                    queryset=Chat.objects.filter(
                        community=community, participant_2=profile
                    ),
                ),
                Prefetch(
                    "profile__chats_as_participant_2",
                    queryset=Chat.objects.filter(
                        community=community, participant_1=profile
                    ),
                ),
            )
        )
    else:
        # For unauthenticated users or regular users, only show moderators
        target_memberships = CommunityMembership.objects.filter(
            community=community, role=moderator_role, status="active"
        ).select_related("profile")

        # If authenticated regular user, add chat prefetch
        if profile and user_membership:
            target_memberships = target_memberships.exclude(
                profile=profile
            ).prefetch_related(
                Prefetch(
                    "profile__chats_as_participant_1",
                    queryset=Chat.objects.filter(
                        community=community, participant_2=profile
                    ),
                ),
                Prefetch(
                    "profile__chats_as_participant_2",
                    queryset=Chat.objects.filter(
                        community=community, participant_1=profile
                    ),
                ),
            )

    # Apply search filter
    if filters.search:
        search_term = filters.search.strip()
        if search_term:
            target_memberships = target_memberships.filter(
                Q(profile__username__icontains=search_term)
                | Q(profile__display_name__icontains=search_term)
            )

    # Build user data with chat information (if authenticated)
    users_data = []

    for membership in target_memberships:
        target_user = membership.profile

        # Initialize chat data
        chat = None
        last_message_data = None
        unread_count = 0
        has_chatted = False

        # Only get chat data for authenticated users
        if profile and user_membership:
            # Find existing chat between users
            for chat_obj in target_user.chats_as_participant_1.all():
                if chat_obj.participant_2 == profile:
                    chat = chat_obj
                    break

            if not chat:
                for chat_obj in target_user.chats_as_participant_2.all():
                    if chat_obj.participant_1 == profile:
                        chat = chat_obj
                        break

            # Get last message and unread count if chat exists
            has_chatted = bool(chat)

            if chat:
                # Get last timeline item
                last_timeline_item = chat.timeline_items.order_by("-created_at").first()

                if last_timeline_item:
                    # Determine sender name
                    sender_name = (
                        last_timeline_item.sender.display_name
                        or last_timeline_item.sender.username
                    )

                    last_message_data = {
                        "id": str(last_timeline_item.id),
                        "content": last_timeline_item.content,
                        "message_type": last_timeline_item.item_type,
                        "file_name": last_timeline_item.file_name,
                        "call_duration": last_timeline_item.call_duration,
                        "call_status": last_timeline_item.call_status,
                        "created_at": last_timeline_item.created_at,
                        "is_read": last_timeline_item.is_read,
                        "sender_id": last_timeline_item.sender.id,
                        "sender_name": sender_name,
                    }

                # Get unread count for current user
                try:
                    participant = ChatParticipant.objects.get(chat=chat, user=profile)
                    unread_count = participant.get_unread_count()
                except ChatParticipant.DoesNotExist:
                    unread_count = 0

        # Apply unread filter (only for authenticated users)
        if filters.unread_only and (not profile or unread_count == 0):
            continue

        # Build user data - directly from PseudonymousProfile
        user_data = {
            "user_id": target_user.id,
            "username": target_user.username,
            "display_name": target_user.display_name,
            "headline": target_user.headline,
            "avatar": target_user.avatar.url if target_user.avatar else None,
            "is_online": getattr(
                target_user, "is_online", False
            ),  # Assuming this field is added
            "last_seen": getattr(
                target_user, "last_seen", None
            ),  # Assuming this field is added
            "is_mentor": membership.role == "moderator",  # True for moderators
            "message_rate": 0.0,  # TODO: Fetch from community-dependent model
            "role": membership.role,
            "chat_id": str(chat.id) if chat else None,
            "last_message": last_message_data,
            "unread_count": unread_count,
            "has_chatted": has_chatted,
        }

        users_data.append(user_data)

    # Sort users based on authentication status
    if profile and user_membership:
        # For authenticated users: chatted first, then alphabetical
        def sort_key(user_item):
            if user_item["has_chatted"] and user_item["last_message"]:
                # Users with chats: sort by latest message time (most recent first)
                return (0, -user_item["last_message"]["created_at"].timestamp())
            elif user_item["has_chatted"]:
                # Users with chats but no messages
                return (1, user_item["display_name"].lower())
            else:
                # Moderators without chats: sort alphabetically by name
                return (2, user_item["display_name"].lower())

        users_data.sort(key=sort_key)
    else:
        # For unauthenticated users: simple alphabetical sort
        users_data.sort(key=lambda x: x["display_name"].lower())

    # Apply pagination
    total_count = len(users_data)
    paginator = Paginator(users_data, filters.per_page)

    if filters.page > paginator.num_pages and paginator.num_pages > 0:
        filters.page = paginator.num_pages

    try:
        page_obj = paginator.page(filters.page)
    except Exception:
        return 400, {"message": "Invalid page number"}

    return {
        "users": list(page_obj.object_list),
        "total_count": total_count,
        "page": filters.page,
        "per_page": filters.per_page,
        "total_pages": paginator.num_pages,
        "has_next": page_obj.has_next(),
        "has_previous": page_obj.has_previous(),
    }


@router.post(
    "/get-or-create-chat",
    response={200: CreateChatResponseSchema, 400: Message, 404: Message},
    auth=PseudonymousJWTAuth(),
)
def get_or_create_chat_endpoint(request, data: CreateChatRequestSchema):
    """
    Get existing chat or create new one between authenticated user and mentor.

    This is a convenience endpoint that always returns a chat (creates if doesn't
    exist).
    """

    profile = request.auth

    # Validate community exists
    try:
        community = Community.objects.get(id=data.community_id, is_active=True)
    except Community.DoesNotExist:
        return 404, {"message": "Community not found"}

    # Validate mentor exists
    try:
        mentor = PseudonymousProfile.objects.get(id=data.mentor_id)
    except PseudonymousProfile.DoesNotExist:
        return 404, {"message": "Mentor not found"}

    # Check memberships (same validation as above)
    try:
        CommunityMembership.objects.get(
            community=community, profile=profile, status="active"
        )
    except CommunityMembership.DoesNotExist:
        return 400, {"message": "You are not a member of this community"}

    try:
        mentor_membership = CommunityMembership.objects.get(
            community=community, profile=mentor, status="active"
        )

        if mentor_membership.role != "moderator":
            return 400, {"message": "Target user is not a mentor in this community"}

    except CommunityMembership.DoesNotExist:
        return 400, {"message": "Mentor is not a member of this community"}

    if profile.id == mentor.id:
        return 400, {"message": "Cannot create chat with yourself"}

    # Use the helper function to get or create chat
    chat = get_or_create_chat(profile, mentor, community)

    # Check if chat was just created (simple heuristic)
    was_created = not chat.timeline_items.exists()

    return {
        "chat_id": str(chat.id),
        "mentor_id": mentor.id,
        "mentor_username": mentor.username,
        "mentor_display_name": mentor.display_name,
        "community_id": community.id,
        "created": was_created,
        "message": "Chat ready" if not was_created else "Chat created successfully",
    }


# Helper function (same as before)
def get_or_create_chat(user1, user2, community):
    """
    Get existing chat between two users or create a new one
    """
    # Try to find existing chat in both directions
    chat = Chat.objects.filter(
        Q(participant_1=user1, participant_2=user2, community=community)
        | Q(participant_1=user2, participant_2=user1, community=community)
    ).first()

    if not chat:
        # Create new chat
        chat = Chat.objects.create(
            participant_1=user1, participant_2=user2, community=community
        )

        # Create chat participants
        ChatParticipant.objects.create(chat=chat, user=user1)
        ChatParticipant.objects.create(chat=chat, user=user2)

    return chat
