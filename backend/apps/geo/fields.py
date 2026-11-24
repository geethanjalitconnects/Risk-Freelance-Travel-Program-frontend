from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import City


@extend_schema_field(OpenApiTypes.STR)
class CityField(serializers.Field):
    """Accepts a city code ("MAA") or a city name ("Chennai", any case); returns the City.

    The frontend sends names from the search form and codes from the risk calculator.
    Serializes back to the code, which is what ride objects carry in ``from`` / ``to``.
    """

    default_error_messages = {"unknown": "Pick a city from the list."}

    def to_internal_value(self, data):
        value = str(data or "").strip()
        city = (
            City.objects.filter(is_active=True, code=value.upper()).first()
            or City.objects.filter(is_active=True, name__iexact=value).first()
        )
        if not city:
            self.fail("unknown")
        return city

    def to_representation(self, value):
        return value.code if isinstance(value, City) else value
