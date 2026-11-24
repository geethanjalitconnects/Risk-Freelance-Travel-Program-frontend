"""Razorpay webhooks: POST /api/v1/payments/razorpay/webhook (configure this URL in the Razorpay
Dashboard with the webhook secret in RAZORPAY_WEBHOOK_SECRET).

The raw body's HMAC signature is checked before anything is parsed or stored. Each event is stored
once by its X-Razorpay-Event-Id, so redeliveries are acknowledged without being applied twice.
"""
import hashlib
import json
import logging

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import checkout, razorpay, refunds, route
from .models import WebhookEvent, WebhookStatus

logger = logging.getLogger(__name__)

PAYMENT_EVENTS = {"payment.captured", "payment.failed", "payment.authorized", "order.paid"}
REFUND_EVENTS = {"refund.processed", "refund.failed"}
TRANSFER_EVENTS = {"transfer.processed", "transfer.failed", "transfer.reversed", "settlement.processed"}


def dispatch(event_type, payload):
    p = payload.get("payload", {})
    if event_type in PAYMENT_EVENTS:
        checkout.apply_payment(p["payment"]["entity"], source="webhook")
        return True
    if event_type in REFUND_EVENTS:
        refunds.on_refund_event(p["refund"]["entity"])
        return True
    if event_type in TRANSFER_EVENTS and "transfer" in p:
        route.on_transfer_event(p["transfer"]["entity"])
        return True
    return False


class RazorpayWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def post(self, request):
        raw = request.body  # read before DRF parses anything
        if not razorpay.verify_webhook_signature(raw, request.headers.get("X-Razorpay-Signature", "")):
            logger.warning("Razorpay webhook with a bad signature rejected")
            return Response({"detail": "Invalid signature."}, status=400)
        payload = json.loads(raw)
        # Razorpay sends a unique X-Razorpay-Event-Id; the body digest is a stable fallback.
        event_id = request.headers.get("X-Razorpay-Event-Id") or "sha256:" + hashlib.sha256(raw).hexdigest()[:50]
        try:
            with transaction.atomic():
                event = WebhookEvent.objects.create(event_id=event_id[:60], event_type=payload.get("event", "")[:60], payload=payload)
        except IntegrityError:
            return Response({"status": "duplicate"})
        try:
            handled = dispatch(event.event_type, payload)
            event.status = WebhookStatus.PROCESSED if handled else WebhookStatus.IGNORED
        except Exception as e:  # noqa: BLE001 - recorded; Razorpay retries on non-2xx
            logger.exception("Webhook %s failed", event.event_id)
            event.status, event.error = WebhookStatus.FAILED, str(e)[:300]
            event.processed_at = timezone.now()
            event.save()
            return Response({"status": "error"}, status=500)
        event.processed_at = timezone.now()
        event.save()
        return Response({"status": "ok"})
