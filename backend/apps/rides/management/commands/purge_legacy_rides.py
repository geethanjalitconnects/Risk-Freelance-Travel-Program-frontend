"""ONE-OFF, IRREVERSIBLE: delete every ride (and its bookings, payments, refunds, transfers,
withdrawals and earnings-ledger rows) plus the old 14 hardcoded cities, so the database can move
to areas picked from Google Places.

Approved by the product owner for the development database. Run BEFORE `migrate` when upgrading
a database that still has the old cities:

    python manage.py purge_legacy_rides            # shows what would be deleted
    python manage.py purge_legacy_rides --yes      # deletes it

Raw SQL is used on purpose: the ledger and audit models refuse deletes through the ORM.
Users, payout details, payment settings, fare settings and webhook logs are kept. Earnings
balances are reset to zero because their ledger rows are deleted.
"""
from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection, transaction

# Children first, so foreign keys are never left dangling.
ORDER = [
    ("payments", "Transfer", None),
    ("payments", "Refund", None),
    ("payments", "EarningEntry", None),
    ("payments", "FinancialAuditLog", "booking_id IS NOT NULL"),
    ("payments", "Withdrawal", None),
    ("payments", "Payment", None),
    ("bookings", "CompletionConfirmation", None),
    ("bookings", "ProblemReport", None),
    ("bookings", "Cancellation", None),
    ("bookings", "CheckIn", None),
    ("bookings", "TripEvent", None),
    ("bookings", "Booking", None),
    ("rides", "Ride", None),
    ("places", "PlaceCache", None),
    ("geo", "MeetingPoint", None),
    ("geo", "RouteProfile", None),
    ("geo", "City", None),
]


class Command(BaseCommand):
    help = "IRREVERSIBLE: delete all rides, bookings, payments and the old hardcoded cities."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Actually delete (otherwise only counts).")

    def handle(self, *args, yes, **opts):
        existing = set(connection.introspection.table_names())
        plan = []
        with connection.cursor() as cur:
            for app, model, where in ORDER:
                table = apps.get_model(app, model)._meta.db_table
                if table not in existing:
                    continue
                clause = f" WHERE {where}" if where else ""
                cur.execute(f'SELECT COUNT(*) FROM "{table}"{clause}')
                plan.append((table, clause, cur.fetchone()[0]))
        for table, clause, n in plan:
            self.stdout.write(f"  {table}{clause}: {n} row(s)")
        if not yes:
            self.stdout.write(self.style.WARNING("Nothing deleted. Re-run with --yes to delete the rows above."))
            return

        accounts = apps.get_model("payments", "EarningsAccount")._meta.db_table
        with transaction.atomic(), connection.cursor() as cur:
            for table, clause, _ in plan:
                cur.execute(f'DELETE FROM "{table}"{clause}')
            if accounts in existing:
                cur.execute(f'UPDATE "{accounts}" SET held_paise = 0, available_paise = 0, owed_paise = 0')
        self.stdout.write(self.style.SUCCESS("Deleted. Now run: python manage.py migrate"))
