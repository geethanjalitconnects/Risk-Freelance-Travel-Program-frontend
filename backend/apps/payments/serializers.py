"""Payout details API: input validation and the masked output. The full account number and UPI id
are write-only: they are never returned, logged or put in error messages."""
import re

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import PayoutAccount, PayoutMethod
from .validators import normalize_account_number, normalize_ifsc, normalize_upi, validate_ifsc

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z .'-]{1,99}$")


def _django(fn, value):
    try:
        return fn(value)
    except DjangoValidationError as e:
        raise serializers.ValidationError(e.messages[0])


class PayoutAccountInputSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=PayoutMethod.choices)
    holder_name = serializers.CharField(max_length=100)
    bank_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    account_number = serializers.CharField(max_length=40, required=False, allow_blank=True, default="", write_only=True)
    confirm_account_number = serializers.CharField(
        max_length=40, required=False, allow_blank=True, default="", write_only=True
    )
    ifsc = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    upi_id = serializers.CharField(max_length=300, required=False, allow_blank=True, default="", write_only=True)

    def validate_holder_name(self, value):
        value = " ".join(value.split())
        if not NAME_RE.match(value):
            raise serializers.ValidationError("Enter the name exactly as it appears on the bank account.")
        return value

    def validate(self, attrs):
        errors = {}
        if attrs["method"] == PayoutMethod.BANK:
            attrs["bank_name"] = " ".join(attrs["bank_name"].split())
            if not attrs["bank_name"]:
                errors["bank_name"] = "Enter your bank's name."
            try:
                attrs["account_number"] = _django(normalize_account_number, attrs["account_number"])
            except serializers.ValidationError as e:
                errors["account_number"] = e.detail[0]
            else:
                confirm = re.sub(r"[\s-]", "", attrs["confirm_account_number"])
                if confirm != attrs["account_number"]:
                    errors["confirm_account_number"] = "The account numbers don't match."
            attrs["ifsc"] = normalize_ifsc(attrs["ifsc"])
            try:
                _django(validate_ifsc, attrs["ifsc"])
            except serializers.ValidationError as e:
                errors["ifsc"] = e.detail[0]
        else:
            try:
                attrs["upi_id"] = _django(normalize_upi, attrs["upi_id"])
            except serializers.ValidationError as e:
                errors["upi_id"] = e.detail[0]
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class PayoutAccountOutSerializer(serializers.ModelSerializer):
    """Masked: last 4 digits of the account, masked UPI id."""

    display = serializers.CharField(read_only=True)

    class Meta:
        model = PayoutAccount
        fields = [
            "method", "holder_name", "bank_name", "ifsc", "account_last4", "upi_masked", "display", "status",
            "verified_at", "updated_at",
        ]
        read_only_fields = fields
