"""Verification rules in one place: submission, review decisions, document access and retention.

Status flow:
    (none) / any status --submit (all documents)--> pending
    pending --approve (every document approved)--> approved
    pending --reject (reason)--> rejected
    pending --request_resubmit (a document rejected)--> resubmit_requested
    resubmit_requested --replace_document (no rejected document left)--> pending
    approved --replace_document--> pending     (a new document needs a new review)
    approved --revoke (reason)--> revoked
Every document is reviewed on its own (approve, or reject with a reason). Every status change is
written to VerificationStatusChange, and approved / rejected / resubmit_requested queue one email
(see emails.py) in the same transaction. The user's verified_id / verified_license flags (used by
the risk score and ride cards) are true only while the status is APPROVED.
"""
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import crypto, emails, storage
from .models import (
    ID_DOCUMENT_KINDS,
    REQUIRED_DOCUMENT_KINDS,
    DocumentAccessLog,
    DocumentKind,
    DocumentStatus,
    DriverVerification,
    EmailKind,
    IdType,
    VerificationDocument,
    VerificationStatus,
    VerificationStatusChange,
)


class ReviewError(Exception):
    pass


# ---------------------------------------------------------------- reading status


def get_verification(user) -> Optional[DriverVerification]:
    try:
        return user.driver_verification
    except DriverVerification.DoesNotExist:
        return None


def status_of(user) -> str:
    v = get_verification(user)
    return v.status if v else VerificationStatus.NOT_SUBMITTED


def is_approved(user) -> bool:
    return status_of(user) == VerificationStatus.APPROVED


@dataclass
class PublishBlock:
    code: str
    message: str


def publish_block(user) -> Optional[PublishBlock]:
    """Why ``user`` can't publish or edit rides, or None when they are approved."""
    v = get_verification(user)
    status = v.status if v else VerificationStatus.NOT_SUBMITTED
    if status == VerificationStatus.APPROVED:
        return None
    if status == VerificationStatus.PENDING:
        return PublishBlock("verification_pending", "Your documents are being reviewed. You can publish rides once they are approved.")
    if status == VerificationStatus.REJECTED:
        return PublishBlock("verification_rejected", f"Your verification was rejected: {v.reason} Please fix this and resubmit.")
    if status == VerificationStatus.RESUBMIT_REQUESTED:
        return PublishBlock(
            "verification_resubmit_requested", f"Please re-upload the documents that were not accepted. {v.reason}"
        )
    if status == VerificationStatus.REVOKED:
        return PublishBlock("verification_revoked", f"Your verification was revoked: {v.reason} Please resubmit your documents.")
    return PublishBlock(
        "verification_required", "To publish rides, submit your vehicle number, driving licence and a government ID for review."
    )


# ---------------------------------------------------------------- internals


def _record(v, from_status, to_status, actor, reason=""):
    VerificationStatusChange.objects.create(
        verification=v, from_status=from_status, to_status=to_status, actor=actor, reason=reason
    )


def _sync_user_flags(v):
    approved = v.status == VerificationStatus.APPROVED
    user = v.user
    if (user.verified_id, user.verified_license) != (approved, approved):
        user.verified_id = user.verified_license = approved
        user.save(update_fields=["verified_id", "verified_license"])


def delete_documents(v, kinds=None) -> int:
    """Delete stored files (and their rows). ``kinds`` limits it to some document types."""
    docs = v.documents.all()
    if kinds:
        docs = docs.filter(kind__in=kinds)
    names = list(docs.values_list("storage_name", flat=True))
    count = len(names)
    docs.delete()
    transaction.on_commit(lambda: [storage.delete(n) for n in names])
    if not v.documents.exists():
        v.documents_deleted_at = timezone.now()
        v.save(update_fields=["documents_deleted_at"])
    return count


def _locked(v) -> DriverVerification:
    return DriverVerification.objects.select_for_update().select_related("user").get(pk=v.pk)


def _save_email(user, email):
    email = (email or "").strip()
    if email and email != user.email:
        user.email = email
        user.save(update_fields=["email"])


def _store(v, kind, data, content_type) -> VerificationDocument:
    name = storage.save_encrypted(crypto.encrypt(data))
    try:
        return VerificationDocument.objects.create(
            verification=v, kind=kind, storage_name=name, content_type=content_type, size=len(data)
        )
    except Exception:
        storage.delete(name)  # don't leave an orphaned encrypted file if the row can't be saved
        raise


def missing_required(v) -> list:
    have = set(v.documents.values_list("kind", flat=True))
    return [k for k in REQUIRED_DOCUMENT_KINDS if k not in have]


# ---------------------------------------------------------------- submission (driver)


@transaction.atomic
def submit(user, *, vehicle_number, id_type, aadhaar_masked, files: dict, email=None) -> DriverVerification:
    """Create or replace the user's submission. ``files`` maps kind -> (bytes, content_type).

    Resubmitting deletes the previous documents and sends the driver back to review (also when
    they were approved: e.g. a new vehicle number needs a new review).
    """
    _save_email(user, email)
    v = DriverVerification.objects.select_for_update().filter(user=user).first()
    previous = v.status if v else VerificationStatus.NOT_SUBMITTED
    if v is None:
        v = DriverVerification(user=user)
    else:
        old = list(v.documents.values_list("storage_name", flat=True))
        v.documents.all().delete()
        transaction.on_commit(lambda: [storage.delete(n) for n in old])

    v.status = VerificationStatus.PENDING
    v.vehicle_number = vehicle_number
    v.id_type = id_type
    v.aadhaar_masked_declared = bool(aadhaar_masked) if id_type == IdType.AADHAAR else False
    v.aadhaar_masked_confirmed = False
    v.submitted_at = timezone.now()
    v.reviewed_at = None
    v.reviewed_by = None
    v.reason = ""
    v.documents_deleted_at = None
    v.save()

    saved = []
    try:
        for kind, (data, content_type) in files.items():
            saved.append(_store(v, kind, data, content_type).storage_name)
    except Exception:
        for name in saved:  # don't leave orphaned encrypted files if the transaction fails
            storage.delete(name)
        raise

    _record(v, previous, VerificationStatus.PENDING, user, "Resubmitted" if previous != VerificationStatus.NOT_SUBMITTED else "Submitted")
    _sync_user_flags(v)
    return v


@transaction.atomic
def replace_document(user, *, kind, data, content_type, aadhaar_masked=False) -> DriverVerification:
    """Upload one new or replacement document (e.g. one the reviewer rejected).

    * approved -> pending: a new document needs a new review; publishing is blocked until then.
    * resubmit_requested -> pending once no document is rejected and none is missing.
    * pending stays pending. Rejected / revoked / not submitted: submit everything again instead.
    """
    v = DriverVerification.objects.select_for_update().select_related("user").filter(user=user).first()
    allowed = (VerificationStatus.PENDING, VerificationStatus.APPROVED, VerificationStatus.RESUBMIT_REQUESTED)
    if v is None or v.status not in allowed:
        raise ReviewError("Submit all your documents with the verification form.")
    if kind in ID_DOCUMENT_KINDS and v.id_type == IdType.AADHAAR and not aadhaar_masked:
        raise ReviewError("Upload the masked Aadhaar downloaded from UIDAI and confirm that it is masked.")

    old = v.documents.filter(kind=kind).first()
    if old is not None:
        name = old.storage_name
        old.delete()
        transaction.on_commit(lambda: storage.delete(name))
    _store(v, kind, data, content_type)
    v.documents_deleted_at = None
    if kind in ID_DOCUMENT_KINDS and v.id_type == IdType.AADHAAR:
        v.aadhaar_masked_declared, v.aadhaar_masked_confirmed = True, False

    previous = v.status
    if previous == VerificationStatus.APPROVED or (
        previous == VerificationStatus.RESUBMIT_REQUESTED
        and not v.documents.filter(status=DocumentStatus.REJECTED).exists()
        and not missing_required(v)
    ):
        v.status = VerificationStatus.PENDING
        v.submitted_at = timezone.now()
        v.reviewed_at = None
        v.reviewed_by = None
        v.reason = ""
        _record(v, previous, VerificationStatus.PENDING, user, f"Re-uploaded {DocumentKind(kind).label}")
    v.save()
    _sync_user_flags(v)
    return v


# ---------------------------------------------------------------- review (admin)


@transaction.atomic
def review_document(v, document_id, admin, *, approve: bool, reason="") -> VerificationDocument:
    """Approve or reject one document of a pending submission. Rejecting needs a reason."""
    reason = (reason or "").strip()
    if not approve and not reason:
        raise ReviewError("A reason is required to reject a document.")
    v = _locked(v)
    if v.status != VerificationStatus.PENDING:
        raise ReviewError("Documents can be reviewed only while the submission is pending.")
    doc = v.documents.select_for_update().filter(pk=document_id).first()
    if doc is None:
        raise ReviewError("This document is not part of the submission.")
    doc.status = DocumentStatus.APPROVED if approve else DocumentStatus.REJECTED
    doc.rejection_reason = "" if approve else reason
    doc.reviewed_at = timezone.now()
    doc.reviewed_by = admin
    doc.save(update_fields=["status", "rejection_reason", "reviewed_at", "reviewed_by"])
    return doc


@transaction.atomic
def approve(v, admin, *, aadhaar_masked_confirmed=False) -> DriverVerification:
    v = _locked(v)
    if v.status != VerificationStatus.PENDING:
        raise ReviewError("Only pending submissions can be approved.")
    if v.id_type == IdType.AADHAAR and not aadhaar_masked_confirmed:
        raise ReviewError("Confirm that the Aadhaar copy is masked before approving.")
    if not v.documents.exists():
        raise ReviewError("This submission has no documents.")
    if missing_required(v):
        raise ReviewError("Some required documents are missing.")
    if v.documents.exclude(status=DocumentStatus.APPROVED).exists():
        raise ReviewError("Approve every document before approving the profile.")
    v.status = VerificationStatus.APPROVED
    v.aadhaar_masked_confirmed = v.id_type == IdType.AADHAAR
    v.reviewed_at = timezone.now()
    v.reviewed_by = admin
    v.reason = ""
    v.save()
    _record(v, VerificationStatus.PENDING, VerificationStatus.APPROVED, admin)
    _sync_user_flags(v)
    emails.queue(v, EmailKind.APPROVED)
    return v


@transaction.atomic
def reject(v, admin, *, reason: str, unmasked_aadhaar=False) -> DriverVerification:
    reason = (reason or "").strip()
    if not reason:
        raise ReviewError("A reason is required to reject.")
    v = _locked(v)
    if v.status != VerificationStatus.PENDING:
        raise ReviewError("Only pending submissions can be rejected.")
    if unmasked_aadhaar:
        # An unmasked Aadhaar copy must not be kept: delete the ID documents at once.
        delete_documents(v, kinds=ID_DOCUMENT_KINDS)
        reason = f"{reason} (The unmasked Aadhaar copy has been deleted.)"
    v.status = VerificationStatus.REJECTED
    v.reviewed_at = timezone.now()
    v.reviewed_by = admin
    v.reason = reason
    v.save()
    _record(v, VerificationStatus.PENDING, VerificationStatus.REJECTED, admin, reason)
    _sync_user_flags(v)
    emails.queue(v, EmailKind.REJECTED, reason)
    return v


@transaction.atomic
def request_resubmit(v, admin, *, note="") -> DriverVerification:
    """Send a pending submission back to the driver to re-upload the rejected documents.
    The reason shown and emailed is the optional note plus each rejected document's reason."""
    v = _locked(v)
    if v.status != VerificationStatus.PENDING:
        raise ReviewError("Only pending submissions can be sent back for re-upload.")
    rejected = list(v.documents.filter(status=DocumentStatus.REJECTED))
    if not rejected:
        raise ReviewError("Reject at least one document (with a reason) before asking for a re-upload.")
    note = (note or "").strip()
    lines = ([note] if note else []) + [f"{d.get_kind_display()}: {d.rejection_reason}" for d in rejected]
    reason = "\n".join(lines)[:1000]
    v.status = VerificationStatus.RESUBMIT_REQUESTED
    v.reviewed_at = timezone.now()
    v.reviewed_by = admin
    v.reason = reason
    v.save()
    _record(v, VerificationStatus.PENDING, VerificationStatus.RESUBMIT_REQUESTED, admin, reason)
    _sync_user_flags(v)
    emails.queue(v, EmailKind.RESUBMIT_REQUESTED, reason)
    return v


@transaction.atomic
def revoke(v, admin, *, reason: str) -> DriverVerification:
    """Withdraw an approval: blocks new rides and hides the driver's rides from search
    (booked rides stay available to the passengers who booked them)."""
    reason = (reason or "").strip()
    if not reason:
        raise ReviewError("A reason is required to revoke.")
    v = _locked(v)
    if v.status != VerificationStatus.APPROVED:
        raise ReviewError("Only approved verifications can be revoked.")
    v.status = VerificationStatus.REVOKED
    v.reviewed_at = timezone.now()
    v.reviewed_by = admin
    v.reason = reason
    v.save()
    _record(v, VerificationStatus.APPROVED, VerificationStatus.REVOKED, admin, reason)
    _sync_user_flags(v)
    return v


# ---------------------------------------------------------------- documents


def open_document(document: VerificationDocument, admin, ip_address=None) -> bytes:
    """Decrypt a document for an admin and log the access. Callers must check permissions."""
    DocumentAccessLog.objects.create(
        verification_id=document.verification_id,
        document_id=document.pk,
        kind=document.kind,
        admin=admin,
        ip_address=ip_address,
    )
    return crypto.decrypt(storage.read(document.storage_name))


@transaction.atomic
def purge_expired(now=None) -> dict:
    """Retention: delete documents of rejected / revoked / sent-back submissions reviewed more than
    DOCUMENT_RETENTION_DAYS ago, and of accounts deactivated that long ago."""
    now = now or timezone.now()
    cutoff = now - timedelta(days=settings.DOCUMENT_RETENTION_DAYS)
    due = DriverVerification.objects.filter(documents__isnull=False).filter(
        Q(
            status__in=[VerificationStatus.REJECTED, VerificationStatus.REVOKED, VerificationStatus.RESUBMIT_REQUESTED],
            reviewed_at__lt=cutoff,
        )
        | Q(user__is_active=False, user__deactivated_at__lt=cutoff)
    ).distinct()
    verifications = documents = 0
    for v in due:
        documents += delete_documents(v)
        verifications += 1
    return {"verifications": verifications, "documents": documents}
