"""Complete bookings automatically ``auto_complete_hours`` after the ride's scheduled arrival, when
nobody reported a problem. Run every 15 minutes (cron / Windows Task Scheduler)."""
import logging

from django.core.management.base import BaseCommand

from apps.bookings.completion import auto_complete, due_for_auto_complete

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Auto-complete rides 24 h after arrival when no problem was reported."

    def handle(self, *args, **options):
        done = failed = 0
        for pk in list(due_for_auto_complete()):
            try:
                done += bool(auto_complete(pk))
            except Exception:  # one bad booking must not stop the rest
                failed += 1
                logger.exception("Auto-complete failed for booking %s", pk)
        self.stdout.write(f"Auto-completed {done} booking(s); {failed} failed.")
