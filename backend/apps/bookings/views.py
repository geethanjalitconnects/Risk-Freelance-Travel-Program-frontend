from django.conf import settings
from django.db import transaction
from django.db.models import Case, IntegerField, Value, When
from django.http import Http404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.rides.serializers import RideSerializer
from apps.rides.views import _ride_response

from . import cancellation, completion, services
from .models import BookingStatus
from .serializers import (
    BookingCreateSerializer,
    BookingOutSerializer,
    CancelQuoteOutSerializer,
    CheckInInputSerializer,
    PaymentVerifySerializer,
    ProblemInputSerializer,
    RideCancelInputSerializer,
    RideCancelQuoteOutSerializer,
    RateInputSerializer,
    RideCompleteInputSerializer,
    booking_queryset,
    serialize_bookings,
)

# Same order as the Trips page: live trip first, then upcoming, past, cancelled.
STATUS_RANK = Case(
    When(status=BookingStatus.IN_PROGRESS, then=Value(0)),
    When(status=BookingStatus.CONFIRMED, then=Value(1)),
    When(status=BookingStatus.COMPLETED, then=Value(2)),
    default=Value(3),
    output_field=IntegerField(),
)


def _error(err: services.TripError):
    return Response({"detail": err.message, "code": err.code}, status=err.status)


def _one(request, pk, status_code=status.HTTP_200_OK):
    booking = booking_queryset().filter(pk=pk, passenger=request.user).first()
    if booking is None:
        raise Http404
    return Response(serialize_bookings([booking])[0], status=status_code)


class BookingListView(APIView):
    """My bookings (GET) and book seats on a ride (POST).

    Booking is refused (409, with a ``code``) when the ride is full, has left, is your own,
    you already booked it, or its "Who can travel with me" setting doesn't match your gender.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=BookingOutSerializer(many=True))
    def get(self, request):
        bookings = list(
            booking_queryset().filter(passenger=request.user).annotate(rank=STATUS_RANK).order_by("rank", "-created_at")
        )
        return Response(serialize_bookings(bookings))

    @extend_schema(request=BookingCreateSerializer, responses={201: BookingOutSerializer, 409: OpenApiTypes.OBJECT})
    def post(self, request):
        s = BookingCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            booking = services.create_booking(request.user, s.validated_data["ride_id"], s.validated_data["seats"])
        except services.TripError as e:
            return _error(e)
        return _one(request, booking.pk, status.HTTP_201_CREATED)


class BookingDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=BookingOutSerializer)
    def get(self, request, pk):
        return _one(request, pk)


class BookingActionView(APIView):
    """Base for POST /bookings/<id>/<action>. Locks the booking, runs ``act`` and returns it."""

    permission_classes = [IsAuthenticated]
    input_serializer = None

    def act(self, booking, data):  # pragma: no cover - overridden
        raise NotImplementedError

    def post(self, request, pk):
        data = {}
        if self.input_serializer:
            s = self.input_serializer(data=request.data)
            s.is_valid(raise_exception=True)
            data = s.validated_data
        try:
            with transaction.atomic():
                self.act(services.locked_booking(pk, request.user), data)
        except services.TripError as e:
            return _error(e)
        return _one(request, pk)


def _doc(request=None):
    return extend_schema(request=request, responses={200: BookingOutSerializer, 409: OpenApiTypes.OBJECT})


class CancelView(BookingActionView):
    """Cancel a booking whose trip hasn't started. Frees the seats. A paid booking is refunded to
    the original payment method: 85% more than 24 h before departure, 90% within 24 h (see
    GET cancellation-quote for the exact amounts first)."""

    def act(self, booking, data):
        services.cancel(booking)

    @_doc()
    def post(self, request, pk):
        return super().post(request, pk)


class StartView(BookingActionView):
    """Start the protected trip: switches on check-ins, sharing and SOS."""

    def act(self, booking, data):
        services.start(booking)

    @_doc()
    def post(self, request, pk):
        return super().post(request, pk)


class CheckInView(BookingActionView):
    """Confirm the next checkpoint (pickup, mid, near, in that order)."""

    input_serializer = CheckInInputSerializer

    def act(self, booking, data):
        services.check_in(booking, data["key"])

    @_doc(CheckInInputSerializer)
    def post(self, request, pk):
        return super().post(request, pk)


class MissedCheckInView(BookingActionView):
    """Development only (404 unless DEBUG): simulate missing the next check-in."""

    def act(self, booking, data):
        services.mark_missed(booking)

    @_doc()
    def post(self, request, pk):
        if not settings.DEBUG:
            raise Http404
        return super().post(request, pk)


class ShareView(BookingActionView):
    """Create the live-trip link and text it to trusted contacts."""

    def act(self, booking, data):
        services.share(booking)

    @_doc()
    def post(self, request, pk):
        return super().post(request, pk)


class SosView(BookingActionView):
    """Raise an SOS: records it in the trip log and texts trusted contacts at once."""

    def act(self, booking, data):
        services.sos(booking)

    @_doc()
    def post(self, request, pk):
        return super().post(request, pk)


class CompleteView(BookingActionView):
    """Swipe "ride complete" as the passenger. The booking completes when the driver has confirmed
    too (or automatically 24 h after arrival if no problem is reported)."""

    def act(self, booking, data):
        completion.confirm_by_passenger(booking, booking.passenger)

    @_doc()
    def post(self, request, pk):
        return super().post(request, pk)


class RateView(BookingActionView):
    """Rate the driver 1-5 after a completed trip (once)."""

    input_serializer = RateInputSerializer

    def act(self, booking, data):
        services.rate(booking, data["stars"])

    @_doc(RateInputSerializer)
    def post(self, request, pk):
        return super().post(request, pk)


class ProblemView(BookingActionView):
    """Report a problem (driver didn't show up, or something else). Holds the driver's payment and
    stops the ride from completing until VConnects reviews it."""

    input_serializer = ProblemInputSerializer

    def act(self, booking, data):
        completion.report_by_passenger(booking, booking.passenger, data["kind"], data["details"])

    @_doc(ProblemInputSerializer)
    def post(self, request, pk):
        return super().post(request, pk)


class RideCompleteView(APIView):
    """The driver swipes "ride complete" for the whole ride. Passengers listed in ``noShow`` are
    reported as no-shows (allowed from 30 minutes after departure) instead of confirmed."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=RideCompleteInputSerializer, responses={200: RideSerializer, 409: OpenApiTypes.OBJECT})
    def post(self, request, pk):
        s = RideCompleteInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            ride = completion.complete_ride(pk, request.user, s.validated_data["no_show"], s.validated_data["note"])
        except services.TripError as e:
            return _error(e)
        return _ride_response(request, ride)


class CancelQuoteView(APIView):
    """What cancelling this booking now would refund (paise), before the passenger confirms."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: CancelQuoteOutSerializer, 409: OpenApiTypes.OBJECT})
    def get(self, request, pk):
        booking = booking_queryset().filter(pk=pk, passenger=request.user).first()
        if booking is None:
            raise Http404
        try:
            q = cancellation.passenger_quote(booking)
        except services.TripError as e:
            return _error(e)
        s = q.settlement
        return Response({"rule": s.rule, "paid": q.paid, "total_paid": s.total_paid, "refund": s.refund,
                         "fee": s.vconnects_kept, "message": q.message})


def _own_ride(request, pk):
    from apps.rides.models import Ride

    ride = Ride.objects.filter(pk=pk, driver=request.user).first()
    if ride is None:
        raise Http404
    return ride


class RideCancelQuoteView(APIView):
    """For the driver: what cancelling this ride now means for passengers and for them."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: RideCancelQuoteOutSerializer, 409: OpenApiTypes.OBJECT})
    def get(self, request, pk):
        try:
            q = cancellation.publisher_quote(_own_ride(request, pk))
        except services.TripError as e:
            return _error(e)
        return Response({"passengers": len(q.bookings), "paid_passengers": q.paid_count, "refund_total": q.refund_total,
                         "penalty": q.penalty_total, "within_window": q.late, "message": q.message})


class RideCancelView(APIView):
    """The driver cancels a ride that has bookings (before departure). Every passenger is refunded
    in full; within 24 h of departure the driver's penalty is deducted from their earnings."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=RideCancelInputSerializer, responses={204: None, 409: OpenApiTypes.OBJECT})
    def post(self, request, pk):
        s = RideCancelInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            cancellation.cancel_ride_by_publisher(pk, request.user, s.validated_data["reason"])
        except services.TripError as e:
            return _error(e)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- payment (Phase 3)


class PriceQuoteView(APIView):
    """Price breakdown before booking (paise): ride amount, VConnects platform fee, total."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        from apps.payments import money
        from apps.payments.models import PaymentSettings
        from apps.rides.models import Ride

        s = BookingCreateSerializer(data={"ride_id": request.query_params.get("rideId"), "seats": request.query_params.get("seats", 1)})
        s.is_valid(raise_exception=True)
        ride = Ride.objects.filter(pk=s.validated_data["ride_id"]).first()
        if ride is None:
            raise Http404
        settings_ = PaymentSettings.load()
        a = money.price_booking(ride.price, s.validated_data["seats"], settings_.policy())
        return Response({
            "ride_amount": a.ride_amount, "platform_fee": a.platform_fee, "total": a.total,
            "platform_fee_percent": settings_.platform_fee_bps / 100, "seat_hold_minutes": settings_.seat_hold_minutes,
            "payments_enabled": bool(settings.PAYMENTS_ENABLED),
        })


class PayView(APIView):
    """Start (or retry) paying for a held booking: returns Razorpay Checkout options."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT, 409: OpenApiTypes.OBJECT})
    def post(self, request, pk):
        from apps.payments import checkout

        try:
            with transaction.atomic():
                payment = checkout.start_payment(services.locked_booking(pk, request.user))
        except checkout.PaymentError as e:
            return Response({"detail": e.message, "code": e.code}, status=e.status)
        return Response(checkout.checkout_options(payment))


class PaymentVerifyView(APIView):
    """Checkout returned success. The signature is checked and the payment is fetched from Razorpay
    on the server; the booking is confirmed only if Razorpay says it is captured."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=PaymentVerifySerializer, responses={200: BookingOutSerializer, 400: OpenApiTypes.OBJECT})
    def post(self, request, pk):
        from apps.payments import checkout

        s = PaymentVerifySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        booking = booking_queryset().filter(pk=pk, passenger=request.user).first()
        if booking is None:
            raise Http404
        d = s.validated_data
        try:
            checkout.verify_checkout(booking, d["razorpay_order_id"], d["razorpay_payment_id"], d["razorpay_signature"])
        except checkout.PaymentError as e:
            return Response({"detail": e.message, "code": e.code}, status=e.status)
        return _one(request, pk)
