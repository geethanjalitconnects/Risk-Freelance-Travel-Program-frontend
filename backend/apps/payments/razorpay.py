"""A small Razorpay API client (Payment Gateway + Route), and signature checks.

Keys come from RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET / RAZORPAY_WEBHOOK_SECRET (test keys in
development). Secrets are never logged and never put in error messages. Only the standard library
is used, so there's no extra dependency to audit.
"""
import base64
import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.request

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)

API = "https://api.razorpay.com"


class RazorpayError(Exception):
    """A Razorpay call failed. ``status`` is the HTTP status (0 = network), ``code`` Razorpay's error code."""

    def __init__(self, message, status=0, code=""):
        super().__init__(message)
        self.message, self.status, self.code = message, status, code

    @property
    def retryable(self):
        return self.status == 0 or self.status >= 500 or self.status == 429


def configured() -> bool:
    return bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET)


def _auth():
    if not configured():
        raise ImproperlyConfigured("RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set.")
    token = f"{settings.RAZORPAY_KEY_ID}:{settings.RAZORPAY_KEY_SECRET}".encode()
    return "Basic " + base64.b64encode(token).decode()


def request(method, path, body=None, *, idempotency_key=None, timeout=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": _auth(), "Content-Type": "application/json"}
    if idempotency_key:
        headers["X-Razorpay-Idempotency"] = idempotency_key  # honoured by the APIs that support it
    req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout or settings.RAZORPAY_TIMEOUT_SECONDS) as res:
            return json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read() or b"{}").get("error", {})
        except ValueError:
            err = {}
        message = err.get("description") or f"Razorpay returned HTTP {e.code}."
        logger.warning("Razorpay %s %s failed: %s %s", method, path.split("?")[0], e.code, err.get("code", ""))
        raise RazorpayError(message, e.code, err.get("code", "")) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.warning("Razorpay %s %s unreachable: %s", method, path.split("?")[0], type(e).__name__)
        raise RazorpayError("Couldn't reach Razorpay. Please try again.") from None


# ---------------------------------------------------------------- payment gateway


def create_order(amount_paise, receipt, notes=None):
    return request("POST", "/v1/orders", {
        "amount": amount_paise, "currency": "INR", "receipt": receipt[:40], "notes": notes or {},
    })


def fetch_payment(payment_id):
    return request("GET", f"/v1/payments/{payment_id}")


def fetch_order_payments(order_id):
    return request("GET", f"/v1/orders/{order_id}/payments").get("items", [])


def capture_payment(payment_id, amount_paise):
    return request("POST", f"/v1/payments/{payment_id}/capture", {"amount": amount_paise, "currency": "INR"})


def create_refund(payment_id, amount_paise, notes=None, *, idempotency_key=None, reverse_all=False):
    body = {"amount": amount_paise, "speed": "normal", "notes": notes or {}}
    if reverse_all:
        body["reverse_all"] = 1
    return request("POST", f"/v1/payments/{payment_id}/refund", body, idempotency_key=idempotency_key)


# ---------------------------------------------------------------- Route


def create_transfer(payment_id, account_id, amount_paise, notes=None, *, idempotency_key=None):
    """Transfer the publisher's share of a captured payment to their linked account, ON HOLD."""
    return request("POST", f"/v1/payments/{payment_id}/transfers", {"transfers": [{
        "account": account_id, "amount": amount_paise, "currency": "INR", "on_hold": 1, "notes": notes or {},
    }]}, idempotency_key=idempotency_key)


def release_transfer(transfer_id):
    return request("PATCH", f"/v1/transfers/{transfer_id}", {"on_hold": 0})


def reverse_transfer(transfer_id, amount_paise=None, *, idempotency_key=None):
    body = {"amount": amount_paise} if amount_paise else {}
    return request("POST", f"/v1/transfers/{transfer_id}/reversals", body, idempotency_key=idempotency_key)


def fetch_transfer(transfer_id):
    return request("GET", f"/v1/transfers/{transfer_id}")


def create_linked_account(payload):
    return request("POST", "/v2/accounts", payload)


# ---------------------------------------------------------------- signatures


def _hmac(secret, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_payment_signature(order_id, payment_id, signature) -> bool:
    """Checkout's handler signature: HMAC-SHA256(order_id|payment_id, key secret)."""
    if not (order_id and payment_id and signature and settings.RAZORPAY_KEY_SECRET):
        return False
    expected = _hmac(settings.RAZORPAY_KEY_SECRET, f"{order_id}|{payment_id}".encode())
    return hmac.compare_digest(expected, signature)


def verify_webhook_signature(raw_body: bytes, signature) -> bool:
    """X-Razorpay-Signature: HMAC-SHA256(raw body, webhook secret). Never parse an unverified body."""
    if not (signature and settings.RAZORPAY_WEBHOOK_SECRET):
        return False
    return hmac.compare_digest(_hmac(settings.RAZORPAY_WEBHOOK_SECRET, raw_body), signature)
