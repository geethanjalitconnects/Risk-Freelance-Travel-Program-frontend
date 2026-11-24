"""Validation and masking for publisher payout details."""
import re

from django.core.exceptions import ValidationError

IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")  # 4 letters (bank), a zero, 6 branch characters
ACCOUNT_RE = re.compile(r"^\d{9,18}$")  # Indian bank account numbers are 9 to 18 digits
UPI_RE = re.compile(r"^[a-z0-9][a-z0-9.\-_]{1,255}@[a-z][a-z0-9]{1,63}$")


def normalize_ifsc(value: str) -> str:
    return (value or "").strip().upper()


def validate_ifsc(value: str):
    if not IFSC_RE.match(normalize_ifsc(value)):
        raise ValidationError("Enter a valid 11-character IFSC, like HDFC0001234.", code="invalid_ifsc")


def normalize_account_number(value: str) -> str:
    number = re.sub(r"[\s-]", "", value or "")
    if not ACCOUNT_RE.match(number):
        raise ValidationError("Enter a valid account number (9 to 18 digits).", code="invalid_account_number")
    return number


def normalize_upi(value: str) -> str:
    upi = (value or "").strip().lower()
    if not UPI_RE.match(upi):
        raise ValidationError("Enter a valid UPI id, like name@okbank.", code="invalid_upi")
    return upi


def mask_upi(upi: str) -> str:
    """name1234@okaxis -> na******@okaxis"""
    handle, _, bank = upi.partition("@")
    return f"{handle[:2]}{'*' * max(2, len(handle) - 2)}@{bank}"
