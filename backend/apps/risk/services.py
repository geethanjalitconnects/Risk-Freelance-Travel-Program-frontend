"""Glue between the database (cities, route profiles, users) and the pure scoring model."""
from datetime import datetime
from typing import Optional

from django.utils import timezone

from apps.geo.models import RouteProfile
from apps.geo.routing import compute_route_profile, road_km

from .scoring import DriverProfile, Route, VehicleProfile, score_trip


def route_between(origin, destination, km: Optional[int] = None) -> Route:
    """Route risk inputs for two areas (City) or picked places (places.resolve.Resolved).

    ``km`` is the ride's distance; when omitted it is estimated from the places' coordinates.
    Incident index, highway share and ghat sections come from a RouteProfile row an admin has
    entered for the two areas, otherwise from the deterministic default.
    """
    if km is None:
        km = road_km(origin, destination)
    row = RouteProfile.objects.between(origin.code, destination.code).first()
    if row:
        return Route(
            km=km,
            incident_index=row.incident_index,
            highway_share=row.highway_share,
            ghat_sections=row.ghat_sections,
        )
    return Route(**compute_route_profile(origin, destination, km))


def to_local_naive(dt: datetime) -> datetime:
    """Aware datetime -> naive Asia/Kolkata wall-clock time (what the model reasons about)."""
    if timezone.is_aware(dt):
        dt = timezone.localtime(dt)
    return dt.replace(tzinfo=None)


def score(
    origin,
    destination,
    depart: datetime,
    driver: Optional[DriverProfile],
    vehicle: Optional[VehicleProfile],
    route: Optional[Route] = None,
) -> dict:
    """Score a trip between two areas or picked places (anything with ``code`` and ``coast``).
    Pass ``route`` when the ride's distance is known (always for stored rides)."""
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
