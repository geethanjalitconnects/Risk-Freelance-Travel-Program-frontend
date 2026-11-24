"""Rides in the admin: read-mostly. Fare, seats and bookings can't be edited here; an admin can
cancel rides (which cancels their bookings and writes to each passenger's trip log)."""
from django import forms
from django.contrib import admin, messages
from django.template.response import TemplateResponse

from apps.bookings.models import Booking
from apps.bookings.services import TripError, admin_cancel_ride

from .models import Ride, RideStatus


class CancelRideForm(forms.Form):
    reason = forms.CharField(
        max_length=300, widget=forms.Textarea(attrs={"rows": 3, "cols": 70}),
        help_text="Written to each affected passenger's trip log.",
        error_messages={"required": "A reason is required."},
    )


class BookingInline(admin.TabularInline):
    model = Booking
    extra = 0
    can_delete = False
    fields = ["passenger", "seats", "total", "status", "created_at", "rating"]
    readonly_fields = fields
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Ride)
class RideAdmin(admin.ModelAdmin):
    list_display = ["route", "depart", "driver", "price", "seats_total", "travel_with", "status", "created_at"]
    list_filter = ["status", "travel_with", ("depart", admin.DateFieldListFilter), "origin", "destination"]
    search_fields = ["id", "driver__phone", "driver__name"]
    list_select_related = ["driver", "origin", "destination"]
    date_hierarchy = "depart"
    inlines = [BookingInline]
    actions = ["cancel_selected"]
    fieldsets = (
        ("Trip", {"fields": ("driver", "origin", "destination", "pickup", "dropoff", "depart", "arrive", "duration_min", "km")}),
        ("Offer", {"fields": ("price", "seats_total", "travel_with", "ac", "bags", "notes")}),
        ("Vehicle", {"fields": ("vehicle_model", "vehicle_year", "vehicle_features")}),
        ("Status", {"fields": ("status", "created_at", "updated_at", "cancelled_at", "cancelled_by", "cancellation_reason")}),
    )
    readonly_fields = [f for fs in fieldsets for f in fs[1]["fields"]]

    @admin.display(description="Route")
    def route(self, obj):
        return f"{obj.origin.name} → {obj.destination.name}"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False  # read-only; cancellation is an action

    def has_delete_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.has_perm("rides.change_ride"):
            actions.pop("cancel_selected", None)
        return actions

    @admin.action(description="Cancel selected rides (cancels their bookings; reason required)")
    def cancel_selected(self, request, queryset):
        rides = list(queryset.filter(status=RideStatus.ACTIVE).select_related("origin", "destination", "driver"))
        if not rides:
            self.message_user(request, "None of the selected rides is active.", messages.WARNING)
            return None
        form = CancelRideForm(request.POST if "confirm" in request.POST else None)
        if "confirm" in request.POST and form.is_valid():
            cancelled_rides = cancelled_bookings = 0
            for ride in rides:
                try:
                    cancelled_bookings += admin_cancel_ride(ride, request.user, form.cleaned_data["reason"])
                    cancelled_rides += 1
                except TripError as e:
                    self.message_user(request, f"{ride}: {e.message}", messages.ERROR)
            self.message_user(
                request, f"Cancelled {cancelled_rides} ride(s) and {cancelled_bookings} booking(s).", messages.SUCCESS
            )
            return None
        return TemplateResponse(request, "admin/rides/ride/cancel.html", {
            **self.admin_site.each_context(request),
            "title": "Cancel rides",
            "opts": self.model._meta,
            "rides": rides,
            "open_bookings": Booking.objects.not_cancelled().filter(ride__in=rides, status__in=["confirmed", "in_progress"]).count(),
            "form": form,
            "selected_ids": [str(r.pk) for r in rides],
        })
