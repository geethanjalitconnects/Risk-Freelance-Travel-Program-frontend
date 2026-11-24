import re

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.exceptions import APIException

from . import google
from .resolve import NotInIndia, Resolved, UnknownPlace, resolve

PLACE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,300}$")


class PlacesUnavailable(APIException):
    status_code = 503
    default_code = "places_unavailable"
    default_detail = "Location search is unavailable right now. Please try again in a moment."


@extend_schema_field(OpenApiTypes.STR)
class PlaceField(serializers.Field):
    """A Google place ID picked from the suggestions -> Resolved (area + coordinates).
    Serializes back to the area code."""

    default_error_messages = {
        "pick": "Pick a place from the suggestions.",
        "not_india": "Only places in India are supported.",
        "unknown": "We couldn't recognise that place. Try a nearby town or area.",
    }

    def to_internal_value(self, data):
        value = str(data or "").strip()
        if not PLACE_ID_RE.match(value):
            self.fail("pick")
        try:
            return resolve(value)
        except NotInIndia:
            self.fail("not_india")
        except UnknownPlace:
            self.fail("unknown")
        except google.PlacesError as e:
            if e.status in (400, 404):
                self.fail("pick")
            raise PlacesUnavailable() from None

    def to_representation(self, value):
        if isinstance(value, Resolved):
            return value.area.code
        return getattr(value, "code", value)
