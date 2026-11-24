"""Test fixture: 14 sample areas with meeting points, route profiles and cached place coordinates.

Only for tests. Areas in real use are created from picked places (apps.places.resolve).
"""
from itertools import combinations
from types import SimpleNamespace

from django.db import transaction
from django.utils import timezone

from .data import CITIES, MEETING_POINT_SUFFIXES
from .models import City, DistanceSource, MeetingPoint, RouteProfile
from .routing import compute_route_profile


def place_id(code: str) -> str:
    """The fake Google place ID that stands for a sample area in tests."""
    return f"ChIJtest{code}place"


def by_name(name: str) -> str:
    return place_id(next(c["code"] for c in CITIES if c["name"] == name))


def point(code: str):
    row = next(c for c in CITIES if c["code"] == code)
    return SimpleNamespace(code=code, lat=row["lat"], lng=row["lng"])


@transaction.atomic
def seed_geo(overwrite_routes: bool = False) -> dict:
    from apps.places.models import PlaceCache

    cities = []
    for row in CITIES:
        city, _ = City.objects.update_or_create(
            code=row["code"],
            defaults={"name": row["name"], "district": row["name"], "state": row["state"], "coast": row["coast"]},
        )
        cities.append(city)
        for order, suffix in enumerate(MEETING_POINT_SUFFIXES):
            MeetingPoint.objects.update_or_create(city=city, name=f"{city.name} {suffix}", defaults={"order": order})
        PlaceCache.objects.update_or_create(
            place_id=place_id(row["code"]),
            defaults={"area": city, "lat": row["lat"], "lng": row["lng"], "fetched_at": timezone.now()},
        )

    created = 0
    for a, b in combinations(sorted(cities, key=lambda c: c.code), 2):
        values = compute_route_profile(point(a.code), point(b.code))
        if overwrite_routes:
            RouteProfile.objects.update_or_create(
                city_a=a, city_b=b, defaults={**values, "km_source": DistanceSource.ESTIMATE, "km_updated_at": None}
            )
        else:
            _, was_created = RouteProfile.objects.get_or_create(city_a=a, city_b=b, defaults=values)
            created += was_created
    return {"cities": len(cities), "routes_created": created}
