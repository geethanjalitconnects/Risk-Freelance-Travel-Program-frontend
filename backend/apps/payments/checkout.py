"""Paying for a booking (Phase 3).

    POST /bookings            booking created as pending_payment; seats held for seat_hold_minutes
    POST /bookings/<id>/pay   one Razorpay order per booking (reused on retry) -> Checkout options
    Checkout succeeds         POST /bookings/<id>/payment/verify: the signature is checked, then the
                              payment is FETCHED FROM RAZORPAY on the server; only a captured payment
                              of the right order and amount confirms the booking
    webhook payment.captured  same confirmation path (whichever arrives first wins; the other no-ops)
    hold runs out unpaid      manage.py expire_payment_holds marks the booking expired, seats freed
    paid after the hold       confirmed if the seats are still free, otherwise refunded in full

The browser's Checkout callback alone never confirms anything.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.bookings.models import ACTIVE_STATUSES, Booking, BookingStatus, EventType, TripEvent

from . import audit, ledger, money, razorpay
from .models import FinancialAction, Payment, PaymentSettings, PaymentStatus

logger = logging.getLogger(__name__)


class PaymentError(Exception):
    def __init__(self, message, code, status=409):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def enabled() -> bool:
    return bool(settings.PAYMENTS_ENABLED)


def _event(booking, type_, text):
    TripEvent.objects.create(booking=booking, type=type_, text=text[:200])


def hold_deadline(now=None):
    return (now or timezone.now()) + timedelta(minutes=PaymentSettings.load().seat_hold_minutes)


# ---------------------------------------------------------------- holds


def expire_holds(ride_id=None, now=None) -> int:
    """Release seats held by unpaid bookings whose hold ran out."""
    now = now or timezone.now()
    qs = Booking.objects.filter(status=BookingStatus.PENDING_PAYMENT, hold_expires_at__lte=now)
    if ride_id is not None:
        qs = qs.filter(ride_id=ride_id)
    n = 0
    for pk in list(qs.values_list("pk", flat=True)):
        with transaction.atomic():
            b = Booking.objects.select_for_update().get(pk=pk)
            if b.status == BookingStatus.PENDING_PAYMENT and b.hold_expires_at and b.hold_expires_at <= now:
                b.status = BookingStatus.EXPIRED
                b.save(update_fields=["status"])
                _event(b, EventType.CANCELLED, "Payment wasn't completed in time, so the seats were released.")
                n += 1
    return n


# ---------------------------------------------------------------- order


def start_payment(booking) -> Payment:
    """Create (or reuse) the Razorpay order for a held booking. The caller holds the row lock."""
    if not enabled():
        raise PaymentError("Online payment isn't switched on.", "payments_disabled", 503)
    if booking.status != BookingStatus.PENDING_PAYMENT:
        raise PaymentError("This booking doesn't need payment.", "invalid_state")
    if booking.hold_expires_at and booking.hold_expires_at <= timezone.now():
        raise PaymentError("Your seat hold ran out. Please book again.", "hold_expired")
    payment = booking.payments.filter(razorpay_order_id__isnull=False).first()
    if payment is not None:
        return payment  # one order per booking: a retry pays the same order, so it can't be paid twice
    try:
        order = razorpay.create_order(
            booking.total_paise, f"bk_{booking.pk.hex[:24]}",
            {"booking_id": str(booking.pk), "ride_id": str(booking.ride_id)},
        )
    except razorpay.RazorpayError as e:
        raise PaymentError(e.message if e.status and e.status < 500 else "Payment is unavailable right now. Please try again.",
                           "gateway_error", 502)
    if order.get("amount") != booking.total_paise:
        raise PaymentError("The payment amount didn't match. Please try again.", "amount_mismatch", 502)
    return Payment.objects.create(
        booking=booking, amount_paise=booking.total_paise, razorpay_order_id=order["id"],
        idempotency_key=f"booking:{booking.pk}:order",
    )


def checkout_options(payment) -> dict:
    """What the frontend passes to Razorpay Checkout. The key id is public; the secret never leaves the server."""
    b = payment.booking
    return {
        "key_id": settings.RAZORPAY_KEY_ID,
        "order_id": payment.razorpay_order_id,
        "amount": payment.amount_paise,
        "currency": payment.currency,
        "name": "VConnects",
        "description": f"{b.ride.origin.name} → {b.ride.destination.name}, {b.seats} seat{'s' if b.seats > 1 else ''}",
        "hold_expires_at": int(b.hold_expires_at.timestamp() * 1000) if b.hold_expires_at else None,
    }


# ---------------------------------------------------------------- verification


def verify_checkout(booking, order_id, payment_id, signature):
    """Checkout returned: check the signature, then ask Razorpay for the payment itself."""
    payment = booking.payments.filter(razorpay_order_id=order_id).first()
    if payment is None or not razorpay.verify_payment_signature(order_id, payment_id, signature):
        audit.record(FinancialAction.PAYMENT_FAILED, label="system", user=booking.passenger, booking=booking,
                     reference=(payment_id or "")[:40], reason="invalid_signature")
        raise PaymentError("We couldn't verify this payment. If money was taken, it will be refunded automatically.",
                           "invalid_signature", 400)
    try:
        rp = razorpay.fetch_payment(payment_id)
    except razorpay.RazorpayError:
        raise PaymentError("We couldn't confirm the payment with Razorpay yet. It will update automatically.",
                           "gateway_error", 502)
    apply_payment(rp, source="checkout")


def apply_payment(rp: dict, source: str):
    """Apply a Razorpay payment entity (from our fetch or a verified webhook). Idempotent."""
    order_id, amount = rp.get("order_id"), rp.get("amount")
    payment = Payment.objects.filter(razorpay_order_id=order_id).first()
    if payment is None:
        logger.info("Razorpay payment for unknown order ignored (%s)", source)
        return None
    if amount != payment.amount_paise or rp.get("currency", "INR") != payment.currency:
        logger.error("Amount mismatch on payment %s: expected %s", payment.pk, payment.amount_paise)
        audit.record(FinancialAction.PAYMENT_FAILED, label="razorpay", user=payment.booking.passenger,
                     booking=payment.booking, amount=amount, reference=rp.get("id", ""), reason="amount_mismatch")
        return payment
    status = rp.get("status")
    if status == "authorized":  # only if the account isn't set to auto-capture
        try:
            rp = razorpay.capture_payment(rp["id"], payment.amount_paise)
            status = rp.get("status")
        except razorpay.RazorpayError:
            logger.warning("Capture failed for payment %s; the webhook or a retry will finish it", payment.pk)
            return payment
    if status == "captured":
        return on_captured(payment.pk, rp, source)
    if status == "failed":
        return on_failed(payment.pk, rp)
    return payment


@transaction.atomic
def on_failed(payment_pk, rp):
    payment = Payment.objects.select_for_update().get(pk=payment_pk)
    if payment.status in (PaymentStatus.CAPTURED,):
        return payment
    payment.status = PaymentStatus.FAILED
    payment.razorpay_payment_id = payment.razorpay_payment_id or rp.get("id")
    payment.error_code = (rp.get("error_code") or "")[:60]
    payment.error_description = (rp.get("error_description") or "")[:300]
    payment.save()
    audit.record(FinancialAction.PAYMENT_FAILED, label="razorpay", user=payment.booking.passenger, booking=payment.booking,
                 amount=payment.amount_paise, reference=rp.get("id", ""), code=payment.error_code)
    # The booking stays held: the passenger can try again on the same order until the hold runs out.
    return payment


def _seats_free_for(booking) -> bool:
    ride = booking.ride
    if ride.status != "active" or ride.depart <= timezone.now():
        return False
    others = ride.open_bookings().exclude(pk=booking.pk)
    taken = sum(others.values_list("seats", flat=True))
    return ride.seats_total - taken >= booking.seats


@transaction.atomic
def on_captured(payment_pk, rp, source):
    payment = Payment.objects.select_for_update().get(pk=payment_pk)
    booking = Booking.objects.select_for_update().select_related("ride", "passenger").get(pk=payment.booking_id)
    if payment.status == PaymentStatus.CAPTURED:
        return payment  # webhook and verify both arrived: the second one is a no-op
    payment.status = PaymentStatus.CAPTURED
    payment.razorpay_payment_id = rp["id"]
    payment.method = (rp.get("method") or "")[:20]
    payment.error_code = payment.error_description = ""
    payment.captured_at = timezone.now()
    payment.save()
    audit.record(FinancialAction.PAYMENT_CAPTURED, label="razorpay" if source == "webhook" else "system",
                 user=booking.passenger, booking=booking, amount=payment.amount_paise, reference=rp["id"],
                 source=source, method=payment.method)

    if booking.status == BookingStatus.PENDING_PAYMENT or (
        booking.status == BookingStatus.EXPIRED and _seats_free_for(booking)
    ):
        if booking.status == BookingStatus.PENDING_PAYMENT and not _seats_free_for(booking):
            return _refund_unavailable(booking)
        booking.status = BookingStatus.CONFIRMED
        booking.hold_expires_at = None
        booking.save(update_fields=["status", "hold_expires_at"])
        _event(booking, EventType.BOOKED, f"Payment of {money.format_inr(payment.amount_paise)} received. Booking confirmed.")
        ledger.hold_earning(booking)
        from . import route

        route.queue_transfer(booking)  # no-op until Route is enabled
        return payment
    if booking.status in ACTIVE_STATUSES:
        return payment
    return _refund_unavailable(booking)


def _refund_unavailable(booking):
    """Paid, but the seats are gone (hold expired and rebooked, ride cancelled or left): full refund."""
    from apps.bookings.cancellation import amounts_of, settle
    from apps.bookings.models import Cancellation, CancelledBy

    from . import refunds

    if Cancellation.objects.filter(booking=booking).exists():  # already settled earlier: refund the whole payment
        refunds.request_refund(booking, booking.total_paise, money.Rule.SEATS_UNAVAILABLE)
        return booking.payments.filter(status=PaymentStatus.CAPTURED).first()
    settle(booking, money.seats_unavailable(amounts_of(booking)), cancelled_by=CancelledBy.SYSTEM,
           reason="Paid after the seats were no longer available")
    _event(booking, EventType.CANCELLED, "Your payment arrived after the seats were released, so it is being refunded in full.")
    return booking.payments.filter(status=PaymentStatus.CAPTURED).first()
