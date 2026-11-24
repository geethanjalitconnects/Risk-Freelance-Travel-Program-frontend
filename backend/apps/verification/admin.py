"""Driver verifications in the Django admin (read-only).

Review decisions (per-document approve / reject, approve profile, request re-upload, reject,
revoke) are made only in the admin dashboard (/#/admin/review/<userId> in the React app), so
every decision goes through the same rules, audit log and emails. This screen keeps the list,
search, status history, document viewer and access log, and links to the dashboard.

Permissions: view_driververification to see the screens, view_documents to open documents.
"""
from axes.helpers import get_client_ip_address
from django.conf import settings
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db.models import Case, IntegerField, Value, When
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_sameorigin

from . import services
from .crypto import DocumentDecryptionError
from .models import DocumentAccessLog, DriverVerification, IdType, VerificationDocument, VerificationStatus, VerificationStatusChange
from .validators import normalize_vehicle_number

REVIEW_PERM = "verification.review_driververification"
DOCUMENTS_PERM = "verification.view_documents"


class StatusFilter(admin.SimpleListFilter):
    title = "status"
    parameter_name = "status"

    def lookups(self, request, model_admin):
        return [(s, VerificationStatus(s).label) for s in ("pending", "resubmit_requested", "approved", "rejected", "revoked")]

    def queryset(self, request, queryset):
        return queryset.filter(status=self.value()) if self.value() else queryset


class _ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class StatusHistoryInline(_ReadOnlyInline):
    model = VerificationStatusChange
    fields = ["at", "from_status", "to_status", "actor", "reason"]
    readonly_fields = fields
    verbose_name_plural = "Status history"


class AccessLogInline(_ReadOnlyInline):
    """Superusers (auditors) only: reviewers have no permission on this model."""

    model = DocumentAccessLog
    fields = ["at", "admin", "kind", "ip_address"]
    readonly_fields = fields
    verbose_name_plural = "Document access log"


@admin.register(DriverVerification)
class DriverVerificationAdmin(admin.ModelAdmin):
    change_form_template = "admin/verification/driververification/change_form.html"
    list_display = ["driver_name", "driver_phone", "vehicle_number", "id_type", "status", "submitted_at", "reviewed_by", "reviewed_at"]
    list_filter = [StatusFilter, "id_type"]
    search_fields = ["user__phone", "user__name", "vehicle_number"]
    list_select_related = ["user", "reviewed_by"]
    list_per_page = 50
    actions = None
    inlines = [StatusHistoryInline, AccessLogInline]
    fieldsets = (
        ("Driver", {"fields": ("driver_name", "driver_phone", "driver_gender", "account_active")}),
        ("Submission", {"fields": ("vehicle_number", "id_type", "aadhaar_masked_declared", "submitted_at")}),
        ("Review", {"fields": ("status", "reviewed_by", "reviewed_at", "reason", "aadhaar_masked_confirmed")}),
    )
    readonly_fields = [
        "driver_name", "driver_phone", "driver_gender", "account_active", "vehicle_number", "id_type",
        "aadhaar_masked_declared", "submitted_at", "status", "reviewed_by", "reviewed_at", "reason",
        "aadhaar_masked_confirmed",
    ]

    # ---------------------------------------------------------------- list

    def get_queryset(self, request):
        # The review queue: pending first, oldest submission first; then everything else.
        queue = Case(When(status=VerificationStatus.PENDING, then=Value(0)), default=Value(1), output_field=IntegerField())
        return super().get_queryset(request).annotate(queue=queue).order_by("queue", "submitted_at")

    def get_search_results(self, request, queryset, search_term):
        qs, distinct = super().get_search_results(request, queryset, search_term)
        try:  # "tn 09 ab 1234" finds TN09AB1234
            plate = normalize_vehicle_number(search_term)
        except Exception:  # noqa: BLE001 - not a plate; the normal search already ran
            plate = None
        if plate:
            qs = qs | queryset.filter(vehicle_number=plate)
        return qs, distinct

    @admin.display(description="Driver", ordering="user__name")
    def driver_name(self, obj):
        return obj.user.name or "(no name)"

    @admin.display(description="Phone", ordering="user__phone")
    def driver_phone(self, obj):
        return obj.user.phone

    @admin.display(description="Gender")
    def driver_gender(self, obj):
        return obj.user.get_gender_display()

    @admin.display(description="Account active", boolean=True)
    def account_active(self, obj):
        return obj.user.is_active

    # ---------------------------------------------------------------- permissions

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False  # decisions only in the admin dashboard

    def has_delete_permission(self, request, obj=None):
        return False  # deleting would bypass history and retention; reject / revoke instead

    # ---------------------------------------------------------------- detail page

    def change_view(self, request, object_id, form_url="", extra_context=None):
        obj = self.get_object(request, object_id)
        context = dict(extra_context or {})
        if obj is not None:
            can_review = request.user.has_perm(REVIEW_PERM)
            context.update(
                documents=[
                    {"kind": d.get_kind_display(), "ext": d.extension.upper(), "kb": max(1, d.size // 1024),
                     "content_type": d.content_type, "url": reverse("admin:verification_document", args=[d.pk])}
                    for d in obj.documents.all()
                ],
                documents_deleted=obj.documents_deleted_at is not None,
                can_open_documents=request.user.has_perm(DOCUMENTS_PERM),
                is_aadhaar=obj.id_type == IdType.AADHAAR,
                review_actions=(
                    [("review", "Review in admin dashboard", f"{settings.APP_URL}/#/admin/review/{obj.user_id}")]
                    if can_review else []
                ),
            )
        return super().change_view(request, object_id, form_url, extra_context=context)

    def get_urls(self):
        wrap = self.admin_site.admin_view
        return [
            path("document/<uuid:doc_id>/", wrap(self.document_view), name="verification_document"),
        ] + super().get_urls()

    # ---------------------------------------------------------------- document view

    @method_decorator(xframe_options_sameorigin)  # the PDF preview is shown in an iframe on the review page
    def document_view(self, request, doc_id):
        """Decrypt and return one document. Admin-only, logged, never cached, never public."""
        if not request.user.has_perm(DOCUMENTS_PERM):
            raise PermissionDenied
        doc = get_object_or_404(VerificationDocument.objects.select_related("verification"), pk=doc_id)
        try:
            data = services.open_document(doc, request.user, get_client_ip_address(request))
        except (DocumentDecryptionError, FileNotFoundError):
            return HttpResponse("This document can't be opened (missing file or wrong encryption key).", status=410, content_type="text/plain")
        response = HttpResponse(data, content_type=doc.content_type)
        response["Content-Disposition"] = f'inline; filename="{doc.kind}.{doc.extension}"'
        response["Cache-Control"] = "no-store, private, max-age=0"
        response["Pragma"] = "no-cache"
        response["X-Content-Type-Options"] = "nosniff"
        response["Referrer-Policy"] = "no-referrer"
        return response


@admin.register(DocumentAccessLog)
class DocumentAccessLogAdmin(admin.ModelAdmin):
    """Audit of every document opening (superusers)."""

    list_display = ["at", "admin", "kind", "verification", "ip_address"]
    list_filter = ["kind", ("at", admin.DateFieldListFilter)]
    search_fields = ["admin__phone", "admin__name", "verification__user__phone", "verification__vehicle_number"]
    list_select_related = ["admin", "verification__user"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
