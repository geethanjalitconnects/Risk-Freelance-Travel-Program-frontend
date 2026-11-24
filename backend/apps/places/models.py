"""Place cache (coordinates kept at most 30 days) and daily usage counters."""
from django.db import models
from django.db.models import F


class PlaceCache(models.Model):
    """A picked Google place: its area and coordinates. Google allows coordinates to be cached for
    at most 30 consecutive days, so rows are re-fetched or deleted by `refresh_place_cache`
    (PLACES_COORDINATE_DAYS, default 29). The place ID itself may be kept indefinitely."""

    place_id = models.CharField(max_length=300, primary_key=True)
    area = models.ForeignKey("geo.City", on_delete=models.CASCADE, related_name="+")
    lat = models.FloatField()
    lng = models.FloatField()
    fetched_at = models.DateTimeField()

    class Meta:
        verbose_name = "cached place (coordinates expire)"
        verbose_name_plural = "cached places (coordinates expire)"
        indexes = [models.Index(fields=["fetched_at"])]

    def __str__(self):
        return f"{self.place_id} → {self.area}"


class UsageKind(models.TextChoices):
    AUTOCOMPLETE = "autocomplete", "Autocomplete call to Google"
    DETAILS = "details", "Place Details call to Google"
    AUTOCOMPLETE_CACHED = "autocomplete_cached", "Autocomplete answered from cache"
    DETAILS_CACHED = "details_cached", "Place Details answered from cache"
    REVERSE = "reverse", "Reverse geocoding call to Google (current location)"
    ERROR = "error", "Google call failed"


class PlacesUsage(models.Model):
    """Daily call counters, to watch Google cost from the admin."""

    day = models.DateField()
    kind = models.CharField(max_length=24, choices=UsageKind.choices)
    count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-day", "kind"]
        verbose_name_plural = "places usage"
        constraints = [models.UniqueConstraint(fields=["day", "kind"], name="uniq_places_usage_day_kind")]

    def __str__(self):
        return f"{self.day} {self.kind}: {self.count}"

    @classmethod
    def bump(cls, kind, day=None):
        from django.utils import timezone

        day = day or timezone.localdate()
        row, _ = cls.objects.get_or_create(day=day, kind=kind)
        cls.objects.filter(pk=row.pk).update(count=F("count") + 1)
