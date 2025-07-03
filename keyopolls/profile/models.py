import random
import string
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone


class PseudonymousProfile(models.Model):
    username = models.CharField(max_length=50, unique=True)
    display_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    password_hash = models.CharField(max_length=255)

    avatar = models.ImageField(
        upload_to="avatars/",
        blank=True,
        null=True,
        help_text="Profile picture for the user. Optional.",
    )

    banner = models.ImageField(
        upload_to="banners/",
        blank=True,
        null=True,
        help_text="Banner image for the profile. Optional.",
    )

    about = models.TextField(
        blank=True,
        null=True,
        help_text="Short bio or description for the profile. Optional.",
    )

    # Aura scores
    aura_polls = models.IntegerField(default=0)
    aura_comments = models.IntegerField(default=0)

    # Authentication fields
    google_id = models.CharField(max_length=100, blank=True, null=True)
    is_email_verified = models.BooleanField(default=False)

    # OTP fields (stored directly in profile)
    otp = models.CharField(max_length=6, blank=True, null=True)
    otp_created_at = models.DateTimeField(blank=True, null=True)
    otp_attempts = models.IntegerField(default=0)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_login = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"{self.username} ({self.display_name})"

    @property
    def total_aura(self):
        """Calculate total aura score"""
        return self.aura_polls + self.aura_comments

    @property
    def is_profile_complete(self):
        """Check if profile is complete"""
        return bool(self.username)

    def set_password(self, raw_password):
        """Hash and set password"""
        self.password_hash = make_password(raw_password)

    def check_password(self, raw_password):
        """Check if provided password matches"""
        return check_password(raw_password, self.password_hash)

    def generate_otp(self):
        """Generate and store OTP"""
        self.otp = "".join(random.choices(string.digits, k=6))
        self.otp_created_at = timezone.now()
        self.otp_attempts = 0
        self.save()
        return self.otp

    def verify_otp(self, provided_otp):
        """Verify OTP with expiry and attempt limits"""
        if not self.otp or not self.otp_created_at:
            return False, "No OTP found"

        # Check if OTP is expired (5 minutes)
        if timezone.now() - self.otp_created_at > timedelta(minutes=5):
            self.clear_otp()
            return False, "OTP expired"

        # Check attempt limit (max 3 attempts)
        if self.otp_attempts >= 3:
            self.clear_otp()
            return False, "Too many failed attempts"

        if self.otp == provided_otp:
            self.clear_otp()
            self.is_email_verified = True
            self.save()
            return True, "OTP verified successfully"
        else:
            self.otp_attempts += 1
            self.save()
            return False, f"Invalid OTP. {3 - self.otp_attempts} attempts remaining"

    def clear_otp(self):
        """Clear OTP data"""
        self.otp = None
        self.otp_created_at = None
        self.otp_attempts = 0
        self.save()

    def update_last_login(self):
        """Update last login timestamp"""
        self.last_login = timezone.now()
        self.save()

    class Meta:
        db_table = "pseudonymous_profiles"
        ordering = ["-created_at"]
