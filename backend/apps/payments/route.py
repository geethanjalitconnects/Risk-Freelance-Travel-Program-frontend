"""Razorpay Route: paying publishers (Phase 8). SWITCHED OFF until Razorpay approves Route
(``ROUTE_ENABLED=False``). With it off, every function here is a no-op and nothing is sent.

Flow (client decision, 2026-11-20):
    payment captured   -> Transfer of the publisher's 90% of the ride amount to their linked
                          account, settlement ON HOLD (VConnects keeps both 10% fees)
    ride verified      -> ledger: held -> available (completion.py); the transfer stays on hold
    publisher withdraws-> the eligible held transfers are RELEASED; Razorpay settles them to the
                          publisher's bank/UPI. Penalties still owed in the ledger are recovered
                          first by partially reversing a held transfer.
    booking cancelled  -> the held transfer is REVERSED before the passenger is refunded
    webhooks           -> transfer / settlement status updates (verified signature only)

Every Razorpay call carries an idempotency key derived from our row ids, and every row is locked
while it changes, so transfers, releases and reversals can't happen twice. Nothing is ever marked
successful without Razorpay's response or a verified webhook.
"""
import logging

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import audit, razorpay
from .models import (
    FinancialAction,
    PaymentStatus,
    PayoutAccount,
    PayoutAccountStatus,
    Transfer,
    TransferStatus,
    Withdrawal,
    WithdrawalStatus,
)

logger = logging.getLogger(__name__)


def enabled() -> bool:
    return bool(settings.ROUTE_ENABLED) and razorpay.configured()


def _linked_account(user):
    pa = PayoutAccount.objects.filter(user=user).first()
    if pa is None or pa.status != PayoutAccountStatus.VERIFIED or not pa.provider_account_id:
        return None
    return pa


# ---------------------------------------------------------------- transfers


def queue_transfer(booking):
    """After a captured payment: record the publisher's transfer and send it after commit."""
    if not enabled():
        return None
    payment = booking.payments.filter(status=PaymentStatus.CAPTURED).first()
    pa = PayoutAccount.objects.filter(user=booking.ride.driver).first()
    t, created = Transfer.objects.get_or_create(
        booking=booking,
        defaults={
            "payment": payment, "linked_account_id": pa.provider_account_id if pa else "",
            "amount_paise": booking.publisher_earning_paise, "idempotency_key": f"booking:{booking.pk}:transfer",
        },
    )
    if created:
        transaction.on_commit(lambda: send_transfer(t.pk))
    return t


def send_transfer(transfer_pk):
    """Create the on-hold transfer at Razorpay. Waits (stays queued) until the publisher's linked
    account is verified and past its cooling period. Never raises."""
    if not enabled():
        return None
    with transaction.atomic():
        t = Transfer.objects.select_for_update().select_related("booking__ride__driver", "payment").get(pk=transfer_pk)
        if t.status != TransferStatus.QUEUED or t.razorpay_transfer_id:
            return t
        pa = _linked_account(t.booking.ride.driver)
        if pa is None or (pa.transfers_allowed_at and pa.transfers_allowed_at > timezone.now()):
            return t  # retried by manage.py process_route
        t.linked_account_id = pa.provider_account_id
        t.attempts += 1
        try:
            rp = razorpay.create_transfer(
                t.payment.razorpay_payment_id, t.linked_account_id, t.amount_paise,
                {"booking_id": str(t.booking_id)}, idempotency_key=t.idempotency_key,
            )
        except razorpay.RazorpayError as e:
            t.last_error = e.message[:300]
            if not e.retryable:
                t.status = TransferStatus.FAILED
            t.save()
            return t
        entity = (rp.get("items") or [rp])[0]
        t.razorpay_transfer_id = entity["id"]
        t.status = TransferStatus.ON_HOLD
        t.settlement_status = entity.get("settlement_status", "on_hold") or ""
        t.last_error = ""
        t.save()
        audit.record(FinancialAction.LEDGER_POSTED, label="razorpay", user=t.booking.ride.driver, booking=t.booking,
                     amount=t.amount_paise, reference=t.razorpay_transfer_id, route="transfer_created")
        return t


def reverse_for_cancellation(booking):
    """Before refunding a cancelled booking: take back the publisher's held transfer."""
    if not enabled():
        return None
    with transaction.atomic():
        t = Transfer.objects.select_for_update().filter(booking=booking).first()
        if t is None:
            return None
        if t.status == TransferStatus.QUEUED:  # never sent: just cancel it
            t.status = TransferStatus.REVERSED
            t.save(update_fields=["status", "updated_at"])
            return t
        if t.status != TransferStatus.ON_HOLD:
            logger.error("Transfer %s is %s, can't reverse automatically", t.pk, t.status)
            return t
        return _reverse(t, t.releasable_paise, key=f"{t.idempotency_key}:reverse")


def _reverse(t, amount, *, key):
    """Reverse ``amount`` of a locked transfer. Records only what Razorpay confirms."""
    if amount <= 0:
        return t
    try:
        razorpay.reverse_transfer(t.razorpay_transfer_id, amount, idempotency_key=key)
    except razorpay.RazorpayError as e:
        t.last_error = e.message[:300]
        t.save(update_fields=["last_error", "updated_at"])
        raise
    t.reversed_paise += amount
    if t.reversed_paise >= t.amount_paise:
        t.status = TransferStatus.REVERSED
    t.save()
    audit.record(FinancialAction.LEDGER_POSTED, label="razorpay", user=t.booking.ride.driver, booking=t.booking,
                 amount=amount, reference=t.razorpay_transfer_id, route="transfer_reversed")
    return t


# ---------------------------------------------------------------- withdrawals = releases


def eligible_transfers(user):
    """Held transfers of verified-complete bookings, not yet released."""
    return Transfer.objects.filter(
        booking__ride__driver=user, status=TransferStatus.ON_HOLD, withdrawal__isnull=True,
        booking__status__in=["completed", "cancelled"],  # cancelled = upheld passenger no-show (driver paid)
    ).exclude(booking__status="cancelled", booking__cancellation__publisher_earning_paise=0)


def release_for_withdrawal(withdrawal_pk):
    """Release the eligible transfers for a withdrawal (row locks + idempotency keys). The ledger was
    debited when the withdrawal was requested. Penalties the ledger already deducted are recovered by
    reversing that part of a transfer before release. Never raises; failures leave the withdrawal
    processing for ``process_route`` and an admin."""
    if not enabled():
        return None
    with transaction.atomic():
        w = Withdrawal.objects.select_for_update().get(pk=withdrawal_pk)
        if w.status != WithdrawalStatus.PENDING:
            return w
        transfers = list(eligible_transfers(w.user).select_for_update().order_by("created_at"))
        backing = sum(t.releasable_paise for t in transfers)
        excess = backing - w.amount_paise  # > 0: penalties already taken from the ledger
        try:
            for t in transfers:
                if excess > 0:
                    take = min(excess, t.releasable_paise)
                    _reverse(t, take, key=f"withdrawal:{w.pk}:recover:{t.pk}")
                    excess -= take
                if t.releasable_paise > 0:
                    razorpay.release_transfer(t.razorpay_transfer_id)
                    t.status = TransferStatus.RELEASED
                t.withdrawal = w
                t.save()
        except razorpay.RazorpayError as e:
            w.failure_reason = e.message[:300]
            w.save(update_fields=["failure_reason", "updated_at"])
            return w
        w.status = WithdrawalStatus.PROCESSING
        w.provider_ref = ",".join(t.razorpay_transfer_id for t in transfers)[:60]
        w.save()
        audit.record(FinancialAction.WITHDRAWAL_UPDATED, label="razorpay", user=w.user, amount=w.amount_paise,
                     reference=str(w.pk), status=w.status, transfers=len(transfers))
        return w


@transaction.atomic
def on_transfer_event(entity: dict):
    """Verified webhook (transfer.* / settlement events): update the transfer, and the withdrawal
    once all its transfers have settled. Unknown transfers are ignored."""
    t = Transfer.objects.select_for_update().filter(razorpay_transfer_id=entity.get("id")).first()
    if t is None:
        return None
    t.settlement_status = (entity.get("settlement_status") or t.settlement_status)[:20]
    if entity.get("error", {}).get("code") or entity.get("status") == "failed":
        t.status = TransferStatus.FAILED
        t.last_error = (entity.get("error", {}).get("description") or "Transfer failed")[:300]
    elif t.settlement_status == "settled":
        t.status = TransferStatus.SETTLED
    t.save()
    w = t.withdrawal
    if w and w.status == WithdrawalStatus.PROCESSING:
        statuses = set(w.transfers.values_list("status", flat=True)) - {TransferStatus.REVERSED}
        if statuses == {TransferStatus.SETTLED}:
            w.status = WithdrawalStatus.PAID
            w.completed_at = timezone.now()
            w.save()
            audit.record(FinancialAction.WITHDRAWAL_UPDATED, label="razorpay", user=w.user, amount=w.amount_paise,
                         reference=str(w.pk), status=w.status)
    return t


# ---------------------------------------------------------------- linked accounts


def onboard(payout_account, *, email, phone):
    """Create the publisher's Route linked account (account -> stakeholder -> Route product with
    their bank details). Admin-triggered after KYC; raises RazorpayError on failure. The account is
    usable only once Razorpay activates the product and the cooling period has passed.

    Field values (category, subcategory, KYC) must be confirmed with Razorpay for this account:
    see ROUTE_PROFILE_CATEGORY / ROUTE_PROFILE_SUBCATEGORY and the README checklist."""
    if not enabled():
        raise razorpay.RazorpayError("Route isn't enabled.", 0, "route_disabled")
    pa = payout_account
    if pa.method != "bank":
        raise razorpay.RazorpayError("Route linked accounts here are set up with a bank account.", 400, "bank_required")
    user = pa.user
    if not pa.provider_account_id:
        acc = razorpay.create_linked_account({
            "email": email, "phone": phone, "type": "route", "reference_id": str(user.pk)[:20],
            "legal_business_name": pa.holder_name, "business_type": "individual", "contact_name": pa.holder_name,
            "profile": {"category": settings.ROUTE_PROFILE_CATEGORY, "subcategory": settings.ROUTE_PROFILE_SUBCATEGORY},
        })
        pa.provider_account_id = acc["id"]
        pa.save(update_fields=["provider_account_id", "updated_at"])
    acc_id = pa.provider_account_id
    razorpay.request("POST", f"/v2/accounts/{acc_id}/stakeholders", {"name": pa.holder_name, "email": email},
                     idempotency_key=f"stakeholder:{pa.pk}:{acc_id}")
    product = razorpay.request("POST", f"/v2/accounts/{acc_id}/products",
                               {"product_name": "route", "tnc_accepted": True},
                               idempotency_key=f"product:{pa.pk}:{acc_id}")
    product = razorpay.request("PATCH", f"/v2/accounts/{acc_id}/products/{product['id']}", {
        "settlements": {"account_number": pa.account_number(), "ifsc_code": pa.ifsc, "beneficiary_name": pa.holder_name},
        "tnc_accepted": True,
    })
    if product.get("activation_status") == "activated":
        pa.status = PayoutAccountStatus.VERIFIED
        pa.verified_at = timezone.now()
        pa.transfers_allowed_at = timezone.now() + timedelta(hours=settings.ROUTE_COOLING_HOURS)
        pa.save()
    audit.record(FinancialAction.PAYOUT_ACCOUNT_CHANGED, label="razorpay", user=user, reference=acc_id,
                 route="linked_account", activation_status=product.get("activation_status"))
    return product.get("activation_status")
