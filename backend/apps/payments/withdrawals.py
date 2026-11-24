"""Publisher withdrawals (Phase 7: request + ledger; Phase 8 sends them to the payout provider).

A withdrawal takes the whole available balance. It is refused unless every rule passes (payout
details saved and not failed, not frozen, nothing owed, at least the minimum, under the daily
limit, no other withdrawal in flight). The ledger is debited in the same transaction, so the same
money can never be requested twice. Each swipe sends an idempotency key: repeating it returns the
withdrawal already created instead of a second one.

Requests are switched off (``PAYOUTS_ENABLED=False``) until Razorpay confirms the payout flow.
"""
import re

from django.conf import settings
from django.db import transaction

from . import audit, ledger
from .models import FinancialAction, PayoutAccount, PayoutAccountStatus, Withdrawal, WithdrawalStatus

KEY_RE = re.compile(r"^[A-Za-z0-9-]{16,64}$")


class WithdrawalError(Exception):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def payouts_enabled() -> bool:
    """Withdrawals need both switches: PAYOUTS_ENABLED and Route itself (ROUTE_ENABLED + keys)."""
    from . import route

    return bool(getattr(settings, "PAYOUTS_ENABLED", False)) and route.enabled()


def block_for(user, account=None):
    """Why ``user`` can't withdraw now, as (code, message), or None. Checked again on request."""
    if not payouts_enabled():
        return ("payouts_unavailable", "Withdrawals open once our payout partner is connected. Your earnings are safe.")
    pa = PayoutAccount.objects.filter(user=user).first()
    if pa is None:
        return ("no_payout_account", "Add your bank account or UPI id to withdraw.")
    if pa.status == PayoutAccountStatus.FAILED:
        return ("payout_account_failed", "We couldn't verify your payout details. Update them to withdraw.")
    if Withdrawal.objects.filter(user=user, status__in=[WithdrawalStatus.PENDING, WithdrawalStatus.PROCESSING]).exists():
        return ("in_progress", "A withdrawal is already on its way.")
    return ledger.withdrawal_block(user, account)


@transaction.atomic
def request_withdrawal(user, key: str, request=None):
    """Create a withdrawal of the whole available balance. Returns ``(withdrawal, created)``."""
    if not KEY_RE.match(key or ""):
        raise WithdrawalError("bad_key", "Missing or invalid Idempotency-Key header.", status=400)
    full_key = f"user:{user.pk}:{key}"
    existing = Withdrawal.objects.filter(idempotency_key=full_key).first()
    if existing is not None:
        return existing, False

    account = ledger.account_for(user, lock=True)  # serialises withdrawals per publisher
    block = block_for(user, account)
    if block:
        raise WithdrawalError(block[0], block[1], status=503 if block[0] == "payouts_unavailable" else 409)

    from . import route

    pa = PayoutAccount.objects.get(user=user)
    if pa.status != PayoutAccountStatus.VERIFIED:
        raise WithdrawalError("payout_account_pending", "Your payout details are still being verified.")
    # Only money Razorpay actually holds for this publisher can be released.
    backing = sum(t.releasable_paise for t in route.eligible_transfers(user))
    amount = min(account.available_paise, backing)
    if amount <= 0:
        raise WithdrawalError("nothing_to_release", "Nothing is ready to withdraw yet.")
    w = Withdrawal.objects.create(
        user=user, amount_paise=amount, method=pa.method, destination=pa.display, idempotency_key=full_key,
    )
    ledger.debit_withdrawal(w)
    audit.record(
        FinancialAction.WITHDRAWAL_UPDATED, actor=user, user=user, amount=w.amount_paise, reference=str(w.pk),
        request=request, status=w.status, destination=w.destination,
    )
    transaction.on_commit(lambda: route.release_for_withdrawal(w.pk))
    return w, True
