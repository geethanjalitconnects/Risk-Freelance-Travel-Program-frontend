import io
from contextlib import redirect_stdout
from datetime import datetime, time, timedelta
from unittest import mock

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import TrustedContact, User
from apps.accounts.sms import LocmemSMSBackend
from apps.bookings.models import Booking, BookingStatus
from apps.geo.models import City
from apps.geo.testing import seed_geo
from apps.rides.models import Ride, RideStatus, TravelWith
from apps.verification.testing import approve_driver

LOCMEM = "apps.accounts.sms.LocmemSMSBackend"


def local(days=1, hour=7):
    return timezone.make_aware(datetime.combine(timezone.localdate() + timedelta(days=days), time(hour, 0)))


@override_settings(SMS_BACKEND=LOCMEM, DEBUG=False)
class BookingTestBase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        seed_geo()
        cls.maa, cls.blr = City.objects.get(code="MAA"), City.objects.get(code="BLR")
        cls.driver = User.objects.create_user("+919000000001", name="Meera Nair", gender="F", verified_id=True, verified_license=True)
        cls.woman = User.objects.create_user("+919000000002", name="Divya", gender="F")
        cls.man = User.objects.create_user("+919000000003", name="Ravi", gender="M")
        cls.unset = User.objects.create_user("+919000000004", name="Sam")
        approve_driver(cls.driver)  # rides are only bookable from approved drivers

    def setUp(self):
        LocmemSMSBackend.outbox = []

    def make_ride(self, **over):
        fields = dict(
            driver=self.driver, origin=self.maa, destination=self.blr, pickup="Chennai Central Bus Stand",
            dropoff="Bengaluru Central Bus Stand", depart=local(), duration_min=300, km=370, price=600,
            seats_total=3, vehicle_model="Hyundai Creta", vehicle_year=2023, vehicle_features=["airbags", "abs"],
        )
        fields.update(over)
        return Ride.objects.create(**fields)

    def as_user(self, user):
        if user is None:
            self.client.credentials()
        else:
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")

    def book(self, ride, user=None, seats=1):
        if user is not None:
            self.as_user(user)
        return self.client.post(reverse("booking-list"), {"rideId": str(ride.id), "seats": seats}, format="json")

    def action(self, booking_id, name, body=None):
        return self.client.post(reverse(f"booking-{name}", args=[booking_id]), body or {}, format="json")


class CreateBookingTests(BookingTestBase):
    def test_booking_has_frontend_shape(self):
        ride = self.make_ride()
        r = self.book(ride, self.woman, seats=2)
        self.assertEqual(r.status_code, 201, r.content)
        b = r.json()
        self.assertEqual(b["rideId"], str(ride.id))
        self.assertEqual((b["seats"], b["total"], b["status"]), (2, 1200, "confirmed"))
        self.assertIsNone(b["trip"])
        self.assertIsNone(b["rating"])
        self.assertIsInstance(b["createdAt"], int)
        self.assertIn(b["riskBand"], ["low", "moderate", "elevated", "high"])
        self.assertIsInstance(b["riskScore"], int)
        self.assertEqual(b["events"][0]["type"], "booked")
        self.assertEqual(b["events"][0]["text"], "Booked 2 seats.")
        self.assertEqual((b["ride"]["from"], b["ride"]["to"]), ("MAA", "BLR"))
        self.assertEqual(b["ride"]["driver"]["name"], "Meera Nair")
        self.assertNotIn("phone", b["ride"]["driver"])
        self.assertEqual(b["ride"]["vehicle"]["model"], "Hyundai Creta")
        self.assertRegex(b["ride"]["depart"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d$")

        detail = self.client.get(reverse("ride-detail", args=[ride.id])).json()
        self.assertEqual(detail["seatsLeft"], 1)
        self.assertEqual(detail["myBookingId"], b["id"])
        self.assertEqual(detail["cannotBookCode"], "already_booked")

    def test_risk_is_frozen_at_booking_time(self):
        ride = self.make_ride()
        b = self.book(ride, self.woman).json()
        ride_risk = self.client.get(reverse("ride-detail", args=[ride.id])).json()["risk"]
        self.assertEqual((b["riskScore"], b["riskBand"]), (ride_risk["score"], ride_risk["band"]["key"]))

    def test_refusals(self):
        ride = self.make_ride(seats_total=2)
        cases = [
            (self.driver, ride, 1, 409, "own_ride"),
            (self.woman, ride, 3, 409, "seats"),
            (self.woman, self.make_ride(depart=timezone.now() - timedelta(minutes=5)), 1, 409, "departed"),
            (self.woman, self.make_ride(status=RideStatus.CANCELLED), 1, 409, "unavailable"),
        ]
        for user, r_, seats, code, err in cases:
            with self.subTest(err=err):
                res = self.book(r_, user, seats)
                self.assertEqual(res.status_code, code, res.content)
                self.assertEqual(res.json()["code"], err)

        self.assertEqual(self.book(ride, self.woman, 2).status_code, 201)
        full = self.book(ride, self.man)
        self.assertEqual((full.status_code, full.json()["code"]), (409, "full"))
        self.as_user(self.woman)
        self.assertEqual(self.book(ride).json()["code"], "already_booked")

    def test_input_validation_and_auth(self):
        ride = self.make_ride()
        self.assertEqual(self.book(ride, self.woman, seats=5).status_code, 400)
        r = self.client.post(reverse("booking-list"), {"rideId": "00000000-0000-0000-0000-000000000000"}, format="json")
        self.assertEqual(r.status_code, 404)
        self.as_user(None)
        self.assertEqual(self.book(ride).status_code, 401)


class TravelWithEnforcementTests(BookingTestBase):
    def test_women_only(self):
        ride = self.make_ride(travel_with=TravelWith.WOMEN, seats_total=4)
        refused = self.book(ride, self.man)
        self.assertEqual((refused.status_code, refused.json()["code"]), (409, "travel_with"))
        self.assertEqual(refused.json()["detail"], "This ride is women only.")
        unset = self.book(ride, self.unset)
        self.assertIn("Set your gender", unset.json()["detail"])
        self.assertEqual(self.book(ride, self.woman).status_code, 201)
        self.assertEqual(Booking.objects.count(), 1)

    def test_men_only(self):
        male_driver = approve_driver(User.objects.create_user("+919000000009", name="Arjun", gender="M"))
        ride = self.make_ride(driver=male_driver, travel_with=TravelWith.MEN)
        self.assertEqual(self.book(ride, self.woman).json()["code"], "travel_with")
        self.assertEqual(self.book(ride, self.man).status_code, 201)

    def test_booking_then_locks_passenger_gender(self):
        ride = self.make_ride(travel_with=TravelWith.WOMEN)
        self.book(ride, self.woman)
        r = self.client.patch(reverse("me"), {"gender": "M"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("gender", r.json())


class CancelTests(BookingTestBase):
    def test_cancel_frees_seats_and_allows_rebooking(self):
        ride = self.make_ride(seats_total=1)
        b = self.book(ride, self.woman).json()
        r = self.action(b["id"], "cancel")
        self.assertEqual(r.json()["status"], "cancelled")
        self.assertEqual(r.json()["events"][-1]["text"], "Booking cancelled.")
        self.assertEqual(self.client.get(reverse("ride-detail", args=[ride.id])).json()["seatsLeft"], 1)
        self.assertEqual(self.book(ride, self.woman).status_code, 201)

    def test_cannot_cancel_started_trip(self):
        b = self.book(self.make_ride(), self.woman).json()
        self.action(b["id"], "start")
        r = self.action(b["id"], "cancel")
        self.assertEqual((r.status_code, r.json()["code"]), (409, "invalid_state"))


class TripLifecycleTests(BookingTestBase):
    def test_full_protected_trip(self):
        ride = self.make_ride()
        bid = self.book(ride, self.woman).json()["id"]

        self.assertEqual(self.action(bid, "checkins", {"key": "pickup"}).json()["code"], "invalid_state")
        r = self.action(bid, "start").json()
        self.assertEqual(r["status"], "in_progress")
        self.assertEqual(set(r["trip"]), {"startedAt", "checkins", "missed", "shared", "sos"})
        self.assertEqual((r["trip"]["checkins"], r["trip"]["missed"], r["trip"]["shared"], r["trip"]["sos"]), ({}, {}, False, None))
        self.assertEqual(r["nextCheckpoint"], "pickup")
        self.assertEqual(self.action(bid, "start").status_code, 409)

        self.assertEqual(self.action(bid, "checkins", {"key": "mid"}).json()["code"], "out_of_order")
        self.assertEqual(self.action(bid, "checkins", {"key": "bogus"}).status_code, 400)
        for key in ("pickup", "mid", "near"):
            r = self.action(bid, "checkins", {"key": key})
            self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(set(body["trip"]["checkins"]), {"pickup", "mid", "near"})
        self.assertIsNone(body["nextCheckpoint"])
        self.assertEqual(self.action(bid, "checkins", {"key": "near"}).json()["code"], "already_checked_in")

        self.assertEqual(self.action(bid, "rate", {"stars": 5}).json()["code"], "invalid_state")
        # Completion needs both sides: the passenger's swipe alone doesn't complete the trip.
        r = self.action(bid, "complete").json()
        self.assertEqual(r["status"], "in_progress")
        self.assertIsInstance(r["completion"]["passengerConfirmedAt"], int)
        self.assertFalse(r["completion"]["canConfirm"])
        self.as_user(self.driver)
        self.assertEqual(self.client.post(reverse("ride-complete", args=[ride.id]), {}, format="json").status_code, 200)
        self.as_user(self.woman)
        r = self.client.get(reverse("booking-detail", args=[bid])).json()
        self.assertEqual(r["status"], "completed")
        self.assertIsInstance(r["completedAt"], int)
        self.assertIn("Arrived safely.", r["events"][-1]["text"])

        self.assertEqual(self.action(bid, "rate", {"stars": 9}).json()["stars"], ["Choose 1 to 5 stars."])
        r = self.action(bid, "rate", {"stars": 4}).json()
        self.assertEqual(r["rating"], 4)
        self.assertEqual(r["events"][-1]["text"], "Rated the driver 4/5.")
        self.assertEqual(self.action(bid, "rate", {"stars": 5}).json()["code"], "already_rated")

        types = [e["type"] for e in r["events"]]
        self.assertEqual(types, ["booked", "started", "checkin", "checkin", "checkin", "confirmed", "confirmed", "completed", "rated"])

        # The driver's public stats now reflect the trip.
        driver = self.client.get(reverse("ride-detail", args=[self.make_ride().id])).json()["driver"]
        self.assertEqual((driver["rating"], driver["trips"]), (4.0, 1))

    def test_other_users_bookings_are_invisible(self):
        bid = self.book(self.make_ride(), self.woman).json()["id"]
        self.as_user(self.man)
        self.assertEqual(self.client.get(reverse("booking-detail", args=[bid])).status_code, 404)
        self.assertEqual(self.action(bid, "start").status_code, 404)
        self.assertEqual(self.client.get(reverse("booking-list")).json(), [])

    def test_list_order_matches_trips_page(self):
        ids = {}
        for status in ("completed", "cancelled", "in_progress", "confirmed"):
            b = self.book(self.make_ride(), self.woman).json()
            Booking.objects.filter(pk=b["id"]).update(status=status, started_at=timezone.now())
            ids[status] = b["id"]
        listed = [b["id"] for b in self.client.get(reverse("booking-list")).json()]
        self.assertEqual(listed, [ids["in_progress"], ids["confirmed"], ids["completed"], ids["cancelled"]])


class SafetyAlertTests(BookingTestBase):
    def setUp(self):
        super().setUp()
        TrustedContact.objects.create(user=self.woman, name="Amma", phone="+91 98400 00001", relation="Mother")
        TrustedContact.objects.create(user=self.woman, name="Old landline", phone="2345 6789")  # valid contact, but no country code: can't get SMS
        self.bid = self.book(self.make_ride(), self.woman).json()["id"]

    def test_sos_texts_contacts(self):
        self.assertEqual(self.action(self.bid, "sos").json()["code"], "invalid_state")
        self.action(self.bid, "start")
        with self.captureOnCommitCallbacks(execute=True):
            r = self.action(self.bid, "sos")
        body = r.json()
        self.assertIsInstance(body["trip"]["sos"], int)
        self.assertEqual(body["events"][-1]["text"], "SOS raised. 1 trusted contact alerted.")
        self.assertEqual(len(LocmemSMSBackend.outbox), 1)
        msg = LocmemSMSBackend.outbox[0]
        self.assertEqual(msg["phone"], "+919840000001")
        self.assertIn("SOS from Divya", msg["message"])
        self.assertIn("Chennai to Bengaluru", msg["message"])
        self.assertIn("112", msg["message"])

    def test_share_creates_link_once(self):
        self.action(self.bid, "start")
        with self.captureOnCommitCallbacks(execute=True):
            body = self.action(self.bid, "share").json()
        self.assertTrue(body["trip"]["shared"])
        self.assertTrue(body["shareUrl"].startswith("https://vconnects.example/track/"))
        self.assertIn(body["shareUrl"], LocmemSMSBackend.outbox[0]["message"])
        with self.captureOnCommitCallbacks(execute=True):
            again = self.action(self.bid, "share").json()
        self.assertEqual(again["shareUrl"], body["shareUrl"])
        self.assertEqual(len(LocmemSMSBackend.outbox), 1)

    def test_no_contacts(self):
        TrustedContact.objects.all().delete()
        self.action(self.bid, "start")
        body = self.action(self.bid, "sos").json()
        self.assertIn("No trusted contacts", body["events"][-1]["text"])

    def test_sms_failure_does_not_undo_sos(self):
        self.action(self.bid, "start")
        with mock.patch.object(LocmemSMSBackend, "send", side_effect=RuntimeError("provider down")):
            with self.captureOnCommitCallbacks(execute=True):
                r = self.action(self.bid, "sos")
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(Booking.objects.get(pk=self.bid).sos_at)

    def test_missed_check_in_is_debug_only(self):
        self.action(self.bid, "start")
        self.assertEqual(self.action(self.bid, "missed").status_code, 404)

        out = io.StringIO()
        with override_settings(DEBUG=True), redirect_stdout(out):
            with self.captureOnCommitCallbacks(execute=True):
                r = self.action(self.bid, "missed")
            self.action(self.bid, "missed")  # same checkpoint again: no new alert or event
        body = r.json()
        self.assertIn("pickup", body["trip"]["missed"])
        self.assertEqual(body["events"][-1]["text"], "Missed check-in: Picked up and seat belt on. 1 trusted contact alerted.")
        self.assertIn("missed a safety check-in", out.getvalue())  # DEBUG prints SMS to the console
        events = self.client.get(reverse("booking-detail", args=[self.bid])).json()["events"]
        self.assertEqual(sum(e["type"] == "missed" for e in events), 1)

        # Checking in afterwards still works and moves on.
        r = self.action(self.bid, "checkins", {"key": "pickup"}).json()
        self.assertEqual(r["nextCheckpoint"], "mid")
