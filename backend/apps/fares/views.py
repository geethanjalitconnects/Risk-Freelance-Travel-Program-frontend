from djangorestframework_camel_case.util import underscoreize
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.places.fields import PlaceField
from apps.risk.serializers import SAME_AREA
from apps.risk.services import route_between
from common.serializers import FromFieldMixin

from .services import fare_range


class QuoteInputSerializer(FromFieldMixin, serializers.Serializer):
    origin = PlaceField()
    to = PlaceField()

    def validate(self, attrs):
        if attrs["from"].area == attrs["to"].area:
            raise serializers.ValidationError({"to": SAME_AREA})
        return attrs


FareQuote = inline_serializer(
    "FareQuote",
    {
        "km": serializers.IntegerField(),
        "min_fare": serializers.IntegerField(),
        "max_fare": serializers.IntegerField(),
        "rate_per_km": serializers.DecimalField(max_digits=7, decimal_places=2),
        "max_increase_percent": serializers.IntegerField(),
    },
)


class FareQuoteView(APIView):
    """Allowed fare range per seat for a route (shown and enforced on the Publish page)."""

    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter("from", OpenApiTypes.STR, required=True, description="Google place ID"),
            OpenApiParameter("to", OpenApiTypes.STR, required=True, description="Google place ID"),
        ],
        responses=FareQuote,
    )
    def get(self, request):
        s = QuoteInputSerializer(data=underscoreize(request.query_params.dict()))
        s.is_valid(raise_exception=True)
        km = route_between(s.validated_data["from"], s.validated_data["to"]).km
        return Response(quote(km))


def quote(km: int) -> dict:
    r = fare_range(km)
    return {
        "km": r.km, "min_fare": r.min_fare, "max_fare": r.max_fare,
        "rate_per_km": str(r.rate_per_km), "max_increase_percent": r.max_increase_percent,
    }
