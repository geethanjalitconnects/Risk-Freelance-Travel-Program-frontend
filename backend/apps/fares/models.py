from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class FareSettings(models.Model):
    """The single fare-settings record (edited in the admin). Changes apply to rides created or
    edited afterwards; existing rides keep their fare until they are edited."""

    rate_per_km = models.DecimalField(
        max_digits=7, decimal_places=2, default=Decimal("15.00"),
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Rupees per km per seat. Minimum fare = rate x route distance.",
    )
    min_fare_floor = models.PositiveIntegerField(
        default=50, validators=[MinValueValidator(1)], help_text="No seat costs less than this (Rs), even on short routes."
    )
    rounding_step = models.PositiveIntegerField(
        default=10, validators=[MinValueValidator(1)],
        help_text="Fares are multiples of this (Rs). The minimum rounds up, the maximum rounds down.",
    )
    max_increase_percent = models.PositiveSmallIntegerField(
        default=50, validators=[MaxValueValidator(500)],
        help_text="How far above the minimum a driver may price a seat (50 = up to 150% of the minimum).",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = "fare settings"
        verbose_name_plural = "fare settings"

    def __str__(self):
        return f"Rs {self.rate_per_km}/km, +{self.max_increase_percent}% max"

    def save(self, *args, **kwargs):
        self.pk = 1  # a single record
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "FareSettings":
        """The settings record; created with the defaults above the first time it's needed."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
