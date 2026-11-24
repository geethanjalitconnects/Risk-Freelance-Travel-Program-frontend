from rest_framework import serializers

from .models import City


class AreaSerializer(serializers.ModelSerializer):
    meeting_points = serializers.SlugRelatedField(many=True, read_only=True, slug_field="name")
    region = serializers.CharField(read_only=True)

    class Meta:
        model = City
        fields = ["code", "name", "district", "state", "region", "meeting_points"]
