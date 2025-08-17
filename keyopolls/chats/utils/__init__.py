from datetime import datetime

from django.db import transaction
from django.utils import timezone

from keyopolls.chats.models import TimelineItem
from keyopolls.communities.models import CommunityMembership
from keyopolls.transactions.models import Transaction


class ChatServiceError(Exception):
    """Custom exception for chat service validation errors"""

    pass


def validate_and_process_chat_message(
    chat, sender, service_item=None, timeline_item_data=None
):
    """
    Validates chat message creation rules and processes transactions.

    Args:
        chat: Chat instance
        sender: PseudonymousProfile instance (message sender)
        service_item: ServiceItem instance (if message is related to a service)
        timeline_item_data: Dict with timeline item data for transaction creation

    Returns:
        dict: Contains validation result and transaction info

    Raises:
        ChatServiceError: If validation fails
    """

    # Determine if sender is moderator
    moderator = get_chat_moderator(chat)
    is_sender_moderator = sender == moderator

    # If sender is not moderator, apply user restrictions
    if not is_sender_moderator:
        # Check if user can send message (hasn't received reply for last message)
        validate_user_can_send_message(chat, sender)

        # If service item is provided, validate service-related restrictions
        if service_item:
            validate_service_usage(service_item, sender)

            # Check if user has enough credits
            if service_item.price > 0:
                validate_user_credits(sender, service_item.price)

    # Process transactions if needed
    transaction_info = None
    if service_item and service_item.price > 0:
        transaction_info = process_service_transaction(
            chat, sender, service_item, is_sender_moderator, timeline_item_data
        )

    return {
        "can_send": True,
        "transaction_info": transaction_info,
        "is_sender_moderator": is_sender_moderator,
    }


def get_chat_moderator(chat):
    """
    Identifies the moderator in a chat.

    Args:
        chat: Chat instance

    Returns:
        PseudonymousProfile: The moderator participant

    Raises:
        ChatServiceError: If no moderator found or multiple moderators
    """
    # Check if participant_1 is moderator
    p1_membership = CommunityMembership.objects.filter(
        community=chat.community,
        profile=chat.participant_1,
        status="active",
        role__in=["moderator", "creator"],
    ).first()

    # Check if participant_2 is moderator
    p2_membership = CommunityMembership.objects.filter(
        community=chat.community,
        profile=chat.participant_2,
        status="active",
        role__in=["moderator", "creator"],
    ).first()

    moderators = []
    if p1_membership:
        moderators.append(chat.participant_1)
    if p2_membership:
        moderators.append(chat.participant_2)

    if len(moderators) == 0:
        raise ChatServiceError("No moderator found in this chat")
    elif len(moderators) > 1:
        raise ChatServiceError("Multiple moderators found in this chat")

    return moderators[0]


def validate_user_can_send_message(chat, user):
    """
    Validates if user can send a message based on reply requirements.
    User cannot send a message if they haven't received a reply for their last message.

    Args:
        chat: Chat instance
        user: PseudonymousProfile instance

    Raises:
        ChatServiceError: If user cannot send message
    """
    # Get the last message sent by the user
    last_user_message = (
        TimelineItem.objects.filter(
            chat=chat,
            sender=user,
            item_type__in=["text", "image", "video", "document", "audio", "service"],
        )
        .order_by("-created_at")
        .first()
    )

    if not last_user_message:
        # No previous messages, user can send
        return

    # Check if there's a reply from moderator after the user's last message
    moderator = get_chat_moderator(chat)
    moderator_reply = TimelineItem.objects.filter(
        chat=chat,
        sender=moderator,
        created_at__gt=last_user_message.created_at,
        item_type__in=["text", "image", "video", "document", "audio", "service"],
    ).exists()

    if not moderator_reply:
        raise ChatServiceError(
            "You cannot send another message until the moderator replies to your "
            "previous message"
        )


def validate_service_usage(service_item, user):
    """
    Validates service usage limits (max_messages_a_day).

    Args:
        service_item: ServiceItem instance
        user: PseudonymousProfile instance

    Raises:
        ChatServiceError: If service limit exceeded
    """
    if not service_item.max_messages_a_day:
        # No limit set
        return

    # Count messages sent today for this service
    today = timezone.now().date()
    today_start = datetime.combine(today, datetime.min.time())
    today_start = timezone.make_aware(today_start)

    messages_today = TimelineItem.objects.filter(
        service_item=service_item, sender=user, created_at__gte=today_start
    ).count()

    if messages_today >= service_item.max_messages_a_day:
        raise ChatServiceError(
            f"Daily message limit ({service_item.max_messages_a_day}) "
            f"reached for service '{service_item.name}'"
        )


def validate_user_credits(user, required_amount):
    """
    Validates if user has enough credits for the service.

    Args:
        user: PseudonymousProfile instance
        required_amount: Decimal amount required

    Raises:
        ChatServiceError: If insufficient credits
    """
    if user.total_credits < required_amount:
        raise ChatServiceError(
            f"Insufficient credits. Required: {required_amount}, "
            f"Available: {user.total_credits}"
        )


@transaction.atomic
def process_service_transaction(
    chat, sender, service_item, is_sender_moderator, timeline_item_data
):
    """
    Processes transactions for service usage.

    Args:
        chat: Chat instance
        sender: PseudonymousProfile instance
        service_item: ServiceItem instance
        is_sender_moderator: Boolean indicating if sender is moderator
        timeline_item_data: Dict with timeline item data

    Returns:
        dict: Transaction information
    """
    if service_item.price <= 0:
        return None

    moderator = get_chat_moderator(chat)
    user = chat.get_other_participant(moderator)

    transaction_info = {"user_transaction": None, "moderator_transaction": None}

    if not is_sender_moderator:
        # User is sending message - debit user's account
        # Deduct credits from user
        user.total_credits -= service_item.price
        user.save(update_fields=["total_credits"])

        # Create debit transaction for user
        user_transaction = Transaction.objects.create(
            user=user,
            transaction_type="message_sent",
            amount=service_item.price,
            status="completed",
            description=f"Message sent using service: {service_item.name}",
            completed_at=timezone.now(),
        )
        transaction_info["user_transaction"] = user_transaction

    else:
        # Moderator is replying - credit moderator's account
        # Check if this is a reply to a user's service message
        last_user_service_message = (
            TimelineItem.objects.filter(
                chat=chat,
                sender=user,
                service_item=service_item,
                item_type__in=[
                    "text",
                    "image",
                    "video",
                    "document",
                    "audio",
                    "service",
                ],
            )
            .order_by("-created_at")
            .first()
        )

        if last_user_service_message:
            # Check if moderator already replied to this service message
            existing_moderator_reply = TimelineItem.objects.filter(
                chat=chat,
                sender=moderator,
                created_at__gt=last_user_service_message.created_at,
            ).exists()

            if not existing_moderator_reply:
                # This is the first reply, credit the moderator
                moderator.total_credits += service_item.price
                moderator.save(update_fields=["total_credits"])

                # Create credit transaction for moderator
                moderator_transaction = Transaction.objects.create(
                    user=moderator,
                    transaction_type="message_received",
                    amount=service_item.price,
                    status="completed",
                    description=f"Payment received for service: {service_item.name}",
                    completed_at=timezone.now(),
                )
                transaction_info["moderator_transaction"] = moderator_transaction

                # Update service stats
                service_item.increment_purchase_stats(service_item.price)

    return transaction_info


def update_transaction_with_timeline_item(transaction_info, timeline_item):
    """
    Updates transactions with the created timeline item reference.

    Args:
        transaction_info: Dict containing transaction information
        timeline_item: Created TimelineItem instance
    """
    if not transaction_info:
        return

    for tx in [
        transaction_info.get("user_transaction"),
        transaction_info.get("moderator_transaction"),
    ]:
        if tx:
            tx.timeline_item = timeline_item
            tx.save(update_fields=["timeline_item"])
