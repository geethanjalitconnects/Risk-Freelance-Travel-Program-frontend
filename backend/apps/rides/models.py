import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.bookings.models import CLOSED_STATUSES, BookingStatus


class TravelWith(models.TextChoices):
    """"Who can travel with me". Women-only / men-only rides can only be offered by drivers of
    that gender, and only passengers of that gender can book them."""

    ANYONE = "anyone", "Anyone"
    WOMEN = "women", "Women only"
    MEN = "men", "Men only"


# The gender a restricted ride requires, for both its driver and its passengers.
REQUIRED_GENDER = {TravelWith.WOMEN: "F", TravelWith.MEN: "M"}


class RideStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    CANCELLED = "cancelled", "Removed"


class Bags(models.TextChoices):
    # The three luggage options the frontend shows.
    BACKPACK = "Backpack only", "Backpack only"
    CABIN = "One cabin bag", "One cabin bag"
    LARGE = "One large bag", "One large bag"


NOT_CANCELLED = ~Q(bookings__status__in=CLOSED_STATUSES)  # bookings that hold seats


class RideQuerySet(models.QuerySet):
    def active(self):
        return self.filter(status=RideStatus.ACTIVE)

    def with_booked_seats(self):
        return self.annotate(
            booked_seats=Coalesce(Sum("bookings__seats", filter=NOT_CANCELLED), Value(0)),
        )

    def listed(self):
        """Rides anyone can find and book: active, from an active account whose driver
        verification is approved. Rides of unapproved, revoked or deactivated drivers drop out of
        search automatically (and come back on re-approval / reactivation)."""
        return self.active().filter(driver__is_active=True, driver__driver_verification__status="approved")

    def for_display(self):
        return self.select_related(
            "driver", "driver__driver_verification", "origin", "destination"
        ).with_booked_seats()


class Ride(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    driver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="rides")

    origin = models.ForeignKey("geo.City", on_delete=models.PROTECT, related_name="+")
    destination = models.ForeignKey("geo.City", on_delete=models.PROTECT, related_name="+")
    pickup = models.CharField(max_length=120)
    dropoff = models.CharField(max_length=120)

    depart = models.DateTimeField()
    duration_min = models.PositiveIntegerField()
    arrive = models.DateTimeField(help_text="depart + duration_min, stored for querying")
    km = models.PositiveIntegerField()

    price = models.PositiveIntegerField(help_text="Rupees per seat")
    seats_total = models.PositiveSmallIntegerField()
    travel_with = models.CharField(max_length=6, choices=TravelWith.choices, default=TravelWith.ANYONE)

    # The vehicle is stored on the ride: the frontend has no saved-vehicles feature, and a
    # snapshot keeps each ride's risk inputs stable if the driver later lists another car.
    vehicle_model = models.CharField(max_length=80)
    vehicle_year = models.PositiveSmallIntegerField()
    vehicle_features = models.JSONField(default=list, blank=True)

    ac = models.BooleanField(default=True)
    bags = models.CharField(max_length=20, choices=Bags.choices, default=Bags.CABIN)
    notes = models.CharField(max_length=140, blank=True)

    status = models.CharField(max_length=10, choices=RideStatus.choices, default=RideStatus.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    # Set when an admin cancels the ride (a driver removing an unbooked ride leaves them empty).
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    cancellation_reason = models.CharField(max_length=300, blank=True)

    objects = RideQuerySet.as_manager()

    class Meta:
        ordering = ["depart"]
        indexes = [
            models.Index(fields=["origin", "destination", "depart"]),
            models.Index(fields=["driver", "status"]),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(seats_total__gte=1, seats_total__lte=4), name="ride_seats_1_4"),
            models.CheckConstraint(condition=Q(price__gte=1), name="ride_price_positive"),
            models.CheckConstraint(condition=~Q(origin=F("destination")), name="ride_cities_differ"),
        ]

    def __str__(self):
        return f"{self.origin_id} -> {self.destination_id} {timezone.localtime(self.depart):%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        self.arrive = self.depart + timedelta(minutes=self.duration_min)
        super().save(*args, **kwargs)

    # ---- booking-derived facts (queried fresh; use for rule checks) ----

    def open_bookings(self):
        return self.bookings.not_cancelled()

    def has_bookings(self) -> bool:
        return self.open_bookings().exists()

    def count_booked_seats(self) -> int:
        return self.open_bookings().aggregate(n=Coalesce(Sum("seats"), Value(0)))["n"]

    @property
    def is_restricted(self) -> bool:
        return self.travel_with != TravelWith.ANYONE

    @property
    def has_departed(self) -> bool:
        return self.depart <= timezone.now()

    @property
    def is_listed(self) -> bool:
        """Same rule as RideQuerySet.listed(), for a loaded ride."""
        from apps.verification.services import is_approved

        return self.status == RideStatus.ACTIVE and self.driver.is_active and is_approved(self.driver)
