from datetime import date, datetime
from typing import List, Optional

from ninja import Schema


class CreditsSummarySchema(Schema):
    total_credits: float
    total_earned: float


class TransactionFiltersSchema(Schema):
    # Transaction filtering
    transaction_type: Optional[str] = None
    status: Optional[str] = None

    # Amount filtering
    min_amount: Optional[float] = None
    max_amount: Optional[float] = None

    # Date filtering
    date_from: Optional[date] = None
    date_to: Optional[date] = None

    # Payment method filtering
    payment_method: Optional[str] = None

    # Search in description
    search: Optional[str] = None

    # Show only credits or debits
    credits_only: Optional[bool] = None
    debits_only: Optional[bool] = None

    # Pagination
    page: int = 1
    per_page: int = 20

    # Sorting
    # Options: -created_at, created_at, -amount, amount, -completed_at, completed_at
    order_by: str = "-created_at"


class TimelineItemSchema(Schema):
    id: str
    item_type: str
    content: Optional[str] = None
    file_name: Optional[str] = None
    created_at: datetime


class TransactionSchema(Schema):
    id: str
    transaction_type: str
    transaction_type_display: str
    amount: float
    status: str
    status_display: str
    description: Optional[str] = None
    payment_method: Optional[str] = None
    payment_reference: Optional[str] = None
    is_credit: bool
    is_debit: bool
    created_at: datetime
    completed_at: Optional[datetime] = None
    timeline_item: Optional[TimelineItemSchema] = None


class TransactionSummarySchema(Schema):
    total_credits: float
    total_debits: float
    current_balance: float
    total_transactions: int
    pending_amount: float


class TransactionsResponseSchema(Schema):
    transactions: List[TransactionSchema]
    summary: TransactionSummarySchema
    total_count: int
    page: int
    per_page: int
    total_pages: int
    has_next: bool
    has_previous: bool
