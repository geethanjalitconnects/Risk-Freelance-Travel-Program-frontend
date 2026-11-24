from django.db.models import Prefetch
from rest_framework import generics
from rest_framework.permissions import AllowAny

from .models import City, MeetingPoint
from .serializers import CitySerializer


class CityListView(generics.ListAPIView):
    """All active cities with their meeting points (first one is the default pickup/drop-off)."""

    serializer_class = CitySerializer
    permission_classes = [AllowAny]
    pagination_class = None
    queryset = City.objects.filter(is_active=True).prefetch_related(
        Prefetch("meeting_points", queryset=MeetingPoint.objects.order_by("order", "name"))
    )


class CityDetailView(generics.RetrieveAPIView):
    serializer_class = CitySerializer
    permission_classes = [AllowAny]
    lookup_field = "code"
    queryset = CityListView.queryset
