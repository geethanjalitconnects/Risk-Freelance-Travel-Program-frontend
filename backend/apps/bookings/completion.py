"""Ride completion, no-shows and problem reports (Phase 5).

A booking completes only when BOTH sides confirm it, or automatically ``auto_complete_hours`` after
the scheduled arrival when nobody has reported a problem:

    passenger swipes "complete"  ─┐
                                   ├─ both confirmed ──> completed ──> publisher's earning released
    publisher swipes the ride    ─┘
    no problem reported + arrival + 24 h  ──(manage.py auto_complete_bookings)──> completed

An open problem report freezes the booking: it can't complete (by swipe or automatically) and the
publisher's earning stays held until an admin upholds or dismisses the report.

Earnings: ``ledger.release_earning`` moves the held earning to available. Bookings only have a held
earning once their payment is captured (Phase 3); until then completion releases nothing.
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.payments import audit, ledger, money
from apps.payments.models import EarningEntry, FinancialAction, PaymentSettings
from apps.rides.models import Ride

from .cancellation import amounts_of, settle
from .models import (
    ACTIVE_STATUSES,
    Booking,
    BookingStatus,
    CancelledBy,
    CompletionConfirmation,
    CompletionSource,
    EventType,
    Party,
    ProblemKind,
    ProblemReport,
    ProblemStatus,
    TripEvent,
)
from .services import TripError

logger = logging.getLogger(__name__)

MIN_DETAILS = 10


def _event(booking, type_, text):
    TripEvent.objects.create(booking=booking, type=type_, text=text)


def _settings():
    return PaymentSettings.load()


def has_open_problem(booking) -> bool:
    return booking.problems.filter(status=ProblemStatus.OPEN).exists()


def ride_started(ride, now=None) -> bool:
    """The publisher can complete a ride once it has departed, or once a passenger has started
    their trip (so a ride that leaves early can be completed on arrival)."""
    now = now or timezone.now()
    return ride.depart <= now or ride.bookings.filter(status=BookingStatus.IN_PROGRESS).exists()


def no_show_from(ride):
    return ride.depart + timedelta(minutes=_settings().no_show_after_minutes)


def auto_complete_at(ride):
    return ride.arrive + timedelta(hours=_settings().auto_complete_hours)


def passenger_can_confirm(booking, now=None) -> bool:
    now = now or timezone.now()
    if booking.status == BookingStatus.IN_PROGRESS:
        return True
    return booking.status == BookingStatus.CONFIRMED and booking.ride.depart <= now


def report_kinds(booking, party, now=None) -> list:
    """Which problems ``party`` can report on this booking right now."""
    now = now or timezone.now()
    if booking.status not in ACTIVE_STATUSES:
        return []
    kinds = [ProblemKind.OTHER]
    if party == Party.PASSENGER and booking.ride.depart <= now:
        kinds.insert(0, ProblemKind.PUBLISHER_NO_SHOW)
    if party == Party.PUBLISHER and now >= no_show_from(booking.ride):
        kinds.insert(0, ProblemKind.PASSENGER_NO_SHOW)
    return kinds


# ---------------------------------------------------------------- confirming


def _confirm(booking, party, source, actor=None):
    obj, created = CompletionConfirmation.objects.get_or_create(
        booking=booking, party=party, defaults={"source": source, "actor": actor}
    )
    return created


def _both_confirmed(booking) -> bool:
    return set(booking.confirmations.values_list("party", flat=True)) >= {Party.PASSENGER, Party.PUBLISHER}


def _release(booking):
    """Move the publisher's held earning to available, if the booking has one."""
    if not EarningEntry.objects.filter(idempotency_key=f"booking:{booking.pk}:held").exists():
        logger.info("Booking %s completed with no held earning (no captured payment).", booking.pk)
        return None
    entry, created = ledger.release_earning(booking)
    if created:
        audit.record(
            FinancialAction.BOOKING_SETTLED, label="system", user=booking.ride.driver, booking=booking,
            amount=booking.publisher_earning_paise, reference=entry.idempotency_key, rule=money.Rule.COMPLETED,
        )
    return entry


def finalize(booking, source):
    """Complete a booking whose ride both sides confirmed (or that auto-completed). The caller holds
    the booking's row lock. No-op if it already left the active states."""
    if booking.status not in ACTIVE_STATUSES:
        return False
    if has_open_problem(booking):
        raise TripError("A problem was reported on this trip. VConnects is reviewing it.", "problem_open")
    booking.status = BookingStatus.COMPLETED
    booking.completed_at = timezone.now()
    booking.save(update_fields=["status", "completed_at"])
    text = {
        CompletionSource.SWIPE: "Ride complete: you and the driver both confirmed. Arrived safely.",
        CompletionSource.AUTO: "Ride completed automatically (no problem was reported).",
        CompletionSource.ADMIN: "Ride marked complete by VConnects.",
    }[source]
    _event(booking, EventType.COMPLETED, text)
    _release(booking)
    return True


def confirm_by_passenger(booking, user):
    """The passenger swipes "ride complete". The caller holds the booking's row lock."""
    if booking.status not in ACTIVE_STATUSES:
        raise TripError("This trip can't be completed.", "invalid_state")
    if not passenger_can_confirm(booking):
        raise TripError("You can confirm the ride once it has left.", "not_departed")
    if booking.problems.filter(status=ProblemStatus.OPEN, party=Party.PASSENGER).exists():
        raise TripError("You reported a problem on this trip. VConnects is reviewing it.", "problem_open")
    # If the driver reported this passenger as a no-show, the passenger's swipe still counts as
    # their side of the story for the reviewer; the booking stays frozen until the decision.
    if _confirm(booking, Party.PASSENGER, CompletionSource.SWIPE, user):
        _event(booking, EventType.CONFIRMED, "You confirmed the ride is complete.")
    if _both_confirmed(booking) and not has_open_problem(booking):
        finalize(booking, CompletionSource.SWIPE)


@transaction.atomic
def complete_ride(ride_id, publisher, no_show_ids=(), note=""):
    """The publisher swipes "ride complete" for the whole ride. Passengers in ``no_show_ids`` are
    reported as no-shows instead of confirmed. Returns the ride."""
    ride = Ride.objects.select_for_update().filter(pk=ride_id, driver=publisher).first()
    if ride is None:
        raise TripError("Ride not found.", "not_found", status=404)
    now = timezone.now()
    if not ride_started(ride, now):
        raise TripError("You can complete the ride once it has left.", "not_departed")

    bookings = list(Booking.objects.select_for_update().filter(ride=ride, status__in=ACTIVE_STATUSES).order_by("created_at"))
    if not bookings:
        raise TripError("There are no passengers left to confirm on this ride.", "nothing_to_complete")
    no_show_ids = {str(i) for i in no_show_ids}
    unknown = no_show_ids - {str(b.pk) for b in bookings}
    if unknown:
        raise TripError("Some of those passengers aren't on this ride.", "unknown_booking", status=400)
    if no_show_ids and now < no_show_from(ride):
        when = timezone.localtime(no_show_from(ride)).strftime("%H:%M")
        raise TripError(f"You can report a no-show from {when}, 30 minutes after departure.", "too_early")

    note = " ".join((note or "").split())[:500]
    for b in bookings:
        if str(b.pk) in no_show_ids:
            details = "Marked as a no-show by the driver when completing the ride."
            if note:
                details += f" Driver's note: {note}"
            _open_report(b, publisher, Party.PUBLISHER, ProblemKind.PASSENGER_NO_SHOW, details)
            continue
        if _confirm(b, Party.PUBLISHER, CompletionSource.SWIPE, publisher):
            _event(b, EventType.CONFIRMED, "The driver confirmed the ride is complete.")
        if _both_confirmed(b) and not has_open_problem(b):
            finalize(b, CompletionSource.SWIPE)
    return ride


# ---------------------------------------------------------------- problems


def _open_report(booking, user, party, kind, details):
    report = booking.problems.filter(kind=kind, status=ProblemStatus.OPEN).first()
    if report:
        return report
    report = ProblemReport.objects.create(booking=booking, raised_by=user, party=party, kind=kind, details=details)
    label = ProblemKind(kind).label
    _event(booking, EventType.PROBLEM, f"Problem reported: {label}. Payment is on hold until VConnects reviews it.")
    return report


def report_by_passenger(booking, user, kind, details):
    """The caller holds the booking's row lock."""
    details = " ".join((details or "").split())
    if kind not in report_kinds(booking, Party.PASSENGER):
        raise TripError("You can't report that on this trip.", "invalid_kind")
    if len(details) < MIN_DETAILS:
        raise TripError("Tell us what happened (at least a few words).", "details_required", status=400)
    return _open_report(booking, user, Party.PASSENGER, kind, details[:2000])


# ---------------------------------------------------------------- admin decisions


@transaction.atomic
def resolve_problem(report_id, admin, *, uphold: bool, note: str):
    """An admin decides an open report.

    passenger no-show  upheld:    booking cancelled, publisher paid as for a completed ride, no refund
                       dismissed: the passenger did travel; the publisher's confirmation is added
    publisher no-show  upheld:    booking cancelled, 100% refund, within-24-hours publisher penalty
    other              upheld:    booking cancelled, 100% refund, no penalty
    dismissed (any):   the report closes; the booking completes now if both sides confirmed or
                       its auto-complete time has passed, otherwise it waits as normal
    """
    note = " ".join((note or "").split())
    if not note:
        raise TripError("Add a note explaining the decision.", "note_required", status=400)
    report = ProblemReport.objects.select_for_update().select_related("booking").get(pk=report_id)
    if report.status != ProblemStatus.OPEN:
        raise TripError("This report has already been decided.", "already_decided")
    booking = Booking.objects.select_for_update().select_related("ride").get(pk=report.booking_id)

    report.status = ProblemStatus.UPHELD if uphold else ProblemStatus.DISMISSED
    report.resolution_note = note[:1000]
    report.resolved_by = admin
    report.resolved_at = timezone.now()
    report.save(update_fields=["status", "resolution_note", "resolved_by", "resolved_at"])

    active = booking.status in ACTIVE_STATUSES
    if uphold and active:
        amounts = amounts_of(booking)
        if report.kind == ProblemKind.PASSENGER_NO_SHOW:
            settlement = money.passenger_no_show(amounts)
            _event(booking, EventType.CANCELLED, f"Marked as a no-show after review: {note}")
        elif report.kind == ProblemKind.PUBLISHER_NO_SHOW:
            settlement = money.publisher_no_show(amounts, booking.policy())
            _event(booking, EventType.CANCELLED, f"Driver no-show confirmed. You'll get a full refund. {note}")
        else:
            settlement = money.admin_full_refund(amounts)
            _event(booking, EventType.CANCELLED, f"Booking cancelled after review. You'll get a full refund. {note}")
        settle(booking, settlement, cancelled_by=CancelledBy.ADMIN, actor=admin, reason=note)
    elif not uphold and active:
        _event(booking, EventType.PROBLEM, f"Problem report closed after review: {note}")
        if report.kind == ProblemKind.PASSENGER_NO_SHOW:
            _confirm(booking, Party.PUBLISHER, CompletionSource.ADMIN, admin)
        if not has_open_problem(booking) and (
            _both_confirmed(booking) or timezone.now() >= auto_complete_at(booking.ride)
        ):
            finalize(booking, CompletionSource.ADMIN)
    return report


# ---------------------------------------------------------------- automatic completion


def due_for_auto_complete(now=None):
    now = now or timezone.now()
    cutoff = now - timedelta(hours=_settings().auto_complete_hours)
    return (
        Booking.objects.filter(status__in=ACTIVE_STATUSES, ride__arrive__lte=cutoff)
        .exclude(problems__status=ProblemStatus.OPEN)
        .values_list("pk", flat=True)
    )


def auto_complete(booking_id) -> bool:
    with transaction.atomic():
        booking = Booking.objects.select_for_update().select_related("ride").get(pk=booking_id)
        if booking.status not in ACTIVE_STATUSES or has_open_problem(booking):
            return False
        if timezone.now() < auto_complete_at(booking.ride):
            return False
        for party in (Party.PASSENGER, Party.PUBLISHER):
            _confirm(booking, party, CompletionSource.AUTO)
        return finalize(booking, CompletionSource.AUTO)
