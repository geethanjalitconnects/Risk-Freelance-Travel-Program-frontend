"""Writing the financial audit log."""
from .models import FinancialAuditLog


def _ip(request):
    if request is None:
        return None
    return request.META.get("REMOTE_ADDR") or None


def record(action, *, actor=None, label=None, user=None, booking=None, amount=None, reference="", request=None, **details):
    """Append one audit row. ``actor`` is the user who acted (None for the system or Razorpay; pass
    ``label`` then). Never put account numbers, UPI ids or secrets in ``details``."""
    return FinancialAuditLog.objects.create(
        actor=actor,
        actor_label=label or (str(actor) if actor else "system"),
        action=action,
        user=user,
        booking=booking,
        amount_paise=amount,
        reference=reference[:80],
        details=details,
        ip_address=_ip(request),
    )
