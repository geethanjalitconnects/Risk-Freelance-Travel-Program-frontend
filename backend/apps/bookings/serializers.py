from datetime import timedelta

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Prefetch
from django.utils import timezone
from rest_framework import serializers

from apps.payments import money
from apps.payments.models import PaymentSettings, Refund
from apps.rides.serializers import area_payload, DriverOutSerializer, VehicleOutSerializer, driver_payload, vehicle_payload
from apps.rides.services import driver_stats

from . import alerts, completion
from .models import (
    ACTIVE_STATUSES,
    CHECKPOINTS,
    Booking,
    BookingStatus,
    CheckIn,
    CheckInKind,
    Party,
    ProblemKind,
    ProblemReport,
    ProblemStatus,
    TripEvent,
)


def _ms(dt):
    """Epoch milliseconds, like Date.now() values in the frontend's booking objects."""
    return int(dt.timestamp() * 1000) if dt else None


def _local(dt):
    return timezone.localtime(dt).strftime("%Y-%m-%dT%H:%M")


def booking_queryset():
    return Booking.objects.select_related(
        "ride", "ride__driver", "ride__driver__driver_verification", "ride__origin", "ride__destination"
    ).prefetch_related(
        Prefetch("checkins", queryset=CheckIn.objects.order_by("at")),
        Prefetch("events", queryset=TripEvent.objects.order_by("at", "id")),
        "confirmations",
        Prefetch("problems", queryset=ProblemReport.objects.order_by("-created_at")),
        Prefetch("refunds", queryset=Refund.objects.order_by("created_at")),
    ).select_related("cancellation")


def amounts_payload(b):
    """The price breakdown frozen at booking time, in paise (null for bookings made before payments)."""
    a = b.amounts()
    if a is None:
        return None
    return {"ride_amount": a.ride_amount, "platform_fee": a.platform_fee, "total": a.total}


RULE_LABELS = dict(money.Rule.CHOICES)


def cancellation_payload(b):
    try:
        c = b.cancellation
    except ObjectDoesNotExist:
        return None
    refund = next((r for r in b.refunds.all()), None)
    return {
        "by": c.cancelled_by,
        "rule": c.rule,
        "label": RULE_LABELS.get(c.rule, c.rule),
        "reason": c.reason,
        "total_paid": c.total_paid_paise,
        "refund": c.refund_paise,
        "fee": c.vconnects_kept_paise,
        "refund_status": refund.status if refund else None,  # null: nothing was paid, so nothing to refund
        "at": _ms(c.created_at),
    }


def open_problem(b):
    """The newest open problem report on a booking (from prefetched rows), as a small payload."""
    p = next((p for p in b.problems.all() if p.status == ProblemStatus.OPEN), None)
    if p is None:
        return None
    return {"kind": p.kind, "label": ProblemKind(p.kind).label, "party": p.party, "created_at": _ms(p.created_at)}


def confirmed_parties(b) -> dict:
    return {c.party: c.at for c in b.confirmations.all()}


def completion_payload(b, auto_hours, now) -> dict:
    """Where the passenger's two-sided completion stands (for the Trips page)."""
    done = confirmed_parties(b)
    problem = open_problem(b)
    active = b.status in ACTIVE_STATUSES
    open_kinds = {p.kind for p in b.problems.all() if p.status == ProblemStatus.OPEN}
    return {
        "passenger_confirmed_at": _ms(done.get(Party.PASSENGER)),
        "publisher_confirmed_at": _ms(done.get(Party.PUBLISHER)),
        "can_confirm": bool(
            active
            and Party.PASSENGER not in done
            and not any(p.status == ProblemStatus.OPEN and p.party == Party.PASSENGER for p in b.problems.all())
            and completion.passenger_can_confirm(b, now)
        ),
        "report_kinds": [
            {"value": k, "label": ProblemKind(k).label}
            for k in completion.report_kinds(b, Party.PASSENGER, now)
            if k not in open_kinds
        ],
        "open_problem": problem,
        "auto_complete_at": _ms(b.ride.arrive + timedelta(hours=auto_hours)) if active else None,
    }


def _ride_snapshot(ride, stats, show_vehicle_number):
    return {
        "id": ride.pk,
        "source": "published",
        "from": ride.origin_id,
        "to": ride.destination_id,
        "from_area": area_payload(ride.origin),
        "to_area": area_payload(ride.destination),
        "date": timezone.localtime(ride.depart).date().isoformat(),
        "depart": _local(ride.depart),
        "arrive": _local(ride.arrive),
        "duration_min": ride.duration_min,
        "km": ride.km,
        "price": ride.price,
        "seats_total": ride.seats_total,
        "pickup": ride.pickup,
        "dropoff": ride.dropoff,
        "travel_with": ride.travel_with,
        "women_only": ride.travel_with == "women",
        "ac": ride.ac,
        "bags": ride.bags,
        "notes": ride.notes,
        "status": ride.status,
        "driver": driver_payload(ride.driver, stats),
        # The registration number is for passengers holding a booking (to find the car at pickup).
        "vehicle": vehicle_payload(ride, show_number=show_vehicle_number),
    }


def _next_checkpoint(checkins):
    done = {c.key for c in checkins if c.kind == CheckInKind.OK}
    return next((key for key, _ in CHECKPOINTS if key not in done), None)


def serialize_bookings(bookings) -> list:
    """Bookings in the shape the Trips page reads (see bookRide() in the frontend's store.js).

    Pass bookings from ``booking_queryset()``.
    """
    stats = driver_stats(b.ride.driver_id for b in bookings)
    auto_hours = PaymentSettings.load().auto_complete_hours
    now = timezone.now()
    out = []
    for b in bookings:
        checkins = list(b.checkins.all())
        trip = None
        if b.started_at:
            trip = {
                "started_at": _ms(b.started_at),
                "checkins": {c.key: _ms(c.at) for c in checkins if c.kind == CheckInKind.OK},
                "missed": {c.key: _ms(c.at) for c in checkins if c.kind == CheckInKind.MISSED},
                "shared": b.shared,
                "sos": _ms(b.sos_at),
            }
        out.append(
            {
                "id": b.pk,
                "ride_id": b.ride_id,
                "ride": _ride_snapshot(b.ride, stats[b.ride.driver_id], b.status != BookingStatus.CANCELLED),
                "risk_score": b.risk_score,
                "risk_band": b.risk_band,
                "seats": b.seats,
                "total": b.total,
                "created_at": _ms(b.created_at),
                "status": b.status,
                "trip": trip,
                "next_checkpoint": _next_checkpoint(checkins) if b.status == BookingStatus.IN_PROGRESS else None,
                "share_url": alerts.share_url(b) if b.shared else None,
                "events": [{"t": _ms(e.at), "type": e.type, "text": e.text} for e in b.events.all()],
                "rating": b.rating,
                "completed_at": _ms(b.completed_at),
                "completion": completion_payload(b, auto_hours, now),
                "amounts": amounts_payload(b),
                "hold_expires_at": _ms(b.hold_expires_at) if b.status == BookingStatus.PENDING_PAYMENT else None,
                "cancellation": cancellation_payload(b),
            }
        )
    return out


# ---------------------------------------------------------------- input


class BookingCreateSerializer(serializers.Serializer):
    ride_id = serializers.UUIDField()
    seats = serializers.IntegerField(min_value=1, max_value=4, default=1)


class CheckInInputSerializer(serializers.Serializer):
    key = serializers.ChoiceField(choices=[k for k, _ in CHECKPOINTS])


class ProblemInputSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=[ProblemKind.PUBLISHER_NO_SHOW, ProblemKind.OTHER])
    details = serializers.CharField(max_length=2000)


class RideCompleteInputSerializer(serializers.Serializer):
    no_show = serializers.ListField(child=serializers.UUIDField(), required=False, default=list, max_length=4)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class RateInputSerializer(serializers.Serializer):
    stars = serializers.IntegerField(
        min_value=1, max_value=5, error_messages={"min_value": "Choose 1 to 5 stars.", "max_value": "Choose 1 to 5 stars."}
    )


# ---------------------------------------------------------------- output (documentation)


class TripStateSerializer(serializers.Serializer):
    started_at = serializers.IntegerField(help_text="epoch ms")
    checkins = serializers.DictField(child=serializers.IntegerField(), help_text="checkpoint key -> epoch ms")
    missed = serializers.DictField(child=serializers.IntegerField(), help_text="checkpoint key -> epoch ms")
    shared = serializers.BooleanField()
    sos = serializers.IntegerField(allow_null=True, help_text="epoch ms of the last SOS")


class TripEventOutSerializer(serializers.Serializer):
    t = serializers.IntegerField(help_text="epoch ms")
    type = serializers.CharField()
    text = serializers.CharField()


class BookingRideSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    from_area = serializers.DictField(help_text="{code, name, district, state, region}")
    to_area = serializers.DictField()
    to = serializers.CharField()
    depart = serializers.CharField()
    arrive = serializers.CharField()
    price = serializers.IntegerField()
    travel_with = serializers.CharField()
    driver = DriverOutSerializer()
    vehicle = VehicleOutSerializer()


class ProblemOutSerializer(serializers.Serializer):
    kind = serializers.CharField()
    label = serializers.CharField()
    party = serializers.CharField()
    created_at = serializers.IntegerField(help_text="epoch ms")


class KindOutSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()


class CompletionOutSerializer(serializers.Serializer):
    passenger_confirmed_at = serializers.IntegerField(allow_null=True, help_text="epoch ms")
    publisher_confirmed_at = serializers.IntegerField(allow_null=True, help_text="epoch ms")
    can_confirm = serializers.BooleanField()
    report_kinds = KindOutSerializer(many=True)
    open_problem = ProblemOutSerializer(allow_null=True)
    auto_complete_at = serializers.IntegerField(allow_null=True, help_text="epoch ms")


class AmountsOutSerializer(serializers.Serializer):
    ride_amount = serializers.IntegerField(help_text="paise")
    platform_fee = serializers.IntegerField(help_text="paise")
    total = serializers.IntegerField(help_text="paise: what the passenger pays")


class CancellationOutSerializer(serializers.Serializer):
    by = serializers.CharField()
    rule = serializers.CharField()
    label = serializers.CharField()
    reason = serializers.CharField()
    total_paid = serializers.IntegerField(help_text="paise")
    refund = serializers.IntegerField(help_text="paise")
    fee = serializers.IntegerField(help_text="paise kept by VConnects")
    refund_status = serializers.CharField(allow_null=True)
    at = serializers.IntegerField(help_text="epoch ms")


class CancelQuoteOutSerializer(serializers.Serializer):
    rule = serializers.CharField()
    paid = serializers.BooleanField()
    total_paid = serializers.IntegerField(help_text="paise")
    refund = serializers.IntegerField(help_text="paise")
    fee = serializers.IntegerField(help_text="paise")
    message = serializers.CharField()


class RideCancelQuoteOutSerializer(serializers.Serializer):
    passengers = serializers.IntegerField()
    paid_passengers = serializers.IntegerField()
    refund_total = serializers.IntegerField(help_text="paise")
    penalty = serializers.IntegerField(help_text="paise, deducted from your earnings")
    within_window = serializers.BooleanField()
    message = serializers.CharField()


class PaymentVerifySerializer(serializers.Serializer):
    razorpay_order_id = serializers.CharField(max_length=40)
    razorpay_payment_id = serializers.CharField(max_length=40)
    razorpay_signature = serializers.CharField(max_length=128)


class RideCancelInputSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300)


class BookingOutSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    ride_id = serializers.UUIDField()
    ride = BookingRideSerializer()
    risk_score = serializers.IntegerField()
    risk_band = serializers.CharField()
    seats = serializers.IntegerField()
    total = serializers.IntegerField()
    created_at = serializers.IntegerField(help_text="epoch ms")
    status = serializers.ChoiceField(choices=BookingStatus.choices)
    trip = TripStateSerializer(allow_null=True)
    next_checkpoint = serializers.CharField(allow_null=True)
    share_url = serializers.CharField(allow_null=True)
    events = TripEventOutSerializer(many=True)
    rating = serializers.IntegerField(allow_null=True)
    completed_at = serializers.IntegerField(allow_null=True, help_text="epoch ms")
    completion = CompletionOutSerializer()
    amounts = AmountsOutSerializer(allow_null=True)
    hold_expires_at = serializers.IntegerField(allow_null=True, help_text="epoch ms: unpaid seats are released then")
    cancellation = CancellationOutSerializer(allow_null=True)
