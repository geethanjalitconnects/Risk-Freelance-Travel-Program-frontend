"""Fare rules: minimum = rate x km (rounded up to the step, at least the floor), maximum =
minimum + max_increase_percent (rounded down to the step, never below the minimum)."""
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from .models import FareSettings


@dataclass(frozen=True)
class FareRange:
    km: int
    min_fare: int
    max_fare: int
    rate_per_km: Decimal
    max_increase_percent: int

    def contains(self, price: int) -> bool:
        return self.min_fare <= price <= self.max_fare

    def error_for(self, price: int):
        if price < self.min_fare:
            return f"The fare must be at least ₹{self.min_fare} per seat for this {self.km} km route."
        if price > self.max_fare:
            return (
                f"The fare can be at most ₹{self.max_fare} per seat for this route "
                f"({self.max_increase_percent}% above the ₹{self.min_fare} minimum)."
            )
        return None


def _round(value: Decimal, step: int, mode) -> int:
    step = Decimal(step)
    return int((value / step).to_integral_value(rounding=mode) * step)


def fare_range(km: int, settings: FareSettings = None) -> FareRange:
    s = settings or FareSettings.load()
    raw_min = s.rate_per_km * Decimal(km)
    minimum = max(Decimal(s.min_fare_floor), Decimal(_round(raw_min, s.rounding_step, ROUND_CEILING)))
    raw_max = minimum * (Decimal(100) + Decimal(s.max_increase_percent)) / Decimal(100)
    maximum = max(minimum, Decimal(_round(raw_max, s.rounding_step, ROUND_FLOOR)))
    return FareRange(
        km=km, min_fare=int(minimum), max_fare=int(maximum),
        rate_per_km=s.rate_per_km, max_increase_percent=s.max_increase_percent,
    )
