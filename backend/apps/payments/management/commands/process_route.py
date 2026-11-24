"""Route housekeeping (no-op while ROUTE_ENABLED is off): send queued transfers whose linked
account is ready, and retry releases for withdrawals still pending. Run every 5 minutes."""
from django.core.management.base import BaseCommand

from apps.payments import route
from apps.payments.models import Transfer, TransferStatus, Withdrawal, WithdrawalStatus


class Command(BaseCommand):
    help = "Send queued Route transfers and pending releases."

    def handle(self, *args, **options):
        if not route.enabled():
            self.stdout.write("Route is disabled (ROUTE_ENABLED=False); nothing to do.")
            return
        for pk in list(Transfer.objects.filter(status=TransferStatus.QUEUED).values_list("pk", flat=True)):
            route.send_transfer(pk)
        for pk in list(Withdrawal.objects.filter(status=WithdrawalStatus.PENDING).values_list("pk", flat=True)):
            route.release_for_withdrawal(pk)
        self.stdout.write("Route queue processed.")
