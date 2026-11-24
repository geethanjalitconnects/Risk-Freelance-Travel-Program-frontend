from django.db import models
from django.db.models import F, Q


class Coast(models.TextChoices):
    EAST = "east", "East coast (north-east monsoon)"
    WEST = "west", "West coast (south-west monsoon)"
    INLAND = "inland", "Inland"


class City(models.Model):
    code = models.CharField(max_length=3, primary_key=True)
    name = models.CharField(max_length=80, unique=True)
    state = models.CharField(max_length=80)
    lat = models.FloatField()
    lng = models.FloatField()
    coast = models.CharField(max_length=6, choices=Coast.choices)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "cities"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class MeetingPoint(models.Model):
    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name="meeting_points")
    name = models.CharField(max_length=120)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["city", "order", "name"]
        constraints = [models.UniqueConstraint(fields=["city", "name"], name="uniq_meeting_point_per_city")]

    def __str__(self):
        return self.name


class DistanceSource(models.TextChoices):
    ESTIMATE = "estimate", "Estimate (straight line x 1.28)"
    ORS = "ors", "OpenRouteService road distance"
    MANUAL = "manual", "Set by an admin"


class RouteProfileQuerySet(models.QuerySet):
    def between(self, code_a: str, code_b: str):
        a, b = sorted([code_a, code_b])
        return self.filter(city_a_id=a, city_b_id=b)


class RouteProfile(models.Model):
    """Risk inputs for a city pair. Undirected: stored once with city_a.code < city_b.code."""

    city_a = models.ForeignKey(City, on_delete=models.CASCADE, related_name="+")
    city_b = models.ForeignKey(City, on_delete=models.CASCADE, related_name="+")
    km = models.PositiveIntegerField(help_text="Road distance used for fares, duration and risk.")
    km_source = models.CharField(max_length=8, choices=DistanceSource.choices, default=DistanceSource.ESTIMATE)
    km_updated_at = models.DateTimeField(null=True, blank=True)
    incident_index = models.FloatField(help_text="0-10, higher means more incidents on the corridor.")
    highway_share = models.PositiveSmallIntegerField(help_text="Percent of the drive on highways.")
    ghat_sections = models.PositiveSmallIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    objects = RouteProfileQuerySet.as_manager()

    class Meta:
        ordering = ["city_a", "city_b"]
        constraints = [
            models.UniqueConstraint(fields=["city_a", "city_b"], name="uniq_route_pair"),
            models.CheckConstraint(condition=Q(city_a__lt=F("city_b")), name="route_pair_ordered"),
        ]

    def __str__(self):
        return f"{self.city_a_id} - {self.city_b_id}"

    @property
    def hours(self) -> float:
        from .routing import AVERAGE_SPEED_KMH

        return self.km / AVERAGE_SPEED_KMH
