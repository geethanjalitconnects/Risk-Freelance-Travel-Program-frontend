"""Passenger refunds, always to the original payment method through Razorpay's Refunds API.

``request_refund`` records the refund (one per booking and rule, so it can't be created twice) and
sends it to Razorpay after the database commit. A failed send is retried by
``manage.py process_refunds``; Razorpay's webhooks (refund.processed / refund.failed) move it on.
Bookings with no captured payment have nothing to refund.
"""
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import audit, razorpay
from .models import FinancialAction, PaymentStatus, Refund, RefundStatus

logger = logging.getLogger(__name__)


def request_refund(booking, amount: int, rule: str):
    """Record a refund of ``amount`` paise for ``booking``. Returns the Refund, or None when there
    is nothing to refund. Safe to call twice for the same booking and rule."""
    if amount <= 0:
        return None
    payment = booking.payments.filter(status=PaymentStatus.CAPTURED).first()
    if payment is None:
        logger.info("Booking %s: no captured payment, so no refund to record.", booking.pk)
        return None
    refund, created = Refund.objects.get_or_create(
        idempotency_key=f"booking:{booking.pk}:refund:{rule}",
        defaults={"payment": payment, "booking": booking, "amount_paise": amount, "rule": rule},
    )
    if created:
        audit.record(
            FinancialAction.REFUND_CREATED, label="system", user=booking.passenger, booking=booking, amount=amount,
            reference=refund.idempotency_key, rule=rule,
        )
        if settings.PAYMENTS_ENABLED and razorpay.configured():
            transaction.on_commit(lambda: send(refund.pk))
    return refund


def send(refund_pk) -> Refund:
    """Send one pending refund to Razorpay. Never raises; failures are recorded for a retry."""
    with transaction.atomic():
        refund = Refund.objects.select_for_update().select_related("payment", "booking").get(pk=refund_pk)
        if refund.razorpay_refund_id or refund.status not in (RefundStatus.PENDING, RefundStatus.FAILED):
            return refund  # already accepted by Razorpay: never send twice
        refund.attempts += 1
        try:
            rp = razorpay.create_refund(
                refund.payment.razorpay_payment_id, refund.amount_paise,
                {"booking_id": str(refund.booking_id), "rule": refund.rule},
                idempotency_key=refund.idempotency_key,
            )
        except razorpay.RazorpayError as e:
            refund.status = RefundStatus.PENDING if e.retryable else RefundStatus.FAILED
            refund.last_error = e.message[:300]
            refund.save(update_fields=["attempts", "status", "last_error"])
            logger.warning("Refund %s not accepted (attempt %s)", refund.pk, refund.attempts)
            return refund
        refund.razorpay_refund_id = rp["id"]
        refund.status = RefundStatus.PROCESSED if rp.get("status") == "processed" else RefundStatus.PROCESSING
        refund.processed_at = timezone.now() if refund.status == RefundStatus.PROCESSED else None
        refund.last_error = ""
        refund.save()
        audit.record(FinancialAction.REFUND_UPDATED, label="razorpay", user=refund.booking.passenger,
                     booking=refund.booking, amount=refund.amount_paise, reference=rp["id"], status=refund.status)
        return refund


@transaction.atomic
def on_refund_event(rp: dict):
    """refund.processed / refund.failed from a verified webhook."""
    refund = Refund.objects.select_for_update().filter(razorpay_refund_id=rp.get("id")).first()
    if refund is None:
        return None
    new = {"processed": RefundStatus.PROCESSED, "failed": RefundStatus.FAILED}.get(rp.get("status"))
    if new is None or refund.status == new:
        return refund
    refund.status = new
    if new == RefundStatus.PROCESSED:
        refund.processed_at = timezone.now()
    refund.save()
    audit.record(FinancialAction.REFUND_UPDATED, label="razorpay", user=refund.booking.passenger, booking=refund.booking,
                 amount=refund.amount_paise, reference=refund.razorpay_refund_id, status=new)
    return refund
