from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle, UserRateThrottle
from rest_framework.views import APIView
from djangorestframework_camel_case.parser import CamelCaseMultiPartParser

from . import services
from .models import DocumentKind
from .serializers import DocumentUploadSerializer, VerificationStatusSerializer, VerificationSubmitSerializer, status_payload


class MyVerificationView(APIView):
    """The signed-in user's driver verification.

    GET: status (not_submitted / pending / approved / rejected / resubmit_requested / revoked),
    the reason, each document's review result, and whether they can publish. No document contents
    or links are ever returned.

    POST (multipart): submit or resubmit the vehicle number, licence (front + back) and a
    government ID (front, optional back). Resubmitting replaces the previous documents and puts
    the account back into review.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [CamelCaseMultiPartParser, MultiPartParser]

    def get_throttles(self):
        if self.request.method == "POST":
            self.throttle_scope = "verification_submit"
            return [UserRateThrottle(), ScopedRateThrottle()]
        return super().get_throttles()

    @extend_schema(responses=VerificationStatusSerializer)
    def get(self, request):
        return Response(status_payload(request.user, services.get_verification(request.user)))

    @extend_schema(request={"multipart/form-data": VerificationSubmitSerializer}, responses={201: VerificationStatusSerializer})
    def post(self, request):
        s = VerificationSubmitSerializer(data=request.data, context={"user": request.user})
        s.is_valid(raise_exception=True)
        d = s.validated_data
        v = services.submit(
            request.user,
            email=d.get("email"),
            vehicle_number=d["vehicle_number"],
            id_type=d["id_type"],
            aadhaar_masked=d.get("aadhaar_masked", False),
            files=s.files(),
        )
        request.user.refresh_from_db()
        return Response(status_payload(request.user, v), status=status.HTTP_201_CREATED)


class MyDocumentUploadView(APIView):
    """POST (multipart ``file``): upload one new or replacement document, e.g. one the reviewer
    asked to re-upload. An approved driver who replaces a document goes back to review, and can't
    publish or edit rides until it is approved again."""

    permission_classes = [IsAuthenticated]
    parser_classes = [CamelCaseMultiPartParser, MultiPartParser]
    throttle_scope = "verification_submit"

    def get_throttles(self):
        return [UserRateThrottle(), ScopedRateThrottle()]

    @extend_schema(request={"multipart/form-data": DocumentUploadSerializer}, responses={200: VerificationStatusSerializer})
    def post(self, request, kind):
        if kind not in DocumentKind.values:
            return Response({"detail": "Unknown document type."}, status=status.HTTP_404_NOT_FOUND)
        s = DocumentUploadSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data, content_type = s.validated_data["file"]
        try:
            v = services.replace_document(
                request.user, kind=kind, data=data, content_type=content_type,
                aadhaar_masked=s.validated_data.get("aadhaar_masked", False),
            )
        except services.ReviewError as e:
            return Response({"detail": str(e), "code": "invalid_state"}, status=status.HTTP_409_CONFLICT)
        request.user.refresh_from_db()
        return Response(status_payload(request.user, v))
