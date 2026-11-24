"""Keep cached Google coordinates within the 30-day limit. Run daily (cron / Task Scheduler).

- Places used by upcoming active rides are re-fetched from Google once their row is older than
  PLACES_COORDINATE_DAYS - 3 days (Place Details, Essentials fields: a few billed calls a day).
- Every other row older than PLACES_COORDINATE_DAYS is deleted.
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.places import google, resolve
from apps.places.models import PlaceCache


class Command(BaseCommand):
    help = "Refresh coordinates used by upcoming rides and delete coordinates older than the limit."

    def handle(self, *args, **opts):
        from apps.rides.models import Ride

        now = timezone.now()
        limit = now - timedelta(days=settings.PLACES_COORDINATE_DAYS)
        refresh_before = limit + timedelta(days=3)
        in_use = set()
        for a, b in Ride.objects.active().filter(depart__gt=now).values_list("origin_place_id", "destination_place_id"):
            in_use.update(p for p in (a, b) if p)

        refreshed = failed = 0
        for place_id in PlaceCache.objects.filter(place_id__in=in_use, fetched_at__lt=refresh_before).values_list("place_id", flat=True):
            try:
                resolve.resolve(place_id, refresh=True)
                refreshed += 1
            except (google.PlacesError, resolve.NotInIndia, resolve.UnknownPlace):
                failed += 1

        deleted, _ = PlaceCache.objects.filter(fetched_at__lt=limit).delete()
        self.stdout.write(f"Refreshed {refreshed}, failed {failed}, deleted {deleted} expired cached place(s).")
