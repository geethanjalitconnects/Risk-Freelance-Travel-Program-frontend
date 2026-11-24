from datetime import datetime, time, timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import PhoneOTP, User
from apps.bookings.models import Booking, BookingStatus
from apps.geo.models import City
from apps.geo.testing import seed_geo
from apps.rides.models import Ride, RideStatus, TravelWith
from apps.verification.testing import approve_driver


def when(days=1, hour=7):
    return timezone.make_aware(datetime.combine(timezone.localdate() + timedelta(days=days), time(hour, 0)))


class PanelTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_geo()
        cls.root = User.objects.create_superuser("+919000000001", password="Root-pass-424242", name="Root")
        cls.driver = approve_driver(User.objects.create_user("+919000000002", name="Meera", gender="F"))
        cls.rider = User.objects.create_user("+919000000003", name="Ravi", gender="M")
        cls.maa, cls.blr = City.objects.get(code="MAA"), City.objects.get(code="BLR")

    def setUp(self):
        self.client.force_login(self.root)

    def ride(self, driver=None, **over):
        fields = dict(
            driver=driver or self.driver, origin=self.maa, destination=self.blr, pickup="Chennai Central Bus Stand",
            dropoff="Bengaluru Central Bus Stand", depart=when(), duration_min=300, km=370, price=5600, seats_total=3,
            vehicle_model="Creta", vehicle_year=2023,
        )
        fields.update(over)
        return Ride.objects.create(**fields)

    def book(self, ride, passenger, status=BookingStatus.CONFIRMED):
        return Booking.objects.create(ride=ride, passenger=passenger, seats=1, total=ride.price, risk_score=30, risk_band="moderate", status=status)


class UserPanelTests(PanelTestBase):
    url = reverse("admin:accounts_user_changelist")

    def ids(self, **params):
        return {u.pk for u in self.client.get(self.url, params).context["cl"].result_list}

    def test_search_and_filters(self):
        self.assertEqual(self.ids(q="9000000003"), {self.rider.pk})
        self.assertEqual(self.ids(gender="F"), {self.driver.pk})
        self.assertEqual(self.ids(verification="approved"), {self.driver.pk})
        self.assertEqual(self.ids(verification="not_submitted"), {self.root.pk, self.rider.pk})

    def test_users_cannot_be_deleted_and_active_flag_is_action_only(self):
        self.assertEqual(self.client.get(reverse("admin:accounts_user_delete", args=[self.rider.pk])).status_code, 403)
        page = self.client.get(reverse("admin:accounts_user_change", args=[self.rider.pk])).content.decode()
        self.assertNotIn('name="is_active"', page)

    def test_deactivate(self):
        upcoming = self.book(self.ride(), self.rider)
        past = self.book(self.ride(depart=when(days=-2)), self.rider, status=BookingStatus.COMPLETED)
        own_ride = self.ride(driver=self.rider)  # the rider also published a ride (unapproved, but still)
        refresh = RefreshToken.for_user(self.rider)
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
        self.assertEqual(api.get("/api/v1/me").status_code, 200)

        r = self.client.post(self.url, {"action": "deactivate_selected", "_selected_action": [self.rider.pk]}, follow=True)
        self.assertContains(r, "cancelled 1 upcoming booking")
        self.rider.refresh_from_db()
        self.assertFalse(self.rider.is_active)
        self.assertIsNotNone(self.rider.deactivated_at)
        upcoming.refresh_from_db()
        past.refresh_from_db()
        self.assertEqual((upcoming.status, past.status), ("cancelled", "completed"))
        self.assertIn("deactivated", upcoming.events.last().text)
        self.assertEqual(api.get("/api/v1/me").status_code, 401)  # existing access token stops working
        self.assertEqual(APIClient().post("/api/v1/auth/refresh", {"refresh": str(refresh)}, format="json").status_code, 401)
        self.assertFalse(Ride.objects.listed().filter(pk=own_ride.pk).exists())

        self.client.post(self.url, {"action": "reactivate_selected", "_selected_action": [self.rider.pk]})
        self.rider.refresh_from_db()
        self.assertTrue(self.rider.is_active)
        self.assertIsNone(self.rider.deactivated_at)

    def test_deactivated_driver_rides_hidden_but_booked_kept(self):
        booked, unbooked = self.ride(), self.ride()
        self.book(booked, self.rider)
        self.client.post(self.url, {"action": "deactivate_selected", "_selected_action": [self.driver.pk]})
        self.assertFalse(Ride.objects.listed().filter(pk__in=[booked.pk, unbooked.pk]).exists())
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.rider).access_token}")
        self.assertEqual(api.get(f"/api/v1/rides/{booked.pk}").status_code, 200)  # the passenger keeps it
        self.assertEqual(APIClient().get(f"/api/v1/rides/{unbooked.pk}").status_code, 404)
        booked.refresh_from_db()
        self.assertEqual(booked.status, RideStatus.ACTIVE)  # admin cancels it manually if needed

    def test_cannot_deactivate_self(self):
        r = self.client.post(self.url, {"action": "deactivate_selected", "_selected_action": [self.root.pk]}, follow=True)
        self.assertContains(r, "can&#x27;t deactivate your own account")
        self.root.refresh_from_db()
        self.assertTrue(self.root.is_active)

    def test_otp_codes_never_shown(self):
        PhoneOTP.objects.create(phone="+919000000003", code_hash="deadbeef" * 8, expires_at=timezone.now())
        page = self.client.get(reverse("admin:accounts_phoneotp_changelist")).content.decode()
        self.assertNotIn("deadbeef", page)
        otp = PhoneOTP.objects.get()
        self.assertNotIn("deadbeef", self.client.get(reverse("admin:accounts_phoneotp_change", args=[otp.pk])).content.decode())


class RidePanelTests(PanelTestBase):
    url = reverse("admin:rides_ride_changelist")

    def test_filters_and_read_only(self):
        women = self.ride(travel_with=TravelWith.WOMEN)
        self.ride()
        ids = {r.pk for r in self.client.get(self.url, {"travel_with": "women"}).context["cl"].result_list}
        self.assertEqual(ids, {women.pk})
        page = self.client.get(reverse("admin:rides_ride_change", args=[women.pk])).content.decode()
        self.assertNotIn('name="price"', page)
        self.assertNotIn('name="seats_total"', page)
        self.assertEqual(self.client.get(reverse("admin:rides_ride_add")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:rides_ride_delete", args=[women.pk])).status_code, 403)

    def test_cancel_ride_cancels_bookings_and_logs(self):
        ride = self.ride()
        confirmed = self.book(ride, self.rider)
        other = User.objects.create_user("+919000000004", name="Divya", gender="F")
        live = self.book(ride, other, status=BookingStatus.IN_PROGRESS)

        r = self.client.post(self.url, {"action": "cancel_selected", "_selected_action": [ride.pk]})
        self.assertContains(r, "2 open bookings")  # confirmation page
        r = self.client.post(self.url, {"action": "cancel_selected", "_selected_action": [ride.pk], "confirm": "yes", "reason": ""})
        self.assertContains(r, "A reason is required.")

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self.url, {"action": "cancel_selected", "_selected_action": [ride.pk], "confirm": "yes", "reason": "Driver reported unwell."})
        ride.refresh_from_db()
        self.assertEqual((ride.status, ride.cancelled_by, ride.cancellation_reason), ("cancelled", self.root, "Driver reported unwell."))
        for b in (confirmed, live):
            b.refresh_from_db()
            self.assertEqual(b.status, "cancelled")
            self.assertIn("Ride cancelled by VConnects: Driver reported unwell.", b.events.last().text)

    @override_settings(RIDE_CANCELLED_NOTIFIERS=["common.test_admin_panels.record_notification"])
    def test_cancellation_notifiers_run_after_commit(self):
        ride = self.ride()
        self.book(ride, self.rider)
        NOTIFIED.clear()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self.url, {"action": "cancel_selected", "_selected_action": [ride.pk], "confirm": "yes", "reason": "Weather."})
        self.assertEqual(NOTIFIED, [(1, "Weather.")])

    @override_settings(RIDE_CANCELLED_NOTIFIERS=["common.test_admin_panels.broken_notifier"])
    def test_failing_notifier_does_not_undo_cancellation(self):
        ride = self.ride()
        self.book(ride, self.rider)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self.url, {"action": "cancel_selected", "_selected_action": [ride.pk], "confirm": "yes", "reason": "Weather."})
        ride.refresh_from_db()
        self.assertEqual(ride.status, "cancelled")


class BookingPanelTests(PanelTestBase):
    def test_read_only_and_no_share_token(self):
        b = self.book(self.ride(travel_with=TravelWith.WOMEN), self.rider)
        Booking.objects.filter(pk=b.pk).update(shared=True, share_token="secret-share-token")
        url = reverse("admin:bookings_booking_changelist")
        self.assertEqual({x.pk for x in self.client.get(url, {"travel_with": "women"}).context["cl"].result_list}, {b.pk})
        page = self.client.get(reverse("admin:bookings_booking_change", args=[b.pk])).content.decode()
        self.assertNotIn("secret-share-token", page)
        self.assertNotIn('name="seats"', page)
        self.assertEqual(self.client.get(reverse("admin:bookings_booking_add")).status_code, 403)


NOTIFIED = []


def record_notification(bookings, reason):
    NOTIFIED.append((len(bookings), reason))


def broken_notifier(bookings, reason):
    raise RuntimeError("SMS provider down")
