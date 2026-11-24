"""Payments, refunds, publisher earnings and the financial audit trail.

All amounts are integer paise and all rates basis points (see ``money.py``).

Not here yet, on purpose: the Razorpay Route transfer model and the payout-provider calls. They
wait until Razorpay confirms account eligibility and the permitted fund flow (client decision,
2026-11-20). Provider ids are stored in neutral ``provider_*`` fields where the provider isn't
settled yet.
"""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q

from . import money
from .validators import validate_ifsc

BPS_FIELD = dict(validators=[MinValueValidator(0), MaxValueValidator(money.BPS)])


class ImmutableError(Exception):
    """Ledger and audit rows are append-only."""


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ImmutableError(f"{self.model.__name__} rows can't be updated.")

    def delete(self):
        raise ImmutableError(f"{self.model.__name__} rows can't be deleted.")


class AppendOnlyModel(models.Model):
    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableError(f"{type(self).__name__} rows can't be changed once written.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableError(f"{type(self).__name__} rows can't be deleted.")


# ---------------------------------------------------------------- settings


class PaymentSettings(models.Model):
    """The single payment-settings record (edited in the Django admin; every change is audited).
    Rates are snapshotted on each booking when it is made, so changes apply to new bookings only."""

    platform_fee_bps = models.PositiveIntegerField(
        default=1000, **BPS_FIELD, help_text="Added to the ride amount, paid by the passenger. 1000 = 10%."
    )
    publisher_commission_bps = models.PositiveIntegerField(
        default=1000, **BPS_FIELD, help_text="Taken from the ride amount before it reaches the publisher. 1000 = 10%."
    )
    cancel_window_hours = models.PositiveSmallIntegerField(
        default=24, validators=[MaxValueValidator(720)],
        help_text="Cancellations at most this many hours before departure use the 'within' rates.",
    )
    passenger_cancel_early_bps = models.PositiveIntegerField(
        default=1500, **BPS_FIELD,
        help_text="Kept from the total paid when the passenger cancels more than the window before departure.",
    )
    passenger_cancel_late_bps = models.PositiveIntegerField(
        default=1000, **BPS_FIELD, help_text="Kept from the total paid when the passenger cancels within the window.",
    )
    publisher_penalty_early_bps = models.PositiveIntegerField(
        default=0, **BPS_FIELD,
        help_text="Charged to the publisher (of the ride amount) for cancelling more than the window before departure.",
    )
    publisher_penalty_late_bps = models.PositiveIntegerField(
        default=1000, **BPS_FIELD,
        help_text="Charged to the publisher (of the ride amount) for cancelling within the window, or a no-show.",
    )
    seat_hold_minutes = models.PositiveSmallIntegerField(
        default=10, validators=[MinValueValidator(1), MaxValueValidator(60)],
        help_text="How long seats stay reserved while the passenger pays.",
    )
    auto_complete_hours = models.PositiveSmallIntegerField(
        default=24, validators=[MinValueValidator(1)],
        help_text="Rides complete automatically this long after the scheduled arrival, unless a problem is reported.",
    )
    no_show_after_minutes = models.PositiveSmallIntegerField(
        default=30, help_text="A publisher can report a passenger no-show this long after departure.",
    )
    min_withdrawal_paise = models.PositiveIntegerField(default=10000, help_text="In paise. 10000 = ₹100.")
    max_withdrawals_per_day = models.PositiveSmallIntegerField(default=3, validators=[MinValueValidator(1)])
    gst_bps = models.PositiveIntegerField(
        default=0, **BPS_FIELD,
        help_text="GST included in VConnects' fees, for reporting only. Pending CA advice: leave at 0.",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    POLICY_FIELDS = [f.name for f in money.FeePolicy.__dataclass_fields__.values()]

    class Meta:
        verbose_name = verbose_name_plural = "payment settings"

    def __str__(self):
        return "Payment settings"

    def save(self, *args, **kwargs):
        self.pk = 1  # a single record
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "PaymentSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def policy(self) -> money.FeePolicy:
        return money.FeePolicy(**{name: getattr(self, name) for name in self.POLICY_FIELDS})

    def withdrawal_limits(self) -> money.WithdrawalLimits:
        return money.WithdrawalLimits(min_withdrawal=self.min_withdrawal_paise, max_per_day=self.max_withdrawals_per_day)


# ---------------------------------------------------------------- payments


class PaymentStatus(models.TextChoices):
    CREATED = "created", "Created"  # Razorpay order created, passenger hasn't paid yet
    AUTHORIZED = "authorized", "Authorized"
    CAPTURED = "captured", "Captured"  # verified server-side (webhook + signature)
    FAILED = "failed", "Failed"


class Payment(models.Model):
    """One Razorpay payment attempt for a booking. A booking is confirmed only when its payment is
    captured and verified on the server."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey("bookings.Booking", on_delete=models.PROTECT, related_name="payments")
    amount_paise = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="INR")
    status = models.CharField(max_length=12, choices=PaymentStatus.choices, default=PaymentStatus.CREATED)
    razorpay_order_id = models.CharField(max_length=40, unique=True, null=True, blank=True)
    razorpay_payment_id = models.CharField(max_length=40, unique=True, null=True, blank=True)
    method = models.CharField(max_length=20, blank=True)
    error_code = models.CharField(max_length=60, blank=True)
    error_description = models.CharField(max_length=300, blank=True)
    idempotency_key = models.CharField(max_length=80, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    captured_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount_paise__gte=100), name="payment_at_least_1_rupee"),
            # At most one captured payment per booking.
            models.UniqueConstraint(
                fields=["booking"], condition=Q(status="captured"), name="one_captured_payment_per_booking"
            ),
        ]

    def __str__(self):
        return f"{money.format_inr(self.amount_paise)} {self.status} ({self.razorpay_payment_id or self.razorpay_order_id or self.pk})"


class RefundStatus(models.TextChoices):
    PENDING = "pending", "Pending"  # recorded, not yet accepted by Razorpay
    PROCESSING = "processing", "Processing"  # accepted by Razorpay
    PROCESSED = "processed", "Processed"
    FAILED = "failed", "Failed"


class Refund(models.Model):
    """Money going back to the passenger's original payment method."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    booking = models.ForeignKey("bookings.Booking", on_delete=models.PROTECT, related_name="refunds")
    amount_paise = models.PositiveIntegerField()
    rule = models.CharField(max_length=24, choices=money.Rule.CHOICES)
    status = models.CharField(max_length=12, choices=RefundStatus.choices, default=RefundStatus.PENDING)
    razorpay_refund_id = models.CharField(max_length=40, unique=True, null=True, blank=True)
    idempotency_key = models.CharField(max_length=80, unique=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.CheckConstraint(condition=Q(amount_paise__gte=1), name="refund_positive")]

    def __str__(self):
        return f"Refund {money.format_inr(self.amount_paise)} ({self.status})"


class WebhookStatus(models.TextChoices):
    RECEIVED = "received", "Received"
    PROCESSED = "processed", "Processed"
    IGNORED = "ignored", "Ignored"  # an event type we don't act on
    FAILED = "failed", "Failed"


class WebhookEvent(models.Model):
    """Every verified Razorpay webhook, stored once by its event id so a redelivery is a no-op.
    Only events whose signature verified are stored."""

    event_id = models.CharField(max_length=60, unique=True)
    event_type = models.CharField(max_length=60)
    payload = models.JSONField()
    status = models.CharField(max_length=10, choices=WebhookStatus.choices, default=WebhookStatus.RECEIVED)
    error = models.CharField(max_length=300, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.event_type} {self.event_id}"


# ---------------------------------------------------------------- publisher payout details


class PayoutMethod(models.TextChoices):
    BANK = "bank", "Bank account"
    UPI = "upi", "UPI"


class PayoutAccountStatus(models.TextChoices):
    PENDING = "pending", "Pending verification"
    VERIFIED = "verified", "Verified"
    FAILED = "failed", "Verification failed"


class PayoutAccount(models.Model):
    """A publisher's bank / UPI details. The account number and UPI id are encrypted; only the last
    4 digits and a masked UPI id are ever shown. Use ``set_account_number`` / ``set_upi_id``."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payout_account")
    method = models.CharField(max_length=4, choices=PayoutMethod.choices, default=PayoutMethod.BANK)
    holder_name = models.CharField(max_length=100)
    bank_name = models.CharField(max_length=100, blank=True)
    ifsc = models.CharField(max_length=11, blank=True, validators=[validate_ifsc])
    account_number_enc = models.BinaryField(null=True, blank=True, editable=False)
    account_last4 = models.CharField(max_length=4, blank=True)
    upi_id_enc = models.BinaryField(null=True, blank=True, editable=False)
    upi_masked = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=10, choices=PayoutAccountStatus.choices, default=PayoutAccountStatus.PENDING)
    # The provider's id for this account (Route linked account or payout fund account), once known.
    provider_account_id = models.CharField(max_length=60, blank=True)
    # Route: transfers to a new linked account wait until this time (cooling period, to confirm with Razorpay).
    transfers_allowed_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.holder_name}: {self.display}"

    @property
    def display(self) -> str:
        if self.method == PayoutMethod.UPI:
            return self.upi_masked or "UPI"
        return f"{self.bank_name or 'Bank'} ••••{self.account_last4}"

    def set_account_number(self, number: str):
        from . import crypto
        from .validators import normalize_account_number

        number = normalize_account_number(number)
        self.account_number_enc = crypto.encrypt_text(number)
        self.account_last4 = number[-4:]

    def account_number(self) -> str:
        """Decrypted, for the payout provider only. Never return it from an API or log it."""
        from . import crypto

        return crypto.decrypt_text(bytes(self.account_number_enc)) if self.account_number_enc else ""

    def set_upi_id(self, upi: str):
        from . import crypto
        from .validators import mask_upi, normalize_upi

        upi = normalize_upi(upi)
        self.upi_id_enc = crypto.encrypt_text(upi)
        self.upi_masked = mask_upi(upi)

    def upi_id(self) -> str:
        from . import crypto

        return crypto.decrypt_text(bytes(self.upi_id_enc)) if self.upi_id_enc else ""

    def clean(self):
        if self.method == PayoutMethod.BANK and not (self.ifsc and self.account_last4):
            raise ValidationError("A bank payout account needs an IFSC and an account number.")
        if self.method == PayoutMethod.UPI and not self.upi_masked:
            raise ValidationError("A UPI payout account needs a UPI id.")


# ---------------------------------------------------------------- publisher earnings ledger


class EarningsAccount(models.Model):
    """A publisher's running balances, kept in step with their EarningEntry rows by ``ledger.post``
    (and checked by ``manage.py reconcile_earnings``). Lock the row to change it.

    held       earnings for paid bookings whose ride isn't verified complete yet (or is disputed)
    available  verified earnings the publisher can withdraw
    owed       penalties not yet recovered (paid off from the next earnings)
    """

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="earnings")
    held_paise = models.BigIntegerField(default=0)
    available_paise = models.BigIntegerField(default=0)
    owed_paise = models.BigIntegerField(default=0)
    withdrawals_frozen = models.BooleanField(default=False)
    frozen_reason = models.CharField(max_length=300, blank=True)
    frozen_at = models.DateTimeField(null=True, blank=True)
    frozen_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(held_paise__gte=0, available_paise__gte=0, owed_paise__gte=0),
                name="earnings_balances_non_negative",
            ),
        ]

    def __str__(self):
        return f"Earnings of {self.user}"


class EntryKind(models.TextChoices):
    EARNING_HELD = "earning_held", "Earning held (booking paid)"
    EARNING_RELEASED = "earning_released", "Earning released (ride verified)"
    EARNING_REVERSED = "earning_reversed", "Earning reversed (booking cancelled)"
    PENALTY = "penalty", "Cancellation penalty"
    WITHDRAWAL = "withdrawal", "Withdrawal"
    WITHDRAWAL_REVERSED = "withdrawal_reversed", "Withdrawal failed, returned"
    ADJUSTMENT = "adjustment", "Adjustment by VConnects"


class EarningEntry(AppendOnlyModel):
    """One immutable line in a publisher's earnings ledger. Each delta is signed; the *_after
    fields are the account's balances right after this entry."""

    account = models.ForeignKey(EarningsAccount, on_delete=models.PROTECT, related_name="entries")
    kind = models.CharField(max_length=20, choices=EntryKind.choices)
    held_delta = models.BigIntegerField(default=0)
    available_delta = models.BigIntegerField(default=0)
    owed_delta = models.BigIntegerField(default=0)
    held_after = models.BigIntegerField()
    available_after = models.BigIntegerField()
    owed_after = models.BigIntegerField()
    booking = models.ForeignKey("bookings.Booking", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    withdrawal = models.ForeignKey(
        "payments.Withdrawal", null=True, blank=True, on_delete=models.PROTECT, related_name="entries"
    )
    idempotency_key = models.CharField(max_length=120, unique=True)
    description = models.CharField(max_length=300)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name_plural = "earning entries"
        indexes = [models.Index(fields=["account", "created_at"])]
        constraints = [
            models.CheckConstraint(
                condition=~Q(held_delta=0, available_delta=0, owed_delta=0), name="entry_changes_something"
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.description}"


class WithdrawalStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    PAID = "paid", "Paid"
    FAILED = "failed", "Failed"  # money returned to available
    REJECTED = "rejected", "Rejected"  # money returned to available


class Withdrawal(models.Model):
    """A publisher taking their whole available balance out. The ledger is debited when the request
    is made, so the same money can't be requested twice; failure or rejection credits it back."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="withdrawals")
    amount_paise = models.PositiveIntegerField()
    method = models.CharField(max_length=4, choices=PayoutMethod.choices)
    destination = models.CharField(max_length=120, help_text="Masked snapshot, e.g. 'HDFC ••••1234'.")
    status = models.CharField(max_length=12, choices=WithdrawalStatus.choices, default=WithdrawalStatus.PENDING)
    idempotency_key = models.CharField(max_length=80, unique=True)
    provider_ref = models.CharField(max_length=60, blank=True, help_text="Payout / transfer id at the provider.")
    utr = models.CharField(max_length=40, blank=True)
    failure_reason = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount_paise__gte=1), name="withdrawal_positive"),
            # One withdrawal in flight per publisher.
            models.UniqueConstraint(
                fields=["user"], condition=Q(status__in=["pending", "processing"]), name="one_open_withdrawal_per_user"
            ),
        ]

    def __str__(self):
        return f"{money.format_inr(self.amount_paise)} to {self.destination} ({self.status})"


# ---------------------------------------------------------------- audit


class FinancialAction(models.TextChoices):
    SETTINGS_CHANGED = "settings_changed", "Payment settings changed"
    WITHDRAWALS_FROZEN = "withdrawals_frozen", "Withdrawals frozen"
    WITHDRAWALS_UNFROZEN = "withdrawals_unfrozen", "Withdrawals unfrozen"
    LEDGER_POSTED = "ledger_posted", "Ledger entry posted"
    PAYOUT_ACCOUNT_CHANGED = "payout_account_changed", "Payout details changed"
    PAYMENT_CAPTURED = "payment_captured", "Payment captured"
    PAYMENT_FAILED = "payment_failed", "Payment failed"
    REFUND_CREATED = "refund_created", "Refund created"
    REFUND_UPDATED = "refund_updated", "Refund status changed"
    WITHDRAWAL_UPDATED = "withdrawal_updated", "Withdrawal status changed"
    BOOKING_SETTLED = "booking_settled", "Booking settled"


class FinancialAuditLog(AppendOnlyModel):
    """Who did what to money, when. Append-only. Never store full account numbers, UPI ids or
    secrets in ``details``."""

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    actor_label = models.CharField(max_length=150, help_text="Who acted: a user, 'system' or 'razorpay'.")
    action = models.CharField(max_length=30, choices=FinancialAction.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        help_text="The user whose money this concerns.",
    )
    booking = models.ForeignKey("bookings.Booking", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    amount_paise = models.BigIntegerField(null=True, blank=True)
    reference = models.CharField(max_length=80, blank=True, help_text="Razorpay id or ledger key.")
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-at", "-id"]

    def __str__(self):
        return f"{self.get_action_display()} by {self.actor_label}"


# ---------------------------------------------------------------- Route transfers (Phase 8)


class TransferStatus(models.TextChoices):
    QUEUED = "queued", "Queued (not sent yet)"
    ON_HOLD = "on_hold", "Created, settlement on hold"
    RELEASED = "released", "Released for settlement"
    SETTLED = "settled", "Settled to the publisher"
    REVERSED = "reversed", "Reversed"
    FAILED = "failed", "Failed"


class Transfer(models.Model):
    """The publisher's share of one captured payment, sent to their Route linked account with
    settlement ON HOLD, released by a withdrawal after the ride is verified complete. One per
    booking; every Razorpay call carries an idempotency key so it can't be repeated."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.OneToOneField("bookings.Booking", on_delete=models.PROTECT, related_name="transfer")
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="transfers")
    linked_account_id = models.CharField(max_length=40)
    amount_paise = models.PositiveIntegerField()
    reversed_paise = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, choices=TransferStatus.choices, default=TransferStatus.QUEUED)
    razorpay_transfer_id = models.CharField(max_length=40, unique=True, null=True, blank=True)
    settlement_status = models.CharField(max_length=20, blank=True)
    withdrawal = models.ForeignKey("payments.Withdrawal", null=True, blank=True, on_delete=models.PROTECT, related_name="transfers")
    idempotency_key = models.CharField(max_length=80, unique=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount_paise__gte=1), name="transfer_positive"),
            models.CheckConstraint(condition=Q(reversed_paise__lte=F("amount_paise")), name="transfer_reversal_within_amount"),
        ]

    def __str__(self):
        return f"{money.format_inr(self.amount_paise)} to {self.linked_account_id} ({self.status})"

    @property
    def releasable_paise(self):
        return self.amount_paise - self.reversed_paise
