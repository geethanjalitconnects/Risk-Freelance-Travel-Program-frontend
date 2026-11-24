"""Bookings and the protected-trip lifecycle (check-ins, sharing, SOS, rating)."""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.payments.money import Rule


class BookingStatus(models.TextChoices):
    # Same values the frontend's status tags use (st-confirmed, st-in_progress, ...).
    PENDING_PAYMENT = "pending_payment", "Awaiting payment"  # seats held while the passenger pays
    CONFIRMED = "confirmed", "Confirmed"  # payment verified on the server
    IN_PROGRESS = "in_progress", "In progress"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"
    EXPIRED = "expired", "Expired"  # not paid before the seat hold ran out


ACTIVE_STATUSES = (BookingStatus.CONFIRMED, BookingStatus.IN_PROGRESS)
# Bookings that no longer hold seats.
CLOSED_STATUSES = (BookingStatus.CANCELLED, BookingStatus.EXPIRED)


class BookingQuerySet(models.QuerySet):
    def not_cancelled(self):
        """Bookings that hold seats: everything except cancelled and expired ones."""
        return self.exclude(status__in=CLOSED_STATUSES)


class Booking(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ride = models.ForeignKey("rides.Ride", on_delete=models.PROTECT, related_name="bookings")
    passenger = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="bookings")
    seats = models.PositiveSmallIntegerField()
    total = models.PositiveIntegerField(help_text="price x seats at booking time")

    # Money, frozen at booking time (paise). Empty for bookings made before payments existed.
    ride_amount_paise = models.PositiveIntegerField(null=True, blank=True, help_text="Seat price x seats.")
    platform_fee_paise = models.PositiveIntegerField(null=True, blank=True, help_text="Added for the passenger.")
    total_paise = models.PositiveIntegerField(null=True, blank=True, help_text="What the passenger pays.")
    publisher_commission_paise = models.PositiveIntegerField(null=True, blank=True)
    publisher_earning_paise = models.PositiveIntegerField(null=True, blank=True)
    fee_policy = models.JSONField(default=dict, blank=True, help_text="The rates in force when this booking was made.")
    hold_expires_at = models.DateTimeField(null=True, blank=True, help_text="Seats are released after this if unpaid.")

    # Risk is frozen at booking time, as in the frontend (riskScore / riskBand on the booking).
    risk_score = models.PositiveSmallIntegerField()
    risk_band = models.CharField(max_length=10)

    status = models.CharField(max_length=16, choices=BookingStatus.choices, default=BookingStatus.CONFIRMED)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    shared = models.BooleanField(default=False)
    share_token = models.CharField(max_length=32, unique=True, null=True, blank=True)
    sos_at = models.DateTimeField(null=True, blank=True)

    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    rated_at = models.DateTimeField(null=True, blank=True)

    objects = BookingQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # One live booking per passenger per ride (the frontend's "You have booked this ride").
            models.UniqueConstraint(
                fields=["ride", "passenger"],
                condition=~Q(status__in=CLOSED_STATUSES),
                name="one_open_booking_per_ride_passenger",
            ),
            models.CheckConstraint(condition=Q(seats__gte=1, seats__lte=4), name="booking_seats_1_4"),
            models.CheckConstraint(
                condition=Q(rating__isnull=True) | Q(rating__gte=1, rating__lte=5), name="booking_rating_1_5"
            ),
        ]
        indexes = [models.Index(fields=["passenger", "status"])]

    def __str__(self):
        return f"{self.passenger} on {self.ride_id} ({self.status})"

    def set_amounts(self, amounts, policy):
        """Freeze the price breakdown and the rates on this booking (``money.BookingAmounts``)."""
        self.ride_amount_paise = amounts.ride_amount
        self.platform_fee_paise = amounts.platform_fee
        self.total_paise = amounts.total
        self.publisher_commission_paise = amounts.publisher_commission
        self.publisher_earning_paise = amounts.publisher_earning
        self.fee_policy = policy.to_dict()

    def amounts(self):
        """The frozen ``money.BookingAmounts``, or None for bookings made before payments."""
        from apps.payments.money import BookingAmounts

        if self.total_paise is None:
            return None
        return BookingAmounts(
            ride_amount=self.ride_amount_paise, platform_fee=self.platform_fee_paise, total=self.total_paise,
            publisher_commission=self.publisher_commission_paise, publisher_earning=self.publisher_earning_paise,
        )

    def policy(self):
        """The frozen ``money.FeePolicy`` (current settings for bookings made before payments)."""
        from apps.payments.models import PaymentSettings
        from apps.payments.money import FeePolicy

        return FeePolicy.from_dict(self.fee_policy) if self.fee_policy else PaymentSettings.load().policy()


# Same keys, labels and order as CHECKPOINTS in the frontend's Trips page.
CHECKPOINTS = [
    ("pickup", "Picked up and seat belt on"),
    ("mid", "Mid-way check-in"),
    ("near", "Nearing destination"),
]
CHECKPOINT_LABELS = dict(CHECKPOINTS)


class CheckInKind(models.TextChoices):
    OK = "ok", "Checked in"
    MISSED = "missed", "Missed"


class CheckIn(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="checkins")
    key = models.CharField(max_length=10, choices=CHECKPOINTS)
    kind = models.CharField(max_length=6, choices=CheckInKind.choices)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["at"]
        constraints = [models.UniqueConstraint(fields=["booking", "key", "kind"], name="one_checkin_per_kind")]

    def __str__(self):
        return f"{self.key} {self.kind} for {self.booking_id}"


class EventType(models.TextChoices):
    # The event types the frontend's trip log uses.
    BOOKED = "booked"
    CANCELLED = "cancelled"
    STARTED = "started"
    CHECKIN = "checkin"
    MISSED = "missed"
    SHARED = "shared"
    SOS = "sos"
    COMPLETED = "completed"
    RATED = "rated"
    CONFIRMED = "confirmed"  # one side confirmed the ride is complete
    PROBLEM = "problem"  # a problem was reported or decided


class TripEvent(models.Model):
    """One line in the booking's trip log."""

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="events")
    type = models.CharField(max_length=10, choices=EventType.choices)
    text = models.CharField(max_length=200)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["at", "id"]

    def __str__(self):
        return f"{self.type}: {self.text}"


# ---------------------------------------------------------------- cancellation and completion


class Party(models.TextChoices):
    PASSENGER = "passenger", "Passenger"
    PUBLISHER = "publisher", "Publisher"


class CancelledBy(models.TextChoices):
    PASSENGER = "passenger", "Passenger"
    PUBLISHER = "publisher", "Publisher"
    ADMIN = "admin", "VConnects"
    SYSTEM = "system", "System"


class Cancellation(models.Model):
    """How a cancelled (or no-show) booking was settled, written once with the amounts the money
    service computed. Refunds and ledger entries reference the same booking."""

    booking = models.OneToOneField(Booking, on_delete=models.PROTECT, related_name="cancellation")
    cancelled_by = models.CharField(max_length=10, choices=CancelledBy.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    reason = models.CharField(max_length=300, blank=True)
    minutes_before_departure = models.IntegerField(help_text="Negative when after departure.")
    rule = models.CharField(max_length=24, choices=Rule.CHOICES)
    total_paid_paise = models.PositiveIntegerField()
    refund_paise = models.PositiveIntegerField()
    vconnects_kept_paise = models.PositiveIntegerField()
    publisher_earning_paise = models.PositiveIntegerField(default=0)
    publisher_penalty_paise = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(total_paid_paise=F("refund_paise") + F("vconnects_kept_paise") + F("publisher_earning_paise")),
                name="cancellation_amounts_add_up",
            ),
        ]

    def __str__(self):
        return f"{self.get_rule_display()} for {self.booking_id}"


class CompletionSource(models.TextChoices):
    SWIPE = "swipe", "Swiped in the app"
    AUTO = "auto", "Automatic (no problem reported)"
    ADMIN = "admin", "Admin decision"


class CompletionConfirmation(models.Model):
    """One party confirming that the ride took place. Earnings are released only when both the
    passenger and the publisher have confirmed, or the ride auto-completes."""

    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, related_name="confirmations")
    party = models.CharField(max_length=10, choices=Party.choices)
    source = models.CharField(max_length=6, choices=CompletionSource.choices, default=CompletionSource.SWIPE)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["at"]
        constraints = [models.UniqueConstraint(fields=["booking", "party"], name="one_confirmation_per_party")]

    def __str__(self):
        return f"{self.party} confirmed {self.booking_id}"


class ProblemKind(models.TextChoices):
    PASSENGER_NO_SHOW = "passenger_no_show", "Passenger didn't show up"
    PUBLISHER_NO_SHOW = "publisher_no_show", "Publisher didn't show up"
    OTHER = "other", "Other problem"


class ProblemStatus(models.TextChoices):
    OPEN = "open", "Open"
    UPHELD = "upheld", "Upheld"
    DISMISSED = "dismissed", "Dismissed"


class ProblemReport(models.Model):
    """A problem with a booking, raised by either side. While a report is open the booking can't
    auto-complete and the publisher's earning stays held."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, related_name="problems")
    raised_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    party = models.CharField(max_length=10, choices=Party.choices)
    kind = models.CharField(max_length=20, choices=ProblemKind.choices)
    details = models.TextField(max_length=2000)
    status = models.CharField(max_length=10, choices=ProblemStatus.choices, default=ProblemStatus.OPEN)
    resolution_note = models.CharField(max_length=1000, blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["booking", "kind"], condition=Q(status="open"), name="one_open_problem_per_kind"
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} on {self.booking_id} ({self.status})"
