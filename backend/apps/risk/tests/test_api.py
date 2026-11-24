from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.geo.testing import place_id, seed_geo


class RiskApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        seed_geo()

    def test_config(self):
        r = self.client.get(reverse("risk-config"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual([b["key"] for b in r.json()["bands"]], ["low", "moderate", "elevated", "high"])
        self.assertEqual(r.json()["vehicleFeatures"]["firstaid"], "First-aid kit")

    def test_samples_are_camel_cased(self):
        r = self.client.get(reverse("risk-samples"))
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(len(body["drivers"]), 10)
        self.assertEqual(len(body["vehicles"]), 7)
        self.assertIn("verifiedLicense", body["drivers"][0])

    def test_calculator_accepts_codes_and_returns_frontend_shape(self):
        r = self.client.post(
            reverse("risk-score"),
            {"from": place_id("MAA"), "to": place_id("BLR"), "depart": "2026-11-15T22:30", "sampleDriver": 0, "sampleVehicle": 0},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        risk = r.json()
        self.assertEqual(set(risk), {"score", "band", "components", "tips", "profile"})
        self.assertEqual(set(risk["band"]), {"key", "label", "max"})
        self.assertEqual([c["key"] for c in risk["components"]], ["route", "time", "driver", "weather", "fatigue", "vehicle"])
        self.assertIn("incidentIndex", risk["profile"])

    def test_calculator_accepts_city_names(self):
        r = self.client.post(
            reverse("risk-score"), {"from": place_id("MAA"), "to": place_id("BLR"), "depart": "2026-11-15T10:00"}, format="json"
        )
        self.assertEqual(r.status_code, 200, r.content)

    def test_same_city_rejected(self):
        r = self.client.post(reverse("risk-score"), {"from": place_id("MAA"), "to": place_id("MAA"), "depart": "2026-11-15T10:00"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("to", r.json())

    def test_unknown_city_and_bad_sample_rejected(self):
        r = self.client.post(
            reverse("risk-score"), {"from": "Atlantis", "to": place_id("BLR"), "depart": "2026-11-15T10:00", "sampleDriver": 99}, format="json"
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("from", r.json())
        self.assertIn("sampleDriver", r.json())

    def test_preview_returns_fare_range_and_duration(self):
        r = self.client.post(
            reverse("risk-preview"),
            {"from": place_id("MAA"), "to": place_id("BLR"), "depart": "2026-11-15T07:00", "vehicle": {"model": "Creta", "year": 2023, "features": ["airbags", "abs"]}},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["km"], body["risk"]["profile"]["km"])
        self.assertEqual(body["minFare"] % 10, 0)
        self.assertGreaterEqual(body["minFare"], body["km"] * 15)  # Rs 15/km default
        self.assertEqual(body["maxFare"], body["minFare"] * 3 // 2 // 10 * 10)
        self.assertGreaterEqual(body["durationMin"], 30)
        driver = next(c for c in body["risk"]["components"] if c["key"] == "driver")
        self.assertIn("ID not verified", driver["detail"])

    def test_preview_uses_signed_in_user_verification(self):
        user = User.objects.create_user("+919876543210", name="Asha", verified_id=True, verified_license=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
        r = self.client.post(reverse("risk-preview"), {"from": place_id("MAA"), "to": place_id("BLR"), "depart": "2026-11-15T07:00"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        driver = next(c for c in r.json()["risk"]["components"] if c["key"] == "driver")
        self.assertTrue(driver["detail"].startswith("ID verified, licence verified"))

    def test_preview_rejects_unknown_feature(self):
        r = self.client.post(
            reverse("risk-preview"),
            {"from": place_id("MAA"), "to": place_id("BLR"), "depart": "2026-11-15T07:00", "vehicle": {"features": ["jetpack"]}},
            format="json",
        )
        self.assertEqual(r.status_code, 400)
