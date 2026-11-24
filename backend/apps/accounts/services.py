"""Account administration: deactivate / reactivate.

Deactivating a user:
* blocks sign-in (JWT checks is_active; outstanding refresh tokens are also blacklisted);
* hides their rides from search automatically (RideQuerySet.listed requires an active driver),
  while rides that already have bookings stay available to those passengers;
* cancels their upcoming bookings as a passenger, freeing the seats.
A deactivated driver's booked rides are not cancelled here; an admin can cancel them from Rides.
"""
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from apps.bookings.models import Booking, BookingStatus, EventType, TripEvent


class AccountActionError(Exception):
    pass


@transaction.atomic
def deactivate(user, admin) -> int:
    """Returns how many upcoming bookings were cancelled."""
    if user.pk == admin.pk:
        raise AccountActionError("You can't deactivate your own account.")
    if user.is_superuser and not admin.is_superuser:
        raise AccountActionError("Only a superuser can deactivate a superuser.")
    user = type(user).objects.select_for_update().get(pk=user.pk)
    if user.is_active:
        user.is_active = False
        user.deactivated_at = timezone.now()
        user.save(update_fields=["is_active", "deactivated_at"])

    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)

    now = timezone.now()
    upcoming = list(
        Booking.objects.select_for_update().filter(passenger=user, status=BookingStatus.CONFIRMED, ride__depart__gt=now)
    )
    from apps.bookings.cancellation import cancel_by_vconnects

    for b in upcoming:
        cancel_by_vconnects(b, actor=admin, reason="Account deactivated", now=now)  # full refund, no penalty
        TripEvent.objects.create(booking=b, type=EventType.CANCELLED, text="Booking cancelled: the account was deactivated.")
    return len(upcoming)


@transaction.atomic
def reactivate(user) -> None:
    user = type(user).objects.select_for_update().get(pk=user.pk)
    user.is_active = True
    user.deactivated_at = None
    user.save(update_fields=["is_active", "deactivated_at"])
