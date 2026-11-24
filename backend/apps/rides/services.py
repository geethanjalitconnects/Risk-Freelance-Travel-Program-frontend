"""Read-side helpers: driver stats, per-viewer facts and live risk for a batch of rides."""
from dataclasses import dataclass
from typing import Iterable, Optional

from django.db.models import Avg, Count, Q

from apps.bookings.models import Booking, BookingStatus
from apps.risk import services as risk_services
from apps.risk.scoring import DriverProfile, VehicleProfile

from . import policies
from .models import Ride


@dataclass
class DriverStats:
    rating: Optional[float] = None  # average of passenger ratings, None until rated
    trips: int = 0  # rides with at least one completed passenger trip


def driver_stats(driver_ids: Iterable) -> dict:
    ids = set(driver_ids)
    stats = {i: DriverStats() for i in ids}
    if not ids:
        return stats
    rows = (
        Booking.objects.filter(ride__driver_id__in=ids)
        .values("ride__driver_id")
        .annotate(
            avg=Avg("rating"),
            trips=Count("ride", filter=Q(status=BookingStatus.COMPLETED), distinct=True),
        )
    )
    for row in rows:
        avg = row["avg"]
        stats[row["ride__driver_id"]] = DriverStats(rating=round(avg, 2) if avg is not None else None, trips=row["trips"])
    return stats


def driver_profile(user, stats: DriverStats) -> DriverProfile:
    return DriverProfile(
        verified_id=user.verified_id, verified_license=user.verified_license, rating=stats.rating, trips=stats.trips
    )


def prepare(rides: list, viewer=None) -> list:
    """Attach everything RideSerializer needs, computed in a fixed number of queries.

    Rides must come from ``Ride.objects.for_display()`` (driver/cities joined, booked_seats annotated).
    Sets on each ride: ``_stats``, ``_seats_left``, ``_risk``, ``_my_booking_id``, ``_block`` and,
    for rides the viewer published, ``_passengers`` (their non-cancelled bookings).
    """
    stats = driver_stats(r.driver_id for r in rides)

    # The driver sees who booked their own rides.
    passengers = {}
    if viewer is not None and viewer.is_authenticated:
        own = [r for r in rides if r.driver_id == viewer.pk]
        if own:
            for b in (
                Booking.objects.not_cancelled()
                .filter(ride__in=own)
                .select_related("passenger")
                .prefetch_related("confirmations", "problems")
                .order_by("created_at")
            ):
                passengers.setdefault(b.ride_id, []).append(b)

    my_bookings = {}
    if viewer is not None and viewer.is_authenticated and rides:
        my_bookings = dict(
            Booking.objects.not_cancelled()
            .filter(passenger=viewer, ride__in=rides)
            .values_list("ride_id", "id")
        )

    routes = {}
    for ride in rides:
        key = (ride.origin_id, ride.destination_id)
        if key not in routes:
            routes[key] = risk_services.route_between(ride.origin, ride.destination)

        ride._stats = stats[ride.driver_id]
        ride._seats_left = max(0, ride.seats_total - ride.booked_seats)
        ride._my_booking_id = my_bookings.get(ride.id)
        ride._passengers = passengers.get(ride.id, []) if viewer is not None and ride.driver_id == getattr(viewer, "pk", None) else None
        ride._risk = risk_services.score(
            ride.origin,
            ride.destination,
            ride.depart,
            driver_profile(ride.driver, ride._stats),
            VehicleProfile(year=ride.vehicle_year, features=ride.vehicle_features),
            route=routes[key],
        )
        # "Can this viewer book at least one seat?" The exact seat count is checked when booking.
        ride._block = policies.booking_block(
            ride, viewer, 1, seats_left=ride._seats_left, my_booking_id=ride._my_booking_id
        )
    return rides


def can_view(ride, viewer) -> bool:
    """Listed rides are public. An unlisted one (driver not approved, revoked or deactivated)
    stays visible to its driver and to passengers who already booked it."""
    if ride.is_listed:
        return True
    if viewer is None or not viewer.is_authenticated:
        return False
    return ride.driver_id == viewer.pk or bool(getattr(ride, "_my_booking_id", None))


def load(pk, viewer=None) -> Optional[Ride]:
    ride = Ride.objects.for_display().active().filter(pk=pk).first()
    if ride is None:
        return None
    prepare([ride], viewer)
    return ride if can_view(ride, viewer) else None
