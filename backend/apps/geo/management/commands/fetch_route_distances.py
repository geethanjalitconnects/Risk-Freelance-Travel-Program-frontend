from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.geo.models import City, DistanceSource, RouteProfile
from apps.geo.ors import ORSError, distance_matrix_km
from common.jsmath import js_round


class Command(BaseCommand):
    help = (
        "Fetch road distances for every city pair from OpenRouteService once and store them in the "
        "route profiles. If ORS is unavailable, the current estimates are kept. Routes an admin "
        "edited by hand are left alone unless --include-manual is given."
    )

    def add_arguments(self, parser):
        parser.add_argument("--include-manual", action="store_true", help="Also overwrite distances set by an admin.")

    def handle(self, *args, **opts):
        cities = list(City.objects.filter(is_active=True).order_by("code"))
        try:
            matrix = distance_matrix_km(cities)
        except ORSError as e:
            self.stderr.write(self.style.WARNING(f"{e} Keeping the current distances (estimates are used as the fallback)."))
            return

        updated = skipped = missing = 0
        now = timezone.now()
        with transaction.atomic():
            for route in RouteProfile.objects.select_related("city_a", "city_b"):
                if route.km_source == DistanceSource.MANUAL and not opts["include_manual"]:
                    skipped += 1
                    continue
                legs = [matrix.get((route.city_a_id, route.city_b_id)), matrix.get((route.city_b_id, route.city_a_id))]
                legs = [d for d in legs if d]
                if not legs:
                    missing += 1
                    continue
                route.km = max(1, js_round(sum(legs) / len(legs)))  # average of both directions
                route.km_source = DistanceSource.ORS
                route.km_updated_at = now
                route.save(update_fields=["km", "km_source", "km_updated_at", "updated_at"])
                updated += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Updated {updated} route distances from OpenRouteService; {skipped} manual kept, "
                f"{missing} without a road route (estimate kept)."
            )
        )
