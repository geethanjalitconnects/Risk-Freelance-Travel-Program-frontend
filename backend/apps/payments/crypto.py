"""Encryption at rest for publisher payout details (Fernet: AES-128-CBC + HMAC-SHA256).

Keys come from PAYOUT_ENCRYPTION_KEYS, separate from the document keys so each can be rotated on
its own. The first key encrypts; every key decrypts. Required in production; development falls
back to a key derived from SECRET_KEY.
"""
import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


class PayoutDecryptionError(Exception):
    pass


def _keys() -> list:
    keys = [k.strip() for k in settings.PAYOUT_ENCRYPTION_KEYS if k.strip()]
    if keys:
        return keys
    if settings.DEBUG:
        logger.warning("PAYOUT_ENCRYPTION_KEYS is not set; using a development key derived from SECRET_KEY.")
        digest = hashlib.sha256(f"{settings.SECRET_KEY}:payout-details".encode()).digest()
        return [base64.urlsafe_b64encode(digest).decode()]
    raise ImproperlyConfigured("PAYOUT_ENCRYPTION_KEYS must be set to store payout details.")


def _fernet() -> MultiFernet:
    return MultiFernet([Fernet(k.encode()) for k in _keys()])


def encrypt_text(value: str) -> bytes:
    return _fernet().encrypt(value.encode())


def decrypt_text(token: bytes) -> str:
    try:
        return _fernet().decrypt(token).decode()
    except InvalidToken as e:
        # Never include the token or the value in the message.
        raise PayoutDecryptionError("Payout details could not be decrypted with the configured keys.") from e
