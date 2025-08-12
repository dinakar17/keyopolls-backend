from datetime import datetime, time
from decimal import Decimal

from django.core.paginator import Paginator
from django.db.models import Count, DecimalField, Q, Sum
from django.db.models.functions import Coalesce
from ninja import Query, Router

from keyopolls.common.schemas import Message
from keyopolls.profile.middleware import PseudonymousJWTAuth
from keyopolls.profile.models import PseudonymousProfile
from keyopolls.transactions.models import Transaction
from keyopolls.transactions.schemas import (
    CreditsSummarySchema,
    TransactionFiltersSchema,
    TransactionsResponseSchema,
    TransactionSummarySchema,
)

router = Router(tags=["Transactions"])


@router.get(
    "/transactions",
    response={200: TransactionsResponseSchema, 400: Message, 403: Message},
    auth=PseudonymousJWTAuth(),
)
def get_user_transactions(request, filters: TransactionFiltersSchema = Query(...)):
    """
    Get user's transaction history with comprehensive filtering and summary.

    Features:
    - Filter by transaction type, status, amount range, date range
    - Search in transaction descriptions
    - Filter credits/debits only
    - Pagination with configurable page size
    - Multiple sorting options
    - Transaction summary with balance calculation
    - Includes related timeline items for message transactions

    Query Parameters:
    - transaction_type: Filter by type (purchase, message_sent, message_received,
      refund, bonus)
    - status: Filter by status (pending, completed, failed, cancelled)
    - min_amount/max_amount: Amount range filtering
    - date_from/date_to: Date range filtering (YYYY-MM-DD format)
    - payment_method: Filter by payment method
    - search: Search in transaction descriptions
    - credits_only: Show only credit transactions
    - debits_only: Show only debit transactions
    - page: Page number (default: 1)
    - per_page: Items per page (default: 20, max: 100)
    - order_by: Sort field (created_at, -created_at, amount, -amount, completed_at,
      -completed_at)
    """

    profile = request.auth

    # Validate per_page limit
    if filters.per_page > 100:
        filters.per_page = 100
    if filters.per_page < 1:
        filters.per_page = 20

    # Validate page
    if filters.page < 1:
        filters.page = 1

    # Validate order_by options
    valid_order_fields = [
        "created_at",
        "-created_at",
        "amount",
        "-amount",
        "completed_at",
        "-completed_at",
        "transaction_type",
        "-transaction_type",
        "status",
        "-status",
    ]
    if filters.order_by not in valid_order_fields:
        filters.order_by = "-created_at"

    # Start with user's transactions
    queryset = Transaction.objects.filter(user=profile).select_related("timeline_item")

    # Apply transaction type filter
    if filters.transaction_type:
        valid_types = [choice[0] for choice in Transaction.TRANSACTION_TYPES]
        if filters.transaction_type in valid_types:
            queryset = queryset.filter(transaction_type=filters.transaction_type)
        else:
            return 400, {
                "message": (
                    f"Invalid transaction_type. Valid types: {', '.join(valid_types)}"
                )
            }

    # Apply status filter
    if filters.status:
        valid_statuses = [choice[0] for choice in Transaction.TRANSACTION_STATUS]
        if filters.status in valid_statuses:
            queryset = queryset.filter(status=filters.status)
        else:
            return 400, {
                "message": (
                    f"Invalid status. Valid statuses: {', '.join(valid_statuses)}"
                )
            }

    # Apply amount range filters
    if filters.min_amount is not None:
        if filters.min_amount < 0:
            return 400, {"message": "min_amount cannot be negative"}
        queryset = queryset.filter(amount__gte=Decimal(str(filters.min_amount)))

    if filters.max_amount is not None:
        if filters.max_amount < 0:
            return 400, {"message": "max_amount cannot be negative"}
        queryset = queryset.filter(amount__lte=Decimal(str(filters.max_amount)))

    # Validate amount range
    if (
        filters.min_amount is not None
        and filters.max_amount is not None
        and filters.min_amount > filters.max_amount
    ):
        return 400, {"message": "min_amount cannot be greater than max_amount"}

    # Apply date range filters
    if filters.date_from:
        # Convert date to datetime (start of day)
        date_from_dt = datetime.combine(filters.date_from, time.min)
        queryset = queryset.filter(created_at__gte=date_from_dt)

    if filters.date_to:
        # Convert date to datetime (end of day)
        date_to_dt = datetime.combine(filters.date_to, time.max)
        queryset = queryset.filter(created_at__lte=date_to_dt)

    # Validate date range
    if filters.date_from and filters.date_to and filters.date_from > filters.date_to:
        return 400, {"message": "date_from cannot be later than date_to"}

    # Apply payment method filter
    if filters.payment_method:
        queryset = queryset.filter(payment_method__icontains=filters.payment_method)

    # Apply search filter
    if filters.search:
        search_term = filters.search.strip()
        if search_term:
            queryset = queryset.filter(
                Q(description__icontains=search_term)
                | Q(payment_reference__icontains=search_term)
            )

    # Apply credit/debit filters
    if filters.credits_only and filters.debits_only:
        return 400, {"message": "Cannot filter for both credits_only and debits_only"}

    if filters.credits_only:
        credit_types = ["purchase", "message_received", "refund", "bonus"]
        queryset = queryset.filter(transaction_type__in=credit_types)

    if filters.debits_only:
        debit_types = ["message_sent"]
        queryset = queryset.filter(transaction_type__in=debit_types)

    # Calculate summary before pagination - FIXED WITH OUTPUT FIELDS
    summary_queryset = queryset.aggregate(
        total_credits=Coalesce(
            Sum(
                "amount",
                filter=Q(
                    transaction_type__in=[
                        "purchase",
                        "message_received",
                        "refund",
                        "bonus",
                    ]
                ),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
            Decimal("0.00"),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
        total_debits=Coalesce(
            Sum(
                "amount",
                filter=Q(transaction_type__in=["message_sent"]),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
            Decimal("0.00"),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
        pending_amount=Coalesce(
            Sum(
                "amount",
                filter=Q(status="pending"),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
            Decimal("0.00"),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
        total_transactions=Count("id"),
    )

    # Calculate current balance (all completed transactions) - FIXED WITH OUTPUT FIELDS
    balance_queryset = Transaction.objects.filter(
        user=profile, status="completed"
    ).aggregate(
        credits=Coalesce(
            Sum(
                "amount",
                filter=Q(
                    transaction_type__in=[
                        "purchase",
                        "message_received",
                        "refund",
                        "bonus",
                    ]
                ),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
            Decimal("0.00"),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
        debits=Coalesce(
            Sum(
                "amount",
                filter=Q(transaction_type__in=["message_sent"]),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
            Decimal("0.00"),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
    )

    current_balance = float(balance_queryset["credits"] - balance_queryset["debits"])

    # Apply ordering
    queryset = queryset.order_by(filters.order_by)

    # Get total count before pagination
    total_count = queryset.count()

    # Apply pagination
    paginator = Paginator(queryset, filters.per_page)

    if filters.page > paginator.num_pages and paginator.num_pages > 0:
        filters.page = paginator.num_pages

    try:
        page_obj = paginator.page(filters.page)
    except Exception:
        return 400, {"message": "Invalid page number"}

    # Build response data
    transactions_data = []
    for transaction in page_obj.object_list:
        # Build timeline item data if exists
        timeline_item_data = None
        if transaction.timeline_item:
            timeline_item_data = {
                "id": str(transaction.timeline_item.id),
                "item_type": transaction.timeline_item.item_type,
                "content": transaction.timeline_item.content,
                "file_name": transaction.timeline_item.file_name,
                "created_at": transaction.timeline_item.created_at,
            }

        transaction_data = {
            "id": str(transaction.id),
            "transaction_type": transaction.transaction_type,
            "transaction_type_display": transaction.get_transaction_type_display(),
            "amount": float(transaction.amount),
            "status": transaction.status,
            "status_display": transaction.get_status_display(),
            "description": transaction.description,
            "payment_method": transaction.payment_method,
            "payment_reference": transaction.payment_reference,
            "is_credit": transaction.is_credit(),
            "is_debit": transaction.is_debit(),
            "created_at": transaction.created_at,
            "completed_at": transaction.completed_at,
            "timeline_item": timeline_item_data,
        }
        transactions_data.append(transaction_data)

    # Build summary data
    summary_data = {
        "total_credits": float(summary_queryset["total_credits"]),
        "total_debits": float(summary_queryset["total_debits"]),
        "current_balance": current_balance,
        "total_transactions": summary_queryset["total_transactions"],
        "pending_amount": float(summary_queryset["pending_amount"]),
    }

    return {
        "transactions": transactions_data,
        "summary": summary_data,
        "total_count": total_count,
        "page": filters.page,
        "per_page": filters.per_page,
        "total_pages": paginator.num_pages,
        "has_next": page_obj.has_next(),
        "has_previous": page_obj.has_previous(),
    }


@router.get(
    "/transactions/summary",
    response={200: TransactionSummarySchema, 403: Message},
    auth=PseudonymousJWTAuth(),
)
def get_user_transaction_summary(request):
    """
    Get a quick summary of user's transaction data.

    Returns:
    - Total credits earned
    - Total debits spent
    - Current balance
    - Total transaction count
    - Pending transaction amount
    """

    profile = request.auth

    # Calculate summary for all transactions
    all_transactions = Transaction.objects.filter(user=profile).aggregate(
        total_credits=Coalesce(
            Sum(
                "amount",
                filter=Q(
                    transaction_type__in=[
                        "purchase",
                        "message_received",
                        "refund",
                        "bonus",
                    ]
                ),
            ),
            0,
        ),
        total_debits=Coalesce(
            Sum("amount", filter=Q(transaction_type__in=["message_sent"])), 0
        ),
        pending_amount=Coalesce(Sum("amount", filter=Q(status="pending")), 0),
        total_transactions=Count("id"),
    )

    # Calculate current balance (only completed transactions)
    completed_transactions = Transaction.objects.filter(
        user=profile, status="completed"
    ).aggregate(
        credits=Coalesce(
            Sum(
                "amount",
                filter=Q(
                    transaction_type__in=[
                        "purchase",
                        "message_received",
                        "refund",
                        "bonus",
                    ]
                ),
            ),
            0,
        ),
        debits=Coalesce(
            Sum("amount", filter=Q(transaction_type__in=["message_sent"])), 0
        ),
    )

    current_balance = float(
        completed_transactions["credits"] - completed_transactions["debits"]
    )

    return {
        "total_credits": float(all_transactions["total_credits"]),
        "total_debits": float(all_transactions["total_debits"]),
        "current_balance": current_balance,
        "total_transactions": all_transactions["total_transactions"],
        "pending_amount": float(all_transactions["pending_amount"]),
    }


# Get users' total credits, credits spend, and earned
@router.get(
    "/credits/summary",
    response={200: CreditsSummarySchema},
    auth=PseudonymousJWTAuth(),
)
def get_credits_summary(request):
    """
    Get the total credits, credits spent, and credits earned for the authenticated user.
    """
    profile: PseudonymousProfile = request.auth

    if not profile:
        return 404, {"message": "Profile not found"}

    total_credits = profile.total_credits
    total_earned = profile.total_earned

    return CreditsSummarySchema(
        total_credits=total_credits,
        total_earned=total_earned,
    )
