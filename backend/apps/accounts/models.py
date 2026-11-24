import re
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

# Same rule the frontend applies to trusted-contact phones: optional +, then 8-15 digits/spaces.
CONTACT_PHONE_RE = re.compile(r"^\+?[0-9 ]{8,15}$")
# Login phones are stored in E.164 so they can receive an SMS: +<country code><number>.
E164_RE = re.compile(r"^\+[1-9][0-9]{7,14}$")
MAX_TRUSTED_CONTACTS = 5


def normalize_phone(raw: str) -> str:
    """Normalise a login phone number to E.164.

    Spaces and hyphens are ignored. A bare 10-digit number gets the default country code
    (``PHONE_DEFAULT_COUNTRY_CODE``, +91), so "98765 43210" and "+91 98765 43210" are one account.
    """
    value = re.sub(r"[\s-]", "", raw or "")
    if re.fullmatch(r"[0-9]{10}", value):
        value = settings.PHONE_DEFAULT_COUNTRY_CODE + value
    if not E164_RE.match(value):
        raise ValidationError("Enter a valid mobile number, e.g. +91 98765 43210.")
    return value


def default_languages():
    return ["English"]


class Gender(models.TextChoices):
    # Matches the <select> on the Profile page: "" = Prefer not to say.
    UNSPECIFIED = "", "Prefer not to say"
    FEMALE = "F", "Female"
    MALE = "M", "Male"
    OTHER = "O", "Other"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, phone, password=None, **extra):
        phone = normalize_phone(phone)
        user = self.model(phone=phone, **extra)
        if password:
            user.set_password(password)
        else:
            # Regular users sign in with phone + OTP only.
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_email_user(self, email, **extra):
        """An app user who signs in with an emailed code (no password, phone added later)."""
        user = self.model(phone=None, email=normalize_email(email), **extra)
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_admin(self, username, password, **extra):
        """A dashboard admin who signs in with username + password and has no phone."""
        if not username or not password:
            raise ValueError("Admins need a username and a password.")
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        user = self.model(phone=None, username=username, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        if not password:
            raise ValueError("Superusers need a password to sign in to the Django admin.")
        return self.create_user(phone, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # App users sign in with their phone. Dashboard admins created by `seed_admin` have no phone
    # and sign in with ``username`` instead (NULLs don't clash with the unique constraints).
    phone = models.CharField(max_length=16, unique=True, null=True, blank=True)
    username = models.CharField(max_length=150, unique=True, null=True, blank=True)
    name = models.CharField(max_length=100, blank=True)
    # Sign-in address (a code is emailed to it) and where verification decisions are emailed.
    # Unique (case-insensitive) when set; stored lower-case.
    email = models.EmailField(blank=True)
    gender = models.CharField(max_length=1, choices=Gender.choices, blank=True, default=Gender.UNSPECIFIED)

    # Kept in sync with the driver verification status (apps.verification): True only while an
    # admin-approved verification exists. They feed the risk model's driver factor. Never set by users.
    verified_id = models.BooleanField(default=False)
    verified_license = models.BooleanField(default=False)

    # Shown on the ride detail page for drivers.
    bio = models.CharField(max_length=280, blank=True)
    languages = models.JSONField(default=default_languages, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    # Set when an admin deactivates the account; drives document retention.
    deactivated_at = models.DateTimeField(null=True, blank=True)

    # Admin accounts: a new (seeded) admin must choose their own password before doing anything.
    must_change_password = models.BooleanField(default=False)
    # Bumped on admin logout and password change: every admin token carries it, so older tokens
    # stop working at once.
    admin_token_version = models.PositiveIntegerField(default=0)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        ordering = ["-date_joined"]
        constraints = [
            models.UniqueConstraint(Lower("email"), condition=~Q(email=""), name="uniq_user_email_ci"),
        ]

    def __str__(self):
        return f"{self.name or 'Unnamed'} ({self.email or self.phone or self.username})"

    @property
    def first_name(self):
        return self.name.split()[0] if self.name.strip() else ""

    @property
    def member_since(self) -> int:
        return timezone.localtime(self.date_joined).year


class PhoneOTP(models.Model):
    """A one-time sign-in code. Only a keyed hash of the code is stored."""

    phone = models.CharField(max_length=16, db_index=True)
    code_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "phone OTP"

    def __str__(self):
        return f"OTP for {self.phone} at {self.created_at:%Y-%m-%d %H:%M}"

    @property
    def is_usable(self) -> bool:
        return self.consumed_at is None and self.expires_at > timezone.now()


class EmailOTP(models.Model):
    """A one-time sign-in code sent by email. Only a keyed hash of the code is stored."""

    email = models.EmailField(db_index=True)
    code_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "email OTP"

    def __str__(self):
        return f"OTP for {self.email} at {self.created_at:%Y-%m-%d %H:%M}"


class TrustedContact(models.Model):
    """Someone alerted on a missed check-in or SOS. Up to 5 per user."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="contacts")
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    relation = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.name} ({self.relation or 'contact'}) for {self.user}"


def normalize_email(raw: str) -> str:
    return (raw or "").strip().lower()
