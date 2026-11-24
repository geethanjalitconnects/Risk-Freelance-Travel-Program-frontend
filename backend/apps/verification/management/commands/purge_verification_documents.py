from django.conf import settings
from django.core.management.base import BaseCommand

from apps.verification.services import purge_expired


class Command(BaseCommand):
    help = (
        "Delete documents of rejected / revoked verifications and of deactivated accounts after "
        "DOCUMENT_RETENTION_DAYS. Run daily (cron / scheduled task)."
    )

    def handle(self, *args, **opts):
        result = purge_expired()
        self.stdout.write(
            f"Deleted {result['documents']} documents from {result['verifications']} verifications "
            f"(retention {settings.DOCUMENT_RETENTION_DAYS} days)."
        )
