"""Places proxy, place -> area resolution, the 30-day coordinate cache and nearby search.
Google is always mocked: no real calls."""
import io
import json
import urllib.error
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.geo.models import City
from apps.geo.testing import seed_geo
from apps.places.models import PlaceCache, PlacesUsage
from apps.places.resolve import Resolved
from apps.rides.services import near

KEY = "AIzaTEST-not-a-real-key"
ON = dict(PLACES_ENABLED=True, GOOGLE_MAPS_API_KEY=KEY, PLACES_PRIMARY_TYPES=["(regions)"])
SESSION = "0b6f1c1e-7a52-4d39-9d1b-1d2c3e4f5a6b"
PLACE = "ChIJ_TambaramPlaceId_123"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def ok(payload):
    return FakeResponse(json.dumps(payload).encode())


def http_error(code, status=""):
    body = io.BytesIO(json.dumps({"error": {"status": status}}).encode())
    return urllib.error.HTTPError("https://places.googleapis.com/v1/x", code, "err", {}, body)


AC_PAYLOAD = {"suggestions": [
    {"placePrediction": {
        "placeId": PLACE, "text": {"text": "Tambaram, Chennai, Tamil Nadu, India"},
        "structuredFormat": {"mainText": {"text": "Tambaram"}, "secondaryText": {"text": "Chennai, Tamil Nadu, India"}},
    }},
    {"queryPrediction": {"text": {"text": "tambaram hotels"}}},  # ignored
]}


def place(taluk="Tambaram", district="Chengalpattu", state="Tamil Nadu", country="IN", locality=None,
          location=(12.9249, 80.1000), place_id=PLACE):
    """A Place Details (New) answer with the fields we ask for."""
    comps = []
    if locality:
        comps.append({"longText": locality, "shortText": locality, "types": ["locality", "political"]})
    if taluk:
        comps.append({"longText": taluk, "shortText": taluk, "types": ["administrative_area_level_3", "political"]})
    if district:
        comps.append({"longText": district, "shortText": district, "types": ["administrative_area_level_2", "political"]})
    if state:
        comps.append({"longText": state, "shortText": "XX", "types": ["administrative_area_level_1", "political"]})
    comps.append({"longText": "India" if country == "IN" else "Sri Lanka", "shortText": country, "types": ["country", "political"]})
    out = {"id": place_id, "addressComponents": comps}
    if location:
        out["location"] = {"latitude": location[0], "longitude": location[1]}
    return out


@override_settings(**ON)
class PlacesBase(APITestCase):
    def setUp(self):
        cache.clear()
        p = mock.patch("apps.places.google.urllib.request.urlopen")
        self.urlopen = p.start()
        self.addCleanup(p.stop)

    def ac(self, q="Tambaram", session=SESSION):
        return self.client.get(reverse("places-autocomplete"), {"q": q, "session": session})

    def details(self, place_id=PLACE, session=SESSION):
        return self.client.get(reverse("places-details"), {"placeId": place_id, "session": session})

    def usage(self, kind):
        return sum(PlacesUsage.objects.filter(kind=kind).values_list("count", flat=True))


class AutocompleteTests(PlacesBase):
    def test_request_shape_and_answer(self):
        self.urlopen.return_value = ok(AC_PAYLOAD)
        r = self.ac("  Tambaram  ")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json(), {"suggestions": [{
            "placeId": PLACE, "text": "Tambaram, Chennai, Tamil Nadu, India",
            "main": "Tambaram", "secondary": "Chennai, Tamil Nadu, India",
        }], "attribution": "Google Maps"})

        req = self.urlopen.call_args.args[0]
        self.assertEqual((req.get_method(), req.full_url), ("POST", "https://places.googleapis.com/v1/places:autocomplete"))
        self.assertNotIn(KEY, req.full_url)
        self.assertEqual(req.get_header("X-goog-api-key"), KEY)
        self.assertIn("suggestions.placePrediction.placeId", req.get_header("X-goog-fieldmask"))
        body = json.loads(req.data)
        self.assertEqual(body["input"], "Tambaram")
        self.assertEqual(body["sessionToken"], SESSION)
        self.assertEqual(body["includedRegionCodes"], ["in"])  # the hard India restriction
        self.assertEqual((body["regionCode"], body["languageCode"]), ("in", "en"))
        self.assertIn("rectangle", body["locationBias"])  # never IP-biased to our server
        self.assertEqual(body["includedPrimaryTypes"], ["(regions)"])
        self.assertEqual(self.usage("autocomplete"), 1)

    def test_validation(self):
        self.assertEqual(self.ac("ta").json()["code"], "too_short")
        self.assertEqual(self.ac("x" * 101).json()["code"], "too_long")
        self.assertEqual(self.ac(session="not a token!").json()["code"], "bad_session")
        self.assertEqual(self.ac(session="x" * 37).json()["code"], "bad_session")
        self.urlopen.assert_not_called()

    def test_repeated_query_is_cached(self):
        self.urlopen.return_value = ok(AC_PAYLOAD)
        self.ac("Tambaram")
        r = self.ac("tambaram", session="another-session")
        self.assertEqual(r.json()["suggestions"][0]["main"], "Tambaram")
        self.assertEqual(self.urlopen.call_count, 1)
        self.assertEqual((self.usage("autocomplete"), self.usage("autocomplete_cached")), (1, 1))

    @override_settings(PLACES_ENABLED=False)
    def test_switched_off(self):
        r = self.ac()
        self.assertEqual((r.status_code, r.json()["code"]), (503, "places_disabled"))
        self.urlopen.assert_not_called()

    @override_settings(GOOGLE_MAPS_API_KEY="")
    def test_no_key(self):
        self.assertEqual(self.ac().json()["code"], "places_disabled")

    def test_google_errors_are_friendly_and_never_log_the_key(self):
        for exc in (http_error(403, "PERMISSION_DENIED"), http_error(429, "RESOURCE_EXHAUSTED"),
                    urllib.error.URLError("down"), TimeoutError()):
            cache.clear()
            self.urlopen.side_effect = exc
            with self.assertLogs("apps.places.google", "WARNING") as logs:
                r = self.ac()
            self.assertEqual((r.status_code, r.json()["code"]), (503, "places_unavailable"))
            self.assertIn("try again", r.json()["detail"])
            self.assertNotIn(KEY, " ".join(logs.output))
        self.assertEqual(self.usage("error"), 4)

    def test_throttled(self):
        self.urlopen.return_value = ok({"suggestions": []})
        from rest_framework.throttling import SimpleRateThrottle

        rates = {**SimpleRateThrottle.THROTTLE_RATES, "places_autocomplete": "2/min"}
        with mock.patch.object(SimpleRateThrottle, "THROTTLE_RATES", rates):
            codes = [self.ac(f"query{i}").status_code for i in range(3)]
        self.assertEqual(codes, [200, 200, 429])


class DetailsTests(PlacesBase):
    def test_creates_area_and_caches_coordinates(self):
        self.urlopen.return_value = ok(place(locality="Selaiyur"))
        r = self.details()
        self.assertEqual(r.status_code, 200, r.content)
        area = r.json()["area"]
        self.assertEqual((area["name"], area["district"], area["state"]), ("Tambaram", "Chengalpattu", "Tamil Nadu"))
        self.assertEqual((area["region"], area["meetingPoints"]), ("Chengalpattu, Tamil Nadu", []))
        self.assertNotIn("lat", json.dumps(r.json()))  # coordinates stay on the server

        req = self.urlopen.call_args.args[0]
        self.assertEqual(req.get_method(), "GET")
        self.assertTrue(req.full_url.startswith(f"https://places.googleapis.com/v1/places/{PLACE}?"))
        self.assertIn(f"sessionToken={SESSION}", req.full_url)  # closes the autocomplete session
        self.assertNotIn(KEY, req.full_url)
        self.assertEqual(req.get_header("X-goog-fieldmask"), "id,addressComponents,location")  # Essentials only

        city = City.objects.get(code=area["code"])
        self.assertEqual(city.coast, "east")
        row = PlaceCache.objects.get(place_id=PLACE)
        self.assertEqual((row.area, row.lat, row.lng), (city, 12.9249, 80.1))
        self.assertEqual(self.usage("details"), 1)

    def test_area_falls_back_to_locality_then_district(self):
        self.urlopen.return_value = ok(place(taluk=None, locality="Avadi", district="Tiruvallur"))
        self.assertEqual(self.details().json()["area"]["name"], "Avadi")
        self.urlopen.return_value = ok(place(taluk=None, district="Tiruvallur", place_id="ChIJ_other_place_1"))
        self.assertEqual(self.details("ChIJ_other_place_1").json()["area"]["name"], "Tiruvallur")

    def test_same_place_reuses_the_area_and_cache(self):
        self.urlopen.return_value = ok(place())
        first = self.details().json()["area"]["code"]
        self.urlopen.return_value = ok(place(place_id="ChIJ_tambaram_west"))
        self.assertEqual(self.details("ChIJ_tambaram_west").json()["area"]["code"], first)  # same taluk
        self.details()  # fresh cache row: no Google call
        self.assertEqual(self.urlopen.call_count, 2)
        self.assertEqual(City.objects.count(), 1)

    def test_same_name_in_two_states_gives_two_areas(self):
        self.urlopen.return_value = ok(place(taluk="Aurangabad", district="Aurangabad", state="Maharashtra"))
        a = self.details().json()["area"]["code"]
        self.urlopen.return_value = ok(place(taluk="Aurangabad", district="Aurangabad", state="Bihar", place_id="ChIJ_aurangabad_bihar"))
        self.assertNotEqual(self.details("ChIJ_aurangabad_bihar").json()["area"]["code"], a)

    def test_expired_coordinates_are_fetched_again(self):
        self.urlopen.return_value = ok(place())
        self.details()
        PlaceCache.objects.update(fetched_at=timezone.now() - timedelta(days=30))
        self.urlopen.return_value = ok(place(location=(12.93, 80.11)))
        self.details()
        self.assertEqual(self.urlopen.call_count, 2)
        self.assertEqual(PlaceCache.objects.get().lat, 12.93)

    def test_non_india_is_rejected(self):
        self.urlopen.return_value = ok(place(taluk="Colombo", district="Colombo", state="Western Province", country="LK"))
        r = self.details()
        self.assertEqual((r.status_code, r.json()), (400, {"code": "not_india", "detail": "Only places in India are supported."}))
        self.assertFalse(PlaceCache.objects.exists())
        self.assertFalse(City.objects.exists())

    def test_missing_country_or_state_or_location(self):
        self.urlopen.return_value = ok({"id": PLACE, "addressComponents": []})
        self.assertEqual(self.details().json()["code"], "not_india")
        self.urlopen.return_value = ok(place(state=None))
        self.assertEqual(self.details().json()["code"], "unknown_place")
        self.urlopen.return_value = ok(place(location=None))
        self.assertEqual(self.details().json()["code"], "unknown_place")

    def test_validation_and_errors(self):
        self.assertEqual(self.details(place_id="bad id!").json()["code"], "bad_place")
        self.assertEqual(self.details(session="").json()["code"], "bad_session")
        self.urlopen.side_effect = http_error(404, "NOT_FOUND")
        self.assertEqual(self.details().json()["code"], "bad_place")
        self.urlopen.side_effect = http_error(500)
        r = self.details()
        self.assertEqual((r.status_code, r.json()["code"]), (503, "places_unavailable"))
        self.assertEqual(self.usage("error"), 2)


class RefreshCacheCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_geo()

    @override_settings(**ON)
    def test_deletes_expired_and_refreshes_places_of_upcoming_rides(self):
        from apps.accounts.models import User
        from apps.rides.models import Ride

        driver = User.objects.create_user("+919000000001", name="Asha")
        maa, blr = City.objects.get(code="MAA"), City.objects.get(code="BLR")
        old = timezone.now() - timedelta(days=27)
        PlaceCache.objects.create(place_id="ChIJ_upcoming_ride", area=maa, lat=13.0, lng=80.2, fetched_at=old)
        PlaceCache.objects.create(place_id="ChIJ_expired_place", area=maa, lat=13.0, lng=80.2,
                                  fetched_at=timezone.now() - timedelta(days=31))
        Ride.objects.create(
            driver=driver, origin=maa, destination=blr, origin_place_id="ChIJ_upcoming_ride", pickup="A", dropoff="B",
            depart=timezone.now() + timedelta(days=3), duration_min=300, km=370, price=600, seats_total=3,
            vehicle_model="Creta", vehicle_year=2023,
        )
        answer = place(taluk="Chennai", district="Chennai", location=(13.05, 80.25), place_id="ChIJ_upcoming_ride")
        with mock.patch("apps.places.google.urllib.request.urlopen", return_value=ok(answer)) as urlopen:
            out = io.StringIO()
            call_command("refresh_place_cache", stdout=out)
        self.assertEqual(urlopen.call_count, 1)
        self.assertIn("Refreshed 1, failed 0, deleted 1", out.getvalue())
        self.assertFalse(PlaceCache.objects.filter(place_id="ChIJ_expired_place").exists())
        self.assertEqual(PlaceCache.objects.get(place_id="ChIJ_upcoming_ride").lat, 13.05)
        self.assertTrue(PlaceCache.objects.filter(place_id__startswith="ChIJtest").exists())  # fresh rows kept


class NearbySearchTests(TestCase):
    """services.near: rides start / end within PLACES_SEARCH_RADIUS_KM of the picked places."""

    @classmethod
    def setUpTestData(cls):
        seed_geo()
        cls.maa, cls.blr = City.objects.get(code="MAA"), City.objects.get(code="BLR")
        cls.tambaram = City.objects.create(code="ATAMBARAM01", name="Tambaram", district="Chengalpattu",
                                           state="Tamil Nadu", coast="east")
        PlaceCache.objects.create(place_id="ChIJ_tambaram_stn", area=cls.tambaram, lat=12.9249, lng=80.1000,
                                  fetched_at=timezone.now())

    def ride(self, origin_place, origin=None):
        return SimpleNamespace(origin_place_id=origin_place, origin=origin or self.tambaram,
                               destination_place_id="ChIJtestBLRplace", destination=self.blr)

    def picked(self, lat, lng, area=None):
        return Resolved("ChIJ_searched_place", area or self.maa, lat, lng)

    @override_settings(PLACES_SEARCH_RADIUS_KM=25)
    def test_radius(self):
        ride = self.ride("ChIJ_tambaram_stn")
        bengaluru = self.picked(12.9716, 77.5946, self.blr)
        chennai_central = self.picked(13.0827, 80.2707)  # ~25 km from Tambaram as the crow flies
        guindy = self.picked(13.0067, 80.2206)  # ~16 km
        vellore = self.picked(12.9165, 79.1325)  # ~105 km
        self.assertEqual(near([ride], guindy, bengaluru), [ride])
        self.assertEqual(ride._match["to_km"], 0.0)
        self.assertLess(ride._match["from_km"], 25)
        self.assertEqual(near([ride], vellore, bengaluru), [])
        with override_settings(PLACES_SEARCH_RADIUS_KM=10):
            self.assertEqual(near([ride], guindy, bengaluru), [])
        self.assertIsInstance(near([ride], chennai_central, bengaluru), list)

    def test_without_cached_coordinates_the_same_area_matches(self):
        ride = self.ride("ChIJ_not_cached_place")
        bengaluru = self.picked(12.9716, 77.5946, self.blr)
        self.assertEqual(near([ride], self.picked(0, 0, self.tambaram), bengaluru), [ride])
        self.assertEqual(near([ride], self.picked(12.92, 80.10, self.maa), bengaluru), [])


GEOCODE_OK = {"status": "OK", "results": [{
    "place_id": "ChIJ_geocoded_tambaram",
    "address_components": [
        {"long_name": "Tambaram", "short_name": "Tambaram", "types": ["locality", "political"]},
        {"long_name": "Tambaram", "short_name": "Tambaram", "types": ["administrative_area_level_3", "political"]},
        {"long_name": "Chengalpattu", "short_name": "Chengalpattu", "types": ["administrative_area_level_2", "political"]},
        {"long_name": "Tamil Nadu", "short_name": "TN", "types": ["administrative_area_level_1", "political"]},
        {"long_name": "India", "short_name": "IN", "types": ["country", "political"]},
    ],
    "geometry": {"location": {"lat": 12.9249, "lng": 80.1}},
}]}


class ReverseTests(PlacesBase):
    def reverse(self, lat=12.92, lng=80.11):
        return self.client.get(reverse("places-reverse"), {"lat": lat, "lng": lng})

    def test_position_to_area(self):
        self.urlopen.return_value = ok(GEOCODE_OK)
        r = self.reverse()
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual((body["placeId"], body["label"], body["area"]["name"]),
                         ("ChIJ_geocoded_tambaram", "Tambaram", "Tambaram"))
        url = self.urlopen.call_args.args[0].full_url
        self.assertTrue(url.startswith("https://maps.googleapis.com/maps/api/geocode/json?"))
        self.assertIn("result_type=sublocality%7Clocality%7Cadministrative_area_level_3", url)
        row = PlaceCache.objects.get(place_id="ChIJ_geocoded_tambaram")
        self.assertEqual((row.lat, row.lng), (12.9249, 80.1))  # the place, not the user's position
        self.assertEqual(self.usage("reverse"), 1)

    def test_outside_india_and_bad_input_never_call_google(self):
        self.assertEqual(self.reverse(51.5, -0.12).json()["code"], "not_india")
        self.assertEqual(self.reverse("x", "y").json()["code"], "bad_position")
        self.urlopen.assert_not_called()

    def test_no_result_and_denied(self):
        self.urlopen.return_value = ok({"status": "ZERO_RESULTS", "results": []})
        self.assertEqual(self.reverse().status_code, 404)
        self.urlopen.return_value = ok({"status": "REQUEST_DENIED", "error_message": "API not enabled"})
        with self.assertLogs("apps.places.google", "WARNING") as logs:
            r = self.reverse()
        self.assertEqual((r.status_code, r.json()["code"]), (503, "places_unavailable"))
        self.assertNotIn(KEY, " ".join(logs.output))

    @override_settings(PLACES_ENABLED=False)
    def test_switched_off(self):
        self.assertEqual(self.reverse().json()["code"], "places_disabled")
