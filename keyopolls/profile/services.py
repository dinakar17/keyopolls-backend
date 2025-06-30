import http.client
import json
import logging
import random
import re
import string

import requests
from django.conf import settings
from django.template.loader import render_to_string
from twilio.rest import Client

logger = logging.getLogger(__name__)


class PhoneValidationError(Exception):
    """Exception raised for invalid phone number format."""

    pass


class CommunicationService:
    @staticmethod
    def validate_e164(phone: str) -> bool:
        """
        Validate if the phone number is in E.164 format.
        E.164 format: +[country code][number] with no spaces or special chars
        Example: +14155552671
        """
        e164_pattern = re.compile(r"^\+[1-9]\d{1,14}$")
        return bool(e164_pattern.match(phone))

    @staticmethod
    def send_phone_verification(phone: str, code: str, provider: str = "msg91") -> bool:
        """
        Send phone verification code using the specified provider.

        Args:
            phone: Phone number in E.164 format
            code: Verification code to send
            provider: SMS provider to use ('msg91' or 'twilio'), default is 'msg91'

        Returns:
            bool: True if the SMS was sent successfully, False otherwise
        """
        if provider.lower() == "twilio":
            return CommunicationService._send_twilio_verification(phone, code)
        else:
            # Default to MSG91
            return CommunicationService._send_msg91_verification(phone, code)

    @staticmethod
    def _send_twilio_verification(phone: str, code: str) -> bool:
        """Send verification code via Twilio"""
        try:
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            message = (
                f"{code} is your verification code. "
                "This code will expire in 5 minutes. "
                "Do not share this code with anyone."
            )
            client.messages.create(
                body=message,
                from_=settings.TWILIO_PHONE_NUMBER,
                to=phone,
            )
            logger.info(f"Verification SMS sent via Twilio to {phone}")
            return True
        except Exception as e:
            logger.error(f"Failed to send SMS via Twilio: {str(e)}")
            return False

    @staticmethod
    def _send_msg91_verification(phone: str, code: str) -> bool:
        """Send verification code via MSG91 using the flow API"""
        try:
            # Extract the phone number without '+' prefix and country code
            if not phone.startswith("+"):
                logger.error(f"Phone number {phone} is not in E.164 format")
                return False

            # Extract mobile number (remove '+' prefix)
            mobile = phone[1:]  # Remove '+' from the beginning

            conn = http.client.HTTPSConnection("control.msg91.com")

            # Prepare payload according to Flow API format
            payload = json.dumps(
                {
                    "template_id": settings.MSG91_TEMPLATE_ID,
                    "short_url": "0",
                    "short_url_expiry": "",
                    "realTimeResponse": "1",
                    "recipients": [{"mobiles": mobile, "OTP": code}],
                }
            )

            headers = {
                "authkey": settings.MSG91_AUTH_KEY,
                "accept": "application/json",
                "content-type": "application/json",
            }

            # Use the flow API endpoint
            conn.request("POST", "/api/v5/flow", payload, headers)

            # Get the response
            res = conn.getresponse()
            data = res.read().decode("utf-8")

            # Parse the response
            try:
                response_data = json.loads(data)
                if (
                    res.status in (200, 201, 202)
                    and response_data.get("type") == "success"
                ):
                    logger.info(f"Verification SMS sent via MSG91 to {phone}")
                    return True
                else:
                    logger.error(
                        f"Failed to send SMS via MSG91. Status code: {res.status}, "
                        f"Response: {data}"
                    )
                    return False
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON response from MSG91: {data}")
                return False

        except Exception as e:
            logger.error(f"Failed to send SMS via MSG91: {str(e)}")
            return False

    @staticmethod
    def generate_otp(length: int = 6) -> str:
        """Generate a random OTP of specified length"""
        return "".join(random.choices(string.digits, k=length))

    @staticmethod
    def send_email_otp(email: str, otp: str, template: str = "otp_email.html") -> bool:
        """
        Send OTP via email using ZeptoMail

        Args:
            email: Recipient email address
            otp: OTP code to send
            template: Email template to use

        Returns:
            bool: True if email was sent successfully, False otherwise
        """
        try:
            # Render HTML template with OTP
            html_content = render_to_string(
                template,
                {
                    "otp": otp,
                    "name": email.split("@")[0],  # Using part before @ as name
                },
            )

            url = "https://api.zeptomail.in/v1.1/email"

            payload = {
                "from": {"address": settings.DEFAULT_FROM_EMAIL},
                "to": [
                    {"email_address": {"address": email, "name": email.split("@")[0]}}
                ],
                "subject": "Your Verification Code",
                "htmlbody": html_content,
            }

            headers = {
                "accept": "application/json",
                "content-type": "application/json",
                "authorization": settings.ZEPTOMAIL_API_KEY,
            }

            response = requests.post(url, json=payload, headers=headers, timeout=10)

            if response.ok:  # Checks if status code is in the range [200, 400)
                logger.info(f"OTP email sent successfully to {email}")
                return True
            else:
                logger.error(
                    f"Failed to send OTP email. Status code: {response.status_code}, "
                    f"Response: {response.text}"
                )
                return False

        except Exception as e:
            logger.error(f"Error sending OTP email: {str(e)}")
            return False

    @staticmethod
    def send_notification_email(
        email: str,
        subject: str,
        title: str,
        message: str,
        click_url: str = None,
        recipient_name: str = None,
        notification_type: str = None,
    ) -> bool:
        """
        Send notification email using ZeptoMail

        Args:
            email: Recipient email address
            subject: Email subject line
            title: Notification title
            message: Notification message
            click_url: Optional URL for click action
            recipient_name: Optional recipient name
            notification_type: Type of notification for context

        Returns:
            bool: True if email was sent successfully, False otherwise
        """
        try:
            # Use email prefix as name if no name provided
            if not recipient_name:
                recipient_name = email.split("@")[0]

            # Prepare template context
            context = {
                "title": title,
                "message": message,
                "recipient_name": recipient_name,
                "click_url": click_url,
                "notification_type": notification_type,
                "app_name": getattr(settings, "APP_NAME", "Your App"),
                "app_url": getattr(settings, "FRONTEND_URL", "#"),
            }

            # Render HTML template
            html_content = render_to_string("notification_email.html", context)

            # Prepare ZeptoMail payload
            payload = {
                "from": {"address": settings.DEFAULT_FROM_EMAIL},
                "to": [
                    {
                        "email_address": {
                            "address": email,
                            "name": recipient_name,
                        }
                    }
                ],
                "subject": subject,
                "htmlbody": html_content,
            }

            headers = {
                "accept": "application/json",
                "content-type": "application/json",
                "authorization": settings.ZEPTOMAIL_API_KEY,
            }

            # Send email via ZeptoMail API
            url = "https://api.zeptomail.in/v1.1/email"
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=30,  # Increased timeout for notifications
            )

            if response.status_code == 201:
                logger.info(
                    f"Notification email sent successfully to {email} "
                    f"(Subject: {subject})"
                )
                return True
            else:
                logger.error(
                    f"Failed to send notification email to {email}. "
                    f"Status code: {response.status_code}, Response: {response.text}"
                )
                return False

        except Exception as e:
            logger.error(f"Error sending notification email to {email}: {str(e)}")
            return False
