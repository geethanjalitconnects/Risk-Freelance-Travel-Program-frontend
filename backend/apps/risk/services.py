"""Glue between the database (cities, route profiles, users) and the pure scoring model."""
from datetime import datetime
from typing import Optional

from django.utils import timezone

from apps.geo.models import City, RouteProfile
from apps.geo.routing import compute_route_profile

from .scoring import DriverProfile, Route, VehicleProfile, score_trip


def route_between(origin: City, destination: City) -> Route:
    """Route risk inputs from the RouteProfile table, falling back to the demo formula."""
    row = RouteProfile.objects.between(origin.code, destination.code).first()
    if row:
        return Route(
            km=row.km,
            incident_index=row.incident_index,
            highway_share=row.highway_share,
            ghat_sections=row.ghat_sections,
        )
    return Route(**compute_route_profile(origin, destination))


def to_local_naive(dt: datetime) -> datetime:
    """Aware datetime -> naive Asia/Kolkata wall-clock time (what the model reasons about)."""
    if timezone.is_aware(dt):
        dt = timezone.localtime(dt)
    return dt.replace(tzinfo=None)


def score(
    origin: City,
    destination: City,
    depart: datetime,
    driver: Optional[DriverProfile],
    vehicle: Optional[VehicleProfile],
    route: Optional[Route] = None,
) -> dict:
    """Score a trip. Pass ``route`` when scoring many rides on one corridor to skip the lookup."""
    return score_trip(
        route=route or route_between(origin, destination),
        origin=origin,
        destination=destination,
        depart=to_local_naive(depart),
        driver=driver,
        vehicle=vehicle,
    )


def publishing_driver(user) -> DriverProfile:
    """The driver the Publish page previews: the signed-in user, or an unverified newcomer.

    Like the frontend, a ride being drafted is scored as a driver with no ratings and no trips.
    """
    if user is None or not user.is_authenticated:
        return DriverProfile()
    return DriverProfile(verified_id=user.verified_id, verified_license=user.verified_license)
