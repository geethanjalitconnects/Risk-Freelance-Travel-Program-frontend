import re
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import EmailOTP, Gender, TrustedContact, User, normalize_phone
from apps.accounts.sms import DisabledSMSBackend, SMSError, get_backend
from apps.bookings.models import Booking, BookingStatus
from apps.geo.models import City
from apps.geo.testing import seed_geo
from apps.rides.models import Ride, TravelWith

PHONE = "+919876543210"


class UserModelTests(TestCase):
    def test_regular_user_has_no_usable_password(self):
        u = User.objects.create_user("+91 98765 43210", name="Asha Rao", gender=Gender.FEMALE)
        self.assertEqual(u.phone, PHONE)
        self.assertFalse(u.has_usable_password())
        self.assertEqual(u.first_name, "Asha")
        self.assertEqual(u.languages, ["English"])

    def test_phone_normalisation(self):
        for raw in ["+91 98765 43210", "98765 43210", "9876543210", "+91-98765-43210", " +919876543210 "]:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_phone(raw), PHONE)
        self.assertEqual(normalize_phone("+1 415 555 0100"), "+14155550100")

    def test_invalid_phone_rejected(self):
        for bad in ["", "12345", "phone-number", "+0123456789", "98765"]:
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                normalize_phone(bad)

    def test_phone_is_unique_after_normalising(self):
        User.objects.create_user(PHONE)
        with self.assertRaises(Exception):
            User.objects.create_user("98765 43210")

    def test_superuser_requires_password(self):
        with self.assertRaises(ValueError):
            User.objects.create_superuser("+919000000000", password=None)
        admin = User.objects.create_superuser("+919000000001", password="a-strong-pass-123")
        self.assertTrue(admin.is_staff and admin.is_superuser and admin.has_usable_password())

    def test_gender_choices_match_profile_select(self):
        self.assertEqual([c[0] for c in Gender.choices], ["", "F", "M", "O"])


class MeTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(PHONE, name="Asha Rao", gender="F")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.user).access_token}")

    def patch(self, body):
        return self.client.patch(reverse("me"), body, format="json")

    def test_requires_sign_in(self):
        self.client.credentials()
        self.assertEqual(self.client.get(reverse("me")).status_code, 401)

    def test_shape_is_superset_of_frontend_profile(self):
        body = self.client.get(reverse("me")).json()
        for key in ["name", "phone", "gender", "verifiedId", "verifiedLicense", "contacts"]:
            self.assertIn(key, body)
        self.assertEqual(body["activeTrips"], 0)
        self.assertIsNone(body["genderLocked"])
        self.assertEqual(body["langs"], ["English"])

    def test_update_profile(self):
        r = self.patch({"name": "  Asha   K  Rao ", "gender": "", "bio": "Weekend driver", "langs": ["Tamil", "English", "Tamil"]})
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual((body["name"], body["gender"], body["bio"], body["langs"]), ("Asha K Rao", "", "Weekend driver", ["Tamil", "English"]))

    def test_validation(self):
        self.assertEqual(self.patch({"name": "   "}).json()["name"], ["Enter your name."])
        self.assertIn("gender", self.patch({"gender": "X"}).json())

    def test_phone_is_contact_info_and_verification_is_read_only(self):
        r = self.patch({"phone": "+91 11111 11111", "verifiedId": True})
        self.assertEqual(r.status_code, 200, r.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.phone, "+911111111111")
        self.assertFalse(self.user.verified_id)
        User.objects.create_user("+919000000009")
        self.assertIn("phone", self.patch({"phone": "+919000000009"}).json())  # someone else's number

    def test_sign_in_email_can_be_added_once_but_not_changed(self):
        self.assertEqual(self.patch({"email": " Asha@Example.com "}).json()["email"], "asha@example.com")
        self.assertIn("email", self.patch({"email": "other@example.com"}).json())
        self.assertIn("email", self.patch({"email": ""}).json())
        self.assertEqual(self.patch({"email": "ASHA@example.com"}).status_code, 200)  # same address
        User.objects.create_email_user("taken@example.com")
        other = User.objects.create_user("+919000000008")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(other).access_token}")
        self.assertIn("email", self.patch({"email": "Taken@Example.com"}).json())

    def test_active_trips(self):
        seed_geo()
        driver = User.objects.create_user("+919000000002", gender="M")
        ride = Ride.objects.create(
            driver=driver, origin=City.objects.get(code="MAA"), destination=City.objects.get(code="BLR"),
            pickup="a", dropoff="b", depart=timezone.now(), duration_min=300, km=370, price=600, seats_total=3,
            vehicle_model="Swift", vehicle_year=2022,
        )
        Booking.objects.create(ride=ride, passenger=self.user, seats=1, total=600, risk_score=30, risk_band="moderate", status=BookingStatus.IN_PROGRESS)
        self.assertEqual(self.client.get(reverse("me")).json()["activeTrips"], 1)


class GenderLockApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        seed_geo()
        cls.driver = User.objects.create_user("+919000000001", name="Meera", gender="F")
        cls.passenger = User.objects.create_user("+919000000002", name="Divya", gender="F")

    def make_ride(self, travel_with):
        return Ride.objects.create(
            driver=self.driver, origin=City.objects.get(code="MAA"), destination=City.objects.get(code="BLR"),
            pickup="a", dropoff="b", depart=timezone.now() + timedelta(days=1), duration_min=300, km=370, price=600,
            seats_total=3, vehicle_model="Swift", vehicle_year=2022, travel_with=travel_with,
        )

    def as_user(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")

    def test_passenger_with_restricted_booking_cannot_change_gender(self):
        ride = self.make_ride(TravelWith.WOMEN)
        Booking.objects.create(ride=ride, passenger=self.passenger, seats=1, total=600, risk_score=30, risk_band="moderate")
        self.as_user(self.passenger)
        self.assertIn("booking", self.client.get(reverse("me")).json()["genderLocked"])
        r = self.client.patch(reverse("me"), {"gender": "M"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("women-only or men-only", r.json()["gender"][0])
        # Re-sending the same gender (e.g. a full-form save) is fine.
        self.assertEqual(self.client.patch(reverse("me"), {"gender": "F", "name": "Divya K"}, format="json").status_code, 200)

    def test_driver_with_restricted_ride_cannot_change_gender(self):
        self.make_ride(TravelWith.WOMEN)
        self.as_user(self.driver)
        r = self.client.patch(reverse("me"), {"gender": ""}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("published", r.json()["gender"][0])

    def test_anyone_rides_do_not_lock(self):
        ride = self.make_ride(TravelWith.ANYONE)
        Booking.objects.create(ride=ride, passenger=self.passenger, seats=1, total=600, risk_score=30, risk_band="moderate")
        for user in (self.driver, self.passenger):
            self.as_user(user)
            self.assertEqual(self.client.patch(reverse("me"), {"gender": "O"}, format="json").status_code, 200)


class ContactTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(PHONE, name="Asha")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.user).access_token}")

    def add(self, **body):
        data = {"name": "Amma", "phone": "+91 98400 00000", "relation": "Mother", **body}
        return self.client.post(reverse("contact-list"), data, format="json")

    def test_add_list_delete(self):
        r = self.add()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(set(r.json()), {"id", "name", "phone", "relation"})
        self.assertEqual(len(self.client.get(reverse("contact-list")).json()), 1)
        self.assertEqual(self.client.get(reverse("me")).json()["contacts"][0]["name"], "Amma")
        self.assertEqual(self.client.delete(reverse("contact-detail", args=[r.json()["id"]])).status_code, 204)
        self.assertFalse(TrustedContact.objects.exists())

    def test_validation_matches_profile_page(self):
        self.assertEqual(self.add(name=" ").json()["name"], ["Enter a name."])
        self.assertEqual(self.add(phone="12-34").json()["phone"], ["Enter a valid phone number (8-15 digits)."])
        self.assertEqual(self.add(relation="").status_code, 201)

    def test_max_five(self):
        for i in range(5):
            self.assertEqual(self.add(name=f"C{i}").status_code, 201)
        r = self.add(name="Sixth")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["nonFieldErrors"], ["You can add up to 5 contacts."])

    def test_cannot_delete_someone_elses_contact(self):
        other = User.objects.create_user("+919000000009")
        c = TrustedContact.objects.create(user=other, name="X", phone="9840000000")
        self.assertEqual(self.client.delete(reverse("contact-detail", args=[c.id])).status_code, 404)


EMAIL = "asha@example.com"


class EmailOTPTests(APITestCase):
    def setUp(self):
        cache.clear()

    def send(self, email=EMAIL):
        return self.client.post(reverse("email-otp-send"), {"email": email}, format="json")

    def verify(self, code, email=EMAIL):
        return self.client.post(reverse("email-otp-verify"), {"email": email, "code": code}, format="json")

    def last_code(self):
        from django.core import mail

        return re.search(r"sign-in code is (\d{6})", mail.outbox[-1].body).group(1)

    def test_code_is_emailed_and_hashed(self):
        from django.core import mail

        r = self.send(" Asha@Example.COM ")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["email"], EMAIL)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, [EMAIL])
        code = self.last_code()
        self.assertIn(code, msg.subject)
        self.assertNotIn(code, EmailOTP.objects.get().code_hash)  # only a keyed hash is stored

    def test_first_sign_in_creates_account_then_details(self):
        self.send()
        r = self.verify(self.last_code())
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body["isNewUser"])
        self.assertEqual((body["user"]["email"], body["user"]["phone"]), (EMAIL, None))
        self.assertFalse(body["user"]["profileComplete"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {body['access']}")
        r = self.client.patch(reverse("me"), {"name": "Asha", "gender": "F", "phone": "+91 98765 43210"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["profileComplete"])  # name + mobile number

    def test_returning_user_matched_case_insensitively(self):
        user = User.objects.create_user(PHONE, name="Asha", email=EMAIL)  # an older phone account that added an email
        self.send("ASHA@example.com")
        body = self.verify(self.last_code(), "ASHA@example.com").json()
        self.assertFalse(body["isNewUser"])
        self.assertEqual(body["user"]["id"], str(user.pk))
        self.assertEqual(User.objects.count(), 1)

    def test_wrong_code_expiry_and_reuse(self):
        self.send()
        code = self.last_code()
        wrong = "000000" if code != "000000" else "111111"
        r = self.verify(wrong)
        self.assertEqual((r.status_code, r.json()["code"], r.json()["attemptsLeft"]), (400, "incorrect", 4))
        self.assertEqual(self.verify(code).status_code, 200)
        self.assertEqual(self.verify(code).json()["code"], "expired")  # one use only

    def test_resend_limit_and_bad_input(self):
        self.send()
        r = self.send()
        self.assertEqual((r.status_code, r.json()["code"]), (429, "resend_too_soon"))
        self.assertEqual(self.send("not-an-email").status_code, 400)
        self.assertEqual(self.verify("12ab", EMAIL).status_code, 400)

    def test_disabled_account(self):
        User.objects.create_email_user(EMAIL, is_active=False)
        self.send()
        self.assertEqual(self.verify(self.last_code()).status_code, 403)

    def test_email_failure_lets_the_user_retry(self):
        with mock.patch("django.core.mail.send_mail", side_effect=OSError("SMTP down")):
            r = self.send()
        self.assertEqual((r.status_code, r.json()["code"]), (503, "email_failed"))
        self.assertFalse(EmailOTP.objects.exists())
        self.assertEqual(self.send().status_code, 200)

    def test_refresh_and_logout(self):
        self.send()
        tokens = self.verify(self.last_code()).json()
        r = self.client.post(reverse("token-refresh"), {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        rotated = r.json()["refresh"]
        self.assertEqual(self.client.post(reverse("logout"), {"refresh": rotated}, format="json").status_code, 200)
        self.assertEqual(self.client.post(reverse("token-refresh"), {"refresh": rotated}, format="json").status_code, 401)

    def test_phone_sign_in_endpoints_are_gone(self):
        self.assertEqual(self.client.post("/api/v1/auth/otp/send", {"phone": PHONE}, format="json").status_code, 404)
        self.assertEqual(self.client.post("/api/v1/auth/otp/verify", {"phone": PHONE, "code": "123456"}, format="json").status_code, 404)

    @override_settings(DEBUG=False)
    def test_sms_is_disabled(self):
        backend = get_backend()
        self.assertIsInstance(backend, DisabledSMSBackend)
        with self.assertRaises(SMSError):
            backend.send(PHONE, "hello")

    def test_email_unique_case_insensitive(self):
        from django.db import IntegrityError, transaction

        User.objects.create_email_user(EMAIL)
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_email_user("Asha@Example.com".upper())
        User.objects.create_user("+919000000001")
        User.objects.create_user("+919000000002")  # many accounts without email are fine
