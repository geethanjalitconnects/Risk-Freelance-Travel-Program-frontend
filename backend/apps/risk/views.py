from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.fares.views import quote
from apps.geo.routing import duration_minutes

from . import services
from .samples import SAMPLE_DRIVERS, SAMPLE_VEHICLES
from .scoring import BANDS, VEHICLE_FEATURES, DriverProfile, VehicleProfile
from .serializers import CalculatorInputSerializer, PreviewInputSerializer, PreviewOutSerializer, RiskSerializer


class RiskConfigView(APIView):
    """Risk bands and vehicle safety features (BANDS / VEHICLE_FEATURES in risk.js)."""

    permission_classes = [AllowAny]

    @extend_schema(
        responses=inline_serializer(
            "RiskConfig",
            {"bands": serializers.ListField(child=serializers.DictField()), "vehicle_features": serializers.DictField()},
        )
    )
    def get(self, request):
        return Response({"bands": BANDS, "vehicle_features": VEHICLE_FEATURES})


class RiskSamplesView(APIView):
    """Fictional sample drivers and vehicles used by the Risk program calculator."""

    permission_classes = [AllowAny]

    @extend_schema(
        responses=inline_serializer(
            "RiskSamples",
            {
                "drivers": serializers.ListField(child=serializers.DictField()),
                "vehicles": serializers.ListField(child=serializers.DictField()),
            },
        )
    )
    def get(self, request):
        return Response({"drivers": SAMPLE_DRIVERS, "vehicles": SAMPLE_VEHICLES})


class RiskScoreView(APIView):
    """Risk program calculator: score a trip with one of the sample drivers / vehicles.

    Omitting ``sampleDriver`` or ``sampleVehicle`` scores with the model's default assumption.
    """

    permission_classes = [AllowAny]

    @extend_schema(request=CalculatorInputSerializer, responses=RiskSerializer)
    def post(self, request):
        s = CalculatorInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        driver = vehicle = None
        if data.get("sample_driver") is not None:
            d = SAMPLE_DRIVERS[data["sample_driver"]]
            driver = DriverProfile(
                verified_id=d["verified_id"], verified_license=d["verified_license"], rating=d["rating"], trips=d["trips"]
            )
        if data.get("sample_vehicle") is not None:
            v = SAMPLE_VEHICLES[data["sample_vehicle"]]
            vehicle = VehicleProfile(year=v["year"], features=v["features"])

        return Response(services.score(data["from"], data["to"], data["depart"], driver, vehicle))


class RiskPreviewView(APIView):
    """Live risk preview on the Publish page, scored with the signed-in user as driver.

    Also returns the distance, driving time and the allowed fare range per seat.
    """

    permission_classes = [AllowAny]

    @extend_schema(request=PreviewInputSerializer, responses=PreviewOutSerializer)
    def post(self, request):
        s = PreviewInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        v = data.get("vehicle")
        vehicle = VehicleProfile(year=v.get("year"), features=v.get("features", [])) if v is not None else None
        route = services.route_between(data["from"], data["to"])
        fare = quote(route.km)
        risk = services.score(data["from"], data["to"], data["depart"], services.publishing_driver(request.user), vehicle)

        return Response(
            {
                "km": route.km,
                "duration_min": duration_minutes(route.km),
                "min_fare": fare["min_fare"],
                "max_fare": fare["max_fare"],
                "risk": risk,
            }
        )
