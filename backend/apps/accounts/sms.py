"""Pluggable SMS sending.

Pick a backend with the ``SMS_BACKEND`` setting (a dotted path). When ``DEBUG`` is on, the
console backend is always used, so no SMS is ever sent from a development machine.

To add a real provider (MSG91, Twilio, AWS SNS, ...) subclass ``BaseSMSBackend``, implement
``send()`` and point ``SMS_BACKEND`` at it, e.g. ``SMS_BACKEND=myproject.sms.Msg91Backend``.
"""
import logging
import sys

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
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


class LocmemSMSBackend(BaseSMSBackend):
    """Tests: keep messages in memory (``LocmemSMSBackend.outbox``)."""

    outbox: list = []

    def send(self, phone, message):
        type(self).outbox.append({"phone": phone, "message": message})


def get_backend() -> BaseSMSBackend:
    path = CONSOLE_BACKEND if settings.DEBUG else settings.SMS_BACKEND
    if not path:
        raise ImproperlyConfigured("Set SMS_BACKEND to an SMS provider backend (DEBUG is off).")
    return import_string(path)()


def send_sms(phone: str, message: str) -> None:
    try:
        get_backend().send(phone, message)
    except SMSError:
        logger.exception("SMS to %s failed", phone[:-4] + "****")
        raise
