from axes.helpers import get_client_ip_address

from .models import AdminAuditLog


def actor_label(user) -> str:
    return (user.username or user.phone or str(user.pk)) if user else ""


def record(request, action, *, actor=None, target_user=None, label=None, **details) -> AdminAuditLog:
    """Write one audit row. Call it inside the same transaction as the change it describes."""
    if actor is None:
        actor = getattr(request, "user", None)
    if actor is not None and not getattr(actor, "is_authenticated", False):
        actor = None
    django_request = getattr(request, "_request", request)
    return AdminAuditLog.objects.create(
        actor=actor,
        actor_label=label if label is not None else actor_label(actor),
        action=action,
        target_user=target_user,
        details=details,
        ip_address=get_client_ip_address(django_request) if django_request is not None else None,
    )
