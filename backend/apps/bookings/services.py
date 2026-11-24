"""Booking and trip lifecycle. Every function runs inside a transaction with the booking (or the
ride, when booking) row locked, so double taps and concurrent bookings can't corrupt state.

    confirmed  -- start -->  in_progress  -- both confirm (completion.py) -->  completed  -- rate --> (rated)
    confirmed  -- cancel --> cancelled
"""
import secrets

from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils import timezone

from apps.accounts.models import User
from apps.payments import money
from apps.payments.models import PaymentSettings
from apps.rides import policies
from apps.rides import services as ride_services
from apps.rides.models import Ride, RideStatus

from . import alerts
from .models import CHECKPOINT_LABELS, CHECKPOINTS, Booking, BookingStatus, CheckIn, CheckInKind, EventType, TripEvent


class TripError(Exception):
    def __init__(self, message: str, code: str, status: int = 409):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def _event(booking, type_, text):
    TripEvent.objects.create(booking=booking, type=type_, text=text)


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def _require(booking, status, message):
    if booking.status != status:
        raise TripError(message, "invalid_state")


# ---------------------------------------------------------------- booking


@transaction.atomic
def create_booking(user, ride_id, seats: int) -> Booking:
    from apps.payments import checkout

    ride = Ride.objects.select_for_update().filter(pk=ride_id).first()
    if ride is None:
        raise TripError("Ride not found.", "not_found", status=404)
    if checkout.enabled():
        checkout.expire_holds(ride_id=ride.pk)  # free seats from unpaid holds that ran out
    if ride.status != RideStatus.ACTIVE:
        raise TripError("This ride is no longer available.", "unavailable")
    # Lock the passenger too, so a gender change can't race the women-only / men-only check.
    passenger = User.objects.select_for_update().get(pk=user.pk)

    loaded = ride_services.load(ride.pk, passenger)
    if loaded is None:  # not listed: driver unapproved, revoked or deactivated
        raise TripError("This ride is no longer available.", "unavailable")
    block = policies.booking_block(
        loaded, passenger, seats, seats_left=loaded._seats_left, my_booking_id=loaded._my_booking_id
    )
    if block:
        raise TripError(block.message, block.code)

    # The price breakdown and the rates are frozen on the booking (all maths in payments.money).
    policy = PaymentSettings.load().policy()
    amounts = money.price_booking(ride.price, seats, policy)
    try:
        with transaction.atomic():
            booking = Booking(
                ride=ride,
                passenger=passenger,
                seats=seats,
                total=ride.price * seats,
                risk_score=loaded._risk["score"],
                risk_band=loaded._risk["band"]["key"],
            )
            booking.set_amounts(amounts, policy)
            if checkout.enabled():  # confirmed only once the payment is verified on the server
                booking.status = BookingStatus.PENDING_PAYMENT
                booking.hold_expires_at = checkout.hold_deadline()
            booking.save()
    except IntegrityError:  # unique open booking per ride + passenger
        raise TripError("You have booked this ride.", "already_booked")
    _event(booking, EventType.BOOKED, f"Booked {_plural(seats, 'seat')}." + (
        " Complete the payment to confirm." if booking.status == BookingStatus.PENDING_PAYMENT else ""))
    return booking


def locked_booking(pk, user) -> Booking:
    booking = (
        Booking.objects.select_for_update()
        .filter(pk=pk, passenger=user)
        .first()
    )
    if booking is None:
        raise Http404
    return booking


def cancel(booking):
    """The passenger cancels: refund and fee per the cancellation rules (see cancellation.py)."""
    from .cancellation import cancel_by_passenger

    if booking.status not in (BookingStatus.CONFIRMED, BookingStatus.PENDING_PAYMENT):
        raise TripError("Only a booking whose trip hasn't started can be cancelled.", "invalid_state")
    cancel_by_passenger(booking, booking.passenger)


# ---------------------------------------------------------------- live trip


def start(booking):
    _require(booking, BookingStatus.CONFIRMED, "This trip can't be started.")
    booking.status = BookingStatus.IN_PROGRESS
    booking.started_at = timezone.now()
    booking.save(update_fields=["status", "started_at"])
    _event(booking, EventType.STARTED, "Trip started. Check-ins are on.")


def next_checkpoint(booking):
    """First checkpoint not yet confirmed (a missed one stays "next" until checked in)."""
    done = set(booking.checkins.filter(kind=CheckInKind.OK).values_list("key", flat=True))
    return next((key for key, _ in CHECKPOINTS if key not in done), None)


def check_in(booking, key):
    _require(booking, BookingStatus.IN_PROGRESS, "Start the trip before checking in.")
    nxt = next_checkpoint(booking)
    if nxt is None or booking.checkins.filter(key=key, kind=CheckInKind.OK).exists():
        raise TripError("You've already checked in here.", "already_checked_in")
    if key != nxt:
        raise TripError(f"Check in at “{CHECKPOINT_LABELS[nxt]}” first.", "out_of_order")
    CheckIn.objects.create(booking=booking, key=key, kind=CheckInKind.OK)
    _event(booking, EventType.CHECKIN, f"Checked in: {CHECKPOINT_LABELS[key]}.")


def mark_missed(booking):
    """Development only: simulate not answering the next check-in in time."""
    _require(booking, BookingStatus.IN_PROGRESS, "Start the trip first.")
    key = next_checkpoint(booking)
    if key is None:
        raise TripError("All check-ins are done.", "no_checkpoint")
    if booking.checkins.filter(key=key, kind=CheckInKind.MISSED).exists():
        return  # already missed; like the frontend, don't alert twice
    CheckIn.objects.create(booking=booking, key=key, kind=CheckInKind.MISSED)
    label = CHECKPOINT_LABELS[key]
    sent = alerts.notify_contacts(booking, "missed", label)
    tail = f"{_plural(sent, 'trusted contact')} alerted." if sent else "No trusted contacts to alert."
    _event(booking, EventType.MISSED, f"Missed check-in: {label}. {tail}")


def share(booking):
    _require(booking, BookingStatus.IN_PROGRESS, "Start the trip to share it.")
    if booking.shared:
        return
    booking.shared = True
    booking.share_token = secrets.token_urlsafe(16)
    booking.save(update_fields=["shared", "share_token"])
    sent = alerts.notify_contacts(booking, "share")
    text = (
        f"Live trip link shared with {_plural(sent, 'contact')}."
        if sent
        else "Live trip link created. Add trusted contacts so it reaches someone."
    )
    _event(booking, EventType.SHARED, text)


def sos(booking):
    _require(booking, BookingStatus.IN_PROGRESS, "SOS is available during a trip. If you are in danger, call 112.")
    booking.sos_at = timezone.now()
    booking.save(update_fields=["sos_at"])
    sent = alerts.notify_contacts(booking, "sos")
    tail = f"{_plural(sent, 'trusted contact')} alerted." if sent else "No trusted contacts to alert. Call 112 if you are in danger."
    _event(booking, EventType.SOS, f"SOS raised. {tail}")


# Completing a trip needs both sides now: see completion.py.


def rate(booking, stars: int):
    _require(booking, BookingStatus.COMPLETED, "You can rate the driver after the trip.")
    if booking.rating is not None:
        raise TripError("You've already rated this trip.", "already_rated")
    booking.rating = stars
    booking.rated_at = timezone.now()
    booking.save(update_fields=["rating", "rated_at"])
    _event(booking, EventType.RATED, f"Rated the driver {stars}/5.")


# ---------------------------------------------------------------- admin


@transaction.atomic
def admin_cancel_ride(ride, admin, reason: str) -> int:
    """An admin cancels a ride: the ride is removed and its open bookings (confirmed or in
    progress) are cancelled, each with a line in the passenger's trip log. Returns how many
    bookings were cancelled."""
    from . import notifications

    reason = " ".join((reason or "").split())
    if not reason:
        raise TripError("A reason is required to cancel a ride.", "reason_required")
    ride = Ride.objects.select_for_update().get(pk=ride.pk)
    if ride.status != RideStatus.ACTIVE:
        raise TripError("This ride is already cancelled.", "invalid_state")
    now = timezone.now()
    ride.status = RideStatus.CANCELLED
    ride.cancelled_at = now
    ride.cancelled_by = admin
    ride.cancellation_reason = reason
    ride.save(update_fields=["status", "cancelled_at", "cancelled_by", "cancellation_reason", "updated_at"])

    bookings = list(
        Booking.objects.select_for_update()
        .select_related("passenger", "ride__origin", "ride__destination")
        .filter(ride=ride, status__in=[BookingStatus.CONFIRMED, BookingStatus.IN_PROGRESS])
    )
    from .cancellation import cancel_by_vconnects

    for b in bookings:
        cancel_by_vconnects(b, actor=admin, reason=reason, now=now)  # full refund, no penalty
        _event(b, EventType.CANCELLED, f"Ride cancelled by VConnects: {reason} Your booking has been cancelled.")
    notifications.ride_cancelled(bookings, reason)
    return len(bookings)
