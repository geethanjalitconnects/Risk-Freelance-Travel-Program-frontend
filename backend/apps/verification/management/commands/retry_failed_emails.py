from django.core.management.base import BaseCommand

from apps.verification import emails


class Command(BaseCommand):
    help = "Retry verification emails that failed to send. Schedule every 5 minutes."

    def handle(self, *args, **options):
        result = emails.retry_due()
        self.stdout.write(f"Sent {result['sent']}, failed again {result['failed']}, waiting to retry {result['waiting']}.")
