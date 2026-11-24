"""Cancellations and refunds (Phase 4). Every cancellation goes through ``settle``, which:

1. computes the outcome with ``payments.money`` (never anywhere else),
2. writes one Cancellation record with the amounts (they always add up: a DB constraint checks it),
3. for a PAID booking (a captured payment exists): removes the publisher's held earning (or
   releases it for an upheld passenger no-show), charges the publisher penalty, and records the
   refund to the original payment method,
4. writes a financial audit row.

Rules (client decisions, 2026-11-20). Percentages of the total the passenger paid:
    passenger cancels more than 24 h before departure   15% kept by VConnects, 85% refunded
    passenger cancels within 24 h                         10% kept, 90% refunded
    publisher cancels                                     100% refunded; publisher penalty of the
                                                          ride amount: 0% (> 24 h) / 10% (within 24 h)
    VConnects cancels (admin, account deactivated)        100% refunded, no penalty

Bookings with no captured payment (everything made before Razorpay goes live) are cancelled with
the computed amounts on record, but no refund, earning change or penalty is applied: no money moved.
Refunds are sent to Razorpay in Phase 3; until then they stay "pending".
"""
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.payments import audit, ledger, money, refunds
from apps.payments.models import EarningEntry, FinancialAction, PaymentStatus
from apps.rides.models import Ride, RideStatus

from . import notifications
from .models import ACTIVE_STATUSES, Booking, BookingStatus, Cancellation, CancelledBy, EventType, TripEvent
from .services import TripError


def amounts_of(booking) -> money.BookingAmounts:
    """The frozen breakdown; bookings made before payments are priced with their own rates."""
    return booking.amounts() or money.price_booking(booking.ride.price, booking.seats, booking.policy())


def is_paid(booking) -> bool:
    return booking.payments.filter(status=PaymentStatus.CAPTURED).exists()


def _event(booking, text):
    TripEvent.objects.create(booking=booking, type=EventType.CANCELLED, text=text[:200])


def settle(booking, settlement, *, cancelled_by, actor=None, reason="", now=None) -> Cancellation:
    """Cancel ``booking`` (row locked by the caller) and apply ``settlement``."""
    now = now or timezone.now()
    paid = is_paid(booking)
    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = now
    booking.save(update_fields=["status", "cancelled_at"])
    record = Cancellation.objects.create(
        booking=booking, cancelled_by=cancelled_by, actor=actor, reason=(reason or "")[:300],
        minutes_before_departure=int((booking.ride.depart - now).total_seconds() // 60), rule=settlement.rule,
        total_paid_paise=settlement.total_paid, refund_paise=settlement.refund,
        vconnects_kept_paise=settlement.vconnects_kept, publisher_earning_paise=settlement.publisher_earning,
        publisher_penalty_paise=settlement.publisher_penalty,
    )
    if paid:
        from apps.payments import razorpay, route

        try:
            route.reverse_for_cancellation(booking)  # no-op until Route is enabled
        except razorpay.RazorpayError:
            raise TripError("We couldn't cancel this right now. Please try again in a minute.", "gateway_error", status=503)
        held = EarningEntry.objects.filter(idempotency_key=f"booking:{booking.pk}:held").exists()
        if held and settlement.publisher_earning:
            ledger.release_earning(booking)
        elif held:
            ledger.reverse_earning(booking)
        if settlement.publisher_penalty:
            ledger.charge_penalty(booking, settlement.publisher_penalty)
        refunds.request_refund(booking, settlement.refund, settlement.rule)
    audit.record(
        FinancialAction.BOOKING_SETTLED, actor=actor, label=None if actor else "system", user=booking.passenger,
        booking=booking, amount=settlement.total_paid, reference=f"booking:{booking.pk}:cancellation",
        rule=settlement.rule, paid=paid, refund=settlement.refund, vconnects_kept=settlement.vconnects_kept,
        publisher_earning=settlement.publisher_earning, publisher_penalty=settlement.publisher_penalty,
        cancelled_by=cancelled_by,
    )
    return record


def _pct(part, whole):
    return f"{round(part * 100 / whole)}%" if whole else "0%"


# ---------------------------------------------------------------- passenger


@dataclass
class Quote:
    settlement: money.Settlement
    paid: bool
    message: str


def passenger_quote(booking, now=None) -> Quote:
    """What cancelling now would refund, with the message the passenger sees."""
    if booking.status == BookingStatus.PENDING_PAYMENT:
        s = money.Settlement(rule=money.Rule.PASSENGER_EARLY, total_paid=0, refund=0, vconnects_kept=0,
                             publisher_earning=0, publisher_penalty=0)
        return Quote(s, False, "You haven't paid for this booking yet, so cancelling just releases the seats.")
    if booking.status != BookingStatus.CONFIRMED:
        raise TripError("Only a booking whose trip hasn't started can be cancelled.", "invalid_state")
    now = now or timezone.now()
    s = money.passenger_cancellation(amounts_of(booking), booking.policy(), booking.ride.depart - now)
    paid = is_paid(booking)
    hours = booking.policy().cancel_window_hours
    when = f"more than {hours} hours before departure" if s.rule == money.Rule.PASSENGER_EARLY else f"within {hours} hours of departure"
    if paid:
        message = (
            f"Cancelling {when}: {money.format_inr(s.refund)} ({_pct(s.refund, s.total_paid)}) is refunded to your "
            f"original payment method and {money.format_inr(s.vconnects_kept)} ({_pct(s.vconnects_kept, s.total_paid)}) "
            f"is kept as a cancellation fee."
        )
    else:
        message = "This booking hasn't been paid, so there's nothing to refund."
    return Quote(s, paid, message)


def cancel_by_passenger(booking, user) -> Cancellation:
    """The caller holds the booking's row lock."""
    if booking.status == BookingStatus.PENDING_PAYMENT:  # not paid: just release the seats
        booking.status = BookingStatus.CANCELLED
        booking.cancelled_at = timezone.now()
        booking.save(update_fields=["status", "cancelled_at"])
        _event(booking, "Booking cancelled before payment.")
        return None
    q = passenger_quote(booking)
    record = settle(booking, q.settlement, cancelled_by=CancelledBy.PASSENGER, actor=user)
    if q.paid:
        _event(booking, f"Booking cancelled. {money.format_inr(q.settlement.refund)} will be refunded to your original "
                        f"payment method; {money.format_inr(q.settlement.vconnects_kept)} cancellation fee.")
    else:
        _event(booking, "Booking cancelled.")
    return record


# ---------------------------------------------------------------- publisher


@dataclass
class RideQuote:
    bookings: list  # (booking, settlement) pairs
    refund_total: int
    penalty_total: int
    late: bool
    paid_count: int
    message: str


def _cancellable_ride(ride, now):
    if ride.status != RideStatus.ACTIVE:
        raise TripError("This ride is already cancelled.", "invalid_state")
    if ride.depart <= now or ride.bookings.filter(status=BookingStatus.IN_PROGRESS).exists():
        raise TripError("This ride has already left. Use “Complete this ride” and mark any problems there.", "departed")


def publisher_quote(ride, now=None, bookings=None) -> RideQuote:
    now = now or timezone.now()
    _cancellable_ride(ride, now)
    if bookings is None:
        bookings = list(ride.bookings.filter(status=BookingStatus.CONFIRMED).select_related("ride"))
    pairs, refund_total, penalty_total, paid_count = [], 0, 0, 0
    for b in bookings:
        s = money.publisher_cancellation(amounts_of(b), b.policy(), ride.depart - now)
        pairs.append((b, s))
        if is_paid(b):
            paid_count += 1
            refund_total += s.refund
            penalty_total += s.publisher_penalty
    late = any(s.rule == money.Rule.PUBLISHER_LATE for _, s in pairs) or (
        not pairs and money.FeePolicy().is_late(ride.depart - now)
    )
    if not pairs:
        message = "Nobody has booked this ride. Cancelling removes it."
    else:
        n = len(pairs)
        message = f"{n} passenger{'s' if n > 1 else ''} will be refunded in full"
        message += f" ({money.format_inr(refund_total)})." if paid_count else "."
        if penalty_total:
            message += f" Because you're cancelling within 24 hours of departure, a penalty of {money.format_inr(penalty_total)} is deducted from your earnings."
        else:
            message += " There's no penalty for you."
    return RideQuote(pairs, refund_total, penalty_total, late, paid_count, message)


@transaction.atomic
def cancel_ride_by_publisher(ride_id, publisher, reason) -> Ride:
    reason = " ".join((reason or "").split())
    if len(reason) < 5:
        raise TripError("Tell your passengers why you're cancelling.", "reason_required", status=400)
    ride = Ride.objects.select_for_update().filter(pk=ride_id, driver=publisher).first()
    if ride is None:
        raise TripError("Ride not found.", "not_found", status=404)
    now = timezone.now()
    bookings = list(
        Booking.objects.select_for_update().select_related("ride", "passenger", "ride__origin", "ride__destination")
        .filter(ride=ride, status=BookingStatus.CONFIRMED)
    )
    q = publisher_quote(ride, now, bookings)

    ride.status = RideStatus.CANCELLED
    ride.cancelled_at = now
    ride.cancellation_reason = reason[:300]
    ride.save(update_fields=["status", "cancelled_at", "cancellation_reason", "updated_at"])
    for b, s in q.bookings:
        paid = is_paid(b)
        settle(b, s, cancelled_by=CancelledBy.PUBLISHER, actor=publisher, reason=reason, now=now)
        tail = (f" You'll get a full refund of {money.format_inr(s.refund)} to your original payment method."
                if paid else " Your booking has been cancelled.")
        _event(b, f"The driver cancelled this ride: {reason}{tail}")
    notifications.ride_cancelled([b for b, _ in q.bookings], reason)
    return ride


# ---------------------------------------------------------------- VConnects (admin, deactivation)


def cancel_by_vconnects(booking, *, actor=None, reason="", cancelled_by=CancelledBy.ADMIN, now=None):
    """Full refund, no penalty. The caller holds the row lock and writes the trip-log line."""
    if booking.status not in ACTIVE_STATUSES:
        return None
    return settle(booking, money.admin_full_refund(amounts_of(booking)), cancelled_by=cancelled_by, actor=actor,
                  reason=reason, now=now)
