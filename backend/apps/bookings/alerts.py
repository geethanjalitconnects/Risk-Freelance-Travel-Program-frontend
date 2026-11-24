"""Text a passenger's trusted contacts when they share a trip, raise an SOS or miss a check-in.

Messages go through the same pluggable SMS backend as sign-in codes, so with DEBUG on they are
printed to the console. They are sent only after the database transaction commits, and a failed
SMS never undoes the SOS or check-in itself.
"""
import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import normalize_phone
from apps.accounts.sms import send_sms

logger = logging.getLogger(__name__)


def recipients(user) -> list:
    """Trusted contacts with a number an SMS can reach."""
    out = []
    for c in user.contacts.all():
        try:
            out.append((c.name, normalize_phone(c.phone)))
        except ValidationError:
            logger.warning("Skipping trusted contact %s: phone can't receive SMS", c.pk)
    return out


def share_url(booking) -> str:
    return f"{settings.TRIP_SHARE_BASE_URL.rstrip('/')}/{booking.share_token}" if booking.share_token else ""


def _trip_line(booking) -> str:
    ride = booking.ride
    when = timezone.localtime(ride.depart).strftime("%d %b, %H:%M")
    driver = ride.driver.name or "their driver"
    return f"{ride.origin.name} to {ride.destination.name} ({when}) with {driver}, {ride.vehicle_model}"


def message_for(kind: str, booking, label: str = "") -> str:
    name = booking.passenger.name or "A VConnects traveller"
    trip = _trip_line(booking)
    link = share_url(booking)
    link_text = f" Live trip: {link}" if link else ""
    if kind == "share":
        return f"{name} shared their VConnects trip with you: {trip}.{link_text}"
    if kind == "sos":
        return f"SOS from {name} on a VConnects trip: {trip}. Call them now. If you can't reach them, call 112.{link_text}"
    if kind == "missed":
        return f"{name} missed a safety check-in ({label}) on their VConnects trip: {trip}. Please check on them.{link_text}"
    raise ValueError(kind)


def notify_contacts(booking, kind: str, label: str = "") -> int:
    """Queue the alert for after commit. Returns how many contacts will be texted."""
    to = recipients(booking.passenger)
    if not to:
        return 0
    message = message_for(kind, booking, label)

    def send():
        for _name, phone in to:
            try:
                send_sms(phone, message)
            except Exception:  # noqa: BLE001 - one failed contact must not stop the others
                logger.exception("Trip alert (%s) for booking %s failed", kind, booking.pk)

    transaction.on_commit(send)
    return len(to)
