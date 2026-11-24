"""Encryption at rest for driver verification documents (Fernet: AES-128-CBC + HMAC-SHA256).

Keys come from DOCUMENT_ENCRYPTION_KEYS. The first key encrypts new files; every key can decrypt,
so a key is rotated by putting a new one first and keeping the old one until files are re-saved.
"""
import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


class DocumentDecryptionError(Exception):
    pass


def _keys() -> list:
    keys = [k.strip() for k in settings.DOCUMENT_ENCRYPTION_KEYS if k.strip()]
    if keys:
        return keys
    if settings.DEBUG:
        # Development only: a stable key derived from SECRET_KEY, so local files survive restarts.
        logger.warning("DOCUMENT_ENCRYPTION_KEYS is not set; using a development key derived from SECRET_KEY.")
        digest = hashlib.sha256(f"{settings.SECRET_KEY}:verification-documents".encode()).digest()
        return [base64.urlsafe_b64encode(digest).decode()]
    raise ImproperlyConfigured("DOCUMENT_ENCRYPTION_KEYS must be set to store verification documents.")


def _fernet() -> MultiFernet:
    return MultiFernet([Fernet(k.encode()) for k in _keys()])


def encrypt(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def decrypt(token: bytes) -> bytes:
    try:
        return _fernet().decrypt(token)
    except InvalidToken as e:
        raise DocumentDecryptionError("The document could not be decrypted with the configured keys.") from e


def generate_key() -> str:
    return Fernet.generate_key().decode()
