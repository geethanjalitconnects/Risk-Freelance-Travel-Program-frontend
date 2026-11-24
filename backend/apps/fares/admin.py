from django.contrib import admin
from django.http import HttpResponseRedirect
from django.urls import reverse

from .models import FareSettings


@admin.register(FareSettings)
class FareSettingsAdmin(admin.ModelAdmin):
    """One settings page: the list view goes straight to the single record."""

    fieldsets = (
        (None, {
            "fields": ("rate_per_km", "min_fare_floor", "rounding_step", "max_increase_percent"),
            "description": "Changes apply to rides published or edited from now on. Existing rides keep their fare "
                           "until edited, and rides with bookings can't change their fare.",
        }),
        ("Last change", {"fields": ("updated_at", "updated_by")}),
    )
    readonly_fields = ["updated_at", "updated_by"]

    def changelist_view(self, request, extra_context=None):
        obj = FareSettings.load()
        return HttpResponseRedirect(reverse("admin:fares_faresettings_change", args=[obj.pk]))

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
