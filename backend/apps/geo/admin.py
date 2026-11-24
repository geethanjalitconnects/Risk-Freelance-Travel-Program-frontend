from django.contrib import admin
from django.utils import timezone

from .models import City, DistanceSource, MeetingPoint, RouteProfile


class MeetingPointInline(admin.TabularInline):
    model = MeetingPoint
    extra = 0


@admin.register(City)
class AreaAdmin(admin.ModelAdmin):
    """Areas (taluks) are created when someone first picks a place in them. Add meeting points
    here; they appear in the pickup / drop-off dropdowns when publishing."""

    list_display = ["name", "district", "state", "code", "coast", "is_active", "created_at"]
    list_filter = ["state", "coast", "is_active"]
    search_fields = ["code", "name", "district", "state"]
    readonly_fields = ["code", "created_at"]
    inlines = [MeetingPointInline]


@admin.register(RouteProfile)
class RouteProfileAdmin(admin.ModelAdmin):
    list_display = ["city_a", "city_b", "km", "km_source", "incident_index", "highway_share", "ghat_sections", "updated_at"]
    list_filter = ["km_source", "ghat_sections"]
    search_fields = ["city_a__name", "city_b__name", "city_a__code", "city_b__code"]
    readonly_fields = ["km_source", "km_updated_at", "updated_at"]

    def save_model(self, request, obj, form, change):
        # Marks the distance as set by an admin.
        if "km" in form.changed_data:
            obj.km_source = DistanceSource.MANUAL
            obj.km_updated_at = timezone.now()
        super().save_model(request, obj, form, change)
