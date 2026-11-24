"""Admin dashboard tokens, kept apart from the app's user tokens.

* Signed with ADMIN_JWT_SECRET (not the key that signs user tokens), with audience
  "vconnects-admin" and type "admin": a user token fails here, and an admin token fails on the
  user API (which checks the other key).
* Carry the role (admin / reviewer) and the account's ``admin_token_version``. Signing out or
  changing the password bumps the version, so older tokens stop working at once.
"""
from datetime import timedelta

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.crypto import salted_hmac

AUDIENCE = "vconnects-admin"
ISSUER = "vconnects"
TOKEN_TYPE = "admin"
REVIEW_PERM = "verification.review_driververification"
DOCUMENTS_PERM = "verification.view_documents"


class InvalidAdminToken(Exception):
    pass


def _key() -> str:
    if settings.ADMIN_JWT_SECRET:
        return settings.ADMIN_JWT_SECRET
    # Development only (prod.py requires ADMIN_JWT_SECRET): a key derived from SECRET_KEY that is
    # still different from the one simplejwt uses for user tokens.
    return salted_hmac("vconnects.admin-jwt", "admin-token-signing-key", algorithm="sha256").hexdigest()


def role_of(user):
    """"admin" (superuser), "reviewer" (may review verifications) or None (no dashboard access)."""
    if not (user and user.is_active and user.is_staff):
        return None
    if user.is_superuser:
        return "admin"
    if user.has_perm(REVIEW_PERM):
        return "reviewer"
    return None


def issue(user) -> dict:
    role = role_of(user)
    if role is None:
        raise InvalidAdminToken("No dashboard access.")
    now = timezone.now()
    expires = now + timedelta(minutes=settings.ADMIN_JWT_MINUTES)
    claims = {
        "sub": str(user.pk),
        "role": role,
        "typ": TOKEN_TYPE,
        "ver": user.admin_token_version,
        "aud": AUDIENCE,
        "iss": ISSUER,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }
    return {"token": jwt.encode(claims, _key(), algorithm="HS256"), "expires_at": int(expires.timestamp() * 1000)}


def decode(token: str):
    """Return (user, role) for a valid admin token, or raise InvalidAdminToken."""
    try:
        claims = jwt.decode(
            token, _key(), algorithms=["HS256"], audience=AUDIENCE, issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.PyJWTError as e:
        raise InvalidAdminToken("Invalid or expired admin token.") from e
    if claims.get("typ") != TOKEN_TYPE:
        raise InvalidAdminToken("Not an admin token.")
    user = get_user_model().objects.filter(pk=claims["sub"]).first()
    if user is None or claims.get("ver") != user.admin_token_version:
        raise InvalidAdminToken("This session has ended. Sign in again.")
    role = role_of(user)  # recomputed, so removing someone's access takes effect at once
    if role is None:
        raise InvalidAdminToken("No dashboard access.")
    return user, role
