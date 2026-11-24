"""The Python risk model must give exactly the same output as the frontend's risk.js.

Fixtures come from scripts/risk_parity/generate.mjs, which runs the frontend code itself.
"""
import json
from datetime import datetime
from pathlib import Path

from django.test import TestCase
from djangorestframework_camel_case.util import camelize

from apps.geo.models import City, RouteProfile
from apps.geo.testing import seed_geo
from apps.risk.scoring import DriverProfile, Route, VehicleProfile, score_trip
from apps.risk.services import route_between

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "js_parity.json").read_text())


def driver_from(d):
    if d is None:
        return None
    return DriverProfile(
        verified_id=d["verifiedId"], verified_license=d["verifiedLicense"], rating=d["rating"], trips=d["trips"]
    )


def vehicle_from(v):
    return None if v is None else VehicleProfile(year=v["year"], features=v["features"])


class RouteProfileParityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_geo()

    def test_seeded_route_profiles_match_js(self):
        self.assertEqual(RouteProfile.objects.count(), len(FIXTURE["routes"]))
        for r in FIXTURE["routes"]:
            row = RouteProfile.objects.get(city_a_id=r["a"], city_b_id=r["b"])
            with self.subTest(route=f"{r['a']}-{r['b']}"):
                self.assertEqual(row.km, r["km"])
                self.assertEqual(row.incident_index, r["incidentIndex"])
                self.assertEqual(row.highway_share, r["highwayShare"])
                self.assertEqual(row.ghat_sections, r["ghatSections"])
                self.assertEqual(row.hours, r["hours"])


class ScoreParityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_geo()
        cls.cities = {c.code: c for c in City.objects.all()}

    def test_every_fixture_case_matches_js(self):
        routes = {}
        mismatches = []
        for i, case in enumerate(FIXTURE["cases"]):
            inp = case["input"]
            origin, dest = self.cities[inp["from"]], self.cities[inp["to"]]
            key = (inp["from"], inp["to"])
            if key not in routes:
                routes[key] = route_between(origin, dest, RouteProfile.objects.between(*key).get().km)
            got = score_trip(
                route=routes[key],
                origin=origin,
                destination=dest,
                depart=datetime.fromisoformat(inp["depart"]),
                driver=driver_from(inp["driver"]),
                vehicle=vehicle_from(inp["vehicle"]),
                current_year=FIXTURE["year"],
            )
            if camelize(got) != case["output"]:
                mismatches.append((i, inp, camelize(got), case["output"]))
        self.assertFalse(mismatches, f"{len(mismatches)} mismatches; first: {mismatches[:1]}")


class ScoringUnitTests(TestCase):
    route = Route(km=300, incident_index=5.0, highway_share=70, ghat_sections=0)

    def test_whole_number_incident_index_prints_like_js(self):
        from apps.risk.scoring import Place

        out = score_trip(
            route=self.route, origin=Place("inland"), destination=Place("inland"),
            depart=datetime(2026, 1, 10, 10, 0), driver=None, vehicle=None, current_year=2026,
        )
        self.assertTrue(out["components"][0]["detail"].startswith("Incident index 5/10"))

    def test_band_boundaries(self):
        from apps.risk.scoring import band_for

        self.assertEqual(band_for(29)["key"], "low")
        self.assertEqual(band_for(30)["key"], "moderate")
        self.assertEqual(band_for(69)["key"], "elevated")
        self.assertEqual(band_for(70)["key"], "high")
        self.assertEqual(band_for(100)["key"], "high")
