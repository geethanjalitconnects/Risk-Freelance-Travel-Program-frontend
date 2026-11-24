"""What a driver may see about a passenger.

Name: only once the booking is paid and confirmed (confirmed / in_progress / completed).
Phone: the same, and only until PASSENGER_CONTACT_HOURS after the ride's arrival time
(proposed default 6 h, pending client approval). Cancelled / expired / unpaid: nothing.
"""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

KNOWN = ("confirmed", "in_progress", "completed")
CALLABLE = ("confirmed", "in_progress", "completed")


def identity_visible(booking) -> bool:
    return booking.status in KNOWN


def contact_visible(booking, ride, now=None) -> bool:
    if booking.status not in CALLABLE:
        return False
    now = now or timezone.now()
    hours = getattr(settings, "PASSENGER_CONTACT_HOURS", 6)
    return now <= ride.arrive + timedelta(hours=hours)
