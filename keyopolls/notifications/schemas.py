from typing import Dict, List, Optional

from keyoconnect.profiles.schemas import AuthorSchema
from ninja import Schema
from shared.schemas import PaginationSchema


class TargetInfoSchema(Schema):
    """Schema for target information in notifications"""

    type: str
    id: int
    title: Optional[str] = None
    content: Optional[str] = None


class DeepLinkData(Schema):
    """Schema for deep link data in notifications"""

    screen: str
    params: Optional[dict] = None


# Response Schemas
class NotificationSchema(Schema):
    """Schema for individual notification response"""

    id: int
    notification_type: str
    title: str
    message: str
    priority: str

    # URLs and deep linking
    click_url: Optional[str] = None
    deep_link_data: Optional[DeepLinkData] = None

    # Status
    is_read: bool
    is_clicked: bool

    # Actor information (who triggered the notification)
    actor_info: Optional[AuthorSchema] = None

    # Target information (what the notification is about)
    target_info: Optional[TargetInfoSchema] = None

    # Additional data
    extra_data: Optional[dict] = None

    # Timestamps
    created_at: str
    read_at: Optional[str] = None
    clicked_at: Optional[str] = None

    # Delivery status
    push_sent: bool = False
    email_sent: bool = False


class NotificationSummarySchema(Schema):
    """Schema for notification summary statistics"""

    total_count: int
    unread_count: int
    recent_count: int
    unread_by_type: Dict[str, int]


class NotificationsListResponse(Schema):
    """Schema for notifications list response with metadata"""

    notifications: List[NotificationSchema]

    # Pagination info
    pagination: PaginationSchema

    # Summary stats
    summary: NotificationSummarySchema = {
        "total_count": 0,
        "unread_count": 0,
        "unread_by_type": {},
        "recent_count": 0,  # Last 24 hours
    }

    # Filter info
    applied_filters: dict = {}


class NotificationActionResponse(Schema):
    """Schema for notification action responses"""

    success: bool
    message: str
    updated_count: Optional[int] = None


class NotificationSummaryResponse(Schema):
    """Schema for notification summary statistics"""

    total_count: int
    unread_count: int
    recent_count: int
    recent_unread_count: int
    unread_by_type: Dict[str, int]
    unread_by_priority: Dict[str, int]
    read_percentage: float


"""
FCM Related Schemas
"""


class FCMResponse(Schema):
    """Schema for FCM response"""

    success: bool
    message: str


class NotificationResponse(FCMResponse):
    """Schema for notification response"""

    sent: int
    total: int


class NotificationIn(Schema):
    """Schema for sending a notification"""

    title: str
    body: str
    data: Optional[Dict] = None


class NotificationPreferenceResponse(Schema):
    """Schema for notification preference response"""

    notification_type: str
    in_app_enabled: bool
    push_enabled: bool
    email_enabled: bool
    is_enabled: bool
    custom_thresholds: Optional[List[int]] = None
    can_receive_push: bool


class NotificationPreferenceUpdateIn(Schema):
    """Schema for updating notification preferences"""

    push_enabled: bool
    email_enabled: bool
    in_app_enabled: bool
    is_enabled: bool


class RegisterDeviceIn(Schema):
    """Schema for registering a device"""

    token: str
    device_type: str
    device_info: Optional[dict] = None


class UnregisterDeviceIn(Schema):
    """Schema for unregistering a device"""

    token: str


class BulkNotificationPreferenceUpdateIn(Schema):
    push_enabled: Optional[bool] = None
    email_enabled: Optional[bool] = None
    in_app_enabled: Optional[bool] = None
