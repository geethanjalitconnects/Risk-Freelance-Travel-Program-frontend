from datetime import datetime, time, timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.bookings.models import Booking, BookingStatus
from apps.fares.services import fare_range
from apps.geo.models import City, RouteProfile
from apps.geo.seed import seed_geo
from apps.rides.models import Ride, RideStatus, TravelWith
from apps.rides.policies import gender_lock_reason
from apps.verification.testing import approve_driver


def local(days=1, hour=7, minute=0):
    d = timezone.localdate() + timedelta(days=days)
    return timezone.make_aware(datetime.combine(d, time(hour, minute)))


def fmt(dt):
    return timezone.localtime(dt).strftime("%Y-%m-%dT%H:%M")


class RideTestBase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        seed_geo()
        cls.maa = City.objects.get(code="MAA")
        cls.blr = City.objects.get(code="BLR")
        cls.female = User.objects.create_user("+919000000001", name="Asha Rao", gender="F", verified_id=True, verified_license=True)
        cls.male = User.objects.create_user("+919000000002", name="Ravi Kumar", gender="M")
        cls.unset = User.objects.create_user("+919000000003", name="Sam")
        cls.other_f = User.objects.create_user("+919000000004", name="Divya", gender="F")
        # Publishing requires an approved driver verification.
        for u in (cls.female, cls.male, cls.unset, cls.other_f):
            approve_driver(u)

    def fares(self, a="MAA", b="BLR"):
        """Current allowed fare range for a route (Rs 15/km default settings)."""
        return fare_range(RouteProfile.objects.between(a, b).get().km)

    def auth(self, user):
        if user is None:
            self.client.credentials()
        else:
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")

    def payload(self, **over):
        body = {
            "from": "Chennai",
            "to": "Bengaluru",
            "depart": fmt(local()),
            "price": self.fares().min_fare,
            "seatsTotal": 3,
            "vehicle": {"model": "Hyundai Creta", "year": 2023, "features": ["airbags", "abs"]},
            "notes": "One tea stop.",
        }
        body.update(over)
        return body

    def make_ride(self, driver=None, **over):
        fields = dict(
            driver=driver or self.female,
            origin=self.maa,
            destination=self.blr,
            pickup="Chennai Central Bus Stand",
            dropoff="Bengaluru Central Bus Stand",
            depart=local(),
            duration_min=300,
            km=370,
            price=self.fares().min_fare,
            seats_total=3,
            vehicle_model="Hyundai Creta",
            vehicle_year=2023,
            vehicle_features=["airbags", "abs"],
        )
        fields.update(over)
        return Ride.objects.create(**fields)

    def book(self, ride, passenger, seats=1, status=BookingStatus.CONFIRMED, rating=None):
        return Booking.objects.create(
            ride=ride, passenger=passenger, seats=seats, total=ride.price * seats,
            risk_score=30, risk_band="moderate", status=status, rating=rating,
        )

    def search(self, **params):
        q = {"from": "Chennai", "to": "Bengaluru", "date": local().date().isoformat(), **params}
        return self.client.get(reverse("ride-search"), q)


class PublishTests(RideTestBase):
    def test_publish_returns_frontend_ride_shape(self):
        self.auth(self.female)
        r = self.client.post(reverse("ride-create"), self.payload(), format="json")
        self.assertEqual(r.status_code, 201, r.content)
        ride = r.json()
        for key in [
            "id", "source", "from", "to", "date", "depart", "durationMin", "arrive", "km", "price", "seatsTotal",
            "seatsLeft", "driver", "vehicle", "pickup", "dropoff", "womenOnly", "ac", "bags", "notes", "risk",
        ]:
            self.assertIn(key, ride)
        self.assertEqual((ride["from"], ride["to"]), ("MAA", "BLR"))
        self.assertEqual(ride["depart"], fmt(local()))
        self.assertEqual(ride["date"], local().date().isoformat())
        self.assertRegex(ride["arrive"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d$")
        self.assertEqual(ride["seatsLeft"], 3)
        self.assertEqual(ride["pickup"], "Chennai Central Bus Stand")  # default meeting point
        self.assertEqual(ride["dropoff"], "Bengaluru Central Bus Stand")
        self.assertEqual(ride["travelWith"], "anyone")
        self.assertFalse(ride["womenOnly"])
        self.assertEqual(ride["bags"], "One cabin bag")
        self.assertTrue(ride["ac"])
        self.assertEqual(ride["driver"]["name"], "Asha Rao")
        self.assertIsNone(ride["driver"]["rating"])
        self.assertEqual(ride["driver"]["langs"], ["English"])
        self.assertNotIn("phone", ride["driver"])
        # The driver sees their own registration number; other riders don't (see verification tests).
        self.assertEqual(ride["vehicle"], {"model": "Hyundai Creta", "year": 2023, "features": ["airbags", "abs"], "number": "TN09AB1234"})
        self.assertTrue(ride["isOwn"])
        self.assertFalse(ride["hasBookings"])
        self.assertFalse(ride["canBook"])
        self.assertEqual(ride["cannotBookCode"], "own_ride")
        self.assertEqual(ride["km"], ride["risk"]["profile"]["km"])

    def test_publish_requires_sign_in(self):
        self.auth(None)
        self.assertEqual(self.client.post(reverse("ride-create"), self.payload(), format="json").status_code, 401)

    def test_publish_validation_matches_publish_page(self):
        self.auth(self.female)
        cases = {
            "to": self.payload(to="Chennai"),
            "depart": self.payload(depart=fmt(timezone.now() - timedelta(hours=1))),
            "price": self.payload(price=40),
            "vehicle": self.payload(vehicle={"model": "Swift", "year": 1990}),
            "pickup": self.payload(pickup="Somewhere else"),
            "notes": self.payload(notes="x" * 141),
            "seatsTotal": self.payload(seatsTotal=5),
            "from": self.payload(**{"from": "Atlantis"}),
        }
        for field, body in cases.items():
            with self.subTest(field=field):
                r = self.client.post(reverse("ride-create"), body, format="json")
                self.assertEqual(r.status_code, 400, r.content)
                self.assertIn(field, r.json())
        r = self.client.post(reverse("ride-create"), self.payload(price=40), format="json")
        self.assertIn(f"at least ₹{self.fares().min_fare} per seat", r.json()["price"][0])

    def test_unknown_vehicle_feature_rejected_and_duplicates_removed(self):
        self.auth(self.female)
        bad = self.payload(vehicle={"model": "Swift", "year": 2022, "features": ["jetpack"]})
        self.assertEqual(self.client.post(reverse("ride-create"), bad, format="json").status_code, 400)
        dup = self.payload(vehicle={"model": "Swift", "year": 2022, "features": ["abs", "abs", "gps"]})
        r = self.client.post(reverse("ride-create"), dup, format="json")
        self.assertEqual(r.json()["vehicle"]["features"], ["abs", "gps"])


class TravelWithPublishTests(RideTestBase):
    def attempt(self, user, travel_with):
        self.auth(user)
        return self.client.post(reverse("ride-create"), self.payload(travelWith=travel_with), format="json")

    def test_driver_gender_rules(self):
        expected = {
            (self.female, "women"): 201,
            (self.female, "men"): 400,
            (self.male, "men"): 201,
            (self.male, "women"): 400,
            (self.unset, "women"): 400,
            (self.unset, "men"): 400,
            (self.female, "anyone"): 201,
            (self.male, "anyone"): 201,
            (self.unset, "anyone"): 201,
        }
        for (user, tw), code in expected.items():
            with self.subTest(user=user.name, travel_with=tw):
                r = self.attempt(user, tw)
                self.assertEqual(r.status_code, code, r.content)
                if code == 400:
                    self.assertIn("travelWith", r.json())

    def test_women_only_ride_sets_legacy_flag(self):
        r = self.attempt(self.female, "women")
        self.assertTrue(r.json()["womenOnly"])
        self.assertEqual(r.json()["travelWith"], "women")


class SearchTests(RideTestBase):
    def test_finds_rides_by_city_name_or_code(self):
        ride = self.make_ride()
        self.auth(None)
        for params in ({}, {"from": "MAA", "to": "blr"}):
            r = self.search(**params)
            self.assertEqual(r.status_code, 200, r.content)
            self.assertEqual([x["id"] for x in r.json()], [str(ride.id)])

    def test_hides_cancelled_full_and_soon_departing_rides(self):
        self.make_ride(status=RideStatus.CANCELLED)
        full = self.make_ride(seats_total=1)
        self.book(full, self.male)
        soon = timezone.now() + timedelta(minutes=20)
        if timezone.localtime(soon).date() == local().date():  # only meaningful on the searched date
            self.make_ride(depart=soon)
        self.assertEqual(self.search().json(), [])

    def test_seats_filter_counts_existing_bookings(self):
        ride = self.make_ride(seats_total=3)
        self.book(ride, self.male, seats=2)
        self.assertEqual(self.search(seats=1).json()[0]["seatsLeft"], 1)
        self.assertEqual(self.search(seats=2).json(), [])
        # cancelled bookings free their seats
        Booking.objects.update(status=BookingStatus.CANCELLED)
        self.assertEqual(len(self.search(seats=3).json()), 1)

    def test_filters(self):
        day = self.make_ride(driver=self.female, depart=local(hour=7), travel_with=TravelWith.WOMEN)
        night = self.make_ride(driver=self.male, depart=local(hour=22), travel_with=TravelWith.MEN)
        anyone = self.make_ride(driver=self.unset, depart=local(hour=12))
        ids = lambda r: {x["id"] for x in r.json()}  # noqa: E731
        self.assertEqual(ids(self.search()), {str(day.id), str(night.id), str(anyone.id)})
        self.assertEqual(ids(self.search(womenOnly="true")), {str(day.id)})
        self.assertEqual(ids(self.search(travelWith="men")), {str(night.id)})
        self.assertEqual(ids(self.search(travelWith="anyone")), {str(anyone.id)})
        # Every listed ride has an approved driver, so "verified" no longer narrows the results.
        self.assertEqual(ids(self.search(verified="true")), ids(self.search()))
        self.assertEqual(ids(self.search(daytime="true")), {str(day.id), str(anyone.id)})
        scores = {x["id"]: x["risk"]["score"] for x in self.search().json()}
        cutoff = max(scores.values())
        self.assertEqual(ids(self.search(maxRisk=cutoff)), {k for k, v in scores.items() if v < cutoff})

    def test_sorting(self):
        self.make_ride(depart=local(hour=9), price=900)
        self.make_ride(depart=local(hour=8), price=500)
        self.make_ride(depart=local(hour=23), price=700, vehicle_year=2005, vehicle_features=[])
        earliest = [x["depart"][-5:] for x in self.search().json()]
        self.assertEqual(earliest, ["08:00", "09:00", "23:00"])
        cheapest = [x["price"] for x in self.search(sort="cheapest").json()]
        self.assertEqual(cheapest, [500, 700, 900])
        safest = [x["risk"]["score"] for x in self.search(sort="safest").json()]
        self.assertEqual(safest, sorted(safest))

    def test_bad_searches(self):
        self.assertIn("to", self.search(to="Chennai").json())
        self.assertIn("date", self.search(date=(timezone.localdate() - timedelta(days=1)).isoformat()).json())
        self.assertEqual(self.search(**{"from": "Nowhere"}).status_code, 400)


class DetailTests(RideTestBase):
    def detail(self, ride):
        return self.client.get(reverse("ride-detail", args=[ride.id]))

    def test_anonymous_can_view_but_not_book(self):
        ride = self.make_ride()
        self.auth(None)
        body = self.detail(ride).json()
        self.assertFalse(body["canBook"])
        self.assertEqual(body["cannotBookCode"], "auth")
        self.assertFalse(body["isOwn"])
        self.assertIsNone(body["hasBookings"])

    def test_travel_with_eligibility(self):
        women = self.make_ride(driver=self.female, travel_with=TravelWith.WOMEN)
        men = self.make_ride(driver=self.male, travel_with=TravelWith.MEN)
        cases = [
            (women, self.other_f, True, None),
            (women, self.male, False, "travel_with"),
            (women, self.unset, False, "travel_with"),
            (men, self.male, False, "own_ride"),
            (men, self.other_f, False, "travel_with"),
        ]
        for ride, viewer, can, code in cases:
            with self.subTest(ride=ride.travel_with, viewer=viewer.name):
                self.auth(viewer)
                body = self.detail(ride).json()
                self.assertEqual(body["canBook"], can)
                self.assertEqual(body["cannotBookCode"], code)
        self.auth(self.unset)
        self.assertIn("Set your gender", self.detail(women).json()["cannotBookReason"])

    def test_my_booking_and_driver_stats(self):
        ride = self.make_ride()
        past = self.make_ride(depart=local(days=-3))
        self.book(past, self.male, status=BookingStatus.COMPLETED, rating=4)
        self.book(past, self.other_f, status=BookingStatus.COMPLETED, rating=5)
        booking = self.book(ride, self.male)
        self.auth(self.male)
        body = self.detail(ride).json()
        self.assertEqual(body["myBookingId"], str(booking.id))
        self.assertEqual(body["cannotBookCode"], "already_booked")
        self.assertEqual(body["seatsLeft"], 2)
        self.assertEqual(body["driver"]["rating"], 4.5)
        self.assertEqual(body["driver"]["trips"], 1)
        driver = next(c for c in body["risk"]["components"] if c["key"] == "driver")
        self.assertIn("4.5 rating", driver["detail"])

    def test_unknown_or_removed_ride_is_404(self):
        ride = self.make_ride(status=RideStatus.CANCELLED)
        self.assertEqual(self.detail(ride).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/rides/00000000-0000-0000-0000-000000000000").status_code, 404)


class EditTests(RideTestBase):
    def patch(self, ride, body, user=None):
        self.auth(user or ride.driver)
        return self.client.patch(reverse("ride-detail", args=[ride.id]), body, format="json")

    def test_driver_can_edit_unbooked_ride(self):
        ride = self.make_ride()
        price = self.fares().min_fare + 10
        r = self.patch(ride, {"notes": "Leaving sharp.", "price": price, "travelWith": "women", "seatsTotal": 4})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()["notes"], r.json()["price"], r.json()["travelWith"]), ("Leaving sharp.", price, "women"))

    def test_only_driver_can_edit(self):
        ride = self.make_ride()
        self.assertEqual(self.patch(ride, {"notes": "hi"}, user=self.male).status_code, 403)
        self.auth(None)
        self.assertEqual(self.client.patch(reverse("ride-detail", args=[ride.id]), {"notes": "x"}, format="json").status_code, 401)

    def test_travel_with_rules_apply_on_edit(self):
        ride = self.make_ride(driver=self.male)
        r = self.patch(ride, {"travelWith": "women"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("travelWith", r.json())

    def test_booked_ride_locks_preference_and_trip_terms(self):
        ride = self.make_ride(travel_with=TravelWith.ANYONE, seats_total=3)
        self.book(ride, self.male, seats=2)
        for body, field in [
            ({"travelWith": "women"}, "travelWith"),
            ({"price": self.fares().min_fare + 10}, "price"),
            ({"depart": fmt(local(hour=9))}, "depart"),
            ({"to": "Mysuru"}, "to"),
            ({"vehicle": {"year": 2018}}, "vehicle"),
            ({"seatsTotal": 1}, "seatsTotal"),
        ]:
            with self.subTest(field=field):
                r = self.patch(ride, body)
                self.assertEqual(r.status_code, 400, r.content)
                self.assertIn(field, r.json())
        r = self.patch(ride, {"travelWith": "women"})
        self.assertEqual(r.json()["travelWith"], ["Who can travel with you can't change once the ride has bookings."])
        # Unchanged values and harmless fields are still accepted.
        r = self.patch(ride, {"travelWith": "anyone", "price": self.fares().min_fare, "notes": "Updated", "seatsTotal": 2, "dropoff": "Bengaluru Railway Station"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["dropoff"], "Bengaluru Railway Station")

    def test_cancelled_bookings_do_not_lock(self):
        ride = self.make_ride()
        self.book(ride, self.male, status=BookingStatus.CANCELLED)
        self.assertEqual(self.patch(ride, {"travelWith": "women"}).status_code, 200)

    def test_changing_city_resets_meeting_point(self):
        ride = self.make_ride()
        r = self.patch(ride, {"to": "Mysuru"})  # the old fare is below the longer route's minimum
        self.assertIn("price", r.json())
        r = self.patch(ride, {"to": "Mysuru", "price": self.fares("MAA", "MYS").min_fare})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()["to"], r.json()["dropoff"]), ("MYS", "Mysuru Central Bus Stand"))
        self.assertNotEqual(r.json()["km"], 370)

    def test_departed_ride_cannot_be_edited(self):
        ride = self.make_ride(depart=local(days=-1))
        r = self.patch(ride, {"notes": "late"})
        self.assertEqual(r.status_code, 400)

    def test_put_not_allowed(self):
        ride = self.make_ride()
        self.auth(ride.driver)
        self.assertEqual(self.client.put(reverse("ride-detail", args=[ride.id]), self.payload(), format="json").status_code, 405)


class RemoveTests(RideTestBase):
    def delete(self, ride, user=None):
        self.auth(user or ride.driver)
        return self.client.delete(reverse("ride-detail", args=[ride.id]))

    def test_remove_unbooked_ride(self):
        ride = self.make_ride()
        self.assertEqual(self.delete(ride).status_code, 204)
        ride.refresh_from_db()
        self.assertEqual(ride.status, RideStatus.CANCELLED)
        self.assertEqual(self.client.get(reverse("ride-mine")).json(), [])
        self.assertEqual(self.delete(ride).status_code, 404)

    def test_ride_with_bookings_cannot_be_removed(self):
        for status in (BookingStatus.CONFIRMED, BookingStatus.IN_PROGRESS, BookingStatus.COMPLETED):
            with self.subTest(status=status):
                ride = self.make_ride()
                self.book(ride, self.male, status=status)
                r = self.delete(ride)
                self.assertEqual(r.status_code, 409)
                self.assertIn("has bookings", r.json()["detail"])

    def test_ride_with_only_cancelled_bookings_can_be_removed(self):
        ride = self.make_ride()
        self.book(ride, self.male, status=BookingStatus.CANCELLED)
        self.assertEqual(self.delete(ride).status_code, 204)

    def test_only_driver_can_remove(self):
        self.assertEqual(self.delete(self.make_ride(), user=self.male).status_code, 403)


class MyRidesTests(RideTestBase):
    def test_lists_only_my_active_rides(self):
        mine = self.make_ride(driver=self.female)
        self.make_ride(driver=self.female, status=RideStatus.CANCELLED)
        self.make_ride(driver=self.male)
        self.book(mine, self.male)
        self.auth(self.female)
        body = self.client.get(reverse("ride-mine")).json()
        self.assertEqual([r["id"] for r in body], [str(mine.id)])
        self.assertTrue(body[0]["hasBookings"])
        self.assertEqual(body[0]["seatsLeft"], 2)


class GenderLockTests(RideTestBase):
    def test_passenger_locked_by_active_restricted_booking(self):
        women = self.make_ride(driver=self.female, travel_with=TravelWith.WOMEN)
        self.assertIsNone(gender_lock_reason(self.other_f))
        b = self.book(women, self.other_f)
        self.assertIn("booking", gender_lock_reason(self.other_f))
        b.status = BookingStatus.IN_PROGRESS
        b.save()
        self.assertIsNotNone(gender_lock_reason(self.other_f))
        for done in (BookingStatus.COMPLETED, BookingStatus.CANCELLED):
            b.status = done
            b.save()
            self.assertIsNone(gender_lock_reason(self.other_f))

    def test_passenger_not_locked_by_anyone_ride_or_past_confirmed_booking(self):
        self.book(self.make_ride(), self.other_f)
        self.assertIsNone(gender_lock_reason(self.other_f))
        past = self.make_ride(driver=self.female, travel_with=TravelWith.WOMEN, depart=local(days=-2))
        self.book(past, self.other_f)  # never started, trip time is over
        self.assertIsNone(gender_lock_reason(self.other_f))

    def test_driver_locked_by_active_restricted_ride(self):
        self.make_ride(driver=self.male, travel_with=TravelWith.ANYONE)
        self.assertIsNone(gender_lock_reason(self.male))
        ride = self.make_ride(driver=self.male, travel_with=TravelWith.MEN)
        self.assertIn("published", gender_lock_reason(self.male))
        ride.status = RideStatus.CANCELLED
        ride.save()
        self.assertIsNone(gender_lock_reason(self.male))

    def test_driver_locked_while_past_restricted_ride_is_in_progress(self):
        ride = self.make_ride(driver=self.male, travel_with=TravelWith.MEN, depart=local(days=-1))
        self.assertIsNone(gender_lock_reason(self.male))
        other_m = User.objects.create_user("+919000000009", gender="M")
        self.book(ride, other_m, status=BookingStatus.IN_PROGRESS)
        self.assertIsNotNone(gender_lock_reason(self.male))


class PublisherSeesPassengersTests(RideTestBase):
    def test_driver_sees_who_booked_and_others_do_not(self):
        ride = self.make_ride(driver=self.female)
        self.book(ride, self.male, seats=2)
        self.book(ride, self.other_f, status=BookingStatus.IN_PROGRESS)
        self.book(ride, self.unset, status=BookingStatus.CANCELLED)  # cancelled: not listed

        self.auth(self.female)
        mine = self.client.get(reverse("ride-mine")).json()[0]
        got = [(p["name"], p["seats"], p["status"]) for p in mine["passengers"]]
        self.assertEqual(got, [("Ravi Kumar", 2, "confirmed"), ("Divya", 1, "in_progress")])
        self.assertEqual(mine["seatsLeft"], 0)
        self.assertEqual([p["phone"] for p in mine["passengers"]], [self.male.phone, self.other_f.phone])
        detail = self.client.get(reverse("ride-detail", args=[ride.id])).json()
        self.assertEqual(len(detail["passengers"]), 2)

        self.auth(self.male)  # a passenger doesn't see the passenger list
        self.assertIsNone(self.client.get(reverse("ride-detail", args=[ride.id])).json()["passengers"])
        self.auth(None)
        self.assertIsNone(self.client.get(reverse("ride-detail", args=[ride.id])).json()["passengers"])

    def test_completed_trip_reflects_for_driver(self):
        ride = self.make_ride(driver=self.female)
        b = self.book(ride, self.male)
        Booking.objects.filter(pk=b.pk).update(status=BookingStatus.COMPLETED)
        self.auth(self.female)
        self.assertEqual(self.client.get(reverse("ride-mine")).json()[0]["passengers"][0]["status"], "completed")


class PassengerContactPrivacyTests(RideTestBase):
    """Who can see a passenger's name and phone."""

    def setUp(self):
        super().setUp()
        self.ride = self.make_ride(driver=self.female)

    def mine(self):
        self.auth(self.female)
        return self.client.get(reverse("ride-mine")).json()[0]["passengers"]

    def test_unpaid_booking_shows_seats_only(self):
        self.book(self.ride, self.male, seats=2, status=BookingStatus.PENDING_PAYMENT)
        [p] = self.mine()
        self.assertEqual((p["name"], p["phone"], p["identityHidden"], p["seats"]), (None, None, True, 2))
        self.assertNotIn(self.male.phone, str(p))
        self.assertNotIn(self.male.name, str(p))

    def test_expired_and_cancelled_not_listed(self):
        self.book(self.ride, self.male, status=BookingStatus.EXPIRED)
        self.book(self.ride, self.other_f, status=BookingStatus.CANCELLED)
        self.assertEqual(self.mine(), [])

    def test_confirmed_shows_name_and_phone_to_owner_only(self):
        self.book(self.ride, self.male)
        [p] = self.mine()
        self.assertEqual((p["name"], p["phone"], p["identityHidden"]), ("Ravi Kumar", self.male.phone, False))
        for viewer in (self.male, self.other_f, None):  # passenger, stranger, anonymous
            self.auth(viewer)
            body = self.client.get(reverse("ride-detail", args=[self.ride.id])).content.decode()
            self.assertNotIn(self.male.phone, body)

    def test_never_in_search(self):
        self.book(self.ride, self.male)
        self.auth(self.female)
        body = self.search().content.decode()
        self.assertNotIn(self.male.phone, body)
        self.auth(None)
        self.assertNotIn(self.male.phone, self.search().content.decode())

    def test_phone_hidden_after_arrival_window(self):
        from datetime import timedelta

        from django.test import override_settings
        from apps.bookings.privacy import contact_visible
        b = self.book(self.ride, self.male, status=BookingStatus.COMPLETED)
        arrive = self.ride.arrive
        self.assertTrue(contact_visible(b, self.ride, now=arrive + timedelta(hours=6)))
        self.assertFalse(contact_visible(b, self.ride, now=arrive + timedelta(hours=6, seconds=1)))
        with override_settings(PASSENGER_CONTACT_HOURS=0):
            self.assertFalse(contact_visible(b, self.ride, now=arrive + timedelta(seconds=1)))
        b.status = BookingStatus.CANCELLED
        self.assertFalse(contact_visible(b, self.ride, now=arrive - timedelta(days=1)))
