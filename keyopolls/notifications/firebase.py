import logging

import firebase_admin
from django.conf import settings
from firebase_admin import credentials, messaging

logger = logging.getLogger(__name__)


class FirebaseService:
    """Firebase service for FCM operations"""

    @classmethod
    def initialize(cls):
        """Initialize Firebase Admin SDK"""
        if not firebase_admin._apps:
            try:
                cred = credentials.Certificate(settings.FCM_CREDENTIALS_PATH)
                firebase_admin.initialize_app(cred)
                logger.info("Firebase Admin SDK initialized successfully")
                return True
            except Exception as e:
                logger.error(f"Failed to initialize Firebase Admin SDK: {str(e)}")
                return False
        return True

    @classmethod
    def send_message(cls, token, title, body, data=None, notification_options=None):
        """Send FCM message to a single token"""
        if not cls.initialize():
            return False

        try:
            # Create notification
            notification = messaging.Notification(
                title=title, body=body, **(notification_options or {})
            )

            # Create message
            message = messaging.Message(
                notification=notification, data=data or {}, token=token, topic="all"
            )

            # Send message
            response = messaging.send(message)
            logger.info(f"Successfully sent message: {response}")
            return response
        except Exception as e:
            logger.error(f"Error sending FCM message: {str(e)}")
            return None

    @classmethod
    def send_multicast(cls, tokens, title, body, data=None, notification_options=None):
        """Send FCM message to multiple tokens by iteratively sending individual
        messages."""
        if not cls.initialize():
            return {"success": 0, "failure": len(tokens)}

        if not tokens:
            return {"success": 0, "failure": 0}

        # Create the notification object (shared across messages)
        notification = messaging.Notification(
            title=title, body=body, **(notification_options or {})
        )

        success_count = 0
        failure_count = 0

        # Iterate and send each message individually using messaging.send()
        for token in tokens:
            try:
                message = messaging.Message(
                    notification=notification, data=data or {}, token=token
                )
                response = messaging.send(message)
                logger.info(
                    f"Successfully sent message to token {token[:15]}...: {response}"
                )
                success_count += 1
            except Exception as e:
                logger.error(
                    f"Failed to send message to token {token[:15]}...: {str(e)}"
                )
                failure_count += 1

        return {"success": success_count, "failure": failure_count}
