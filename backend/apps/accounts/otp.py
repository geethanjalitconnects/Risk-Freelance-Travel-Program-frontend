"""Phone sign-in codes: issue, rate-limit and verify.

* 6-digit codes from ``secrets``; only an HMAC (keyed with SECRET_KEY) is stored.
* A code expires after OTP_TTL_SECONDS and allows OTP_MAX_ATTEMPTS wrong guesses.
* Requesting a new code invalidates earlier ones for that number.
* Per number: one code every OTP_RESEND_SECONDS, at most OTP_MAX_SENDS_PER_HOUR an hour.
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

from .models import PhoneOTP
from .sms import SMSError, send_sms


def _hash(phone: str, code: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


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


def issue(phone: str) -> Issued:
    now = timezone.now()
    with transaction.atomic():
        recent = PhoneOTP.objects.select_for_update().filter(phone=phone, created_at__gt=now - timedelta(hours=1))
        latest = recent.first()
        if latest:
            wait = settings.OTP_RESEND_SECONDS - int((now - latest.created_at).total_seconds())
            if wait > 0:
                raise OTPError("Please wait before requesting another code.", "resend_too_soon", retry_after=wait)
        if recent.count() >= settings.OTP_MAX_SENDS_PER_HOUR:
            oldest = recent.order_by("created_at").first()
            wait = 3600 - int((now - oldest.created_at).total_seconds())
            raise OTPError("Too many codes requested for this number. Try again later.", "too_many_codes", retry_after=max(wait, 1))

        PhoneOTP.objects.filter(phone=phone, consumed_at__isnull=True).update(expires_at=now)
        code = _new_code()
        otp = PhoneOTP.objects.create(
            phone=phone, code_hash=_hash(phone, code), expires_at=now + timedelta(seconds=settings.OTP_TTL_SECONDS)
        )
    minutes = settings.OTP_TTL_SECONDS // 60
    try:
        send_sms(phone, f"{code} is your VConnects sign-in code. It expires in {minutes} minutes. Don't share it with anyone.")
    except SMSError:
        otp.delete()  # don't make the user wait out the resend timer for a code they never got
        raise OTPError("We couldn't send the code. Please try again.", "sms_failed")
    return Issued(expires_in=settings.OTP_TTL_SECONDS, resend_in=settings.OTP_RESEND_SECONDS)


def verify(phone: str, code: str) -> None:
    """Consume the code or raise OTPError. Wrong guesses count against the code.

    Errors are raised only after the transaction commits: raising inside ``atomic()`` would roll
    back the attempt counter and allow unlimited guesses.
    """
    error = None
    with transaction.atomic():
        otp = PhoneOTP.objects.select_for_update().filter(phone=phone, consumed_at__isnull=True).first()
        if otp is None or otp.expires_at <= timezone.now():
            error = OTPError("This code has expired. Request a new one.", "expired")
        elif otp.attempts >= settings.OTP_MAX_ATTEMPTS:
            error = OTPError("Too many wrong attempts. Request a new code.", "too_many_attempts", attempts_left=0)
        elif not hmac.compare_digest(otp.code_hash, _hash(phone, code)):
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
