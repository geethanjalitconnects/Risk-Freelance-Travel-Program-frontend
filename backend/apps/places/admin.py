from django.contrib import admin

from .models import PlaceCache, PlacesUsage


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PlacesUsage)
class PlacesUsageAdmin(ReadOnlyAdmin):
    list_display = ["day", "kind", "count"]
    list_filter = ["kind"]
    date_hierarchy = "day"

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PlaceCache)
class PlaceCacheAdmin(ReadOnlyAdmin):
    """Coordinates are deleted or refreshed by `refresh_place_cache` before 30 days."""

    list_display = ["place_id", "area", "fetched_at"]
    search_fields = ["place_id", "area__name", "area__district"]
    list_select_related = ["area"]
