import os
from datetime import timedelta
from unittest import mock

from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.geo.models import City
from apps.rides.models import Ride
from apps.verification import crypto, services
from apps.verification.models import DocumentAccessLog, DriverVerification, VerificationDocument

from .base import JPEG, KEY, PDF, PNG, VerificationTestBase, tomorrow, upload


class SubmissionTests(VerificationTestBase):
    def test_not_submitted_status(self):
        self.as_user(self.driver)
        body = self.client.get("/api/v1/me/driver-verification").json()
        self.assertEqual(body["status"], "not_submitted")
        self.assertFalse(body["canPublish"])
        self.assertEqual(body["blockCode"], "verification_required")
        self.assertEqual(self.client.get(reverse("me")).json()["driverVerification"], "not_submitted")

    def test_submit_creates_pending_with_encrypted_private_files(self):
        r = self.submit()
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual((body["status"], body["vehicleNumber"], body["idType"]), ("pending", "TN09AB1234", "pan"))
        self.assertEqual(sorted(body["documents"]), ["id_front", "licence_back", "licence_front"])
        self.assertEqual(body["blockCode"], "verification_pending")
        for leak in ("url", "storage", ".bin", "dl-front", "ABCDE1234F"):  # nothing that could fetch a document
            self.assertNotIn(leak, r.content.decode())

        docs = VerificationDocument.objects.all()
        self.assertEqual(docs.count(), 3)
        for d in docs:
            with open(os.path.join(self._media, d.storage_name), "rb") as f:
                self.assertNotIn(b"fake", f.read())  # encrypted at rest
            self.assertRegex(d.storage_name, r"^verification/[0-9a-f]{32}\.bin$")  # no names or ID numbers
        self.assertEqual(DriverVerification.objects.get().history.count(), 1)

    def test_id_back_is_optional_and_accepted(self):
        r = self.submit(idType="voter_id", idBack=upload("back.jpg", JPEG))
        self.assertEqual(r.status_code, 201, r.content)
        self.assertIn("id_back", r.json()["documents"])

    def test_validation(self):
        cases = {
            "vehicleNumber": dict(vehicleNumber="not a plate"),
            "licenceBack": dict(licenceBack=None),
            "idFront": dict(idFront=upload("x.gif", b"GIF89a" + b"x" * 50)),
            "idType": dict(idType="driving_licence"),
        }
        for field, over in cases.items():
            with self.subTest(field=field):
                r = self.submit(**over)
                self.assertEqual(r.status_code, 400, r.content)
                self.assertIn(field, r.json())
        r = self.submit(idFront=upload("x.jpg", b"x" * 40))  # named .jpg but isn't one
        self.assertEqual(r.json()["idFront"], ["Upload a JPG, PNG or PDF file."])
        self.assertFalse(DriverVerification.objects.exists())

    @override_settings(DOCUMENT_MAX_BYTES=2 * 1024 * 1024)
    def test_file_size_limit(self):
        r = self.submit(licenceFront=upload("big.jpg", JPEG + b"0" * (2 * 1024 * 1024)))
        self.assertEqual(r.json()["licenceFront"], ["Each file must be 2 MB or smaller."])

    def test_aadhaar_requires_masked_declaration(self):
        r = self.submit(idType="aadhaar")
        self.assertEqual(r.status_code, 400)
        self.assertIn("aadhaarMasked", r.json())
        r = self.submit(idType="aadhaar", aadhaarMasked="true")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(DriverVerification.objects.get().aadhaar_masked_declared)

    def test_bharat_series_plate(self):
        self.assertEqual(self.submit(vehicleNumber="22 BH 1234 AA").json()["vehicleNumber"], "22BH1234AA")

    def test_resubmitting_replaces_documents(self):
        self.submit()
        old = set(VerificationDocument.objects.values_list("storage_name", flat=True))
        with self.captureOnCommitCallbacks(execute=True):
            self.submit(vehicleNumber="KA05MN4321")
        new = set(VerificationDocument.objects.values_list("storage_name", flat=True))
        self.assertFalse(old & new)
        for name in old:
            self.assertFalse(os.path.exists(os.path.join(self._media, name)))
        v = DriverVerification.objects.get()
        self.assertEqual((v.status, v.vehicle_number), ("pending", "KA05MN4321"))
        self.assertEqual(v.history.count(), 2)

    def test_approved_driver_changing_vehicle_goes_back_to_review(self):
        self.submit()
        self.approve(DriverVerification.objects.get(), self.reviewer)
        self.assertEqual(self.submit(vehicleNumber="KA05MN4321").json()["status"], "pending")
        self.driver.refresh_from_db()
        self.assertFalse(self.driver.verified_id)


class ReviewFlowTests(VerificationTestBase):
    def pending(self, **over):
        self.submit(**over)
        return DriverVerification.objects.get(user=self.driver)

    def test_approve_reject_revoke_and_history(self):
        v = self.pending()
        self.approve(v, self.reviewer)
        v.refresh_from_db()
        self.driver.refresh_from_db()
        self.assertEqual((v.status, v.reviewed_by), ("approved", self.reviewer))
        self.assertTrue(self.driver.verified_id and self.driver.verified_license)

        with self.assertRaises(services.ReviewError):
            services.revoke(v, self.reviewer, reason="  ")
        services.revoke(v, self.reviewer, reason="Licence expired.")
        v.refresh_from_db()
        self.driver.refresh_from_db()
        self.assertEqual((v.status, v.reason), ("revoked", "Licence expired."))
        self.assertFalse(self.driver.verified_id)
        steps = list(v.history.order_by("at", "id").values_list("from_status", "to_status", "actor_id"))
        self.assertEqual(steps, [
            ("not_submitted", "pending", self.driver.pk),
            ("pending", "approved", self.reviewer.pk),
            ("approved", "revoked", self.reviewer.pk),
        ])

    def test_reject_requires_reason_and_shows_it_to_driver(self):
        v = self.pending()
        with self.assertRaises(services.ReviewError):
            services.reject(v, self.reviewer, reason="")
        services.reject(v, self.reviewer, reason="Licence photo is blurred.")
        self.as_user(self.driver)
        body = self.client.get("/api/v1/me/driver-verification").json()
        self.assertEqual((body["status"], body["reason"]), ("rejected", "Licence photo is blurred."))
        self.assertIn("Licence photo is blurred.", body["blockMessage"])
        self.assertEqual(self.submit().json()["status"], "pending")  # can fix and resubmit

    def test_aadhaar_approval_needs_masking_confirmation(self):
        v = self.pending(idType="aadhaar", aadhaarMasked="true")
        with self.assertRaises(services.ReviewError):
            self.approve(v, self.reviewer)
        self.approve(v, self.reviewer, aadhaar_masked_confirmed=True)
        v.refresh_from_db()
        self.assertTrue(v.aadhaar_masked_confirmed)

    def test_rejecting_unmasked_aadhaar_deletes_id_documents_now(self):
        v = self.pending(idType="aadhaar", aadhaarMasked="true")
        id_files = list(v.documents.filter(kind="id_front").values_list("storage_name", flat=True))
        with self.captureOnCommitCallbacks(execute=True):
            services.reject(v, self.reviewer, reason="Aadhaar is not masked.", unmasked_aadhaar=True)
        self.assertEqual(sorted(v.documents.values_list("kind", flat=True)), ["licence_back", "licence_front"])
        for name in id_files:
            self.assertFalse(os.path.exists(os.path.join(self._media, name)))
        self.assertIn("deleted", DriverVerification.objects.get().reason)

    def test_only_valid_transitions(self):
        v = self.pending()
        with self.assertRaises(services.ReviewError):
            services.revoke(v, self.reviewer, reason="x")
        self.approve(v, self.reviewer)
        with self.assertRaises(services.ReviewError):
            services.reject(v, self.reviewer, reason="x")
        with self.assertRaises(services.ReviewError):
            self.approve(v, self.reviewer)

    def test_open_document_decrypts_and_logs(self):
        v = self.pending()
        doc = v.documents.get(kind="licence_front")
        self.assertEqual(services.open_document(doc, self.reviewer, "10.0.0.1"), JPEG)
        log = DocumentAccessLog.objects.get()
        self.assertEqual(
            (log.admin, log.kind, log.document_id, log.ip_address), (self.reviewer, "licence_front", doc.pk, "10.0.0.1")
        )


class RetentionTests(VerificationTestBase):
    def test_purge_after_retention_period(self):
        self.submit()
        v = DriverVerification.objects.get()
        services.reject(v, self.reviewer, reason="Blurred")
        self.assertEqual(services.purge_expired()["documents"], 0)  # still within 30 days
        names = list(v.documents.values_list("storage_name", flat=True))
        DriverVerification.objects.update(reviewed_at=timezone.now() - timedelta(days=31))
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(services.purge_expired()["documents"], 3)
        v.refresh_from_db()
        self.assertIsNotNone(v.documents_deleted_at)
        for name in names:
            self.assertFalse(os.path.exists(os.path.join(self._media, name)))

    def test_approved_documents_kept_while_active_then_purged_after_deactivation(self):
        self.submit()
        self.approve(DriverVerification.objects.get(), self.reviewer)
        DriverVerification.objects.update(reviewed_at=timezone.now() - timedelta(days=400))
        self.assertEqual(services.purge_expired()["documents"], 0)
        User.objects.filter(pk=self.driver.pk).update(is_active=False, deactivated_at=timezone.now() - timedelta(days=31))
        self.assertEqual(services.purge_expired()["documents"], 3)


class PublishingAndVisibilityTests(VerificationTestBase):
    def ride_body(self):
        return {
            "from": "MAA", "to": "BLR", "depart": tomorrow().strftime("%Y-%m-%dT%H:%M"), "price": 5600,
            "seatsTotal": 3, "vehicle": {"model": "Hyundai Creta", "year": 2023, "features": []},
        }

    def publish(self, user=None):
        self.as_user(user or self.driver)
        return self.client.post("/api/v1/rides", self.ride_body(), format="json")

    def test_publish_blocked_until_approved(self):
        r = self.publish()
        self.assertEqual((r.status_code, r.json()["code"]), (403, "verification_required"))
        self.submit()
        self.assertEqual(self.publish().json()["code"], "verification_pending")
        services.reject(DriverVerification.objects.get(), self.reviewer, reason="Blurred licence.")
        r = self.publish()
        self.assertEqual(r.json()["code"], "verification_rejected")
        self.assertIn("Blurred licence.", r.json()["detail"])
        self.submit()
        self.approve(DriverVerification.objects.get(), self.reviewer)
        self.assertEqual(self.publish().status_code, 201, self.publish().content)

    def make_ride(self):
        return Ride.objects.create(
            driver=self.driver, origin=City.objects.get(code="MAA"), destination=City.objects.get(code="BLR"),
            pickup="Chennai Central Bus Stand", dropoff="Bengaluru Central Bus Stand", depart=tomorrow(),
            duration_min=300, km=370, price=5600, seats_total=3, vehicle_model="Creta", vehicle_year=2023,
        )

    def search_ids(self):
        r = self.client.get(reverse("ride-search"), {"from": "MAA", "to": "BLR", "date": tomorrow().date().isoformat()})
        return {x["id"] for x in r.json()}

    def test_badge_vehicle_number_and_revocation(self):
        self.submit()
        v = DriverVerification.objects.get()
        booked, unbooked = self.make_ride(), self.make_ride()
        self.client.credentials()
        self.assertEqual(self.search_ids(), set())  # pending: nothing listed, nothing shown as verified

        self.approve(v, self.reviewer)
        self.assertEqual(self.search_ids(), {str(booked.id), str(unbooked.id)})
        detail = self.client.get(reverse("ride-detail", args=[booked.id])).json()
        self.assertTrue(detail["driver"]["verified"])
        self.assertNotIn("number", detail["vehicle"])  # riders without a booking don't see the plate

        self.as_user(self.rider)
        b = self.client.post(reverse("booking-list"), {"rideId": str(booked.id)}, format="json").json()
        self.assertEqual(b["ride"]["vehicle"]["number"], "TN09AB1234")
        self.assertEqual(self.client.get(reverse("ride-detail", args=[booked.id])).json()["vehicle"]["number"], "TN09AB1234")

        services.revoke(v, self.reviewer, reason="Complaint under investigation.")
        self.client.credentials()
        self.assertEqual(self.search_ids(), set())
        self.assertEqual(self.client.get(reverse("ride-detail", args=[unbooked.id])).status_code, 404)
        self.as_user(self.rider)
        kept = self.client.get(reverse("ride-detail", args=[booked.id])).json()  # the passenger keeps their ride
        self.assertFalse(kept["driver"]["verified"])
        self.assertEqual(self.client.get(reverse("booking-list")).json()[0]["id"], b["id"])
        self.as_user(User.objects.create_user("+919000000003", name="Third", gender="M"))
        other = self.client.post(reverse("booking-list"), {"rideId": str(unbooked.id)}, format="json")
        self.assertEqual(other.json()["code"], "unavailable")
        self.as_user(self.driver)
        self.assertEqual({r["listed"] for r in self.client.get(reverse("ride-mine")).json()}, {False})
        self.assertEqual(self.publish().json()["code"], "verification_revoked")

    def test_documents_never_in_public_responses(self):
        self.submit()
        self.approve(DriverVerification.objects.get(), self.reviewer)
        ride = self.make_ride()
        self.client.credentials()
        search = reverse("ride-search") + "?from=MAA&to=BLR&date=" + tomorrow().date().isoformat()
        for url in (reverse("ride-detail", args=[ride.id]), search):
            text = self.client.get(url).content.decode()
            for leak in ("licence_front", "id_front", "storage", ".bin", "TN09AB1234", "idType"):
                self.assertNotIn(leak, text)


class KeyHandlingTests(VerificationTestBase):
    @override_settings(DOCUMENT_ENCRYPTION_KEYS=[], DEBUG=False)
    def test_missing_key_outside_debug_refuses_to_store(self):
        with self.assertRaises(ImproperlyConfigured):
            crypto.encrypt(b"x")

    def test_key_rotation_still_reads_old_files(self):
        old = crypto.encrypt(b"secret")
        with override_settings(DOCUMENT_ENCRYPTION_KEYS=[Fernet.generate_key().decode(), KEY]):
            self.assertEqual(crypto.decrypt(old), b"secret")
        with mock.patch.object(crypto, "_keys", return_value=[Fernet.generate_key().decode()]):
            with self.assertRaises(crypto.DocumentDecryptionError):
                crypto.decrypt(old)
