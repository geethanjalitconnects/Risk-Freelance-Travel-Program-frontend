"""Trip risk model: a faithful port of frontend src/lib/risk.js.

Score runs 0-100, where LOWER is safer. The output dict has the same structure the React
components render (``RiskBreakdown``, ``RiskBadge``, ``ScoreDial``); keys are snake_case here and
camelCased by the API renderer. Parity with the JS version is checked by
apps/risk/tests/test_parity.py against fixtures generated from the frontend code itself.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from common.jsmath import js_num_str, js_round

BANDS = [
    {"key": "low", "label": "Low", "max": 30},
    {"key": "moderate", "label": "Moderate", "max": 50},
    {"key": "elevated", "label": "Elevated", "max": 70},
    {"key": "high", "label": "High", "max": 101},
]

VEHICLE_FEATURES = {
    "airbags": "Airbags",
    "abs": "ABS brakes",
    "dashcam": "Dashcam",
    "gps": "GPS tracker",
    "firstaid": "First-aid kit",
}


def band_for(score: float) -> dict:
    return dict(next(b for b in BANDS if score < b["max"]))


def _clamp(n, lo=0, hi=100):
    return max(lo, min(hi, n))


@dataclass
class DriverProfile:
    verified_id: bool = False
    verified_license: bool = False
    rating: Optional[float] = None
    trips: int = 0


@dataclass
class VehicleProfile:
    year: Optional[int] = None
    features: list = field(default_factory=list)


@dataclass
class Route:
    """The risk inputs of a corridor (normally a geo.RouteProfile row)."""

    km: int
    incident_index: float
    highway_share: int
    ghat_sections: int

    @property
    def hours(self) -> float:
        return self.km / 58


@dataclass
class Place:
    coast: str  # east / west / inland


def city_weather_risk(coast: str, month_idx: int) -> int:
    """Illustrative seasonal rain risk (0-100). ``month_idx`` is 0-based like JS getMonth()."""
    north_east = 9 <= month_idx <= 11
    south_west = 5 <= month_idx <= 8
    if coast == "east":
        return 65 if north_east else 12
    if coast == "west":
        return 75 if south_west else 12
    if south_west:
        return 45
    return 28 if north_east else 12


def driver_risk(driver: Optional[DriverProfile]) -> dict:
    if driver is None:
        return {"value": 30, "detail": "Assumes a verified driver (no driver selected)."}
    v = 70
    notes = []
    if driver.verified_id:
        v -= 22
        notes.append("ID verified")
    else:
        notes.append("ID not verified")
    if driver.verified_license:
        v -= 18
        notes.append("licence verified")
    else:
        notes.append("licence not verified")
    if driver.rating:
        v -= (_clamp(driver.rating, 3, 5) - 3) * 8
        notes.append(f"{driver.rating:.1f} rating")
    else:
        notes.append("no ratings yet")
    if driver.trips >= 100:
        v -= 8
    elif driver.trips >= 25:
        v -= 4
    notes.append(f"{driver.trips} trips")
    return {"value": _clamp(v, 8, 95), "detail": ", ".join(notes) + "."}


def vehicle_risk(vehicle: Optional[VehicleProfile], current_year: int) -> dict:
    if vehicle is None:
        return {"value": 40, "detail": "Assumes a typical vehicle (none selected)."}
    v = 75
    feats = [f for f in (vehicle.features or []) if f in VEHICLE_FEATURES]
    v -= len(feats) * 10
    age = current_year - int(vehicle.year or current_year)
    if age <= 5:
        v -= 10
    elif age > 12:
        v += 10
    feat_text = ", ".join(VEHICLE_FEATURES[f] for f in feats) if feats else "no safety extras listed"
    age_text = "New" if age <= 0 else f"{age}-year-old"
    return {"value": _clamp(v, 10, 95), "detail": f"{age_text} vehicle, {feat_text}."}


def score_trip(
    *,
    route: Route,
    origin: Place,
    destination: Place,
    depart: datetime,
    driver: Optional[DriverProfile],
    vehicle: Optional[VehicleProfile],
    current_year: Optional[int] = None,
) -> dict:
    """Score one trip. ``depart`` must be a naive local (Asia/Kolkata) datetime."""
    if current_year is None:
        from django.utils import timezone

        current_year = timezone.localdate().year

    hours = route.hours
    start_hour = depart.hour + depart.minute / 60

    # Share of the drive that falls at night or dusk, sampled every 15 minutes.
    steps = max(1, math.ceil(hours * 4))
    night = dusk = 0
    for i in range(steps):
        h = (start_hour + i / 4) % 24
        if h >= 22 or h < 5:
            night += 1
        elif (19 <= h < 22) or (5 <= h < 6.5):
            dusk += 1
    night_share = night / steps
    dusk_share = dusk / steps
    time_value = _clamp(12 + night_share * 80 + dusk_share * 30)

    if hours <= 4:
        fatigue_value = 10
    elif hours <= 7:
        fatigue_value = 10 + (hours - 4) * 10
    else:
        fatigue_value = 40 + (hours - 7) * 12
    fatigue_value = _clamp(fatigue_value, 0, 95)

    month = depart.month - 1
    weather_value = max(city_weather_risk(origin.coast, month), city_weather_risk(destination.coast, month))

    d = driver_risk(driver)
    v = vehicle_risk(vehicle, current_year)

    ghat = route.ghat_sections
    ghat_text = f", {ghat} ghat/hill section{'s' if ghat > 1 else ''}" if ghat else ""
    if night_share > 0:
        time_detail = f"{js_round(night_share * 100)}% of the drive is between 10 pm and 5 am."
    elif dusk_share > 0:
        time_detail = f"{js_round(dusk_share * 100)}% of the drive is at dusk or dawn."
    else:
        time_detail = "The whole drive is in daylight."
    if weather_value >= 50:
        weather_detail = "Heavy seasonal rain likely along this route."
    elif weather_value >= 25:
        weather_detail = "Some seasonal rain possible."
    else:
        weather_detail = "No major seasonal weather risk."

    components = [
        {
            "key": "route",
            "label": "Route",
            "weight": 0.25,
            "value": js_round(route.incident_index * 10),
            "detail": f"Incident index {js_num_str(route.incident_index)}/10, {route.highway_share}% highway{ghat_text}.",
        },
        {"key": "time", "label": "Time of day", "weight": 0.2, "value": js_round(time_value), "detail": time_detail},
        {"key": "driver", "label": "Driver", "weight": 0.2, "value": js_round(d["value"]), "detail": d["detail"]},
        {"key": "weather", "label": "Weather", "weight": 0.15, "value": js_round(weather_value), "detail": weather_detail},
        {
            "key": "fatigue",
            "label": "Drive length",
            "weight": 0.1,
            "value": js_round(fatigue_value),
            "detail": f"{route.km} km, about {math.floor(hours)}h {js_round((hours % 1) * 60)}m of driving.",
        },
        {"key": "vehicle", "label": "Vehicle", "weight": 0.1, "value": js_round(v["value"]), "detail": v["detail"]},
    ]

    total = 0
    for c in components:  # same summation order as the JS reduce()
        total += c["value"] * c["weight"]
    score = js_round(total)

    tips = []
    if night_share > 0.25:
        tips.append("Share the live trip with a trusted contact and agree on a lit mid-way stop.")
    if weather_value >= 50:
        tips.append("Rain is likely: allow extra time and ask the driver to keep to a safe speed.")
    if fatigue_value >= 45:
        tips.append("Long drive: plan a break about every two hours.")
    if components[0]["value"] >= 60:
        tips.append("This corridor has a higher incident index. Keep check-ins switched on.")
    if d["value"] >= 50:
        tips.append("Driver has thin verification history. A verified-ID, verified-licence driver lowers risk.")
    if v["value"] >= 55:
        tips.append("Few safety features listed. Confirm seat belts work for every seat before you set off.")
    tips.append("Start the trip in My trips to get scheduled check-ins and one-tap SOS.")

    return {
        "score": score,
        "band": band_for(score),
        "components": components,
        "tips": tips,
        "profile": {
            "km": route.km,
            "hours": hours,
            "incident_index": route.incident_index,
            "highway_share": route.highway_share,
            "ghat_sections": route.ghat_sections,
        },
    }
