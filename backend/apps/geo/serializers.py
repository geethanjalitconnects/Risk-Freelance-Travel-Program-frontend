from rest_framework import serializers

from .models import City


class CitySerializer(serializers.ModelSerializer):
    meeting_points = serializers.SlugRelatedField(many=True, read_only=True, slug_field="name")

    class Meta:
        model = City
        fields = ["code", "name", "state", "lat", "lng", "coast", "meeting_points"]
