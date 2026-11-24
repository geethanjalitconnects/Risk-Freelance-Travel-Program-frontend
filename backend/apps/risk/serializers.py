from rest_framework import serializers

from apps.places.fields import PlaceField
from common.serializers import FromFieldMixin

from .samples import SAMPLE_DRIVERS, SAMPLE_VEHICLES
from .scoring import VEHICLE_FEATURES

SAME_AREA = "Pick a destination in a different area from the start."


class TripInputSerializer(FromFieldMixin, serializers.Serializer):
    """``from`` / ``to`` (Google place IDs picked from the suggestions) and ``depart``
    ("YYYY-MM-DDTHH:mm", local time)."""

    origin = PlaceField()
    to = PlaceField()
    depart = serializers.DateTimeField()

    def validate(self, attrs):
        if attrs["from"].area == attrs["to"].area:
            raise serializers.ValidationError({"to": SAME_AREA})
        return attrs


class VehicleInputSerializer(serializers.Serializer):
    model = serializers.CharField(required=False, allow_blank=True, max_length=80)
    year = serializers.IntegerField(required=False, allow_null=True, min_value=1900, max_value=2100)
    features = serializers.ListField(
        child=serializers.ChoiceField(choices=list(VEHICLE_FEATURES)), required=False, default=list
    )


class PreviewInputSerializer(TripInputSerializer):
    vehicle = VehicleInputSerializer(required=False, allow_null=True)


class CalculatorInputSerializer(TripInputSerializer):
    sample_driver = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=len(SAMPLE_DRIVERS) - 1
    )
    sample_vehicle = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=len(SAMPLE_VEHICLES) - 1
    )


# ---- response shapes (documentation only; views return plain dicts) ----


class BandSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    max = serializers.IntegerField()


class ComponentSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    weight = serializers.FloatField()
    value = serializers.IntegerField()
    detail = serializers.CharField()


class RouteProfileOutSerializer(serializers.Serializer):
    km = serializers.IntegerField()
    hours = serializers.FloatField()
    incident_index = serializers.FloatField()
    highway_share = serializers.IntegerField()
    ghat_sections = serializers.IntegerField()


class RiskSerializer(serializers.Serializer):
    score = serializers.IntegerField()
    band = BandSerializer()
    components = ComponentSerializer(many=True)
    tips = serializers.ListField(child=serializers.CharField())
    profile = RouteProfileOutSerializer()


class PreviewOutSerializer(serializers.Serializer):
    km = serializers.IntegerField()
    duration_min = serializers.IntegerField()
    min_fare = serializers.IntegerField()
    max_fare = serializers.IntegerField()
    risk = RiskSerializer()
