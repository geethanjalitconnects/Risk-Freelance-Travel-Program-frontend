import io
import re
from contextlib import redirect_stdout
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Gender, PhoneOTP, TrustedContact, User, normalize_phone
from apps.accounts.sms import ConsoleSMSBackend, LocmemSMSBackend, SMSError, get_backend
from apps.bookings.models import Booking, BookingStatus
from apps.geo.models import City
from apps.geo.seed import seed_geo
from apps.rides.models import Ride, TravelWith

LOCMEM = "apps.accounts.sms.LocmemSMSBackend"
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


@override_settings(SMS_BACKEND=LOCMEM)
class OTPTestBase(APITestCase):
    def setUp(self):
        cache.clear()  # reset DRF throttle counters
        LocmemSMSBackend.outbox = []

    def send(self, phone=PHONE):
        return self.client.post(reverse("otp-send"), {"phone": phone}, format="json")

    def verify(self, code, phone=PHONE):
        return self.client.post(reverse("otp-verify"), {"phone": phone, "code": code}, format="json")

    def last_code(self):
        return re.match(r"(\d{6}) ", LocmemSMSBackend.outbox[-1]["message"]).group(1)

    def age_codes(self, seconds):
        """Pretend the codes for PHONE were issued ``seconds`` ago."""
        for o in PhoneOTP.objects.filter(phone=PHONE):
            o.created_at -= timedelta(seconds=seconds)
            o.save(update_fields=["created_at"])

    def sign_in(self, phone=PHONE):
        self.send(phone)
        return self.verify(self.last_code(), phone)


class SendOTPTests(OTPTestBase):
    def test_sends_code_without_revealing_it(self):
        r = self.send("98765 43210")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json(), {"sent": True, "phone": PHONE, "expiresIn": 300, "resendIn": 30})
        self.assertEqual(len(LocmemSMSBackend.outbox), 1)
        self.assertEqual(LocmemSMSBackend.outbox[0]["phone"], PHONE)
        self.assertNotIn(self.last_code(), r.content.decode())
        self.assertNotIn(self.last_code(), PhoneOTP.objects.get().code_hash)

    def test_invalid_phone(self):
        r = self.send("123")
        self.assertEqual(r.status_code, 400)
        self.assertIn("phone", r.json())

    def test_resend_cooldown(self):
        self.send()
        r = self.send()
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json()["code"], "resend_too_soon")
        self.assertGreater(r.json()["retryAfter"], 0)
        self.assertEqual(r["Retry-After"], str(r.json()["retryAfter"]))
        self.assertEqual(len(LocmemSMSBackend.outbox), 1)

    def test_new_code_replaces_old_one(self):
        self.send()
        old = self.last_code()
        self.age_codes(31)
        self.assertEqual(self.send().status_code, 200)
        new = self.last_code()
        if old != new:
            self.assertEqual(self.verify(old).json()["code"], "incorrect")
        self.assertEqual(self.verify(new).status_code, 200)

    def test_hourly_limit_per_number(self):
        for _ in range(5):
            self.assertEqual(self.send().status_code, 200)
            self.age_codes(31)
        r = self.send()
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json()["code"], "too_many_codes")
        self.age_codes(3600)
        self.assertEqual(self.send().status_code, 200)

    @override_settings(DEBUG=True)
    def test_debug_prints_code_to_console(self):
        self.assertIsInstance(get_backend(), ConsoleSMSBackend)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(self.send().status_code, 200)
        self.assertRegex(out.getvalue(), rf"\[SMS to \{PHONE}\] \d{{6}} is your VConnects sign-in code")
        self.assertEqual(LocmemSMSBackend.outbox, [])

    @override_settings(SMS_BACKEND="")
    def test_missing_backend_outside_debug_is_an_error(self):
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured):
            get_backend()

    def test_provider_failure_lets_user_retry_immediately(self):
        with mock.patch.object(LocmemSMSBackend, "send", side_effect=SMSError("down")):
            r = self.send()
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["code"], "sms_failed")
        self.assertFalse(PhoneOTP.objects.exists())
        self.assertEqual(self.send().status_code, 200)


class VerifyOTPTests(OTPTestBase):
    def test_first_sign_in_creates_account(self):
        r = self.sign_in()
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body["isNewUser"])
        self.assertFalse(body["user"]["profileComplete"])
        self.assertEqual(body["user"]["phone"], PHONE)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {body['access']}")
        self.assertEqual(self.client.get(reverse("me")).json()["phone"], PHONE)
        self.assertIsNotNone(User.objects.get(phone=PHONE).last_login)

    def test_returning_user(self):
        User.objects.create_user(PHONE, name="Asha")
        body = self.sign_in().json()
        self.assertFalse(body["isNewUser"])
        self.assertTrue(body["user"]["profileComplete"])
        self.assertEqual(User.objects.count(), 1)

    def test_wrong_code_counts_attempts_and_locks(self):
        self.send()
        good = self.last_code()
        wrong = "000000" if good != "000000" else "111111"
        for left in (4, 3, 2, 1):
            r = self.verify(wrong)
            self.assertEqual((r.status_code, r.json()["code"], r.json()["attemptsLeft"]), (400, "incorrect", left))
        self.assertEqual(self.verify(wrong).json()["code"], "too_many_attempts")
        self.assertEqual(self.verify(good).json()["code"], "too_many_attempts")
        self.assertFalse(User.objects.exists())

    def test_expired_and_reused_codes(self):
        self.send()
        code = self.last_code()
        PhoneOTP.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.verify(code).json()["code"], "expired")

        self.age_codes(31)
        self.send()
        code = self.last_code()
        self.assertEqual(self.verify(code).status_code, 200)
        self.assertEqual(self.verify(code).json()["code"], "expired")

    def test_code_must_be_six_digits(self):
        r = self.verify("12ab")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], ["Enter the 6-digit code."])

    def test_code_for_another_number_fails(self):
        self.send()
        r = self.verify(self.last_code(), phone="+919999999999")
        self.assertEqual(r.json()["code"], "expired")

    def test_disabled_account(self):
        User.objects.create_user(PHONE, is_active=False)
        self.assertEqual(self.sign_in().status_code, 403)

    def test_refresh_and_logout(self):
        tokens = self.sign_in().json()
        r = self.client.post(reverse("token-refresh"), {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        rotated = r.json()["refresh"]
        self.assertEqual(self.client.post(reverse("logout"), {"refresh": rotated}, format="json").status_code, 200)
        self.assertEqual(self.client.post(reverse("token-refresh"), {"refresh": rotated}, format="json").status_code, 401)


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

    def test_phone_and_verification_are_read_only_here(self):
        self.patch({"phone": "+911111111111", "verifiedId": True})
        self.user.refresh_from_db()
        self.assertEqual(self.user.phone, PHONE)
        self.assertFalse(self.user.verified_id)

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
