from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import (
    ADMIN_JWT_SECRET,
    ADMIN_URL,
    DOCUMENT_ENCRYPTION_KEYS,
    EMAIL_BACKEND,
    PAYOUT_ENCRYPTION_KEYS,
    SECRET_KEY,
    SMS_BACKEND,
    env,
)

DEBUG = False

if SECRET_KEY.startswith("dev-insecure"):
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY for production.")

if not SMS_BACKEND or SMS_BACKEND.endswith(("ConsoleSMSBackend", "LocmemSMSBackend")):
    raise ImproperlyConfigured("Set SMS_BACKEND to a real SMS provider backend for production.")

if not DOCUMENT_ENCRYPTION_KEYS:
    raise ImproperlyConfigured("Set DOCUMENT_ENCRYPTION_KEYS (manage.py generate_document_key) for production.")

if not PAYOUT_ENCRYPTION_KEYS:
    raise ImproperlyConfigured("Set PAYOUT_ENCRYPTION_KEYS (different from DOCUMENT_ENCRYPTION_KEYS) for production.")

if set(PAYOUT_ENCRYPTION_KEYS) & set(DOCUMENT_ENCRYPTION_KEYS):
    raise ImproperlyConfigured("PAYOUT_ENCRYPTION_KEYS must not reuse any DOCUMENT_ENCRYPTION_KEYS key.")

if env.bool("PAYMENTS_ENABLED", default=False):
    if not (env("RAZORPAY_KEY_ID", default="") and env("RAZORPAY_KEY_SECRET", default="")):
        raise ImproperlyConfigured("Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET when PAYMENTS_ENABLED is on.")
    if len(env("RAZORPAY_WEBHOOK_SECRET", default="")) < 16:
        raise ImproperlyConfigured("Set RAZORPAY_WEBHOOK_SECRET (16+ characters) when PAYMENTS_ENABLED is on.")
    if env("RAZORPAY_KEY_ID").startswith("rzp_test_") and not env.bool("RAZORPAY_ALLOW_TEST_KEYS", default=False):
        raise ImproperlyConfigured("Production is using Razorpay TEST keys. Set live keys (or RAZORPAY_ALLOW_TEST_KEYS=True on staging).")

if ADMIN_URL in ("admin/", "vct-admin/"):
    raise ImproperlyConfigured("Set ADMIN_URL to a private, non-default path for production.")

if len(ADMIN_JWT_SECRET) < 32 or ADMIN_JWT_SECRET == SECRET_KEY:
    raise ImproperlyConfigured("Set ADMIN_JWT_SECRET (32+ characters, different from DJANGO_SECRET_KEY) for production.")

if EMAIL_BACKEND.endswith(("console.EmailBackend", "locmem.EmailBackend", "dummy.EmailBackend")):
    raise ImproperlyConfigured("Set EMAIL_BACKEND (and the SMTP settings) to a real mail backend for production.")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("DJANGO_HSTS_SECONDS", default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("DJANGO_HSTS_INCLUDE_SUBDOMAINS", default=True)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [  # noqa: F405
    "djangorestframework_camel_case.render.CamelCaseJSONRenderer",
]
