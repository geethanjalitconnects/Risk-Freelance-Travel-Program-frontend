from django.contrib.auth.models import update_last_login
from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from . import otp
from .models import TrustedContact, User
from .serializers import (
    AuthResultSerializer,
    MeSerializer,
    MeUpdateSerializer,
    OTPSentSerializer,
    SendOTPSerializer,
    TrustedContactSerializer,
    VerifyOTPSerializer,
)


def _otp_error(err: otp.OTPError, status_code):
    body = {"detail": err.message, "code": err.code}
    if err.retry_after is not None:
        body["retry_after"] = err.retry_after
    if err.attempts_left is not None:
        body["attempts_left"] = err.attempts_left
    response = Response(body, status=status_code)
    if err.retry_after is not None:
        response["Retry-After"] = str(err.retry_after)
    return response


def _me(request, user=None, status_code=status.HTTP_200_OK):
    user = User.objects.prefetch_related("contacts").get(pk=(user or request.user).pk)
    return Response(MeSerializer(user, context={"request": request}).data, status=status_code)


# ---------------------------------------------------------------- auth


class SendOTPView(APIView):
    """Step 1 of sign-in: text a 6-digit code to the phone number.

    The same flow signs up new numbers, so the response never says whether an account exists.
    With DEBUG on, the code is printed to the server console instead of being sent.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [AnonRateThrottle, ScopedRateThrottle]
    throttle_scope = "otp_send"

    @extend_schema(request=SendOTPSerializer, responses={200: OTPSentSerializer, 429: OpenApiTypes.OBJECT})
    def post(self, request):
        s = SendOTPSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        phone = s.validated_data["phone"]
        try:
            issued = otp.issue(phone)
        except otp.OTPError as e:
            code = status.HTTP_503_SERVICE_UNAVAILABLE if e.code == "sms_failed" else status.HTTP_429_TOO_MANY_REQUESTS
            return _otp_error(e, code)
        return Response({"sent": True, "phone": phone, "expires_in": issued.expires_in, "resend_in": issued.resend_in})


class VerifyOTPView(APIView):
    """Step 2 of sign-in: check the code and return JWT tokens.

    Creates the account on first sign-in (``isNewUser: true``). New users should then send their
    name and gender with PATCH /me; ``user.profileComplete`` stays false until a name is set.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [AnonRateThrottle, ScopedRateThrottle]
    throttle_scope = "otp_verify"

    @extend_schema(request=VerifyOTPSerializer, responses={200: AuthResultSerializer, 400: OpenApiTypes.OBJECT})
    def post(self, request):
        s = VerifyOTPSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        phone, code = s.validated_data["phone"], s.validated_data["code"]
        try:
            otp.verify(phone, code)
        except otp.OTPError as e:
            return _otp_error(e, status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            user = User.objects.filter(phone=phone).first()
            is_new = user is None
            if is_new:
                user = User.objects.create_user(phone)
        if not user.is_active:
            return Response({"detail": "This account has been disabled.", "code": "inactive"}, status=status.HTTP_403_FORBIDDEN)
        update_last_login(None, user)

        refresh = RefreshToken.for_user(user)
        user = User.objects.prefetch_related("contacts").get(pk=user.pk)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "is_new_user": is_new,
                "user": MeSerializer(user, context={"request": request}).data,
            }
        )


# ---------------------------------------------------------------- me


class MeView(APIView):
    """The signed-in user's profile. PATCH name, gender, bio or langs.

    Gender can't change while ``genderLocked`` is set (an active women-only / men-only booking,
    or a published women-only / men-only ride that is still active).
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=MeSerializer)
    def get(self, request):
        return _me(request)

    @extend_schema(request=MeUpdateSerializer, responses=MeSerializer)
    def patch(self, request):
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            s = MeUpdateSerializer(user, data=request.data, partial=True)
            s.is_valid(raise_exception=True)
            s.save()
        return _me(request)


class ContactListView(APIView):
    """Trusted contacts (up to 5): alerted on a missed check-in or SOS."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=TrustedContactSerializer(many=True))
    def get(self, request):
        return Response(TrustedContactSerializer(request.user.contacts.all(), many=True).data)

    @extend_schema(request=TrustedContactSerializer, responses={201: TrustedContactSerializer})
    def post(self, request):
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)  # serialise the 5-contact check
            s = TrustedContactSerializer(data=request.data, context={"request": request})
            s.is_valid(raise_exception=True)
            contact = s.save(user=request.user)
        return Response(TrustedContactSerializer(contact).data, status=status.HTTP_201_CREATED)


class ContactDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request, pk):
        get_object_or_404(TrustedContact, pk=pk, user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
