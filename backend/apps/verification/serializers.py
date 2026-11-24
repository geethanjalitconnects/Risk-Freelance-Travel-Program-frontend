from rest_framework import serializers

from .models import DocumentKind, IdType, VerificationStatus
from .services import publish_block
from .validators import normalize_vehicle_number, read_document


class VerificationSubmitSerializer(serializers.Serializer):
    """multipart/form-data: email, vehicleNumber, idType, aadhaarMasked, licenceFront, licenceBack,
    idFront, idBack (optional). ``email`` (where review decisions are sent) is required unless the
    profile already has one."""

    email = serializers.EmailField(required=False, allow_blank=True)
    vehicle_number = serializers.CharField(max_length=20)
    id_type = serializers.ChoiceField(choices=IdType.choices)
    aadhaar_masked = serializers.BooleanField(required=False, default=False)
    licence_front = serializers.FileField(allow_empty_file=True, use_url=False)
    licence_back = serializers.FileField(allow_empty_file=True, use_url=False)
    id_front = serializers.FileField(allow_empty_file=True, use_url=False)
    id_back = serializers.FileField(allow_empty_file=True, use_url=False, required=False)

    def validate_vehicle_number(self, value):
        return normalize_vehicle_number(value)

    def _file(self, value):
        return read_document(value)

    validate_licence_front = validate_licence_back = validate_id_front = validate_id_back = _file

    def validate(self, attrs):
        user = self.context.get("user")
        if not (attrs.get("email") or "").strip() and not (user and user.email):
            raise serializers.ValidationError({"email": "Enter your email address. We email you when your documents are reviewed."})
        if attrs["id_type"] == IdType.AADHAAR and not attrs.get("aadhaar_masked"):
            raise serializers.ValidationError(
                {"aadhaar_masked": "Upload the masked Aadhaar downloaded from UIDAI and confirm that it is masked."}
            )
        return attrs

    def files(self) -> dict:
        d = self.validated_data
        out = {
            DocumentKind.LICENCE_FRONT: d["licence_front"],
            DocumentKind.LICENCE_BACK: d["licence_back"],
            DocumentKind.ID_FRONT: d["id_front"],
        }
        if d.get("id_back"):
            out[DocumentKind.ID_BACK] = d["id_back"]
        return out


class DocumentUploadSerializer(serializers.Serializer):
    """multipart/form-data: file, aadhaarMasked (when replacing a masked Aadhaar)."""

    file = serializers.FileField(allow_empty_file=True, use_url=False)
    aadhaar_masked = serializers.BooleanField(required=False, default=False)

    def validate_file(self, value):
        return read_document(value)


class DocumentReviewSerializer(serializers.Serializer):
    kind = serializers.CharField()
    label = serializers.CharField()
    status = serializers.CharField(help_text="pending / approved / rejected")
    rejection_reason = serializers.CharField(allow_null=True)
    uploaded_at = serializers.DateTimeField()


class VerificationStatusSerializer(serializers.Serializer):
    """What the driver sees about their own verification. Never any file contents or links."""

    status = serializers.ChoiceField(choices=VerificationStatus.choices)
    vehicle_number = serializers.CharField(allow_null=True)
    id_type = serializers.CharField(allow_null=True)
    reason = serializers.CharField(allow_null=True, help_text="Set when rejected, sent back for re-upload or revoked.")
    email = serializers.CharField(allow_blank=True)
    submitted_at = serializers.DateTimeField(allow_null=True)
    reviewed_at = serializers.DateTimeField(allow_null=True)
    documents = serializers.ListField(child=serializers.CharField(), help_text="Kinds of documents on file.")
    document_reviews = DocumentReviewSerializer(many=True)
    can_publish = serializers.BooleanField()
    block_code = serializers.CharField(allow_null=True)
    block_message = serializers.CharField(allow_null=True)


SHOW_REASON = (VerificationStatus.REJECTED, VerificationStatus.REVOKED, VerificationStatus.RESUBMIT_REQUESTED)
# Per-document decisions are shown once the reviewer has sent their decision (not mid-review).
SHOW_DOCUMENT_STATUS = (VerificationStatus.APPROVED, VerificationStatus.RESUBMIT_REQUESTED, VerificationStatus.REJECTED)


def status_payload(user, v) -> dict:
    block = publish_block(user)
    dt = serializers.DateTimeField()
    if v is None:
        return {
            "status": VerificationStatus.NOT_SUBMITTED, "vehicle_number": None, "id_type": None, "reason": None,
            "submitted_at": None, "reviewed_at": None, "documents": [], "document_reviews": [],
            "email": user.email, "can_publish": False,
            "block_code": block.code, "block_message": block.message,
        }
    docs = list(v.documents.all())
    return {
        "status": v.status,
        "vehicle_number": v.vehicle_number,
        "id_type": v.id_type,
        "reason": (v.reason or None) if v.status in SHOW_REASON else None,
        "email": user.email,
        "submitted_at": serializers.DateTimeField().to_representation(v.submitted_at) if v.submitted_at else None,
        "reviewed_at": serializers.DateTimeField().to_representation(v.reviewed_at) if v.reviewed_at else None,
        "documents": [d.kind for d in docs],
        # The driver sees each document's review result, so they know which ones to re-upload.
        "document_reviews": [
            {
                "kind": d.kind,
                "label": d.get_kind_display(),
                "status": d.status if v.status in SHOW_DOCUMENT_STATUS else "pending",
                "rejection_reason": (d.rejection_reason or None) if v.status in SHOW_DOCUMENT_STATUS else None,
                "uploaded_at": dt.to_representation(d.uploaded_at),
            }
            for d in docs
        ],
        "can_publish": block is None,
        "block_code": block.code if block else None,
        "block_message": block.message if block else None,
    }
