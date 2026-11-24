"""Check that every publisher's balances match their ledger. Run daily (cron / Task Scheduler);
exits with status 1 and lists the accounts when anything doesn't add up."""
from django.core.management.base import BaseCommand, CommandError

from apps.payments.ledger import reconcile
from apps.payments.models import EarningsAccount


class Command(BaseCommand):
    help = "Verify publisher earnings balances against the immutable ledger."

    def handle(self, *args, **options):
        bad = 0
        checked = 0
        for account in EarningsAccount.objects.select_related("user").iterator():
            checked += 1
            problems = reconcile(account)
            if problems:
                bad += 1
                self.stderr.write(f"{account.user} ({account.user_id}):")
                for p in problems:
                    self.stderr.write(f"  - {p}")
        if bad:
            raise CommandError(f"{bad} of {checked} earnings accounts don't reconcile.")
        self.stdout.write(self.style.SUCCESS(f"All {checked} earnings accounts reconcile."))
