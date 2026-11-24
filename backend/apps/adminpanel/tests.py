"""Admin dashboard: seeded admin, separate admin tokens, per-document review, the publish gate,
and decision emails."""
import os
from io import StringIO
from unittest import mock

from django.contrib.auth.models import Group
from django.core import mail
from django.core.management import CommandError, call_command
from django.test import TestCase

from apps.accounts.models import User
from apps.verification.models import DocumentStatus, DriverVerification, EmailNotification, EmailStatus, VerificationStatus
from apps.verification.tests.base import JPEG, VerificationTestBase, tomorrow, upload

from .models import AdminAuditLog, AuditAction

ADMIN_ENV = {"ADMIN_USERNAME": "opsadmin", "ADMIN_PASSWORD": "Seeded-Admin-Pass-2026"}
NEW_PASSWORD = "Brand-New-Admin-Pass-77"


def seed(**env):
    out = StringIO()
    with mock.patch.dict(os.environ, {**ADMIN_ENV, **env}):
        call_command("seed_admin", stdout=out)
    return out.getvalue()


class AdminClientMixin:
    def admin_login(self, username="opsadmin", password=ADMIN_ENV["ADMIN_PASSWORD"]):
        self.client.credentials()
        return self.client.post("/api/admin/login", {"username": username, "password": password}, format="json")

    def as_admin(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def ready_admin(self):
        """Seed, sign in, change the first password; leaves the client using the admin token."""
        seed()
        token = self.admin_login().json()["token"]
        self.as_admin(token)
        r = self.client.post("/api/admin/password", {"currentPassword": ADMIN_ENV["ADMIN_PASSWORD"], "newPassword": NEW_PASSWORD}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.admin_token = r.json()["token"]
        self.as_admin(self.admin_token)
        return User.objects.get(username="opsadmin")


class SeedAdminTests(TestCase):
    def test_creates_hashed_admin_that_must_change_password(self):
        self.assertIn("Created admin", seed())
        admin = User.objects.get(username="opsadmin")
        self.assertTrue(admin.is_superuser and admin.is_staff and admin.must_change_password)
        self.assertIsNone(admin.phone)
        self.assertTrue(admin.password.startswith("argon2$"))
        self.assertNotIn(ADMIN_ENV["ADMIN_PASSWORD"], admin.password)
        self.assertTrue(admin.check_password(ADMIN_ENV["ADMIN_PASSWORD"]))

    def test_safe_to_run_twice(self):
        seed()
        self.assertIn("already exists", seed(ADMIN_PASSWORD="Another-Strong-Pass-99"))
        self.assertEqual(User.objects.filter(username="opsadmin").count(), 1)
        self.assertTrue(User.objects.get(username="opsadmin").check_password(ADMIN_ENV["ADMIN_PASSWORD"]))  # not reset

    def test_needs_env_and_a_strong_password(self):
        with mock.patch.dict(os.environ, {"ADMIN_USERNAME": "", "ADMIN_PASSWORD": ""}), self.assertRaises(CommandError):
            call_command("seed_admin", stdout=StringIO())
        with self.assertRaises(CommandError):
            seed(ADMIN_PASSWORD="password")
        self.assertFalse(User.objects.filter(username="opsadmin").exists())


class AdminAuthTests(AdminClientMixin, VerificationTestBase):
    def test_seeded_admin_logs_in_and_must_change_password_first(self):
        seed()
        r = self.admin_login()
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["admin"]["role"], "admin")
        self.assertTrue(r.json()["admin"]["mustChangePassword"])
        first = r.json()["token"]
        self.as_admin(first)
        self.assertEqual(self.client.get("/api/admin/me").status_code, 200)
        r = self.client.get("/api/admin/queue")
        self.assertEqual((r.status_code, r.json()["code"]), (403, "password_change_required"))

        r = self.client.post("/api/admin/password", {"currentPassword": ADMIN_ENV["ADMIN_PASSWORD"], "newPassword": "short"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/admin/password", {"currentPassword": ADMIN_ENV["ADMIN_PASSWORD"], "newPassword": NEW_PASSWORD}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(r.json()["admin"]["mustChangePassword"])

        self.as_admin(r.json()["token"])
        self.assertEqual(self.client.get("/api/admin/queue").status_code, 200)
        self.as_admin(first)  # tokens issued with the old password stop working
        self.assertEqual(self.client.get("/api/admin/me").status_code, 401)
        self.assertEqual(self.admin_login().status_code, 401)
        self.assertEqual(self.admin_login(password=NEW_PASSWORD).status_code, 200)

    def test_wrong_password_is_refused_and_audited(self):
        seed()
        r = self.admin_login(password="Wrong-password-123")
        self.assertEqual((r.status_code, r.json()["code"]), (401, "invalid_credentials"))
        self.assertTrue(AdminAuditLog.objects.filter(action=AuditAction.LOGIN_FAILED, actor_label="opsadmin").exists())

    def test_repeated_failures_lock_the_login(self):
        seed()
        for _ in range(5):
            self.admin_login(password="Wrong-password-123")
        r = self.admin_login()  # even the right password, while locked
        self.assertEqual(r.status_code, 429)

    def test_normal_user_token_cannot_use_admin_api(self):
        self.as_user(self.driver)
        for path in ("/api/admin/me", "/api/admin/queue", "/api/admin/audit"):
            self.assertEqual(self.client.get(path).status_code, 401, path)
        self.submit()
        self.as_user(self.driver)
        r = self.client.post(f"/api/admin/review/{self.driver.pk}/approve", {}, format="json")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(DriverVerification.objects.get().status, VerificationStatus.PENDING)

    def test_admin_token_cannot_act_as_a_user(self):
        self.ready_admin()
        self.assertEqual(self.client.get("/api/v1/me").status_code, 401)
        self.assertEqual(self.client.post("/api/v1/rides", {}, format="json").status_code, 401)

    def test_staff_without_review_permission_and_app_users_cannot_sign_in(self):
        User.objects.create_user("+919000000051", password="Plain-pass-4242", name="Plain Staff", is_staff=True)
        self.assertEqual(self.admin_login("+919000000051", "Plain-pass-4242").status_code, 401)
        self.assertEqual(self.admin_login(self.driver.phone, "anything-at-all").status_code, 401)

    def test_logout_ends_the_session(self):
        self.ready_admin()
        self.assertEqual(self.client.post("/api/admin/logout").status_code, 204)
        self.assertEqual(self.client.get("/api/admin/me").status_code, 401)

    def test_reviewer_role_reviews_but_cannot_read_audit_log(self):
        reviewer = User.objects.create_user("+919000000050", password="Reviewer-pass-42", name="Rita", is_staff=True)
        reviewer.groups.add(Group.objects.get(name="Verification reviewers"))
        r = self.admin_login("+919000000050", "Reviewer-pass-42")
        self.assertEqual(r.json()["admin"]["role"], "reviewer")
        self.as_admin(r.json()["token"])
        self.assertEqual(self.client.get("/api/admin/queue").status_code, 200)
        self.assertEqual(self.client.get("/api/admin/audit").status_code, 403)


class ReviewFlowTests(AdminClientMixin, VerificationTestBase):
    def setUp(self):
        super().setUp()
        self.submit()  # driver@example.com, 3 documents
        self.admin = self.ready_admin()
        self.v = DriverVerification.objects.get(user=self.driver)
        self.base = f"/api/admin/review/{self.driver.pk}"

    def post(self, path, body=None):
        self.as_admin(self.admin_token)
        return self.client.post(self.base + path, body or {}, format="json")

    def approve_all_documents(self):
        for d in self.v.documents.all():
            self.assertEqual(self.post(f"/documents/{d.pk}/approve").status_code, 200)

    def test_queue_and_review_page(self):
        r = self.client.get("/api/admin/queue")
        self.assertEqual(r.json()["counts"]["pending"], 1)
        self.assertEqual(r.json()["results"][0]["userId"], str(self.driver.pk))
        r = self.client.get(self.base)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["documents"]), 3)
        self.assertFalse(r.json()["canApprove"])
        doc = r.json()["documents"][0]
        r = self.client.get(f"/api/admin/documents/{doc['id']}/file")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Cache-Control"], "no-store, private, max-age=0")
        self.assertTrue(AdminAuditLog.objects.filter(action=AuditAction.DOCUMENT_OPENED).exists())

    def test_rejecting_without_a_reason_fails_validation(self):
        doc = self.v.documents.first()
        for path in (f"/documents/{doc.pk}/reject", "/reject", "/revoke"):
            r = self.post(path, {"reason": "   "})
            self.assertEqual(r.status_code, 400, path)
            self.assertIn("reason", r.json())
            r = self.post(path, {})
            self.assertEqual(r.status_code, 400, path)
        doc.refresh_from_db()
        self.assertEqual(doc.status, DocumentStatus.PENDING)
        self.assertEqual(DriverVerification.objects.get().status, VerificationStatus.PENDING)

    def test_profile_needs_every_document_approved(self):
        r = self.post("/approve")
        self.assertEqual(r.status_code, 409)
        self.assertIn("every document", r.json()["detail"])

    def test_approving_sends_exactly_one_email(self):
        self.approve_all_documents()
        with self.captureOnCommitCallbacks(execute=True):
            r = self.post("/approve")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["verification"]["status"], "approved")
        self.assertEqual(r.json()["verification"]["reviewedBy"]["username"], "opsadmin")
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["driver@example.com"])
        self.assertIn("Your profile has been approved. You can now post rides.", msg.body)
        self.assertIn("Hi Meera", msg.body)
        self.assertIn("http://localhost:5174/#/publish", msg.body)

        # Clicking again changes nothing and sends nothing.
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.post("/approve").status_code, 409)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(EmailNotification.objects.filter(status=EmailStatus.SENT).count(), 1)
        self.assertEqual(AdminAuditLog.objects.filter(action=AuditAction.PROFILE_APPROVED).count(), 1)
        self.assertEqual(AdminAuditLog.objects.filter(action=AuditAction.DOCUMENT_APPROVED).count(), 3)

    def test_rejected_document_asks_driver_to_reupload(self):
        licence = self.v.documents.get(kind="licence_front")
        self.assertEqual(self.post("/request-resubmit").status_code, 409)  # nothing rejected yet
        self.assertEqual(self.post(f"/documents/{licence.pk}/reject", {"reason": "Photo is blurred."}).status_code, 200)
        self.assertEqual(self.post("/approve").status_code, 409)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.post("/request-resubmit", {"note": "Please retake in daylight."})
        self.assertEqual(r.json()["verification"]["status"], "resubmit_requested")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Photo is blurred.", mail.outbox[0].body)

        # The driver sees the reason and which document to re-upload; publishing stays blocked.
        self.as_user(self.driver)
        me = self.client.get("/api/v1/me/driver-verification").json()
        self.assertEqual(me["status"], "resubmit_requested")
        self.assertIn("Photo is blurred.", me["reason"])
        self.assertEqual({d["kind"]: d["status"] for d in me["documentReviews"]}["licence_front"], "rejected")
        self.assertEqual(self.client.post("/api/v1/rides", {}, format="json").json()["code"], "verification_resubmit_requested")

        r = self.client.post("/api/v1/me/driver-verification/documents/licence_front", {"file": upload("new.jpg", JPEG)}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["status"], "pending")
        self.assertEqual(self.v.documents.get(kind="licence_front").status, DocumentStatus.PENDING)

    def test_rejecting_the_profile_emails_the_reason(self):
        with self.captureOnCommitCallbacks(execute=True):
            r = self.post("/reject", {"reason": "Licence has expired."})
        self.assertEqual(r.json()["verification"]["status"], "rejected")
        self.assertEqual(r.json()["verification"]["rejectionReason"], "Licence has expired.")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Licence has expired.", mail.outbox[0].body)

    def test_failed_email_keeps_the_approval_and_can_be_retried(self):
        self.approve_all_documents()
        with mock.patch("django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("SMTP down")):
            with self.captureOnCommitCallbacks(execute=True):
                r = self.post("/approve")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(DriverVerification.objects.get().status, VerificationStatus.APPROVED)
        n = EmailNotification.objects.get()
        self.assertEqual((n.status, n.attempts), (EmailStatus.FAILED, 1))
        self.assertIn("SMTP down", n.last_error)
        page = self.client.get(self.base).json()
        self.assertEqual(page["emails"][0]["status"], "failed")
        self.assertTrue(self.client.get("/api/admin/queue?status=approved").json()["results"][0]["emailFailed"])

        r = self.client.post(f"/api/admin/emails/{n.pk}/retry")
        self.assertEqual(r.json()["emails"][0]["status"], "sent")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(self.client.post(f"/api/admin/emails/{n.pk}/retry").status_code, 409)  # no duplicate

    def test_no_email_address_is_shown_not_sent(self):
        User.objects.filter(pk=self.driver.pk).update(email="")
        self.approve_all_documents()
        with self.captureOnCommitCallbacks(execute=True):
            self.post("/approve")
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self.client.get(self.base).json()["emails"][0]["status"], "no_address")

    def test_audit_log_lists_decisions(self):
        self.approve_all_documents()
        self.post("/approve")
        r = self.client.get("/api/admin/audit?action=profile_approved")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["count"], 1)
        self.assertEqual(r.json()["results"][0]["targetUser"]["id"], str(self.driver.pk))


class PublishGateTests(AdminClientMixin, VerificationTestBase):
    """The backend refuses ride publishing unless the profile is approved."""

    def ride_body(self):
        return {
            "from": "MAA", "to": "BLR", "depart": tomorrow().strftime("%Y-%m-%dT%H:%M"), "price": 5600,
            "seatsTotal": 3, "vehicle": {"model": "Hyundai Creta", "year": 2023, "features": []},
        }

    def publish(self):
        self.as_user(self.driver)
        return self.client.post("/api/v1/rides", self.ride_body(), format="json")

    def test_unapproved_user_gets_403_and_approved_user_succeeds(self):
        r = self.publish()
        self.assertEqual((r.status_code, r.json()["code"]), (403, "verification_required"))
        self.submit()
        r = self.publish()
        self.assertEqual((r.status_code, r.json()["code"]), (403, "verification_pending"))
        self.assertEqual(r.json()["detail"], "Your documents are being reviewed. You can publish rides once they are approved.")
        self.approve(DriverVerification.objects.get(), self.reviewer)
        self.assertEqual(self.publish().status_code, 201)

    def test_approved_driver_replacing_a_document_goes_back_to_review(self):
        self.submit()
        self.approve(DriverVerification.objects.get(), self.reviewer)
        self.assertEqual(self.publish().status_code, 201)
        self.as_user(self.driver)
        r = self.client.post("/api/v1/me/driver-verification/documents/id_back", {"file": upload("back.jpg", JPEG)}, format="multipart")
        self.assertEqual((r.status_code, r.json()["status"]), (200, "pending"))
        self.assertFalse(r.json()["canPublish"])
        r = self.publish()
        self.assertEqual((r.status_code, r.json()["code"]), (403, "verification_pending"))
        self.driver.refresh_from_db()
        self.assertFalse(self.driver.verified_id)
