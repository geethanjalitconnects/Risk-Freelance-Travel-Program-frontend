"""Proxy endpoints for Google Places. The browser never sees the API key.

GET /api/v1/places/autocomplete?q=<text>&session=<uuid>
GET /api/v1/places/details?placeId=<id>&session=<same uuid>

Errors are {"code", "detail"}. 503 codes (places_disabled / places_unavailable) tell the
frontend to show "location search unavailable".
"""
import hashlib
import re

from django.conf import settings
from django.core.cache import cache
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from django.db.models import Prefetch

from apps.geo.models import City, MeetingPoint
from apps.geo.serializers import AreaSerializer

from . import google, resolve
from .fields import PLACE_ID_RE
from .models import PlacesUsage, UsageKind

MIN_CHARS = 3
MAX_CHARS = 100
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,36}$")  # Google: URL-safe base64, at most 36 chars

UNAVAILABLE = "Location search is unavailable right now. Please try again in a moment."
NOT_INDIA_MSG = "Only places in India are supported."
UNKNOWN_MSG = "We couldn't recognise that place. Try a nearby town or area."


def _error(code, detail, status):
    return Response({"code": code, "detail": detail}, status=status)


def _guard(request):
    """Common checks; returns an error Response or None."""
    if not settings.PLACES_ENABLED or not google.configured():
        return _error("places_disabled", UNAVAILABLE, 503)
    session = request.query_params.get("session", "")
    if not SESSION_RE.match(session):
        return _error("bad_session", "Invalid search session.", 400)
    return None


class AutocompleteView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []  # public, like ride search; throttled per IP
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "places_autocomplete"

    def get(self, request):
        err = _guard(request)
        if err:
            return err
        q = " ".join(request.query_params.get("q", "").split())
        if len(q) < MIN_CHARS:
            return _error("too_short", f"Type at least {MIN_CHARS} characters.", 400)
        if len(q) > MAX_CHARS:
            return _error("too_long", f"Use at most {MAX_CHARS} characters.", 400)

        types = ",".join(settings.PLACES_PRIMARY_TYPES)
        key = "places:ac:" + hashlib.sha256(f"{types}|{q.lower()}".encode()).hexdigest()
        suggestions = cache.get(key)
        if suggestions is not None:
            PlacesUsage.bump(UsageKind.AUTOCOMPLETE_CACHED)
        else:
            try:
                suggestions = google.autocomplete(q, request.query_params["session"])
            except google.PlacesError:
                PlacesUsage.bump(UsageKind.ERROR)
                return _error("places_unavailable", UNAVAILABLE, 503)
            PlacesUsage.bump(UsageKind.AUTOCOMPLETE)
            cache.set(key, suggestions, settings.PLACES_CACHE_SECONDS)
        return Response({"suggestions": suggestions, "attribution": "Google Maps"})


class DetailsView(APIView):
    """Resolves a picked place to its area (taluk) and closes the autocomplete session.
    Coordinates stay on the server (PlaceCache, at most 30 days); the browser gets the area."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "places_details"

    def get(self, request):
        err = _guard(request)
        if err:
            return err
        place_id = request.query_params.get("placeId", "")
        if not PLACE_ID_RE.match(place_id):
            return _error("bad_place", "Invalid place.", 400)
        try:
            found = resolve.resolve(place_id, request.query_params["session"])
        except resolve.NotInIndia:
            return _error("not_india", NOT_INDIA_MSG, 400)
        except resolve.UnknownPlace:
            return _error("unknown_place", UNKNOWN_MSG, 400)
        except google.PlacesError as e:
            if e.status in (400, 404):
                return _error("bad_place", "That place couldn't be found. Please search again.", 400)
            return _error("places_unavailable", UNAVAILABLE, 503)
        area = City.objects.prefetch_related(
            Prefetch("meeting_points", queryset=MeetingPoint.objects.order_by("order", "name"))
        ).get(pk=found.area.pk)
        return Response({"placeId": place_id, "area": AreaSerializer(area).data})


class ReverseView(APIView):
    """"Use my current location": the area-level place at the browser's position.

    GET /api/v1/places/reverse?lat=<float>&lng=<float>
    The position is used for this one Google call and not stored; the resulting place is cached
    like a picked suggestion (coordinates of the place, at most 30 days).
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "places_reverse"

    def get(self, request):
        if not settings.PLACES_ENABLED or not google.configured():
            return _error("places_disabled", UNAVAILABLE, 503)
        try:
            lat = float(request.query_params.get("lat", ""))
            lng = float(request.query_params.get("lng", ""))
        except ValueError:
            return _error("bad_position", "Invalid position.", 400)
        lo, hi = google.INDIA_BIAS["rectangle"]["low"], google.INDIA_BIAS["rectangle"]["high"]
        if not (lo["latitude"] <= lat <= hi["latitude"] and lo["longitude"] <= lng <= hi["longitude"]):
            return _error("not_india", NOT_INDIA_MSG, 400)
        try:
            found = google.reverse_geocode(lat, lng)
        except google.PlacesError:
            PlacesUsage.bump(UsageKind.ERROR)
            return _error("places_unavailable", UNAVAILABLE, 503)
        PlacesUsage.bump(UsageKind.REVERSE)
        if not found:
            return _error("no_place", "We couldn't find a place at your location. Please type it instead.", 404)
        try:
            place = resolve.store(found["placeId"], found["components"], *found["location"])
        except resolve.NotInIndia:
            return _error("not_india", NOT_INDIA_MSG, 400)
        except resolve.UnknownPlace:
            return _error("no_place", "We couldn't find a place at your location. Please type it instead.", 404)
        area = City.objects.prefetch_related(
            Prefetch("meeting_points", queryset=MeetingPoint.objects.order_by("order", "name"))
        ).get(pk=place.area.pk)
        return Response({"placeId": place.place_id, "label": found["label"] or area.name, "area": AreaSerializer(area).data})
