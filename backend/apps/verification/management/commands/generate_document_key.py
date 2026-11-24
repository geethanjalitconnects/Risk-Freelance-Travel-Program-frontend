from django.core.management.base import BaseCommand

from apps.verification.crypto import generate_key


class Command(BaseCommand):
    help = "Print a new encryption key for DOCUMENT_ENCRYPTION_KEYS. Store it in a secrets manager or .env."

    def handle(self, *args, **opts):
        self.stdout.write(generate_key())
