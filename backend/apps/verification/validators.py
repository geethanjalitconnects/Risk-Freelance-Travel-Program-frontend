import re

from django.conf import settings
from rest_framework import serializers

# Detected from the file's first bytes, never from its name or the browser's claimed type.
SIGNATURES = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"%PDF-", "application/pdf"),
]

# Indian registration numbers: state code, RTO number, optional series, number (e.g. TN09AB1234,
# DL3CAB1234, KA051234) and Bharat series (e.g. 22BH1234AA).
_STANDARD_PLATE = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{1,4}$")
_BH_PLATE = re.compile(r"^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$")


def normalize_vehicle_number(raw: str) -> str:
    value = re.sub(r"[\s.\-]", "", (raw or "").upper())
    if not (_STANDARD_PLATE.match(value) or _BH_PLATE.match(value)):
        raise serializers.ValidationError("Enter a valid vehicle registration number, e.g. TN 09 AB 1234.")
    return value


def read_document(upload) -> tuple:
    """Return (bytes, content_type) or raise a ValidationError. Never echoes the file name."""
    if upload.size == 0:
        raise serializers.ValidationError("The file is empty.")
    if upload.size > settings.DOCUMENT_MAX_BYTES:
        raise serializers.ValidationError(f"Each file must be {settings.DOCUMENT_MAX_BYTES // (1024 * 1024)} MB or smaller.")
    data = upload.read()
    for signature, content_type in SIGNATURES:
        if data.startswith(signature):
            return data, content_type
    raise serializers.ValidationError("Upload a JPG, PNG or PDF file.")
