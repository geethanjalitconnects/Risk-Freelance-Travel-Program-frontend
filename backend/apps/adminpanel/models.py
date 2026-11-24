"""Audit log of the admin dashboard: sign-ins, password changes, every review decision, document
openings and email retries. Rows are never edited or deleted from the app."""
from django.conf import settings
from django.db import models


class AuditAction(models.TextChoices):
    LOGIN = "login", "Signed in"
    LOGIN_FAILED = "login_failed", "Failed sign-in"
    LOGOUT = "logout", "Signed out"
    PASSWORD_CHANGED = "password_changed", "Changed password"
    DOCUMENT_OPENED = "document_opened", "Opened document"
    DOCUMENT_APPROVED = "document_approved", "Approved document"
    DOCUMENT_REJECTED = "document_rejected", "Rejected document"
    PROFILE_APPROVED = "profile_approved", "Approved profile"
    PROFILE_REJECTED = "profile_rejected", "Rejected profile"
    RESUBMIT_REQUESTED = "resubmit_requested", "Requested re-upload"
    APPROVAL_REVOKED = "approval_revoked", "Revoked approval"
    EMAIL_RETRIED = "email_retried", "Retried email"


class AdminAuditLog(models.Model):
    at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    # Kept even if the account changes later; for failed sign-ins, the username that was tried.
    actor_label = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=24, choices=AuditAction.choices, db_index=True)
    target_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-at", "-id"]
        verbose_name = "admin audit entry"
        verbose_name_plural = "admin audit log"

    def __str__(self):
        return f"{self.actor_label or 'unknown'}: {self.get_action_display()} at {self.at:%Y-%m-%d %H:%M}"
