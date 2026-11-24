from django.db.models import Prefetch
from rest_framework import generics
from rest_framework.permissions import AllowAny

from .models import City, MeetingPoint
from .serializers import AreaSerializer


class AreaDetailView(generics.RetrieveAPIView):
    """One area (taluk) with its meeting points, used by the Publish page."""

    serializer_class = AreaSerializer
    permission_classes = [AllowAny]
    lookup_field = "code"
    queryset = City.objects.filter(is_active=True).prefetch_related(
        Prefetch("meeting_points", queryset=MeetingPoint.objects.order_by("order", "name"))
    )
