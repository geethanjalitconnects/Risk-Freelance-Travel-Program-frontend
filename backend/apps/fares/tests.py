import io
import json
from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.fares.models import FareSettings
from apps.fares.services import fare_range
from apps.geo.models import City, DistanceSource, RouteProfile
from apps.geo.testing import place_id, seed_geo
from apps.rides.models import Ride
from apps.verification.testing import approve_driver


def tomorrow():
    return timezone.make_aware(datetime.combine(timezone.localdate() + timedelta(days=1), time(7, 0)))


class FareMathTests(TestCase):
    def setUp(self):
        self.s = FareSettings.load()

    def test_defaults(self):
        self.assertEqual((self.s.rate_per_km, self.s.min_fare_floor, self.s.rounding_step, self.s.max_increase_percent),
                         (Decimal("15.00"), 50, 10, 50))

    def test_minimum_rounds_up_maximum_rounds_down(self):
        r = fare_range(371)  # 5565 -> 5570; 5570 x 1.5 = 8355 -> 8350
        self.assertEqual((r.min_fare, r.max_fare), (5570, 8350))
        r = fare_range(370)  # exact: 5550; 8325 -> 8320
        self.assertEqual((r.min_fare, r.max_fare), (5550, 8320))

    def test_floor_applies_to_short_routes(self):
        r = fare_range(2)  # 30 < floor 50; 75 -> 70
        self.assertEqual((r.min_fare, r.max_fare), (50, 70))

    def test_custom_settings(self):
        self.s.rate_per_km = Decimal("2.90")
        self.s.rounding_step = 25
        self.s.max_increase_percent = 0
        self.s.save()
        r = fare_range(370)  # 1073 -> 1075; no increase allowed
        self.assertEqual((r.min_fare, r.max_fare), (1075, 1075))

    def test_maximum_never_below_minimum(self):
        self.s.max_increase_percent = 1
        self.s.rounding_step = 100
        self.s.save()
        r = fare_range(10)  # min 150 -> 200 (step 100); 202 -> 200
        self.assertEqual((r.min_fare, r.max_fare), (200, 200))

    def test_messages(self):
        r = fare_range(370)
        self.assertIn("at least ₹5550", r.error_for(100))
        self.assertIn("at most ₹8320", r.error_for(9000))
        self.assertIsNone(r.error_for(6000))

    def test_single_record(self):
        FareSettings(rate_per_km=Decimal("9")).save()
        self.assertEqual(FareSettings.objects.count(), 1)
        self.assertEqual(FareSettings.load().rate_per_km, Decimal("9"))


class FareAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = User.objects.create_superuser("+919000000001", password="Root-pass-424242")
        cls.reviewer = User.objects.create_user("+919000000002", password="Rev-pass-4242424", is_staff=True)
        cls.reviewer.groups.add(Group.objects.get(name="Verification reviewers"))

    def test_single_settings_page(self):
        self.client.force_login(self.root)
        r = self.client.get(reverse("admin:fares_faresettings_changelist"))
        self.assertRedirects(r, reverse("admin:fares_faresettings_change", args=[1]))
        self.assertEqual(self.client.get(reverse("admin:fares_faresettings_add")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:fares_faresettings_delete", args=[1])).status_code, 403)
        r = self.client.post(reverse("admin:fares_faresettings_change", args=[1]), {
            "rate_per_km": "12.50", "min_fare_floor": "60", "rounding_step": "5", "max_increase_percent": "40",
        })
        self.assertEqual(r.status_code, 302)
        s = FareSettings.load()
        self.assertEqual((s.rate_per_km, s.min_fare_floor, s.rounding_step, s.max_increase_percent, s.updated_by),
                         (Decimal("12.50"), 60, 5, 40, self.root))

    def test_reviewers_cannot_change_fares(self):
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(reverse("admin:fares_faresettings_change", args=[1])).status_code, 403)


class FareEnforcementTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        seed_geo()
        cls.driver = approve_driver(User.objects.create_user("+919000000001", name="Meera", gender="F"))
        cls.km = RouteProfile.objects.between("MAA", "BLR").get().km
        cls.range = fare_range(cls.km)

    def setUp(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.driver).access_token}")

    def publish(self, price):
        return self.client.post("/api/v1/rides", {
            "from": place_id("MAA"), "to": place_id("BLR"), "depart": tomorrow().strftime("%Y-%m-%dT%H:%M"), "price": price, "seatsTotal": 3,
            "vehicle": {"model": "Creta", "year": 2023, "features": []},
        }, format="json")

    def test_quote_endpoint(self):
        r = self.client.get("/api/v1/fares/quote", {"from": place_id("MAA"), "to": place_id("BLR")})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"km": self.km, "minFare": self.range.min_fare, "maxFare": self.range.max_fare,
                                    "ratePerKm": "15.00", "maxIncreasePercent": 50})
        self.assertEqual(self.client.get("/api/v1/fares/quote", {"from": place_id("MAA"), "to": place_id("MAA")}).status_code, 400)

    def test_publish_within_range_only(self):
        self.assertEqual(self.publish(self.range.min_fare - 10).status_code, 400)
        r = self.publish(self.range.max_fare + 10)
        self.assertIn("at most", r.json()["price"][0])
        self.assertEqual(self.publish(self.range.min_fare).status_code, 201)
        self.assertEqual(self.publish(self.range.max_fare).status_code, 201)

    def test_rate_changes_apply_to_new_and_edited_rides_only(self):
        ride_id = self.publish(self.range.min_fare).json()["id"]
        s = FareSettings.load()
        s.rate_per_km = Decimal("20")
        s.save()
        new = fare_range(self.km)
        # The existing ride keeps its fare, and unrelated edits don't force a new price...
        self.assertEqual(self.client.patch(f"/api/v1/rides/{ride_id}", {"notes": "hi"}, format="json").status_code, 200)
        self.assertEqual(Ride.objects.get(pk=ride_id).price, self.range.min_fare)
        # ...but changing the fare must meet the current range.
        r = self.client.patch(f"/api/v1/rides/{ride_id}", {"price": self.range.min_fare + 10}, format="json")
        self.assertIn(f"at least ₹{new.min_fare}", r.json()["price"][0])
        self.assertEqual(self.client.patch(f"/api/v1/rides/{ride_id}", {"price": new.min_fare}, format="json").status_code, 200)
        self.assertEqual(self.publish(self.range.min_fare).status_code, 400)  # new rides use the new rate

    def test_preview_returns_range(self):
        r = self.client.post("/api/v1/risk/preview", {"from": place_id("MAA"), "to": place_id("BLR"), "depart": tomorrow().strftime("%Y-%m-%dT%H:%M")}, format="json")
        self.assertEqual((r.json()["minFare"], r.json()["maxFare"]), (self.range.min_fare, self.range.max_fare))


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class RouteProfileAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_geo()

    def test_admin_edit_marks_distance_manual(self):
        root = User.objects.create_superuser("+919000000001", password="Root-pass-424242")
        self.client.force_login(root)
        route = RouteProfile.objects.between("MAA", "BLR").get()
        r = self.client.post(reverse("admin:geo_routeprofile_change", args=[route.pk]), {
            "city_a": route.city_a_id, "city_b": route.city_b_id, "km": 346, "incident_index": route.incident_index,
            "highway_share": route.highway_share, "ghat_sections": route.ghat_sections,
        })
        self.assertEqual(r.status_code, 302, r.content[:500])
        route.refresh_from_db()
        self.assertEqual((route.km, route.km_source), (346, DistanceSource.MANUAL))
