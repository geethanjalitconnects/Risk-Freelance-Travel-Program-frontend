from django.urls import reverse
from rest_framework.test import APITestCase

from apps.geo.models import City, MeetingPoint, RouteProfile
from apps.geo.seed import seed_geo


class GeoTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        seed_geo()

    def test_seed_is_idempotent(self):
        result = seed_geo()
        self.assertEqual(result["routes_created"], 0)
        self.assertEqual(City.objects.count(), 14)
        self.assertEqual(MeetingPoint.objects.count(), 42)
        self.assertEqual(RouteProfile.objects.count(), 91)

    def test_seed_keeps_admin_edits_unless_overwritten(self):
        RouteProfile.objects.between("MAA", "BLR").update(incident_index=1.0)
        seed_geo()
        self.assertEqual(RouteProfile.objects.between("BLR", "MAA").get().incident_index, 1.0)
        seed_geo(overwrite_routes=True)
        self.assertNotEqual(RouteProfile.objects.between("BLR", "MAA").get().incident_index, 1.0)

    def test_city_list_matches_frontend_shape(self):
        r = self.client.get(reverse("city-list"))
        self.assertEqual(r.status_code, 200)
        cities = r.json()
        self.assertEqual(len(cities), 14)
        chennai = next(c for c in cities if c["code"] == "MAA")
        self.assertEqual(chennai["name"], "Chennai")
        self.assertEqual(chennai["coast"], "east")
        self.assertEqual(
            chennai["meetingPoints"],
            ["Chennai Central Bus Stand", "Chennai Railway Station", "Chennai Airport Road Junction"],
        )

    def test_city_detail(self):
        self.assertEqual(self.client.get(reverse("city-detail", args=["BLR"])).json()["name"], "Bengaluru")
        self.assertEqual(self.client.get(reverse("city-detail", args=["XXX"])).status_code, 404)
