"""Telling passengers that an admin cancelled their ride.

The trip-log entry is written by the caller in the same transaction. Extra channels (SMS once the
provider and templates are approved, push, email) plug in through RIDE_CANCELLED_NOTIFIERS:
dotted paths to callables ``notifier(bookings, reason)``. They run after the database commit and
a failing notifier never undoes the cancellation.

Example, later:  RIDE_CANCELLED_NOTIFIERS=apps.bookings.notifications.sms_ride_cancelled
"""
import logging

from django.conf import settings
from django.db import transaction
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


def ride_cancelled(bookings: list, reason: str) -> None:
    paths = list(settings.RIDE_CANCELLED_NOTIFIERS)
    if not paths or not bookings:
        return

    def run():
        for path in paths:
            try:
                import_string(path)(bookings, reason)
            except Exception:  # noqa: BLE001
                logger.exception("Ride-cancelled notifier %s failed", path)

    transaction.on_commit(run)


def sms_ride_cancelled(bookings: list, reason: str) -> None:  # pragma: no cover - enable once templates are approved
    """Ready-made SMS notifier using the configured SMS_BACKEND. Not enabled by default."""
    from django.utils import timezone

    from apps.accounts.sms import send_sms

    for b in bookings:
        ride = b.ride
        when = timezone.localtime(ride.depart).strftime("%d %b, %H:%M")
        send_sms(
            b.passenger.phone,
            f"VConnects: your ride {ride.origin.name} to {ride.destination.name} on {when} has been cancelled. "
            f"Your booking is cancelled and no payment is due.",
        )
