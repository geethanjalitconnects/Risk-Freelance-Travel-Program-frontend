"""Email sign-in codes: issue, rate-limit and verify.

* 6-digit codes from ``secrets``; only an HMAC (keyed with SECRET_KEY) is stored.
* A code expires after OTP_TTL_SECONDS and allows OTP_MAX_ATTEMPTS wrong guesses.
* Requesting a new code invalidates earlier ones for that address.
* Per address: one code every OTP_RESEND_SECONDS, at most OTP_MAX_SENDS_PER_HOUR an hour.
  (Per-IP limits are applied by DRF throttles on the views.)
"""
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import EmailOTP


def _hash(ident: str, code: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"{ident}:{code}".encode(), hashlib.sha256).hexdigest()


def _new_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(settings.OTP_LENGTH))


class OTPError(Exception):
    def __init__(self, message: str, code: str, retry_after: Optional[int] = None, attempts_left: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.retry_after = retry_after
        self.attempts_left = attempts_left


@dataclass
class Issued:
    expires_in: int
    resend_in: int


class _Channel:
    def __init__(self, model, field, deliver, failed_message, failed_code):
        self.model, self.field, self.deliver = model, field, deliver
        self.failed_message, self.failed_code = failed_message, failed_code

    def rows(self, ident):
        return self.model.objects.filter(**{self.field: ident})


def _send_email(email, code):
    from django.core.mail import send_mail

    minutes = settings.OTP_TTL_SECONDS // 60
    send_mail(
        subject=f"{code} is your VConnects sign-in code",
        message=(
            f"Your VConnects sign-in code is {code}\n\n"
            f"It expires in {minutes} minutes. Don't share it with anyone: VConnects will never ask for it.\n"
            "If you didn't try to sign in, you can ignore this email."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=False,
    )


EMAIL = _Channel(EmailOTP, "email", _send_email, "We couldn't email the code. Please try again.", "email_failed")


def issue_email(email: str) -> Issued:
    return _issue(EMAIL, email)


def verify_email(email: str, code: str) -> None:
    _verify(EMAIL, email, code)


def _issue(ch: _Channel, ident: str) -> Issued:
    now = timezone.now()
    with transaction.atomic():
        recent = ch.model.objects.select_for_update().filter(**{ch.field: ident}, created_at__gt=now - timedelta(hours=1))
        latest = recent.first()
        if latest:
            wait = settings.OTP_RESEND_SECONDS - int((now - latest.created_at).total_seconds())
            if wait > 0:
                raise OTPError("Please wait before requesting another code.", "resend_too_soon", retry_after=wait)
        if recent.count() >= settings.OTP_MAX_SENDS_PER_HOUR:
            oldest = recent.order_by("created_at").first()
            wait = 3600 - int((now - oldest.created_at).total_seconds())
            raise OTPError("Too many codes requested. Try again later.", "too_many_codes", retry_after=max(wait, 1))

        ch.rows(ident).filter(consumed_at__isnull=True).update(expires_at=now)
        code = _new_code()
        otp = ch.model.objects.create(
            **{ch.field: ident}, code_hash=_hash(ident, code), expires_at=now + timedelta(seconds=settings.OTP_TTL_SECONDS)
        )
    try:
        ch.deliver(ident, code)
    except OSError as e:  # SMTP / socket failures
        import logging

        logging.getLogger(__name__).warning("Sign-in code delivery failed (%s): %s", ch.field, type(e).__name__)
        otp.delete()  # don't make the user wait out the resend timer for a code they never got
        raise OTPError(ch.failed_message, ch.failed_code)
    return Issued(expires_in=settings.OTP_TTL_SECONDS, resend_in=settings.OTP_RESEND_SECONDS)


def _verify(ch: _Channel, ident: str, code: str) -> None:
    """Consume the code or raise OTPError. Wrong guesses count against the code.

    Errors are raised only after the transaction commits: raising inside ``atomic()`` would roll
    back the attempt counter and allow unlimited guesses.
    """
    error = None
    with transaction.atomic():
        otp = ch.model.objects.select_for_update().filter(**{ch.field: ident}, consumed_at__isnull=True).first()
        if otp is None or otp.expires_at <= timezone.now():
            error = OTPError("This code has expired. Request a new one.", "expired")
        elif otp.attempts >= settings.OTP_MAX_ATTEMPTS:
            error = OTPError("Too many wrong attempts. Request a new code.", "too_many_attempts", attempts_left=0)
        elif not hmac.compare_digest(otp.code_hash, _hash(ident, code)):
            otp.attempts += 1
            otp.save(update_fields=["attempts"])
            left = settings.OTP_MAX_ATTEMPTS - otp.attempts
            if left == 0:
                error = OTPError("Too many wrong attempts. Request a new code.", "too_many_attempts", attempts_left=0)
            else:
                error = OTPError("That code isn't right.", "incorrect", attempts_left=left)
        else:
            otp.consumed_at = timezone.now()
            otp.save(update_fields=["consumed_at"])
    if error:
        raise error
