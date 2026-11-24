from datetime import timedelta

from django.db import transaction
from django.http import Http404
from django.utils import timezone
from djangorestframework_camel_case.util import underscoreize
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.verification import services as verification_services
from common.exceptions import Conflict

from . import services
from .models import Ride, RideStatus, TravelWith
from .serializers import RideSearchSerializer, RideSerializer, RideWriteSerializer

# Search hides rides leaving within this window (same as searchRides() in the frontend).
SEARCH_CUTOFF = timedelta(minutes=30)

SORT_KEYS = {
    "earliest": lambda r: r.depart,
    "cheapest": lambda r: r.price,
    "safest": lambda r: r._risk["score"],
}


def _verification_block(user):
    """403 with a code the frontend maps to "submit documents" / "pending review" / "rejected"."""
    block = verification_services.publish_block(user)
    if block is None:
        return None
    return Response({"detail": block.message, "code": block.code}, status=status.HTTP_403_FORBIDDEN)


def _ride_response(request, ride, status_code=status.HTTP_200_OK):
    return Response(RideSerializer(services.load(ride.pk, request.user), context={"request": request, "contacts": True}).data, status=status_code)


class RideSearchView(APIView):
    """Rides on a route and date with enough free seats, each with its live risk score.

    Mirrors the Search page: rides leaving in the next 30 minutes are hidden, and the filters
    and sorts are the ones in the sidebar. Returns a plain array, like searchRides().
    """

    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter("from", OpenApiTypes.STR, required=True, description="City code or name"),
            OpenApiParameter("to", OpenApiTypes.STR, required=True, description="City code or name"),
            OpenApiParameter("date", OpenApiTypes.DATE, required=True),
            OpenApiParameter("seats", OpenApiTypes.INT, description="1-4, default 1"),
            OpenApiParameter("sort", OpenApiTypes.STR, enum=list(RideSearchSerializer.SORTS)),
            OpenApiParameter("verified", OpenApiTypes.BOOL, description="Ignored: search only lists rides of approved drivers"),
            OpenApiParameter("womenOnly", OpenApiTypes.BOOL, description="Same as travelWith=women"),
            OpenApiParameter("travelWith", OpenApiTypes.STR, enum=[c for c, _ in TravelWith.choices]),
            OpenApiParameter("daytime", OpenApiTypes.BOOL, description="Departures 6 am - 5 pm"),
            OpenApiParameter("maxRisk", OpenApiTypes.INT, description="Only scores below this (31, 51, 71)"),
        ],
        responses=RideSerializer(many=True),
    )
    def get(self, request):
        params = RideSearchSerializer(data=underscoreize(request.query_params.dict()))
        params.is_valid(raise_exception=True)
        p = params.validated_data

        candidates = (
            Ride.objects.for_display()
            .listed()  # approved, active drivers only
            .filter(
                origin=p["from"],
                destination=p["to"],
                depart__date=p["date"],
                depart__gt=timezone.now() + SEARCH_CUTOFF,
            )
            .order_by("depart")
        )
        rides = [r for r in candidates if r.seats_total - r.booked_seats >= p["seats"]]
        services.prepare(rides, request.user)

        # "verified" is accepted for compatibility; every listed ride already has an approved driver.
        travel_with = TravelWith.WOMEN if p["women_only"] else p.get("travel_with")
        if travel_with:
            rides = [r for r in rides if r.travel_with == travel_with]
        if p["daytime"]:
            rides = [r for r in rides if 6 <= timezone.localtime(r.depart).hour < 17]
        if p.get("max_risk") is not None:
            rides = [r for r in rides if r._risk["score"] < p["max_risk"]]
        rides.sort(key=SORT_KEYS[p["sort"]])  # stable, so ties stay in departure order

        return Response(RideSerializer(rides, many=True, context={"request": request}).data)


class RideCreateView(APIView):
    """Publish a ride. The signed-in user is the driver."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=RideWriteSerializer, responses={201: RideSerializer, 403: OpenApiTypes.OBJECT})
    def post(self, request):
        blocked = _verification_block(request.user)
        if blocked:
            return blocked
        s = RideWriteSerializer(data=request.data, context={"request": request})
        s.is_valid(raise_exception=True)
        ride = s.save()
        return _ride_response(request, ride, status.HTTP_201_CREATED)


class MyRidesView(APIView):
    """Rides I published (the "Rides you published" list on My trips)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=RideSerializer(many=True))
    def get(self, request):
        rides = list(Ride.objects.for_display().active().filter(driver=request.user).order_by("depart"))
        services.prepare(rides, request.user)
        return Response(RideSerializer(rides, many=True, context={"request": request, "contacts": True}).data)


class RideDetailView(APIView):
    """View a ride (anyone); edit or remove it (its driver only)."""

    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_permissions(self):
        return [AllowAny()] if self.request.method in ("GET", "HEAD", "OPTIONS") else [IsAuthenticated()]

    def _locked_own_ride(self, request, pk):
        """Lock the row so a concurrent booking can't slip in between the check and the write."""
        ride = Ride.objects.select_for_update().filter(pk=pk, status=RideStatus.ACTIVE).first()
        if ride is None:
            raise Http404
        if ride.driver_id != request.user.pk:
            raise PermissionDenied("Only the driver who published this ride can change it.")
        return ride

    @extend_schema(responses=RideSerializer)
    def get(self, request, pk):
        ride = services.load(pk, request.user)
        if ride is None:
            raise Http404
        return Response(RideSerializer(ride, context={"request": request, "contacts": True}).data)

    @extend_schema(request=RideWriteSerializer, responses={200: RideSerializer, 403: OpenApiTypes.OBJECT})
    def patch(self, request, pk):
        blocked = _verification_block(request.user)
        if blocked:
            return blocked
        with transaction.atomic():
            ride = self._locked_own_ride(request, pk)
            s = RideWriteSerializer(ride, data=request.data, partial=True, context={"request": request})
            s.is_valid(raise_exception=True)
            s.save()
        return _ride_response(request, ride)

    @extend_schema(responses={204: None, 409: OpenApiTypes.OBJECT})
    def delete(self, request, pk):
        with transaction.atomic():
            ride = self._locked_own_ride(request, pk)
            if ride.has_bookings():
                raise Conflict("This ride has bookings, so it can't be removed.")
            ride.status = RideStatus.CANCELLED
            ride.cancelled_at = timezone.now()
            ride.save(update_fields=["status", "cancelled_at", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)
