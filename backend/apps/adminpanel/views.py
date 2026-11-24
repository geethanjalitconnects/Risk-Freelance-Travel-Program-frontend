"""Admin dashboard API (/api/admin/*). Every view here authenticates with an admin token only
(AdminJWTAuthentication), so app user tokens are refused. All review rules live in
apps.verification.services; these views add permission checks and the audit log."""
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle
from rest_framework.views import APIView

from apps.verification import emails, services
from apps.verification.crypto import DocumentDecryptionError
from apps.verification.models import (
    REQUIRED_DOCUMENT_KINDS,
    DocumentStatus,
    DriverVerification,
    EmailStatus,
    IdType,
    VerificationDocument,
    VerificationStatus,
)

from . import audit, tokens
from .authentication import AdminJWTAuthentication, IsDashboardStaff, IsSuperAdmin
from .models import AdminAuditLog, AuditAction

DT = serializers.DateTimeField()


def _dt(value):
    return DT.to_representation(value) if value else None


def _who(user):
    if user is None:
        return None
    return {"id": str(user.pk), "name": user.name or audit.actor_label(user), "username": user.username, "phone": user.phone}


def admin_payload(user, role):
    return {
        "id": str(user.pk),
        "username": user.username or user.phone,
        "name": user.name,
        "role": role,
        "must_change_password": user.must_change_password,
        "can_review": user.has_perm(tokens.REVIEW_PERM),
        "can_open_documents": user.has_perm(tokens.DOCUMENTS_PERM),
    }


def _session(user):
    t = tokens.issue(user)
    return {"token": t["token"], "expires_at": t["expires_at"], "admin": admin_payload(user, tokens.role_of(user))}


class AdminView(APIView):
    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [IsDashboardStaff]


# ---------------------------------------------------------------- sign-in


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=256, trim_whitespace=False)


class LoginView(APIView):
    """POST {username, password} -> {token, expiresAt, admin}. Rate-limited per IP, and django-axes
    locks a username + IP after repeated failures."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle, ScopedRateThrottle]
    throttle_scope = "admin_login"

    def post(self, request):
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        username = s.validated_data["username"].strip()
        django_request = request._request
        user = authenticate(django_request, username=username, password=s.validated_data["password"])
        if getattr(django_request, "axes_locked_out", False):
            return Response(
                {"detail": "Too many failed sign-ins. Try again later.", "code": "locked_out"},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        if user is None or tokens.role_of(user) is None:
            audit.record(request, AuditAction.LOGIN_FAILED, actor=None, label=username[:150])
            return Response({"detail": "Invalid username or password.", "code": "invalid_credentials"}, status=status.HTTP_401_UNAUTHORIZED)
        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])
        audit.record(request, AuditAction.LOGIN, actor=user)
        return Response(_session(user))


class LogoutView(AdminView):
    """Ends every dashboard session of this account."""

    allow_before_password_change = True

    def post(self, request):
        user = request.user
        user.admin_token_version += 1
        user.save(update_fields=["admin_token_version"])
        audit.record(request, AuditAction.LOGOUT)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(AdminView):
    allow_before_password_change = True

    def get(self, request):
        return Response(admin_payload(request.user, request.admin_role))


class PasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(trim_whitespace=False)
    new_password = serializers.CharField(trim_whitespace=False, max_length=256)


class PasswordChangeView(AdminView):
    """POST {currentPassword, newPassword}. Required before anything else for a seeded admin.
    Returns a new token; tokens issued with the old password stop working."""

    allow_before_password_change = True

    def post(self, request):
        s = PasswordSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = request.user
        current, new = s.validated_data["current_password"], s.validated_data["new_password"]
        if not user.check_password(current):
            return Response({"current_password": ["Your current password is not correct."]}, status=status.HTTP_400_BAD_REQUEST)
        if new == current:
            return Response({"new_password": ["Choose a password different from the current one."]}, status=status.HTTP_400_BAD_REQUEST)
        try:
            validate_password(new, user)
        except DjangoValidationError as e:
            return Response({"new_password": e.messages}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            user.set_password(new)
            user.must_change_password = False
            user.admin_token_version += 1
            user.save(update_fields=["password", "must_change_password", "admin_token_version"])
            audit.record(request, AuditAction.PASSWORD_CHANGED)
        return Response(_session(user))


# ---------------------------------------------------------------- review queue


QUEUE_FILTERS = {
    "pending": [VerificationStatus.PENDING],
    "resubmit_requested": [VerificationStatus.RESUBMIT_REQUESTED],
    "approved": [VerificationStatus.APPROVED],
    "rejected": [VerificationStatus.REJECTED, VerificationStatus.REVOKED],
    "all": None,
}


class QueueView(AdminView):
    """GET ?status=pending|resubmit_requested|approved|rejected|all&q=<phone, name, email, plate>&page=N"""

    def get(self, request):
        key = request.query_params.get("status", "pending")
        if key not in QUEUE_FILTERS:
            return Response({"status": ["Unknown filter."]}, status=status.HTTP_400_BAD_REQUEST)
        qs = DriverVerification.objects.select_related("user").annotate(
            docs_total=Count("documents", distinct=True),
            docs_approved=Count("documents", filter=Q(documents__status=DocumentStatus.APPROVED), distinct=True),
            docs_rejected=Count("documents", filter=Q(documents__status=DocumentStatus.REJECTED), distinct=True),
            emails_failed=Count("emails", filter=Q(emails__status=EmailStatus.FAILED), distinct=True),
            queue=Case(When(status=VerificationStatus.PENDING, then=Value(0)), default=Value(1), output_field=IntegerField()),
        )
        if QUEUE_FILTERS[key]:
            qs = qs.filter(status__in=QUEUE_FILTERS[key])
        q = (request.query_params.get("q") or "").strip()
        if q:
            plate = q.upper().replace(" ", "").replace("-", "")
            qs = qs.filter(
                Q(user__phone__icontains=q.replace(" ", "")) | Q(user__name__icontains=q)
                | Q(user__email__icontains=q) | Q(vehicle_number__icontains=plate)
            )
        qs = qs.order_by("queue", "submitted_at")
        page = Paginator(qs, 50).get_page(request.query_params.get("page") or 1)
        counts = dict(
            DriverVerification.objects.values_list("status").annotate(n=Count("id")).values_list("status", "n")
        )
        return Response({
            "results": [
                {
                    "user_id": str(v.user_id),
                    "name": v.user.name,
                    "phone": v.user.phone,
                    "email": v.user.email,
                    "vehicle_number": v.vehicle_number,
                    "id_type": v.get_id_type_display(),
                    "status": v.status,
                    "submitted_at": _dt(v.submitted_at),
                    "reviewed_at": _dt(v.reviewed_at),
                    "documents": {"total": v.docs_total, "approved": v.docs_approved, "rejected": v.docs_rejected},
                    "email_failed": v.emails_failed > 0,
                }
                for v in page.object_list
            ],
            "page": page.number,
            "pages": page.paginator.num_pages,
            "count": page.paginator.count,
            "counts": {
                "pending": counts.get(VerificationStatus.PENDING, 0),
                "resubmit_requested": counts.get(VerificationStatus.RESUBMIT_REQUESTED, 0),
                "approved": counts.get(VerificationStatus.APPROVED, 0),
                "rejected": counts.get(VerificationStatus.REJECTED, 0) + counts.get(VerificationStatus.REVOKED, 0),
            },
        })


# ---------------------------------------------------------------- review page


def _verification(user_id) -> DriverVerification:
    return get_object_or_404(DriverVerification.objects.select_related("user", "reviewed_by"), user_id=user_id)


def review_payload(request, v: DriverVerification) -> dict:
    v.refresh_from_db()
    docs = list(v.documents.select_related("reviewed_by"))
    missing = services.missing_required(v)
    all_approved = bool(docs) and not missing and all(d.status == DocumentStatus.APPROVED for d in docs)
    user = v.user
    return {
        "user": {
            "id": str(user.pk), "name": user.name, "phone": user.phone, "email": user.email,
            "gender": user.get_gender_display(), "is_active": user.is_active, "member_since": user.member_since,
        },
        "verification": {
            "id": str(v.pk),
            "status": v.status,
            "vehicle_number": v.vehicle_number,
            "id_type": v.id_type,
            "id_type_label": v.get_id_type_display(),
            "is_aadhaar": v.id_type == IdType.AADHAAR,
            "aadhaar_masked_declared": v.aadhaar_masked_declared,
            "aadhaar_masked_confirmed": v.aadhaar_masked_confirmed,
            "submitted_at": _dt(v.submitted_at),
            "reviewed_at": _dt(v.reviewed_at),
            "reviewed_by": _who(v.reviewed_by),
            "rejection_reason": v.reason or None,
        },
        "documents": [
            {
                "id": str(d.pk), "kind": d.kind, "label": d.get_kind_display(), "required": d.kind in REQUIRED_DOCUMENT_KINDS,
                "status": d.status, "rejection_reason": d.rejection_reason or None,
                "reviewed_by": _who(d.reviewed_by), "reviewed_at": _dt(d.reviewed_at), "uploaded_at": _dt(d.uploaded_at),
                "content_type": d.content_type, "size_kb": max(1, d.size // 1024),
            }
            for d in docs
        ],
        "missing_documents": [str(k.label) for k in missing],
        "can_approve": v.status == VerificationStatus.PENDING and all_approved,
        "can_request_resubmit": v.status == VerificationStatus.PENDING and any(d.status == DocumentStatus.REJECTED for d in docs),
        "history": [
            {"at": _dt(h.at), "from": h.from_status, "to": h.to_status, "actor": _who(h.actor), "reason": h.reason}
            for h in v.history.select_related("actor")[:50]
        ],
        "emails": [
            {
                "id": e.pk, "kind": e.kind, "kind_label": e.get_kind_display(), "to_email": e.to_email, "status": e.status,
                "attempts": e.attempts, "last_error": e.last_error or None, "created_at": _dt(e.created_at), "sent_at": _dt(e.sent_at),
            }
            for e in v.emails.all()[:20]
        ],
    }


class ReviewDetailView(AdminView):
    def get(self, request, user_id):
        return Response(review_payload(request, _verification(user_id)))


class DocumentFileView(AdminView):
    """The decrypted document, for viewers with the view_documents permission. Every opening is
    logged (document access log + audit log). Never cached."""

    def get(self, request, doc_id):
        if not request.user.has_perm(tokens.DOCUMENTS_PERM):
            return Response({"detail": "You don't have permission to open documents."}, status=status.HTTP_403_FORBIDDEN)
        doc = get_object_or_404(VerificationDocument.objects.select_related("verification__user"), pk=doc_id)
        with transaction.atomic():
            audit.record(request, AuditAction.DOCUMENT_OPENED, target_user=doc.verification.user, document=doc.kind)
            try:
                data = services.open_document(doc, request.user, audit.get_client_ip_address(request._request))
            except (DocumentDecryptionError, FileNotFoundError):
                return Response({"detail": "This document can't be opened (missing file or wrong encryption key)."}, status=status.HTTP_410_GONE)
        response = HttpResponse(data, content_type=doc.content_type)
        response["Content-Disposition"] = f'inline; filename="{doc.kind}.{doc.extension}"'
        response["Cache-Control"] = "no-store, private, max-age=0"
        response["Pragma"] = "no-cache"
        response["X-Content-Type-Options"] = "nosniff"
        return response


# ---------------------------------------------------------------- decisions


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(
        max_length=500, error_messages={"blank": "Enter a reason.", "required": "Enter a reason."}
    )


class RejectSerializer(ReasonSerializer):
    unmasked_aadhaar = serializers.BooleanField(required=False, default=False)


class ApproveSerializer(serializers.Serializer):
    aadhaar_masked_confirmed = serializers.BooleanField(required=False, default=False)


class ResubmitSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=400, required=False, allow_blank=True, default="")


class DecisionView(AdminView):
    """POST review/<userId>/<action>. Needs the review permission. Invalid input -> 400,
    a decision that doesn't fit the current status -> 409 (nothing changes, no email)."""

    serializer_class = None
    action = None

    def perform(self, request, v, data):
        raise NotImplementedError

    def post(self, request, user_id, **kwargs):
        if not request.user.has_perm(tokens.REVIEW_PERM):
            return Response({"detail": "You don't have permission to review verifications."}, status=status.HTTP_403_FORBIDDEN)
        v = _verification(user_id)
        data = {}
        if self.serializer_class:
            s = self.serializer_class(data=request.data)
            s.is_valid(raise_exception=True)
            data = s.validated_data
        try:
            with transaction.atomic():
                details = self.perform(request, v, data, **kwargs) or {}
                audit.record(request, self.action, target_user=v.user, **details)
        except services.ReviewError as e:
            return Response({"detail": str(e), "code": "invalid_state"}, status=status.HTTP_409_CONFLICT)
        return Response(review_payload(request, v))


class DocumentApproveView(DecisionView):
    action = AuditAction.DOCUMENT_APPROVED

    def perform(self, request, v, data, doc_id):
        doc = services.review_document(v, doc_id, request.user, approve=True)
        return {"document": doc.kind}


class DocumentRejectView(DecisionView):
    serializer_class = ReasonSerializer
    action = AuditAction.DOCUMENT_REJECTED

    def perform(self, request, v, data, doc_id):
        doc = services.review_document(v, doc_id, request.user, approve=False, reason=data["reason"])
        return {"document": doc.kind, "reason": doc.rejection_reason}


class ApproveView(DecisionView):
    serializer_class = ApproveSerializer
    action = AuditAction.PROFILE_APPROVED

    def perform(self, request, v, data):
        services.approve(v, request.user, aadhaar_masked_confirmed=data["aadhaar_masked_confirmed"])
        return {"status": VerificationStatus.APPROVED}


class RejectView(DecisionView):
    serializer_class = RejectSerializer
    action = AuditAction.PROFILE_REJECTED

    def perform(self, request, v, data):
        v = services.reject(
            v, request.user, reason=data["reason"],
            unmasked_aadhaar=data["unmasked_aadhaar"] and v.id_type == IdType.AADHAAR,
        )
        return {"status": VerificationStatus.REJECTED, "reason": v.reason}


class RequestResubmitView(DecisionView):
    serializer_class = ResubmitSerializer
    action = AuditAction.RESUBMIT_REQUESTED

    def perform(self, request, v, data):
        v = services.request_resubmit(v, request.user, note=data["note"])
        return {"status": VerificationStatus.RESUBMIT_REQUESTED, "reason": v.reason}


class RevokeView(DecisionView):
    serializer_class = ReasonSerializer
    action = AuditAction.APPROVAL_REVOKED

    def perform(self, request, v, data):
        v = services.revoke(v, request.user, reason=data["reason"])
        return {"status": VerificationStatus.REVOKED, "reason": v.reason}


class EmailRetryView(AdminView):
    """POST: send a failed email again now."""

    def post(self, request, email_id):
        if not request.user.has_perm(tokens.REVIEW_PERM):
            return Response({"detail": "You don't have permission to review verifications."}, status=status.HTTP_403_FORBIDDEN)
        from apps.verification.models import EmailNotification

        n = get_object_or_404(EmailNotification.objects.select_related("verification__user"), pk=email_id)
        if n.status not in (EmailStatus.FAILED, EmailStatus.QUEUED):
            return Response({"detail": "Only failed emails can be retried.", "code": "invalid_state"}, status=status.HTTP_409_CONFLICT)
        sent = emails.deliver(n.pk)
        audit.record(request, AuditAction.EMAIL_RETRIED, target_user=n.verification.user, email=n.kind, sent=sent)
        return Response(review_payload(request, n.verification))


# ---------------------------------------------------------------- audit log


class AuditLogView(AdminView):
    """GET ?page=N&action=<action>&user=<target user id>. Admins only."""

    permission_classes = [IsSuperAdmin]

    def get(self, request):
        qs = AdminAuditLog.objects.select_related("actor", "target_user")
        action = request.query_params.get("action")
        if action:
            qs = qs.filter(action=action)
        target = request.query_params.get("user")
        if target:
            qs = qs.filter(target_user_id=target)
        page = Paginator(qs, 50).get_page(request.query_params.get("page") or 1)
        return Response({
            "results": [
                {
                    "id": e.pk, "at": _dt(e.at), "action": e.action, "action_label": e.get_action_display(),
                    "actor": e.actor_label, "target_user": _who(e.target_user), "details": e.details, "ip_address": e.ip_address,
                }
                for e in page.object_list
            ],
            "actions": [{"value": a.value, "label": a.label} for a in AuditAction],
            "page": page.number,
            "pages": page.paginator.num_pages,
            "count": page.paginator.count,
        })
