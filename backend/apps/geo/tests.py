from django.urls import reverse
from rest_framework.test import APITestCase

from apps.geo.models import City, MeetingPoint, RouteProfile
from apps.geo.regions import area_code, coast_for_state
from apps.geo.testing import seed_geo


class GeoTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        seed_geo()

    def test_test_fixture_is_idempotent(self):
        result = seed_geo()
        self.assertEqual(result["routes_created"], 0)
        self.assertEqual(City.objects.count(), 14)
        self.assertEqual(MeetingPoint.objects.count(), 42)
        self.assertEqual(RouteProfile.objects.count(), 91)

    def test_fixture_keeps_admin_edits_unless_overwritten(self):
        RouteProfile.objects.between("MAA", "BLR").update(incident_index=1.0)
        seed_geo()
        self.assertEqual(RouteProfile.objects.between("BLR", "MAA").get().incident_index, 1.0)
        seed_geo(overwrite_routes=True)
        self.assertNotEqual(RouteProfile.objects.between("BLR", "MAA").get().incident_index, 1.0)

    def test_area_detail_with_meeting_points(self):
        body = self.client.get(reverse("area-detail", args=["MAA"])).json()
        self.assertEqual((body["name"], body["state"]), ("Chennai", "Tamil Nadu"))
        self.assertEqual(
            body["meetingPoints"],
            ["Chennai Central Bus Stand", "Chennai Railway Station", "Chennai Airport Road Junction"],
        )
        self.assertNotIn("lat", body)  # no coordinates are stored on areas
        self.assertEqual(self.client.get(reverse("area-detail", args=["XXX"])).status_code, 404)

    def test_no_hardcoded_city_list_endpoint(self):
        self.assertEqual(self.client.get("/api/v1/cities").status_code, 404)

    def test_region_rules(self):
        self.assertEqual(coast_for_state("Tamil Nadu"), "east")
        self.assertEqual(coast_for_state(" kerala "), "west")
        self.assertEqual(coast_for_state("Karnataka"), "inland")
        code = area_code("Tamil Nadu", "Chengalpattu", "Tambaram")
        self.assertEqual(code, area_code("tamil nadu", "chengalpattu", " Tambaram "))
        self.assertEqual((len(code), code[0]), (11, "A"))
        area = City(code="X", name="Tambaram", district="Chengalpattu", state="Tamil Nadu")
        self.assertEqual(area.region, "Chengalpattu, Tamil Nadu")
        self.assertEqual(City(code="Y", name="Salem", district="Salem", state="Tamil Nadu").region, "Tamil Nadu")
