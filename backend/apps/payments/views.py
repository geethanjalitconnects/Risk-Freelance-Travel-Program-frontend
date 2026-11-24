from django.db import transaction
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle, UserRateThrottle
from rest_framework.views import APIView

from apps.verification.services import is_approved

from . import audit, ledger, money, withdrawals
from .models import (
    EntryKind,
    FinancialAction,
    Payment,
    PaymentSettings,
    PaymentStatus,
    PayoutAccount,
    PayoutAccountStatus,
    PayoutMethod,
    Withdrawal,
)
from .serializers import PayoutAccountInputSerializer, PayoutAccountOutSerializer


def _payload(user, account):
    return {"account": PayoutAccountOutSerializer(account).data if account else None, "can_edit": is_approved(user)}


class MyPayoutAccountView(APIView):
    """The signed-in driver's payout details (bank account or UPI).

    Both return ``{account, canEdit}``: the masked details (``null`` when none are saved) and
    whether this user may save them. PUT saves them (the full
    account number is entered twice and never returned). Only drivers whose verification is
    approved can save payout details. Saving resets the details to "pending verification".
    """

    permission_classes = [IsAuthenticated]
    throttle_scope = "payout_account"

    def get_throttles(self):
        if self.request.method == "PUT":
            return [ScopedRateThrottle(), UserRateThrottle()]
        return super().get_throttles()

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        return Response(_payload(request.user, PayoutAccount.objects.filter(user=request.user).first()))

    @extend_schema(
        request=PayoutAccountInputSerializer, responses={200: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT}
    )
    def put(self, request):
        if not is_approved(request.user):
            return Response(
                {"detail": "Add payout details once your driver verification is approved.", "code": "verification_required"},
                status=status.HTTP_403_FORBIDDEN,
            )
        s = PayoutAccountInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data

        with transaction.atomic():
            account = PayoutAccount.objects.select_for_update().filter(user=request.user).first()
            created = account is None
            account = account or PayoutAccount(user=request.user)
            account.method = d["method"]
            account.holder_name = d["holder_name"]
            if d["method"] == PayoutMethod.BANK:
                account.bank_name = d["bank_name"]
                account.ifsc = d["ifsc"]
                account.set_account_number(d["account_number"])
                account.upi_id_enc, account.upi_masked = None, ""
            else:
                account.set_upi_id(d["upi_id"])
                account.bank_name = account.ifsc = account.account_last4 = ""
                account.account_number_enc = None
            # New details must be verified again before any payout.
            account.status = PayoutAccountStatus.PENDING
            account.provider_account_id = ""
            account.verified_at = None
            account.save()
            audit.record(
                FinancialAction.PAYOUT_ACCOUNT_CHANGED, actor=request.user, user=request.user, request=request,
                created=created, method=account.method, destination=account.display,
                ifsc=account.ifsc or None,
            )
        return Response(_payload(request.user, account))


# ---------------------------------------------------------------- earnings and withdrawals (Phase 7)

PAGE_SIZE = 20

# How each ledger entry reads in the history.
ENTRY_TYPE = {
    EntryKind.EARNING_HELD: "hold",
    EntryKind.EARNING_RELEASED: "credit",
    EntryKind.EARNING_REVERSED: "reversal",
    EntryKind.PENALTY: "debit",
    EntryKind.WITHDRAWAL: "withdrawal",
    EntryKind.WITHDRAWAL_REVERSED: "credit",
    EntryKind.ADJUSTMENT: "adjustment",
}


def _ms(dt):
    return int(dt.timestamp() * 1000) if dt else None


def _route(booking):
    if booking is None:
        return None
    ride = booking.ride
    return f"{ride.origin.name} → {ride.destination.name}, {timezone.localtime(ride.depart):%d %b}"


def _entry_payload(e):
    if e.kind in (EntryKind.EARNING_HELD, EntryKind.EARNING_RELEASED, EntryKind.EARNING_REVERSED):
        amount = abs(e.held_delta)
    elif e.kind == EntryKind.PENALTY:
        amount = abs(e.available_delta) + abs(e.owed_delta)
    else:
        amount = abs(e.available_delta) or abs(e.held_delta) or abs(e.owed_delta)
    if e.withdrawal_id:
        entry_status = e.withdrawal.status
    elif e.kind == EntryKind.EARNING_HELD:
        entry_status = "held"
    else:
        entry_status = "completed"
    return {
        "id": e.pk, "at": _ms(e.created_at), "kind": e.kind, "label": e.get_kind_display(),
        "type": ENTRY_TYPE.get(e.kind, "adjustment"), "amount": amount, "status": entry_status,
        "held_delta": e.held_delta, "available_delta": e.available_delta, "owed_delta": e.owed_delta,
        "available_after": e.available_after, "description": e.description, "booking_id": e.booking_id,
        "route": _route(e.booking),
    }


def _withdrawal_payload(w):
    return {
        "id": w.pk, "amount": w.amount_paise, "method": w.method, "destination": w.destination, "status": w.status,
        "utr": w.utr, "failure_reason": w.failure_reason, "created_at": _ms(w.created_at),
        "completed_at": _ms(w.completed_at),
    }


class MyEarningsView(APIView):
    """The driver's balances (paise), whether they can withdraw now (and why not), and where the
    money goes. Nothing here is editable; balances change only through the ledger."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        account = ledger.account_for(request.user)
        limits = PaymentSettings.load().withdrawal_limits()
        block = withdrawals.block_for(request.user, account)
        pa = PayoutAccount.objects.filter(user=request.user).first()
        return Response({
            "held": account.held_paise,
            "available": account.available_paise,
            "owed": account.owed_paise,
            "frozen": account.withdrawals_frozen,
            "can_withdraw": block is None,
            "block": {"code": block[0], "message": block[1]} if block else None,
            "payouts_enabled": withdrawals.payouts_enabled(),
            "min_withdrawal": limits.min_withdrawal,
            "max_per_day": limits.max_per_day,
            "withdrawals_today": ledger.withdrawals_today(request.user),
            "payout_account": PayoutAccountOutSerializer(pa).data if pa else None,
            "is_driver": is_approved(request.user) or account.entries.exists(),
        })


class MyEarningsHistoryView(APIView):
    """The driver's ledger, newest first, 20 per page (``?page=``). Entries are final: never edited;
    corrections appear as new entries."""

    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=[OpenApiParameter("page", OpenApiTypes.INT)], responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        account = ledger.account_for(request.user)
        qs = account.entries.select_related(
            "withdrawal", "booking__ride__origin", "booking__ride__destination"
        ).order_by("-created_at", "-id")
        count = qs.count()
        pages = max(1, -(-count // PAGE_SIZE))
        try:
            page = min(max(1, int(request.query_params.get("page", 1))), pages)
        except ValueError:
            page = 1
        rows = qs[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
        return Response({"results": [_entry_payload(e) for e in rows], "page": page, "pages": pages, "count": count})


class MyWithdrawalsView(APIView):
    """GET: my withdrawals. POST: withdraw the whole available balance (send an ``Idempotency-Key``
    header, a fresh UUID per swipe). 503 ``payouts_unavailable`` until payouts are switched on."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "withdrawals"

    def get_throttles(self):
        if self.request.method == "POST":
            return [ScopedRateThrottle(), UserRateThrottle()]
        return super().get_throttles()

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        rows = Withdrawal.objects.filter(user=request.user).order_by("-created_at")[:50]
        return Response([_withdrawal_payload(w) for w in rows])

    @extend_schema(
        parameters=[OpenApiParameter("Idempotency-Key", OpenApiTypes.STR, OpenApiParameter.HEADER, required=True)],
        request=None, responses={201: OpenApiTypes.OBJECT, 200: OpenApiTypes.OBJECT, 409: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        try:
            w, created = withdrawals.request_withdrawal(request.user, request.headers.get("Idempotency-Key", ""), request)
        except withdrawals.WithdrawalError as e:
            return Response({"detail": e.message, "code": e.code}, status=e.status)
        except ledger.LedgerError as e:
            return Response({"detail": e.message, "code": e.code}, status=status.HTTP_409_CONFLICT)
        return Response(_withdrawal_payload(w), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class MyPaymentsView(APIView):
    """The passenger's payments and refunds, newest first (refunds go to the original payment method)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        payments = (
            Payment.objects.filter(booking__passenger=request.user)
            .exclude(status=PaymentStatus.CREATED)
            .select_related("booking__ride__origin", "booking__ride__destination")
            .prefetch_related("refunds")
            .order_by("-created_at")[:100]
        )
        rule_labels = dict(money.Rule.CHOICES)
        return Response([
            {
                "id": p.pk, "booking_id": p.booking_id, "route": _route(p.booking), "amount": p.amount_paise,
                "status": p.status, "method": p.method, "at": _ms(p.captured_at or p.created_at),
                "refunds": [
                    {"id": r.pk, "amount": r.amount_paise, "status": r.status, "reason": rule_labels.get(r.rule, r.rule),
                     "at": _ms(r.created_at), "processed_at": _ms(r.processed_at)}
                    for r in p.refunds.all()
                ],
            }
            for p in payments
        ])
