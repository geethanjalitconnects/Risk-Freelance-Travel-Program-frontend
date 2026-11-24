from datetime import timedelta

from django.contrib.auth.models import Group
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.verification import services
from apps.verification.models import DocumentAccessLog, DriverVerification, VerificationDocument

from .base import JPEG, VerificationTestBase

CHANGELIST = "admin:verification_driververification_changelist"


class AdminTestBase(VerificationTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.staff_reviewer = User.objects.create_user("+919000000050", password="Reviewer-pass-42", name="Rita Reviewer", is_staff=True)
        cls.staff_reviewer.groups.add(Group.objects.get(name="Verification reviewers"))
        cls.staff_plain = User.objects.create_user("+919000000051", password="Plain-pass-4242", name="Plain Staff", is_staff=True)

    def make_submission(self, user, **over):
        self.submit(user=user, **over)
        self.client.credentials()
        return DriverVerification.objects.get(user=user)



class ReviewerAccessTests(AdminTestBase):
    def test_group_has_only_verification_permissions(self):
        perms = set(Group.objects.get(name="Verification reviewers").permissions.values_list("content_type__app_label", "codename"))
        self.assertEqual(perms, {
            ("verification", "view_driververification"),
            ("verification", "review_driververification"),
            ("verification", "view_documents"),
            ("verification", "view_verificationstatuschange"),
        })

    def test_reviewer_sees_verification_screens_only(self):
        self.client.force_login(self.staff_reviewer)
        self.assertEqual(self.client.get(reverse(CHANGELIST)).status_code, 200)
        for name in ("admin:accounts_user_changelist", "admin:rides_ride_changelist", "admin:bookings_booking_changelist",
                     "admin:verification_documentaccesslog_changelist"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_no_add_or_delete(self):
        self.client.force_login(self.reviewer)  # even a superuser
        self.assertEqual(self.client.get(reverse("admin:verification_driververification_add")).status_code, 403)
        v = self.make_submission(self.driver)
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(reverse("admin:verification_driververification_delete", args=[v.pk])).status_code, 403)


class ListTests(AdminTestBase):
    def test_queue_order_search_and_no_document_links(self):
        old = self.make_submission(self.driver)
        new = self.make_submission(self.rider)
        third = User.objects.create_user("+919000000003", name="Approved Driver")
        done = self.make_submission(third, vehicleNumber="KA05MN4321")
        self.approve(done, self.reviewer)
        DriverVerification.objects.filter(pk=old.pk).update(submitted_at=timezone.now() - timedelta(days=2))

        self.client.force_login(self.staff_reviewer)
        r = self.client.get(reverse(CHANGELIST))
        ids = [v.pk for v in r.context["cl"].result_list]
        self.assertEqual(ids, [old.pk, new.pk, done.pk])
        self.assertNotIn("/document/", r.content.decode())

        r = self.client.get(reverse(CHANGELIST), {"q": "ka 05 mn 4321"})
        self.assertEqual([v.pk for v in r.context["cl"].result_list], [done.pk])
        r = self.client.get(reverse(CHANGELIST), {"status": "pending"})
        self.assertEqual({v.pk for v in r.context["cl"].result_list}, {old.pk, new.pk})


class DocumentViewTests(AdminTestBase):
    def test_reviewer_opens_document_and_it_is_logged(self):
        v = self.make_submission(self.driver)
        doc = v.documents.get(kind="licence_front")
        self.client.force_login(self.staff_reviewer)
        page = self.client.get(reverse("admin:verification_driververification_change", args=[v.pk])).content.decode()
        self.assertIn(reverse("admin:verification_document", args=[doc.pk]), page)
        self.assertEqual(DocumentAccessLog.objects.count(), 0)  # nothing is opened until asked

        r = self.client.get(reverse("admin:verification_document", args=[doc.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, JPEG)
        self.assertEqual(r["Content-Type"], "image/jpeg")
        self.assertIn("no-store", r["Cache-Control"])
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        self.assertEqual(r["X-Frame-Options"], "SAMEORIGIN")
        self.assertIn('filename="licence_front.jpg"', r["Content-Disposition"])
        log = DocumentAccessLog.objects.get()
        self.assertEqual((log.admin, log.kind, log.document_id), (self.staff_reviewer, "licence_front", doc.pk))

    def test_document_view_refuses_others(self):
        v = self.make_submission(self.driver)
        url = reverse("admin:verification_document", args=[v.documents.first().pk])
        self.assertEqual(self.client.get(url).status_code, 302)  # anonymous -> login
        self.client.force_login(self.staff_plain)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.driver)  # the driver is not staff
        self.assertEqual(self.client.get(url).status_code, 302)
        self.assertEqual(DocumentAccessLog.objects.count(), 0)

    def test_deleted_document_file_is_reported_not_crashing(self):
        v = self.make_submission(self.driver)
        doc = v.documents.first()
        VerificationDocument.objects.filter(pk=doc.pk).update(storage_name="verification/missing.bin")
        self.client.force_login(self.staff_reviewer)
        self.assertEqual(self.client.get(reverse("admin:verification_document", args=[doc.pk])).status_code, 410)


class DecisionTests(AdminTestBase):
    """Decisions moved to the admin dashboard (apps.adminpanel); the Django admin only links there."""

    def test_no_decision_actions_and_link_to_dashboard(self):
        v = self.make_submission(self.driver)
        self.client.force_login(self.staff_reviewer)
        url = reverse("admin:verification_driververification_change", args=[v.pk])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, f"/#/admin/review/{self.driver.pk}")
        self.assertNotContains(r, "/review/approve/")
        r = self.client.get(reverse("admin:verification_driververification_changelist"))
        self.assertNotContains(r, "approve_selected")
        self.assertNotContains(r, "reject_selected")
