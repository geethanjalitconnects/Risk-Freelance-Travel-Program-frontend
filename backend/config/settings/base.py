import sys
"""Settings shared by every environment. Values come from environment variables / .env."""
from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-change-me-0123456789-abcdefghij")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third party
    "axes",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    # local
    "apps.accounts",
    "apps.geo",
    "apps.risk",
    "apps.fares",
    "apps.rides",
    "apps.bookings",
    "apps.verification",
    "apps.adminpanel",
    "apps.payments",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # A seeded admin must change their password before using the Django admin.
    "apps.adminpanel.middleware.ForcePasswordChangeMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Must be last: turns a locked-out admin login into a 429 response.
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://postgres:postgres@localhost:5432/vconnects"),
}

AUTH_USER_MODEL = "accounts.User"

# Axes must come first so it can refuse a locked-out login before the password is checked.
# PhoneModelBackend accepts the phone in any common format (7339284804, +91 73392 84804, ...).
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "apps.accounts.backends.PhoneModelBackend",
]

# Staff passwords are hashed with Argon2. The other hashers only verify older hashes, which are
# upgraded to Argon2 on the next successful login.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

# App users sign in with phone + OTP and have no password. Passwords exist only for staff
# accounts (createsuperuser), which sign in to the admin.
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# The frontend works in Indian local time and sends naive "YYYY-MM-DDTHH:mm" strings.
LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---- Admin ----
# Served at a path taken from the environment, not the default /admin/.
ADMIN_URL = env("ADMIN_URL", default="vct-admin/").strip("/") + "/"
ADMIN_SITE_HEADER = "VConnects Travel administration"
ADMIN_SITE_TITLE = "VConnects Travel admin"

# Only the admin uses sessions (the app uses JWT). Short-lived, closed with the browser.
SESSION_COOKIE_AGE = env.int("ADMIN_SESSION_SECONDS", default=8 * 3600)
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

# ---- Admin login protection (django-axes) ----
# After AXES_FAILURE_LIMIT failed logins for the same username from the same IP, that pair is
# locked for AXES_COOLOFF_TIME. A superuser can unlock early under "Axes" in the admin, or with
# `manage.py axes_reset`. Locking on username + IP (not username alone) stops an attacker from
# locking a real admin out from elsewhere.
AXES_ENABLED = env.bool("AXES_ENABLED", default=True)
AXES_FAILURE_LIMIT = env.int("AXES_FAILURE_LIMIT", default=5)
AXES_COOLOFF_TIME = timedelta(minutes=env.int("AXES_COOLOFF_MINUTES", default=30))
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
# The admin login form posts the phone number as "username"; axes would otherwise look for a
# "phone" field (USERNAME_FIELD), find nothing, and lock by IP alone.
AXES_USERNAME_FORM_FIELD = "username"
# Count failures per normalised phone, so typing it in another format doesn't reset the count.
AXES_USERNAME_CALLABLE = "apps.accounts.backends.axes_username"
AXES_RESET_ON_SUCCESS = True
# Behind a reverse proxy, set AXES_IPWARE_PROXY_COUNT to the number of proxies in front of
# Django so the client IP (not the proxy's) is used.
AXES_IPWARE_PROXY_COUNT = env.int("AXES_IPWARE_PROXY_COUNT", default=0)
AXES_IPWARE_META_PRECEDENCE_ORDER = ["HTTP_X_FORWARDED_FOR", "REMOTE_ADDR"]

# ---- Django REST Framework ----
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # Responses use camelCase keys to match the React objects (seatsLeft, durationMin, ...);
    # request bodies may be sent in camelCase and are converted to snake_case.
    "DEFAULT_RENDERER_CLASSES": [
        "djangorestframework_camel_case.render.CamelCaseJSONRenderer",
        "djangorestframework_camel_case.render.CamelCaseBrowsableAPIRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "djangorestframework_camel_case.parser.CamelCaseJSONParser",
        "djangorestframework_camel_case.parser.CamelCaseFormParser",
        "djangorestframework_camel_case.parser.CamelCaseMultiPartParser",
    ],
    "JSON_UNDERSCOREIZE": {"no_underscore_before_number": True},
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # Same shape the frontend's date helpers produce and parse.
    "DATETIME_FORMAT": "%Y-%m-%dT%H:%M",
    "DATETIME_INPUT_FORMATS": ["%Y-%m-%dT%H:%M", "iso-8601"],
    "DATE_FORMAT": "%Y-%m-%d",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "120/min",
        "user": "600/min",
        # Per client IP, on top of the per-number limits in apps/accounts/otp.py.
        "otp_send": env("THROTTLE_OTP_SEND", default="10/hour"),
        "otp_verify": env("THROTTLE_OTP_VERIFY", default="30/hour"),
        # Driver document uploads.
        "verification_submit": env("THROTTLE_VERIFICATION_SUBMIT", default="10/hour"),
        # Admin dashboard: login attempts per client IP (axes also locks username + IP).
        "admin_login": env("THROTTLE_ADMIN_LOGIN", default="10/min"),
        # Saving payout (bank / UPI) details.
        "payout_account": env("THROTTLE_PAYOUT_ACCOUNT", default="10/hour"),
        # Withdrawal requests (the daily limit in PaymentSettings applies as well).
        "withdrawals": env("THROTTLE_WITHDRAWALS", default="10/hour"),
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=30)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", default=30)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    # Deactivated accounts can't use or refresh tokens.
    "CHECK_USER_IS_ACTIVE": True,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "VConnects Travel API",
    "DESCRIPTION": "Carpooling with a built-in travel risk program.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "CAMELIZE_NAMES": True,
    "POSTPROCESSING_HOOKS": [
        "drf_spectacular.contrib.djangorestframework_camel_case.camelize_serializer_fields",
        "drf_spectacular.hooks.postprocess_schema_enums",
    ],
}

# ---- Admin dashboard (/#/admin in the React app, API at /api/admin/) ----
# Admin tokens are signed with their own secret and audience, so a user token never works on the
# admin API and an admin token never works on the user API. Required in production; development
# derives one from SECRET_KEY (still different from the key that signs user tokens).
ADMIN_JWT_SECRET = env("ADMIN_JWT_SECRET", default="")
ADMIN_JWT_MINUTES = env.int("ADMIN_JWT_MINUTES", default=60)

# ---- Email (verification decisions) ----
# Development prints emails to the console. Production: set EMAIL_BACKEND to
# django.core.mail.backends.smtp.EmailBackend and the SMTP settings below.
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=False)
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=15)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="VConnects Travel <no-reply@vconnects.example>")
# A failed email is retried by `manage.py retry_failed_emails` (schedule it every few minutes)
# up to this many attempts in total, or at once from the admin review page.
EMAIL_MAX_ATTEMPTS = env.int("EMAIL_MAX_ATTEMPTS", default=5)
# Links in emails point here (the React app).
APP_URL = env("APP_URL", default="http://localhost:5174").rstrip("/")

# ---- Phone sign-in (OTP) ----
PHONE_DEFAULT_COUNTRY_CODE = env("PHONE_DEFAULT_COUNTRY_CODE", default="+91")
OTP_LENGTH = 6
OTP_TTL_SECONDS = env.int("OTP_TTL_SECONDS", default=300)
OTP_RESEND_SECONDS = env.int("OTP_RESEND_SECONDS", default=30)
OTP_MAX_ATTEMPTS = env.int("OTP_MAX_ATTEMPTS", default=5)
OTP_MAX_SENDS_PER_HOUR = env.int("OTP_MAX_SENDS_PER_HOUR", default=5)

# Dotted path to an apps.accounts.sms.BaseSMSBackend subclass. Ignored while DEBUG is on:
# then codes are printed to the console (apps.accounts.sms.ConsoleSMSBackend).
SMS_BACKEND = env("SMS_BACKEND", default="")

# Prefix of the live-trip link texted to trusted contacts (the share token is appended).
TRIP_SHARE_BASE_URL = env("TRIP_SHARE_BASE_URL", default="https://vconnects.example/track")

# Extra notifiers called when an admin cancels a ride (dotted paths to callables taking a list of
# bookings). The trip-log entry is always written; add an SMS notifier here once templates exist.
RIDE_CANCELLED_NOTIFIERS = env.list("RIDE_CANCELLED_NOTIFIERS", default=[])

# ---- Driver verification documents ----
# Encrypted files live here. This folder is never served by Django or the web server.
PRIVATE_MEDIA_ROOT = Path(env("PRIVATE_MEDIA_ROOT", default=str(BASE_DIR / "private_media")))
# Fernet keys (generate with `manage.py generate_document_key`). The first key encrypts; all keys
# decrypt, so a new key can be put first to rotate without losing old documents. Required in
# production; development falls back to a key derived from SECRET_KEY.
DOCUMENT_ENCRYPTION_KEYS = env.list("DOCUMENT_ENCRYPTION_KEYS", default=[])
DOCUMENT_MAX_BYTES = env.int("DOCUMENT_MAX_BYTES", default=5 * 1024 * 1024)

# ---- Publisher payout details ----
# Fernet keys for bank account numbers and UPI ids (separate from the document keys; same format,
# generate with `manage.py generate_document_key`). First key encrypts, all decrypt. Required in
# production; development falls back to a key derived from SECRET_KEY.
PAYOUT_ENCRYPTION_KEYS = env.list("PAYOUT_ENCRYPTION_KEYS", default=[])
# Withdrawal requests stay off until Razorpay confirms the payout flow (Phase 8).
PAYOUTS_ENABLED = env.bool("PAYOUTS_ENABLED", default=False)

# ---- Razorpay ----
# Test keys in development (rzp_test_...). The key secret and webhook secret never leave the server.
RAZORPAY_KEY_ID = env("RAZORPAY_KEY_ID", default="")
RAZORPAY_KEY_SECRET = env("RAZORPAY_KEY_SECRET", default="")
RAZORPAY_WEBHOOK_SECRET = env("RAZORPAY_WEBHOOK_SECRET", default="")
RAZORPAY_TIMEOUT_SECONDS = env.int("RAZORPAY_TIMEOUT_SECONDS", default=15)
# Bookings wait for a verified payment (pending_payment) when on. Off in the test suite, where
# payment tests switch it on themselves.
_TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"
PAYMENTS_ENABLED = env.bool("PAYMENTS_ENABLED", default=False) and not _TESTING
REFUND_MAX_ATTEMPTS = env.int("REFUND_MAX_ATTEMPTS", default=8)
# Route (publisher transfers on hold, released on withdrawal). OFF until Razorpay approves Route.
PASSENGER_CONTACT_HOURS = env.int("PASSENGER_CONTACT_HOURS", default=6)  # driver sees phone until arrival + N h
ROUTE_ENABLED = env.bool("ROUTE_ENABLED", default=False) and not _TESTING
ROUTE_COOLING_HOURS = env.int("ROUTE_COOLING_HOURS", default=24)  # to confirm with Razorpay
ROUTE_PROFILE_CATEGORY = env("ROUTE_PROFILE_CATEGORY", default="transport")  # to confirm with Razorpay
ROUTE_PROFILE_SUBCATEGORY = env("ROUTE_PROFILE_SUBCATEGORY", default="cab_hailing")  # to confirm with Razorpay
# Rejected / revoked submissions, and accounts deactivated this long ago, lose their documents
# (run `manage.py purge_verification_documents` daily).
DOCUMENT_RETENTION_DAYS = env.int("DOCUMENT_RETENTION_DAYS", default=30)

# Keep uploads in memory only: Django's default spills large files to a temp file on disk, which
# would leave unencrypted ID documents behind. 4 documents x 5 MB plus form fields.
FILE_UPLOAD_HANDLERS = ["django.core.files.uploadhandler.MemoryFileUploadHandler"]
FILE_UPLOAD_MAX_MEMORY_SIZE = 4 * DOCUMENT_MAX_BYTES + 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

# ---- Road distances (OpenRouteService) ----
# Used once by `manage.py fetch_route_distances`; results are stored in RouteProfile.km.
ORS_API_KEY = env("ORS_API_KEY", default="")
ORS_MATRIX_URL = env("ORS_MATRIX_URL", default="https://api.openrouteservice.org/v2/matrix/driving-car")
ORS_TIMEOUT_SECONDS = env.int("ORS_TIMEOUT_SECONDS", default=20)

# ---- CORS: the Vite dev server ----
CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=["http://localhost:5174", "http://127.0.0.1:5174"],
)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
