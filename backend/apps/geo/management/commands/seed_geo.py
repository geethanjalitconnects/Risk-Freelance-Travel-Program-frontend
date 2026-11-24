from django.core.management.base import BaseCommand

from apps.geo.seed import seed_geo


class Command(BaseCommand):
    help = "Load the cities, meeting points and route risk profiles used by the frontend."

    def add_arguments(self, parser):
        parser.add_argument(
            "--overwrite-routes",
            action="store_true",
            help="Reset every route profile to the demo values (discards edits made in the admin).",
        )

    def handle(self, *args, **opts):
        result = seed_geo(overwrite_routes=opts["overwrite_routes"])
        self.stdout.write(
            self.style.SUCCESS(f"Seeded {result['cities']} cities; {result['routes_created']} new route profiles.")
        )
