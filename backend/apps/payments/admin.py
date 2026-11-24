"""Payments in the Django admin.

Editable: the payment settings (every change audited) and the withdrawal freeze on an earnings
account (a reason is required, audited). Everything else is read-only: money moves only through
the services, never by editing rows here.
"""
from django import forms
from django.contrib import admin
from django.http import HttpResponseRedirect
from django.urls import reverse

from . import audit, ledger, money
from .models import (
    EarningEntry,
    EarningsAccount,
    FinancialAction,
    FinancialAuditLog,
    Payment,
    PaymentSettings,
    PayoutAccount,
    Refund,
    Transfer,
    WebhookEvent,
    Withdrawal,
)


def inr(field):
    def show(obj):
        value = getattr(obj, field)
        return money.format_inr(value) if value is not None else "—"

    show.short_description = field.replace("_paise", "").replace("_", " ")
    show.admin_order_field = field
    return show


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# ---------------------------------------------------------------- settings


@admin.register(PaymentSettings)
class PaymentSettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        ("Commission", {
            "fields": ("platform_fee_bps", "publisher_commission_bps"),
            "description": "Rates are in basis points: 100 = 1%, 1000 = 10%. They are saved on each booking when it is "
                           "made, so changes apply to new bookings only.",
        }),
        ("Cancellations", {
            "fields": ("cancel_window_hours", "passenger_cancel_early_bps", "passenger_cancel_late_bps",
                       "publisher_penalty_early_bps", "publisher_penalty_late_bps"),
            "description": "Passenger rates are kept from the total paid. Publisher penalties are a share of the ride amount.",
        }),
        ("Timing", {"fields": ("seat_hold_minutes", "auto_complete_hours", "no_show_after_minutes")}),
        ("Withdrawals", {"fields": ("min_withdrawal_paise", "max_withdrawals_per_day")}),
        ("Tax", {"fields": ("gst_bps",)}),
        ("Last change", {"fields": ("updated_at", "updated_by")}),
    )
    readonly_fields = ["updated_at", "updated_by"]

    def changelist_view(self, request, extra_context=None):
        obj = PaymentSettings.load()
        return HttpResponseRedirect(reverse("admin:payments_paymentsettings_change", args=[obj.pk]))

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        before = PaymentSettings.load()
        changes = {
            name: [getattr(before, name), form.cleaned_data[name]]
            for name in form.changed_data
            if name in form.cleaned_data
        }
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
        if changes:
            audit.record(FinancialAction.SETTINGS_CHANGED, actor=request.user, request=request, changes=changes)


# ---------------------------------------------------------------- payments


class RefundInline(admin.TabularInline):
    model = Refund
    extra = 0
    can_delete = False
    fields = readonly_fields = ["created_at", "amount", "rule", "status", "razorpay_refund_id", "processed_at"]

    @admin.display(description="amount")
    def amount(self, obj):
        return money.format_inr(obj.amount_paise)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(ReadOnlyAdmin):
    list_display = ["created_at", "booking", inr("amount_paise"), "status", "method", "razorpay_payment_id"]
    list_filter = ["status", ("created_at", admin.DateFieldListFilter)]
    search_fields = ["id", "booking__id", "razorpay_order_id", "razorpay_payment_id", "booking__passenger__phone"]
    list_select_related = ["booking"]
    inlines = [RefundInline]
    date_hierarchy = "created_at"


@admin.register(Refund)
class RefundAdmin(ReadOnlyAdmin):
    list_display = ["created_at", "booking", inr("amount_paise"), "rule", "status", "attempts", "razorpay_refund_id"]
    list_filter = ["status", "rule"]
    search_fields = ["id", "booking__id", "razorpay_refund_id", "payment__razorpay_payment_id"]


@admin.register(WebhookEvent)
class WebhookEventAdmin(ReadOnlyAdmin):
    list_display = ["received_at", "event_type", "event_id", "status", "processed_at"]
    list_filter = ["status", "event_type"]
    search_fields = ["event_id"]


# ---------------------------------------------------------------- publishers


@admin.register(PayoutAccount)
class PayoutAccountAdmin(ReadOnlyAdmin):
    """Shows only masked details: the encrypted fields are never rendered."""

    list_display = ["user", "holder_name", "method", "display", "ifsc", "status", "updated_at"]
    list_filter = ["method", "status"]
    search_fields = ["user__phone", "user__name", "holder_name", "ifsc"]
    fields = ["user", "method", "holder_name", "bank_name", "ifsc", "account_last4", "upi_masked", "status",
              "provider_account_id", "verified_at", "created_at", "updated_at"]


class EntryInline(admin.TabularInline):
    model = EarningEntry
    extra = 0
    can_delete = False
    ordering = ["-created_at", "-id"]
    fields = readonly_fields = ["created_at", "kind", "held_delta", "available_delta", "owed_delta", "description"]
    max_num = 0
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class EarningsAccountForm(forms.ModelForm):
    class Meta:
        model = EarningsAccount
        fields = ["withdrawals_frozen", "frozen_reason"]

    def clean(self):
        data = super().clean()
        if data.get("withdrawals_frozen") and not " ".join((data.get("frozen_reason") or "").split()):
            self.add_error("frozen_reason", "Give a reason to freeze withdrawals.")
        return data


@admin.register(EarningsAccount)
class EarningsAccountAdmin(admin.ModelAdmin):
    form = EarningsAccountForm
    list_display = ["user", inr("held_paise"), inr("available_paise"), inr("owed_paise"), "withdrawals_frozen", "updated_at"]
    list_filter = ["withdrawals_frozen"]
    search_fields = ["user__phone", "user__name"]
    list_select_related = ["user"]
    inlines = [EntryInline]
    fieldsets = (
        ("Balances", {"fields": ("user", "held", "available", "owed")}),
        ("Withdrawals", {
            "fields": ("withdrawals_frozen", "frozen_reason", "frozen_at", "frozen_by"),
            "description": "Freezing stops new withdrawals. Balances can't be edited here.",
        }),
    )
    readonly_fields = ["user", "held", "available", "owed", "frozen_at", "frozen_by"]

    held = staticmethod(inr("held_paise"))
    available = staticmethod(inr("available_paise"))
    owed = staticmethod(inr("owed_paise"))

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        # Through the ledger service: locked, audited, and the reason is normalised.
        ledger.set_frozen(
            obj.user, form.cleaned_data["withdrawals_frozen"], actor=request.user,
            reason=form.cleaned_data.get("frozen_reason", ""), request=request,
        )


@admin.register(EarningEntry)
class EarningEntryAdmin(ReadOnlyAdmin):
    list_display = ["created_at", "account", "kind", "held_delta", "available_delta", "owed_delta", "available_after"]
    list_filter = ["kind", ("created_at", admin.DateFieldListFilter)]
    search_fields = ["account__user__phone", "account__user__name", "idempotency_key", "booking__id"]
    list_select_related = ["account__user"]


@admin.register(Withdrawal)
class WithdrawalAdmin(ReadOnlyAdmin):
    list_display = ["created_at", "user", inr("amount_paise"), "destination", "status", "provider_ref", "utr"]
    list_filter = ["status", "method"]
    search_fields = ["id", "user__phone", "user__name", "provider_ref", "utr"]


@admin.register(FinancialAuditLog)
class FinancialAuditLogAdmin(ReadOnlyAdmin):
    list_display = ["at", "actor_label", "action", "user", "booking", "amount", "reference"]
    list_filter = ["action", ("at", admin.DateFieldListFilter)]
    search_fields = ["actor_label", "reference", "user__phone", "booking__id"]

    @admin.display(description="amount")
    def amount(self, obj):
        return money.format_inr(obj.amount_paise) if obj.amount_paise is not None else "—"


@admin.register(Transfer)
class TransferAdmin(ReadOnlyAdmin):
    list_display = ["created_at", "booking", "linked_account_id", inr("amount_paise"), "status", "settlement_status",
                    "razorpay_transfer_id", "withdrawal"]
    list_filter = ["status"]
    search_fields = ["booking__id", "razorpay_transfer_id", "linked_account_id"]
