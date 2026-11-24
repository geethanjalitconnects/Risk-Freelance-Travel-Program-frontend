"""Release seats held by unpaid bookings whose hold ran out. Run every minute."""
from django.core.management.base import BaseCommand

from apps.payments.checkout import expire_holds


class Command(BaseCommand):
    help = "Expire unpaid booking holds."

    def handle(self, *args, **options):
        self.stdout.write(f"Expired {expire_holds()} unpaid booking(s).")
