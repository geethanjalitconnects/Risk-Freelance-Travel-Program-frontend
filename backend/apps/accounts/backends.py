"""Admin sign-in with a phone number typed in any common format.

"7339284804", "73392 84804", "+91 73392-84804" and "+917339284804" all mean the same account, as
in the app's OTP sign-in (see normalize_phone). The lockout tool (django-axes) counts failures on
the same normalised number, so changing the format doesn't earn extra attempts.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import ValidationError

from .models import normalize_phone


def _normalized(raw):
    if raw is None:
        return None
    try:
        return normalize_phone(str(raw))
    except ValidationError:
        return str(raw)  # not a phone number: let the normal lookup fail


class PhoneModelBackend(ModelBackend):
    """Staff sign in with their phone number, or with the username of a seeded admin account."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        field = User.USERNAME_FIELD
        if username is None:
            username = kwargs.pop(field, None)
        else:
            kwargs.pop(field, None)
        if username is None or password is None:
            return None
        user = User.objects.filter(phone=_normalized(username)).first() or User.objects.filter(username=str(username).strip()).first()
        if user is None:
            User().set_password(password)  # same work as a real check, so timing doesn't reveal accounts
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None


def axes_username(request, credentials=None):
    """AXES_USERNAME_CALLABLE: the normalised phone from the login attempt."""
    field = get_user_model().USERNAME_FIELD
    raw = None
    if credentials:
        raw = credentials.get("username", credentials.get(field))
    if raw is None and request is not None:
        data = getattr(request, "POST", {}) or {}
        raw = data.get("username", data.get(field))
    return _normalized(raw)
