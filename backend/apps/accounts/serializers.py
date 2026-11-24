import re

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.bookings.models import Booking, BookingStatus
from apps.rides.policies import gender_lock_reason
from apps.verification.services import status_of

from .models import (
    CONTACT_PHONE_RE,
    MAX_TRUSTED_CONTACTS,
    Gender,
    TrustedContact,
    User,
    normalize_phone,
)

# ---------------------------------------------------------------- OTP


class PhoneField(serializers.CharField):
    def to_internal_value(self, data):
        try:
            return normalize_phone(super().to_internal_value(data))
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.messages)


class SendOTPSerializer(serializers.Serializer):
    phone = PhoneField(max_length=20)


class VerifyOTPSerializer(serializers.Serializer):
    phone = PhoneField(max_length=20)
    code = serializers.CharField(max_length=10)

    def validate_code(self, value):
        value = value.strip()
        if not re.fullmatch(rf"[0-9]{{{settings.OTP_LENGTH}}}", value):
            raise serializers.ValidationError(f"Enter the {settings.OTP_LENGTH}-digit code.")
        return value


class OTPSentSerializer(serializers.Serializer):
    sent = serializers.BooleanField()
    phone = serializers.CharField()
    expires_in = serializers.IntegerField()
    resend_in = serializers.IntegerField()


# ---------------------------------------------------------------- contacts


class TrustedContactSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=100, error_messages={"blank": "Enter a name.", "required": "Enter a name."})
    phone = serializers.CharField(max_length=20)
    relation = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")

    class Meta:
        model = TrustedContact
        fields = ["id", "name", "phone", "relation"]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Enter a name.")
        return value

    def validate_phone(self, value):
        value = value.strip()
        if not CONTACT_PHONE_RE.match(value):
            raise serializers.ValidationError("Enter a valid phone number (8-15 digits).")
        return value

    def validate_relation(self, value):
        return value.strip()

    def validate(self, attrs):
        user = self.context["request"].user
        if self.instance is None and user.contacts.count() >= MAX_TRUSTED_CONTACTS:
            raise serializers.ValidationError(f"You can add up to {MAX_TRUSTED_CONTACTS} contacts.")
        return attrs


# ---------------------------------------------------------------- me


class MeSerializer(serializers.ModelSerializer):
    """The signed-in user. A superset of the frontend's ``profile`` object
    ({name, phone, gender, verifiedId, verifiedLicense, contacts})."""

    langs = serializers.ListField(source="languages", child=serializers.CharField())
    since = serializers.IntegerField(source="member_since")
    contacts = TrustedContactSerializer(many=True, read_only=True)
    active_trips = serializers.SerializerMethodField()
    gender_locked = serializers.SerializerMethodField()
    profile_complete = serializers.SerializerMethodField()
    driver_verification = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "phone", "name", "email", "gender", "verified_id", "verified_license", "bio", "langs", "since",
            "contacts", "active_trips", "gender_locked", "profile_complete", "driver_verification",
        ]

    @extend_schema_field(OpenApiTypes.INT)
    def get_active_trips(self, user):
        """Trips in progress; drives the live dot on "My trips" in the header."""
        return Booking.objects.filter(passenger=user, status=BookingStatus.IN_PROGRESS).count()

    @extend_schema_field(OpenApiTypes.STR)
    def get_gender_locked(self, user):
        """Null, or why gender can't be changed right now."""
        return gender_lock_reason(user)

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_profile_complete(self, user):
        """False until the user has entered a name (the sign-up details step)."""
        return bool(user.name.strip())

    @extend_schema_field(OpenApiTypes.STR)
    def get_driver_verification(self, user):
        """not_submitted / pending / approved / rejected / resubmit_requested / revoked
        (details: GET /me/driver-verification)."""
        return status_of(user)


class MeUpdateSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=100, error_messages={"blank": "Enter your name."})
    gender = serializers.ChoiceField(choices=Gender.choices, allow_blank=True)
    bio = serializers.CharField(max_length=280, allow_blank=True)
    langs = serializers.ListField(
        source="languages", child=serializers.CharField(max_length=30), max_length=10, allow_empty=False
    )
    email = serializers.EmailField(required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ["name", "email", "gender", "bio", "langs"]

    def validate_name(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("Enter your name.")
        return value

    def validate_gender(self, value):
        if value != self.instance.gender:
            reason = gender_lock_reason(self.instance)
            if reason:
                raise serializers.ValidationError(reason)
        return value

    def validate_langs(self, value):
        return list(dict.fromkeys(v.strip() for v in value if v.strip())) or ["English"]


class AuthResultSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    is_new_user = serializers.BooleanField()
    user = MeSerializer()
