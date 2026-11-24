"""Send refunds that Razorpay hasn't accepted yet (network errors, outages). Run every 5 minutes.
Refunds Razorpay rejected outright stay "failed" for an admin to look at."""
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.payments import refunds
from apps.payments.models import Refund, RefundStatus


class Command(BaseCommand):
    help = "Retry pending refunds."

    def handle(self, *args, **options):
        due = Refund.objects.filter(status=RefundStatus.PENDING, razorpay_refund_id__isnull=True,
                                    attempts__lt=settings.REFUND_MAX_ATTEMPTS)
        sent = sum(1 for pk in list(due.values_list("pk", flat=True)) if refunds.send(pk).razorpay_refund_id)
        self.stdout.write(f"{sent} refund(s) accepted by Razorpay.")
