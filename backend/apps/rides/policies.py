"""Business rules for rides, kept in one place so the API, the admin and later the booking
endpoints (step 6) all apply the same checks."""
from dataclasses import dataclass
from typing import Optional

from django.db.models import Q
from django.utils import timezone

from apps.bookings.models import Booking, BookingStatus

from .models import REQUIRED_GENDER, Ride, RideStatus, TravelWith

MAX_SEATS_PER_BOOKING = 4

GENDER_WORD = {"F": "female", "M": "male"}


def driver_travel_with_error(travel_with: str, driver_gender: str) -> Optional[str]:
    """Only female drivers can offer women-only rides, only male drivers men-only rides."""
    required = REQUIRED_GENDER.get(travel_with)
    if required and driver_gender != required:
        label = TravelWith(travel_with).label.lower()
        return f"Only {GENDER_WORD[required]} drivers can offer {label} rides. Set your gender in your profile, or choose Anyone."
    return None


def passenger_gender_error(travel_with: str, passenger_gender: str) -> Optional[str]:
    required = REQUIRED_GENDER.get(travel_with)
    if not required or passenger_gender == required:
        return None
    label = TravelWith(travel_with).label.lower()
    if not passenger_gender:
        return f"This ride is {label}. Set your gender in your profile to book it."
    return f"This ride is {label}."


@dataclass
class BookingBlock:
    code: str
    message: str


def booking_block(ride: Ride, user, seats: int, *, seats_left: int, my_booking_id=None) -> Optional[BookingBlock]:
    """Why ``user`` can't book ``seats`` on ``ride`` right now, or None if they can."""
    if user is None or not user.is_authenticated:
        return BookingBlock("auth", "Sign in to book a seat.")
    if ride.driver_id == user.pk:
        return BookingBlock("own_ride", "This is a ride you published.")
    if not ride.is_listed:
        # Removed, or the driver is no longer approved / active.
        return BookingBlock("unavailable", "This ride is no longer available.")
    if ride.has_departed:
        return BookingBlock("departed", "This ride has already left.")
    if my_booking_id:
        return BookingBlock("already_booked", "You have booked this ride.")
    if seats_left <= 0:
        return BookingBlock("full", "This ride is full.")
    if not 1 <= seats <= min(MAX_SEATS_PER_BOOKING, seats_left):
        return BookingBlock("seats", f"You can book 1 to {min(MAX_SEATS_PER_BOOKING, seats_left)} seats on this ride.")
    msg = passenger_gender_error(ride.travel_with, user.gender)
    if msg:
        return BookingBlock("travel_with", msg)
    return None


# ---- gender lock ----


def gender_lock_reason(user) -> Optional[str]:
    """Why ``user`` can't change their gender right now, or None.

    Locked while the user (a) has an active booking on a women-only / men-only ride, or
    (b) has published a women-only / men-only ride that is still active. "Active" means the trip
    is in progress, or it is still upcoming (it hasn't reached its arrival time).
    Enforced by the profile endpoint (step 4).
    """
    now = timezone.now()
    as_passenger = Booking.objects.filter(
        Q(status=BookingStatus.IN_PROGRESS) | Q(status=BookingStatus.CONFIRMED, ride__arrive__gt=now),
        passenger=user,
        ride__status=RideStatus.ACTIVE,
    ).exclude(ride__travel_with=TravelWith.ANYONE)
    if as_passenger.exists():
        return "You can't change your gender while you have a booking on a women-only or men-only ride."

    as_driver = (
        Ride.objects.filter(driver=user, status=RideStatus.ACTIVE)
        .exclude(travel_with=TravelWith.ANYONE)
        .filter(Q(arrive__gt=now) | Q(bookings__status=BookingStatus.IN_PROGRESS))
    )
    if as_driver.exists():
        return "You can't change your gender while you have a women-only or men-only ride published."
    return None


# ---- editing ----

# Fields passengers relied on when booking. Once a ride has bookings these are frozen.
LOCKED_WHEN_BOOKED = {
    "from": "The route can't change once passengers have booked.",
    "to": "The route can't change once passengers have booked.",
    "depart": "The departure time can't change once passengers have booked.",
    "price": "The price can't change once passengers have booked.",
    "travel_with": "Who can travel with you can't change once the ride has bookings.",
    "vehicle": "The vehicle can't change once passengers have booked.",
}
