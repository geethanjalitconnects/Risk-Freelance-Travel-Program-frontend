"""Emails about verification decisions (approved / rejected / re-upload requested).

* ``queue()`` is called by the review services inside the decision's transaction, only when the
  status actually changed, so repeated clicks never send a second email.
* The email is sent after the transaction commits. If sending fails, the decision stays; the
  row is marked FAILED with the error, logged, and retried by ``retry_due()``
  (``manage.py retry_failed_emails``) or from the admin review page.
* Templates: templates/emails/verification/<kind>_subject.txt, <kind>.txt and <kind>.html.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone

from .models import EmailKind, EmailNotification, EmailStatus

logger = logging.getLogger(__name__)

# Where each email's button takes the driver in the React app.
LINKS = {
    EmailKind.APPROVED: "/#/publish",
    EmailKind.REJECTED: "/#/verification",
    EmailKind.RESUBMIT_REQUESTED: "/#/verification",
}


def queue(verification, kind, reason="") -> EmailNotification:
    """Record the email and send it once the surrounding transaction commits."""
    to = (verification.user.email or "").strip()
    n = EmailNotification.objects.create(
        verification=verification,
        kind=kind,
        to_email=to,
        reason=reason or "",
        status=EmailStatus.QUEUED if to else EmailStatus.NO_ADDRESS,
    )
    if to:
        transaction.on_commit(lambda: deliver(n.pk))
    else:
        logger.warning("No email address for user %s; %s email not sent.", verification.user_id, kind)
    return n


def render(n: EmailNotification) -> tuple:
    """(subject, text body, html body) for a notification."""
    user = n.verification.user
    context = {
        "name": user.first_name or user.name or "there",
        "reason": n.reason,
        "link": settings.APP_URL + LINKS[n.kind],
        "app_url": settings.APP_URL,
    }
    base = f"emails/verification/{n.kind}"
    subject = " ".join(render_to_string(f"{base}_subject.txt", context).split())
    return subject, render_to_string(f"{base}.txt", context), render_to_string(f"{base}.html", context)


def deliver(notification_id) -> bool:
    """Try to send one email. Never raises: a failure is stored on the row and logged."""
    with transaction.atomic():
        n = (
            EmailNotification.objects.select_for_update()
            .select_related("verification__user")
            .filter(pk=notification_id)
            .first()
        )
        if n is None or n.status in (EmailStatus.SENT, EmailStatus.NO_ADDRESS):
            return False
        n.attempts += 1
        n.last_attempt_at = timezone.now()
        try:
            subject, text, html = render(n)
            message = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [n.to_email])
            message.attach_alternative(html, "text/html")
            message.send(fail_silently=False)
        except Exception as e:  # noqa: BLE001 - any mail error must not escape
            n.status = EmailStatus.FAILED
            n.last_error = f"{type(e).__name__}: {e}"[:500]
            n.save(update_fields=["status", "attempts", "last_attempt_at", "last_error"])
            logger.exception("Sending %s email %s failed (attempt %s).", n.kind, n.pk, n.attempts)
            return False
        n.status = EmailStatus.SENT
        n.sent_at = timezone.now()
        n.last_error = ""
        n.save(update_fields=["status", "attempts", "last_attempt_at", "sent_at", "last_error"])
        return True


def retry_due(now=None) -> dict:
    """Retry failed (and stuck queued) emails with a growing wait: 1, 4, 9, 16... minutes after the
    last attempt, up to EMAIL_MAX_ATTEMPTS attempts in total."""
    now = now or timezone.now()
    candidates = EmailNotification.objects.filter(
        Q(status=EmailStatus.FAILED) | Q(status=EmailStatus.QUEUED, created_at__lt=now - timedelta(minutes=5)),
        attempts__lt=settings.EMAIL_MAX_ATTEMPTS,
    )
    sent = failed = waiting = 0
    for n in candidates:
        if n.last_attempt_at and n.last_attempt_at > now - timedelta(minutes=max(1, n.attempts) ** 2):
            waiting += 1
            continue
        if deliver(n.pk):
            sent += 1
        else:
            failed += 1
    return {"sent": sent, "failed": failed, "waiting": waiting}
