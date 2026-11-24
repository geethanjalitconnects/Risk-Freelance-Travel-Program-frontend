"""Turn a Google place ID into our area (taluk) and its coordinates.

Area rows are our own records (name, district, state) taken from the place's address. The
coordinates live in PlaceCache for at most PLACES_COORDINATE_DAYS (Google allows 30).
"""
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.geo.models import City
from apps.geo.regions import area_code, coast_for_state

from . import google
from .models import PlaceCache, PlacesUsage, UsageKind


class NotInIndia(Exception):
    pass


class UnknownPlace(Exception):
    """Google gave no usable state / area for the place."""


@dataclass
class Resolved:
    place_id: str
    area: City
    lat: float
    lng: float

    @property
    def code(self):  # what route-profile maths keys on
        return self.area.code

    @property
    def coast(self):  # what the weather model reads
        return self.area.coast


def _component(components, kind):
    return next((c for c in components if kind in c.get("types", [])), None)


def _text(components, *kinds):
    for kind in kinds:
        c = _component(components, kind)
        if c and (c.get("longText") or "").strip():
            return c["longText"].strip()
    return ""


def area_parts(components):
    """(name, district, state) from Google address components. Raises NotInIndia / UnknownPlace.

    The area is the taluk (administrative_area_level_3) when Google gives one, otherwise the
    locality, otherwise the district.
    """
    country = _component(components, "country")
    if not country or (country.get("shortText") or "").upper() != "IN":
        raise NotInIndia
    state = _text(components, "administrative_area_level_1")
    district = _text(components, "administrative_area_level_2")
    name = _text(components, "administrative_area_level_3", "locality", "sublocality_level_1", "sublocality",
                 "administrative_area_level_2")
    if not state or not name:
        raise UnknownPlace
    return name[:80], district[:80], state[:80]


def area_for(components) -> City:
    name, district, state = area_parts(components)
    code = area_code(state, district, name)
    existing = lambda: (  # noqa: E731
        City.objects.filter(code=code).first()
        or City.objects.filter(name__iexact=name, district__iexact=district, state__iexact=state).first()
    )
    area = existing()
    if area:
        return area
    try:
        with transaction.atomic():
            return City.objects.create(code=code, name=name, district=district, state=state, coast=coast_for_state(state))
    except IntegrityError:  # created by a parallel request
        return existing()


def max_age():
    return timedelta(days=settings.PLACES_COORDINATE_DAYS)


def resolve(place_id, session=None, *, refresh=False) -> Resolved:
    """Area and coordinates of a place: from PlaceCache while fresh, otherwise from Google
    (Place Details, Essentials fields). Raises NotInIndia, UnknownPlace or google.PlacesError."""
    row = PlaceCache.objects.select_related("area").filter(place_id=place_id).first()
    if row and not refresh and row.fetched_at >= timezone.now() - max_age():
        PlacesUsage.bump(UsageKind.DETAILS_CACHED)
        return Resolved(place_id, row.area, row.lat, row.lng)

    try:
        res = google.details(place_id, session or str(uuid.uuid4()))
    except google.PlacesError:
        PlacesUsage.bump(UsageKind.ERROR)
        raise
    PlacesUsage.bump(UsageKind.DETAILS)
    area = area_for(res.get("addressComponents") or [])
    loc = res.get("location") or {}
    if "latitude" not in loc or "longitude" not in loc:
        raise UnknownPlace
    PlaceCache.objects.update_or_create(
        place_id=place_id,
        defaults={"area": area, "lat": loc["latitude"], "lng": loc["longitude"], "fetched_at": timezone.now()},
    )
    return Resolved(place_id, area, loc["latitude"], loc["longitude"])


def cached_points(place_ids):
    """{place_id: (lat, lng)} for fresh cache rows only (no Google calls)."""
    cutoff = timezone.now() - max_age()
    rows = PlaceCache.objects.filter(place_id__in=set(place_ids), fetched_at__gte=cutoff)
    return {r.place_id: (r.lat, r.lng) for r in rows}


def store(place_id, components, lat, lng) -> Resolved:
    """Cache a place whose components and position are already known (reverse geocoding)."""
    area = area_for(components)
    PlaceCache.objects.update_or_create(
        place_id=place_id, defaults={"area": area, "lat": lat, "lng": lng, "fetched_at": timezone.now()},
    )
    return Resolved(place_id, area, lat, lng)
