"""Driver / publisher verification.

A user must have an APPROVED verification to publish rides. Documents are stored encrypted in
private storage (see storage.py / crypto.py) and are only readable through the admin document view.
"""
import uuid

from django.conf import settings
from django.db import models


class VerificationStatus(models.TextChoices):
    NOT_SUBMITTED = "not_submitted", "Not submitted"
    PENDING = "pending", "Pending review"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    RESUBMIT_REQUESTED = "resubmit_requested", "Re-upload requested"
    REVOKED = "revoked", "Revoked"


class DocumentStatus(models.TextChoices):
    PENDING = "pending", "Pending review"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class IdType(models.TextChoices):
    AADHAAR = "aadhaar", "Aadhaar (masked copy)"
    PAN = "pan", "PAN card"
    VOTER_ID = "voter_id", "Voter ID"
    PASSPORT = "passport", "Passport (photo page)"


class DocumentKind(models.TextChoices):
    LICENCE_FRONT = "licence_front", "Driving licence (front)"
    LICENCE_BACK = "licence_back", "Driving licence (back)"
    ID_FRONT = "id_front", "Government ID (front)"
    ID_BACK = "id_back", "Government ID (back)"


ID_DOCUMENT_KINDS = (DocumentKind.ID_FRONT, DocumentKind.ID_BACK)
# Every submission needs these; ID (back) is optional, but once uploaded it is reviewed too.
REQUIRED_DOCUMENT_KINDS = (DocumentKind.LICENCE_FRONT, DocumentKind.LICENCE_BACK, DocumentKind.ID_FRONT)


class DriverVerification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="driver_verification")
    status = models.CharField(max_length=20, choices=VerificationStatus.choices, default=VerificationStatus.PENDING)

    # One vehicle per driver. Changing it means resubmitting, which sends the driver back to review.
    vehicle_number = models.CharField(max_length=16)
    id_type = models.CharField(max_length=10, choices=IdType.choices)
    aadhaar_masked_declared = models.BooleanField(default=False, help_text="The driver ticked 'this Aadhaar copy is masked'.")
    aadhaar_masked_confirmed = models.BooleanField(default=False, help_text="The reviewer confirmed the Aadhaar copy is masked.")

    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reason = models.CharField(max_length=1000, blank=True, help_text="Why it was rejected, sent back for re-upload or revoked.")
    documents_deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["submitted_at"]
        verbose_name = "driver verification"
        indexes = [models.Index(fields=["status", "submitted_at"])]
        permissions = [
            ("review_driververification", "Can approve, reject and revoke driver verifications"),
            ("view_documents", "Can open driver verification documents"),
        ]

    def __str__(self):
        return f"{self.user} ({self.get_status_display()})"

    @property
    def is_approved(self) -> bool:
        return self.status == VerificationStatus.APPROVED


class VerificationDocument(models.Model):
    """One uploaded file. Only the encrypted bytes are stored, under a random name; the original
    file name is never kept (it can contain an ID number)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    verification = models.ForeignKey(DriverVerification, on_delete=models.CASCADE, related_name="documents")
    kind = models.CharField(max_length=14, choices=DocumentKind.choices)
    storage_name = models.CharField(max_length=120)
    content_type = models.CharField(max_length=40)
    size = models.PositiveIntegerField(help_text="Bytes before encryption")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    # Each document is reviewed on its own; the profile can be approved only when all are approved.
    status = models.CharField(max_length=10, choices=DocumentStatus.choices, default=DocumentStatus.PENDING)
    rejection_reason = models.CharField(max_length=500, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["kind"]
        constraints = [models.UniqueConstraint(fields=["verification", "kind"], name="one_document_per_kind")]

    def __str__(self):
        return self.get_kind_display()

    @property
    def extension(self) -> str:
        return {"image/jpeg": "jpg", "image/png": "png", "application/pdf": "pdf"}.get(self.content_type, "bin")


class VerificationStatusChange(models.Model):
    """History: every submission and review decision."""

    verification = models.ForeignKey(DriverVerification, on_delete=models.CASCADE, related_name="history")
    from_status = models.CharField(max_length=20, choices=VerificationStatus.choices)
    to_status = models.CharField(max_length=20, choices=VerificationStatus.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reason = models.CharField(max_length=1000, blank=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at", "-id"]
        verbose_name = "status change"

    def __str__(self):
        return f"{self.from_status} -> {self.to_status}"


class DocumentAccessLog(models.Model):
    """Every time an admin opens a document: who, which document, when."""

    verification = models.ForeignKey(DriverVerification, on_delete=models.CASCADE, related_name="access_logs")
    document_id = models.UUIDField(help_text="Kept even after the document itself is deleted.")
    kind = models.CharField(max_length=14, choices=DocumentKind.choices)
    admin = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at", "-id"]
        verbose_name = "document access"
        verbose_name_plural = "document access log"

    def __str__(self):
        return f"{self.admin} opened {self.get_kind_display()} at {self.at:%Y-%m-%d %H:%M}"


class EmailKind(models.TextChoices):
    APPROVED = "approved", "Profile approved"
    REJECTED = "rejected", "Profile rejected"
    RESUBMIT_REQUESTED = "resubmit_requested", "Re-upload requested"


class EmailStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"
    NO_ADDRESS = "no_address", "No email address"


class EmailNotification(models.Model):
    """One email about a verification decision. Created in the same transaction as the decision,
    sent after it commits; a failed send is kept here (with the error) and retried, never undoing
    the decision."""

    verification = models.ForeignKey(DriverVerification, on_delete=models.CASCADE, related_name="emails")
    kind = models.CharField(max_length=20, choices=EmailKind.choices)
    to_email = models.EmailField(blank=True)
    reason = models.CharField(max_length=1000, blank=True)
    status = models.CharField(max_length=10, choices=EmailStatus.choices, default=EmailStatus.QUEUED)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["status", "last_attempt_at"])]

    def __str__(self):
        return f"{self.get_kind_display()} email to {self.to_email or '(none)'}: {self.get_status_display()}"
