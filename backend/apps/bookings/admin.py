"""Bookings in the admin: read-only (seats, totals and statuses are changed only through the
app or by cancelling the ride). Trip logs and check-ins are shown for support and safety."""
from django import forms
from django.contrib import admin

from apps.payments.money import format_inr

from .models import Booking, Cancellation, CheckIn, CompletionConfirmation, ProblemReport, ProblemStatus, TripEvent


class _ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class CheckInInline(_ReadOnlyInline):
    model = CheckIn
    fields = readonly_fields = ["key", "kind", "at"]


class TripEventInline(_ReadOnlyInline):
    model = TripEvent
    fields = readonly_fields = ["at", "type", "text"]


class CompletionInline(_ReadOnlyInline):
    model = CompletionConfirmation
    fields = readonly_fields = ["at", "party", "source", "actor"]


class ProblemInline(_ReadOnlyInline):
    model = ProblemReport
    fields = readonly_fields = ["created_at", "party", "kind", "status", "details", "resolution_note"]
    show_change_link = True


def _inr(name):
    def show(obj):
        value = getattr(obj, name)
        return format_inr(value) if value is not None else "—"

    show.short_description = name.replace("_paise", "").replace("_", " ")
    return show


class CancellationInline(admin.StackedInline):
    model = Cancellation
    extra = 0
    can_delete = False
    fields = readonly_fields = [
        "created_at", "cancelled_by", "actor", "reason", "minutes_before_departure", "rule",
        "total_paid", "refund", "vconnects_kept", "publisher_earning", "publisher_penalty",
    ]
    total_paid = staticmethod(_inr("total_paid_paise"))
    refund = staticmethod(_inr("refund_paise"))
    vconnects_kept = staticmethod(_inr("vconnects_kept_paise"))
    publisher_earning = staticmethod(_inr("publisher_earning_paise"))
    publisher_penalty = staticmethod(_inr("publisher_penalty_paise"))

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class TravelWithFilter(admin.SimpleListFilter):
    title = "who can travel"
    parameter_name = "travel_with"

    def lookups(self, request, model_admin):
        return [("anyone", "Anyone"), ("women", "Women only"), ("men", "Men only")]

    def queryset(self, request, queryset):
        return queryset.filter(ride__travel_with=self.value()) if self.value() else queryset


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ["passenger", "ride", "seats", "total", "status", "risk_band", "sos_at", "rating", "created_at"]
    list_filter = ["status", TravelWithFilter, ("created_at", admin.DateFieldListFilter), "risk_band"]
    search_fields = ["id", "passenger__phone", "passenger__name", "ride__id", "ride__driver__phone"]
    list_select_related = ["passenger", "ride__origin", "ride__destination"]
    date_hierarchy = "created_at"
    inlines = [CancellationInline, CompletionInline, ProblemInline, CheckInInline, TripEventInline]
    fieldsets = (
        (None, {"fields": (
            "ride", "passenger", "seats", "total", "status", "risk_score", "risk_band", "created_at", "started_at",
            "completed_at", "cancelled_at", "shared", "sos_at", "rating", "rated_at",
        )}),
        ("Money (frozen at booking time)", {"fields": (
            "ride_amount", "platform_fee", "total_paid", "publisher_commission", "publisher_earning", "fee_policy",
            "hold_expires_at",
        )}),
    )
    readonly_fields = [  # the share token is never shown
        "ride", "passenger", "seats", "total", "status", "risk_score", "risk_band", "created_at", "started_at",
        "completed_at", "cancelled_at", "shared", "sos_at", "rating", "rated_at", "ride_amount", "platform_fee",
        "total_paid", "publisher_commission", "publisher_earning", "fee_policy", "hold_expires_at",
    ]
    ride_amount = staticmethod(_inr("ride_amount_paise"))
    platform_fee = staticmethod(_inr("platform_fee_paise"))
    total_paid = staticmethod(_inr("total_paise"))
    publisher_commission = staticmethod(_inr("publisher_commission_paise"))
    publisher_earning = staticmethod(_inr("publisher_earning_paise"))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ProblemDecisionForm(forms.ModelForm):
    decision = forms.ChoiceField(
        choices=[("", "Choose…"), ("uphold", "Uphold"), ("dismiss", "Dismiss")],
        help_text="Passenger no-show upheld: the driver is paid, no refund. Driver no-show upheld: full refund and "
                  "the within-24-hours penalty. Other upheld: full refund, no penalty. Dismissed: the ride carries on "
                  "and completes as normal.",
    )
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), max_length=1000, help_text="Shown in the trip log.")

    class Meta:
        model = ProblemReport
        fields = []

    def clean_note(self):
        note = " ".join(self.cleaned_data["note"].split())
        if not note:
            raise forms.ValidationError("Explain the decision.")
        return note


@admin.register(ProblemReport)
class ProblemReportAdmin(admin.ModelAdmin):
    """Open reports are decided here (uphold or dismiss, with a note). Decided reports are read-only."""

    list_display = ["created_at", "booking", "party", "kind", "status", "resolved_at"]
    list_filter = ["status", "kind", "party"]
    search_fields = ["booking__id", "raised_by__phone", "raised_by__name"]
    readonly_fields = [
        "booking", "raised_by", "party", "kind", "details", "status", "resolution_note", "resolved_by",
        "resolved_at", "created_at",
    ]

    def get_form(self, request, obj=None, **kwargs):
        if obj is not None and obj.status == ProblemStatus.OPEN:
            kwargs["form"] = ProblemDecisionForm
        return super().get_form(request, obj, **kwargs)

    def get_fields(self, request, obj=None):
        fields = list(self.readonly_fields)
        if obj is not None and obj.status == ProblemStatus.OPEN:
            fields += ["decision", "note"]
        return fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return obj is None or obj.status == ProblemStatus.OPEN

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        from .completion import resolve_problem

        resolve_problem(obj.pk, request.user, uphold=form.cleaned_data["decision"] == "uphold", note=form.cleaned_data["note"])

    def save_related(self, request, form, formsets, change):
        pass  # nothing else on the form is editable
