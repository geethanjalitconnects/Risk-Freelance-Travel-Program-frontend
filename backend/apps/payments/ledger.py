"""The publisher earnings ledger. Every balance change goes through ``post``:

- it locks the publisher's EarningsAccount row (``select_for_update``), so concurrent changes queue up;
- it is idempotent: each change carries a unique key, and posting the same key again returns the
  entry already written instead of changing the balance twice;
- it refuses any change that would make a balance negative;
- it writes one immutable EarningEntry with the balances after the change.

The domain helpers below (hold, release, reverse, penalty, withdrawal) build their keys from the
booking or withdrawal id, so calling them twice for the same event is always safe.
"""
from django.db import IntegrityError, transaction
from django.utils import timezone

from . import audit, money
from .models import (
    EarningEntry,
    EarningsAccount,
    EntryKind,
    FinancialAction,
    PaymentSettings,
    Withdrawal,
    WithdrawalStatus,
)


class LedgerError(Exception):
    def __init__(self, message, code="ledger_error"):
        super().__init__(message)
        self.message, self.code = message, code


class InsufficientBalance(LedgerError):
    def __init__(self, message):
        super().__init__(message, "insufficient_balance")


class IdempotencyConflict(LedgerError):
    def __init__(self, key):
        super().__init__(f"Ledger key {key!r} was already used for a different change.", "idempotency_conflict")


def account_for(user, *, lock=False) -> EarningsAccount:
    account, _ = EarningsAccount.objects.get_or_create(user=user)
    if lock:
        account = EarningsAccount.objects.select_for_update().get(pk=account.pk)
    return account


@transaction.atomic
def post(user, kind, *, key, description, held=0, available=0, owed=0, booking=None, withdrawal=None, actor=None):
    """Apply one change to ``user``'s balances. Returns ``(entry, created)``."""
    for name, value in (("held", held), ("available", available), ("owed", owed)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise LedgerError(f"{name} must be an integer number of paise.")
    if not (held or available or owed):
        raise LedgerError("A ledger entry must change at least one balance.")

    account = account_for(user, lock=True)
    existing = EarningEntry.objects.filter(idempotency_key=key).first()
    if existing is not None:
        if existing.account_id != account.pk or existing.kind != kind:
            raise IdempotencyConflict(key)
        return existing, False

    new = {
        "held": account.held_paise + held,
        "available": account.available_paise + available,
        "owed": account.owed_paise + owed,
    }
    negative = [name for name, value in new.items() if value < 0]
    if negative:
        raise InsufficientBalance(f"Not enough {negative[0]} balance for this change.")

    try:
        with transaction.atomic():
            entry = EarningEntry.objects.create(
                account=account, kind=kind, held_delta=held, available_delta=available, owed_delta=owed,
                held_after=new["held"], available_after=new["available"], owed_after=new["owed"],
                booking=booking, withdrawal=withdrawal, idempotency_key=key, description=description[:300],
                created_by=actor,
            )
    except IntegrityError:  # the same key written concurrently for another account
        raise IdempotencyConflict(key)

    account.held_paise, account.available_paise, account.owed_paise = new["held"], new["available"], new["owed"]
    account.save(update_fields=["held_paise", "available_paise", "owed_paise", "updated_at"])
    return entry, True


# ---------------------------------------------------------------- booking events


def _earning(booking) -> int:
    if booking.publisher_earning_paise is None:
        raise LedgerError("This booking has no payment amounts.", "no_amounts")
    return booking.publisher_earning_paise


def hold_earning(booking):
    """The passenger's payment is verified: the publisher's share is held until the ride is verified."""
    return post(
        booking.ride.driver, EntryKind.EARNING_HELD, key=f"booking:{booking.pk}:held", booking=booking,
        held=_earning(booking), description=f"Booking {booking.pk} paid: earning held until the ride is complete.",
    )


def release_earning(booking):
    """The ride is verified complete: held -> available, paying off anything owed first."""
    amount = _earning(booking)
    user = booking.ride.driver
    with transaction.atomic():
        account = account_for(user, lock=True)
        rec = money.recover_owed(account.owed_paise, amount)
        text = f"Booking {booking.pk} complete: earning released."
        if rec.recovered:
            text += f" {money.format_inr(rec.recovered)} used to pay off penalties."
        return post(
            user, EntryKind.EARNING_RELEASED, key=f"booking:{booking.pk}:released", booking=booking,
            held=-amount, available=rec.remaining, owed=-rec.recovered, description=text,
        )


def reverse_earning(booking):
    """The booking was cancelled or refunded before completion: the held earning is removed."""
    return post(
        booking.ride.driver, EntryKind.EARNING_REVERSED, key=f"booking:{booking.pk}:reversed", booking=booking,
        held=-_earning(booking), description=f"Booking {booking.pk} cancelled: held earning removed.",
    )


def charge_penalty(booking, amount: int):
    """A publisher penalty: taken from available earnings first, the rest recorded as owed."""
    if amount <= 0:
        return None, False
    user = booking.ride.driver
    with transaction.atomic():
        account = account_for(user, lock=True)
        split = money.split_penalty(amount, account.available_paise)
        return post(
            user, EntryKind.PENALTY, key=f"booking:{booking.pk}:penalty", booking=booking,
            available=-split.from_available, owed=split.owed,
            description=f"Cancellation penalty of {money.format_inr(amount)} for booking {booking.pk}.",
        )


# ---------------------------------------------------------------- withdrawals


def withdrawals_today(user) -> int:
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    return Withdrawal.objects.filter(
        user=user, created_at__gte=start,
        status__in=[WithdrawalStatus.PENDING, WithdrawalStatus.PROCESSING, WithdrawalStatus.PAID],
    ).count()


def withdrawal_block(user, account=None):
    """Why ``user`` can't withdraw right now, as (code, message), or None."""
    account = account or account_for(user)
    return money.withdrawal_block(
        available=account.available_paise, owed=account.owed_paise, frozen=account.withdrawals_frozen,
        withdrawals_today=withdrawals_today(user), limits=PaymentSettings.load().withdrawal_limits(),
    )


def debit_withdrawal(withdrawal):
    return post(
        withdrawal.user, EntryKind.WITHDRAWAL, key=f"withdrawal:{withdrawal.pk}:debit", withdrawal=withdrawal,
        available=-withdrawal.amount_paise, description=f"Withdrawal to {withdrawal.destination}.",
    )


def return_withdrawal(withdrawal):
    return post(
        withdrawal.user, EntryKind.WITHDRAWAL_REVERSED, key=f"withdrawal:{withdrawal.pk}:returned",
        withdrawal=withdrawal, available=withdrawal.amount_paise,
        description=f"Withdrawal to {withdrawal.destination} {withdrawal.status}: amount returned.",
    )


# ---------------------------------------------------------------- admin


@transaction.atomic
def adjust(user, *, actor, reason, key, held=0, available=0, owed=0, request=None):
    reason = " ".join((reason or "").split())
    if not reason:
        raise LedgerError("A reason is required for an adjustment.", "reason_required")
    entry, created = post(
        user, EntryKind.ADJUSTMENT, key=key, held=held, available=available, owed=owed, actor=actor,
        description=f"Adjustment: {reason}",
    )
    if created:
        audit.record(
            FinancialAction.LEDGER_POSTED, actor=actor, user=user, amount=held + available + owed,
            reference=key, request=request, kind=EntryKind.ADJUSTMENT, held=held, available=available, owed=owed,
            reason=reason,
        )
    return entry, created


@transaction.atomic
def set_frozen(user, frozen: bool, *, actor, reason="", request=None) -> EarningsAccount:
    reason = " ".join((reason or "").split())
    if frozen and not reason:
        raise LedgerError("A reason is required to freeze withdrawals.", "reason_required")
    account = account_for(user, lock=True)
    if account.withdrawals_frozen == frozen:
        return account
    account.withdrawals_frozen = frozen
    account.frozen_reason = reason if frozen else ""
    account.frozen_at = timezone.now() if frozen else None
    account.frozen_by = actor if frozen else None
    account.save(update_fields=["withdrawals_frozen", "frozen_reason", "frozen_at", "frozen_by", "updated_at"])
    audit.record(
        FinancialAction.WITHDRAWALS_FROZEN if frozen else FinancialAction.WITHDRAWALS_UNFROZEN,
        actor=actor, user=user, request=request, reason=reason,
    )
    return account


# ---------------------------------------------------------------- reconciliation


def reconcile(account: EarningsAccount) -> list:
    """Problems with one account's ledger (empty when everything adds up)."""
    from django.db.models import Sum
    from django.db.models.functions import Coalesce

    problems = []
    sums = account.entries.aggregate(
        held=Coalesce(Sum("held_delta"), 0), available=Coalesce(Sum("available_delta"), 0), owed=Coalesce(Sum("owed_delta"), 0)
    )
    actual = {"held": account.held_paise, "available": account.available_paise, "owed": account.owed_paise}
    for name, total in sums.items():
        if total != actual[name]:
            problems.append(f"{name}: balance {actual[name]} but entries add up to {total}")
    last = account.entries.order_by("-created_at", "-id").first()
    if last is not None:
        for name in actual:
            after = getattr(last, f"{name}_after")
            if after != actual[name]:
                problems.append(f"{name}: balance {actual[name]} but the last entry says {after}")
    running = {"held": 0, "available": 0, "owed": 0}
    for e in account.entries.order_by("created_at", "id"):
        for name in running:
            running[name] += getattr(e, f"{name}_delta")
            if running[name] != getattr(e, f"{name}_after"):
                problems.append(f"entry {e.pk}: {name}_after is {getattr(e, f'{name}_after')}, expected {running[name]}")
    return problems
