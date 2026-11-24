"""SMS is turned off: no provider is configured and nothing is ever sent.

With DEBUG on, messages are printed to the console. Otherwise ``DisabledSMSBackend`` refuses them
with ``SMSError``, which callers already handle (phone OTP answers 503; trip alerts are logged
and skipped). Tests may still point the optional ``SMS_BACKEND`` setting at ``LocmemSMSBackend``.
"""
import logging
import sys

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)

CONSOLE_BACKEND = "apps.accounts.sms.ConsoleSMSBackend"


class SMSError(Exception):
    """Raised by a backend when the message could not be handed to the provider."""


class BaseSMSBackend:
    def send(self, phone: str, message: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class ConsoleSMSBackend(BaseSMSBackend):
    """Development: print the message to the server console instead of sending it."""

    def send(self, phone, message):
        line = "-" * 60
        sys.stdout.write(f"\n{line}\n[SMS to {phone}] {message}\n{line}\n")
        sys.stdout.flush()


class DisabledSMSBackend(BaseSMSBackend):
    """Production: SMS is not offered, so every message is refused."""

    def send(self, phone, message):
        raise SMSError("SMS is turned off")


class LocmemSMSBackend(BaseSMSBackend):
    """Tests: keep messages in memory (``LocmemSMSBackend.outbox``)."""

    outbox: list = []

    def send(self, phone, message):
        type(self).outbox.append({"phone": phone, "message": message})


def get_backend() -> BaseSMSBackend:
    path = CONSOLE_BACKEND if settings.DEBUG else getattr(settings, "SMS_BACKEND", "")
    return import_string(path)() if path else DisabledSMSBackend()


def send_sms(phone: str, message: str) -> None:
    try:
        get_backend().send(phone, message)
    except SMSError:
        logger.exception("SMS to %s failed", phone[:-4] + "****")
        raise
