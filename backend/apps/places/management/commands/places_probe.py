"""Try real queries against Google to tune includedPrimaryTypes (costs a few billed requests).

    python manage.py places_probe Tambaram Avadi Madurantakam --types "(regions)"
    python manage.py places_probe Tambaram --types locality,sublocality,administrative_area_level_3 --details

Prints suggestions (and, with --details, the address components and area of the first one).
Never prints the API key.
"""
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test import override_settings

from apps.places import google, resolve


class Command(BaseCommand):
    help = "Query Google Places autocomplete with real inputs (billed) to compare type filters."

    def add_arguments(self, parser):
        parser.add_argument("queries", nargs="+")
        parser.add_argument("--types", default=None, help='Comma list, "(regions)", "(cities)" or "" for none')
        parser.add_argument("--details", action="store_true", help="Also fetch details of the first suggestion")

    def handle(self, *args, queries, types, details, **opts):
        if not google.configured():
            raise CommandError("GOOGLE_MAPS_API_KEY is not set.")
        primary = settings.PLACES_PRIMARY_TYPES if types is None else [t.strip() for t in types.split(",") if t.strip()]
        with override_settings(PLACES_PRIMARY_TYPES=primary):
            self.stdout.write(f"includedPrimaryTypes = {primary or '(none)'}")
            for q in queries:
                session = str(uuid.uuid4())
                try:
                    rows = google.autocomplete(q, session)
                except google.PlacesError as e:
                    self.stdout.write(self.style.ERROR(f"{q}: {e}"))
                    continue
                self.stdout.write(self.style.MIGRATE_HEADING(f"\n{q}: {len(rows)} suggestion(s)"))
                for r in rows:
                    self.stdout.write(f"  {r['main']}  |  {r['secondary']}")
                if details and rows:
                    try:
                        res = google.details(rows[0]["placeId"], session)
                    except google.PlacesError as e:
                        self.stdout.write(self.style.ERROR(f"  details: {e}"))
                        continue
                    for c in res.get("addressComponents", []):
                        self.stdout.write(f"    {','.join(c.get('types', []))}: {c.get('longText')}")
                    try:
                        name, district, state = resolve.area_parts(res.get("addressComponents") or [])
                        self.stdout.write(f"  -> area: {name} | district: {district or '-'} | state: {state}")
                    except resolve.NotInIndia:
                        self.stdout.write("  -> not in India")
                    except resolve.UnknownPlace:
                        self.stdout.write("  -> no usable area in the address")
