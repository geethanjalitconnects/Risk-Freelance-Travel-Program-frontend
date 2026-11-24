from itertools import combinations

from django.db import transaction

from .data import CITIES, MEETING_POINT_SUFFIXES
from .models import City, DistanceSource, MeetingPoint, RouteProfile
from .routing import compute_route_profile


@transaction.atomic
def seed_geo(overwrite_routes: bool = False) -> dict:
    """Idempotently load cities, meeting points and route profiles.

    Existing route profiles are left alone unless ``overwrite_routes`` is set, so real incident
    data entered in the admin is not replaced by the demo values.
    """
    cities = []
    for row in CITIES:
        city, _ = City.objects.update_or_create(code=row["code"], defaults={k: v for k, v in row.items() if k != "code"})
        cities.append(city)
        for order, suffix in enumerate(MEETING_POINT_SUFFIXES):
            MeetingPoint.objects.update_or_create(
                city=city, name=f"{city.name} {suffix}", defaults={"order": order}
            )

    created = 0
    for a, b in combinations(sorted(cities, key=lambda c: c.code), 2):
        values = compute_route_profile(a, b)
        if overwrite_routes:
            RouteProfile.objects.update_or_create(
                city_a=a, city_b=b, defaults={**values, "km_source": DistanceSource.ESTIMATE, "km_updated_at": None}
            )
        else:
            _, was_created = RouteProfile.objects.get_or_create(city_a=a, city_b=b, defaults=values)
            created += was_created
    return {"cities": len(cities), "routes_created": created}
