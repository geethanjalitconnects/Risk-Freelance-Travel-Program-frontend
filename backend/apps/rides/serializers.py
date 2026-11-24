from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.geo.fields import CityField
from apps.fares.services import fare_range
from apps.geo.routing import duration_minutes
from apps.risk import services as risk_services
from apps.risk.scoring import VEHICLE_FEATURES
from apps.risk.serializers import RiskSerializer
from apps.verification.services import get_verification, is_approved
from common.serializers import FromFieldMixin

from . import policies
from .models import Bags, Ride, TravelWith

MIN_VEHICLE_YEAR = 1995


# ---------------------------------------------------------------- read


def driver_payload(driver, stats) -> dict:
    """A driver as the frontend shows one (same keys as DRIVERS in rides.js). Never the phone,
    documents or ID details. ``verified`` is the admin-approved badge."""
    return {
        "id": driver.pk,
        "verified": is_approved(driver),
        "name": driver.name or "VConnects member",
        "gender": driver.gender,
        "rating": stats.rating,
        "trips": stats.trips,
        "verified_id": driver.verified_id,
        "verified_license": driver.verified_license,
        "since": driver.member_since,
        "langs": driver.languages or ["English"],
        "bio": driver.bio,
    }


class DriverOutSerializer(serializers.Serializer):
    """Same keys as the driver objects in the frontend (DRIVERS in rides.js)."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    gender = serializers.CharField()
    rating = serializers.FloatField(allow_null=True)
    trips = serializers.IntegerField()
    verified_id = serializers.BooleanField()
    verified_license = serializers.BooleanField()
    since = serializers.IntegerField()
    verified = serializers.BooleanField(help_text="Admin-approved driver verification (the Verified badge).")
    langs = serializers.ListField(child=serializers.CharField())
    bio = serializers.CharField()


class VehicleOutSerializer(serializers.Serializer):
    model = serializers.CharField()
    year = serializers.IntegerField()
    features = serializers.ListField(child=serializers.CharField())
    number = serializers.CharField(
        required=False, help_text="Registration number: only for the driver and passengers with a booking."
    )


def vehicle_payload(ride, show_number: bool) -> dict:
    out = {"model": ride.vehicle_model, "year": ride.vehicle_year, "features": ride.vehicle_features}
    if show_number:
        v = get_verification(ride.driver)
        if v and v.vehicle_number:
            out["number"] = v.vehicle_number
    return out


class PassengerOutSerializer(serializers.Serializer):
    booking_id = serializers.UUIDField()
    name = serializers.CharField(allow_null=True, help_text="Only once the booking is paid and confirmed")
    phone = serializers.CharField(allow_null=True, help_text="Only to the ride's driver, confirmed bookings, until arrival + PASSENGER_CONTACT_HOURS")
    identity_hidden = serializers.BooleanField(help_text="True while the booking is not confirmed (awaiting payment)")
    seats = serializers.IntegerField()
    status = serializers.CharField(help_text="confirmed / in_progress / completed")
    booked_at = serializers.IntegerField(help_text="epoch ms")
    passenger_confirmed = serializers.BooleanField()
    you_confirmed = serializers.BooleanField()
    open_problem = serializers.CharField(allow_null=True, help_text="Kind of the open problem report, if any")


class RideCompletionOutSerializer(serializers.Serializer):
    can_complete = serializers.BooleanField(help_text="The ride has left and passengers still need your confirmation")
    no_show_from = serializers.CharField(help_text="Local time from which no-shows can be reported")
    no_show_open = serializers.BooleanField()
    awaiting = serializers.IntegerField(help_text="Passengers you haven't confirmed yet")


class RideSerializer(FromFieldMixin, serializers.Serializer):
    """A ride in the exact shape the React pages read (RideCard, RideDetail, Trips), plus
    viewer-specific fields: isOwn, myBookingId, canBook / cannotBookReason, hasBookings.

    Rides must be passed through ``services.prepare`` first.
    """

    id = serializers.UUIDField()
    source = serializers.SerializerMethodField()
    origin = CityField(source="origin")
    to = CityField(source="destination")
    date = serializers.SerializerMethodField()
    depart = serializers.DateTimeField()
    duration_min = serializers.IntegerField()
    arrive = serializers.DateTimeField()
    km = serializers.IntegerField()
    price = serializers.IntegerField()
    seats_total = serializers.IntegerField()
    seats_left = serializers.SerializerMethodField()
    driver = serializers.SerializerMethodField()
    vehicle = serializers.SerializerMethodField()
    pickup = serializers.CharField()
    dropoff = serializers.CharField()
    travel_with = serializers.CharField()
    women_only = serializers.SerializerMethodField()
    ac = serializers.BooleanField()
    bags = serializers.CharField()
    notes = serializers.CharField()
    status = serializers.CharField()
    risk = serializers.SerializerMethodField()
    is_own = serializers.SerializerMethodField()
    my_booking_id = serializers.SerializerMethodField()
    can_book = serializers.SerializerMethodField()
    cannot_book_code = serializers.SerializerMethodField()
    cannot_book_reason = serializers.SerializerMethodField()
    has_bookings = serializers.SerializerMethodField()
    listed = serializers.SerializerMethodField()
    passengers = serializers.SerializerMethodField()
    completion = serializers.SerializerMethodField()

    def _viewer(self):
        request = self.context.get("request")
        return request.user if request else None

    @extend_schema_field(OpenApiTypes.STR)
    def get_source(self, ride):
        return "published"

    @extend_schema_field(OpenApiTypes.DATE)
    def get_date(self, ride):
        return timezone.localtime(ride.depart).date().isoformat()

    @extend_schema_field(OpenApiTypes.INT)
    def get_seats_left(self, ride):
        return ride._seats_left

    @extend_schema_field(DriverOutSerializer)
    def get_driver(self, ride):
        return driver_payload(ride.driver, ride._stats)

    @extend_schema_field(VehicleOutSerializer)
    def get_vehicle(self, ride):
        return vehicle_payload(ride, show_number=self.get_is_own(ride) or bool(ride._my_booking_id))

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_women_only(self, ride):
        # Kept so existing frontend checks (ride.womenOnly) keep working.
        return ride.travel_with == TravelWith.WOMEN

    @extend_schema_field(RiskSerializer)
    def get_risk(self, ride):
        return ride._risk

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_own(self, ride):
        viewer = self._viewer()
        return bool(viewer and viewer.is_authenticated and viewer.pk == ride.driver_id)

    @extend_schema_field(OpenApiTypes.UUID)
    def get_my_booking_id(self, ride):
        return ride._my_booking_id

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_can_book(self, ride):
        return ride._block is None

    @extend_schema_field(OpenApiTypes.STR)
    def get_cannot_book_code(self, ride):
        return ride._block.code if ride._block else None

    @extend_schema_field(OpenApiTypes.STR)
    def get_cannot_book_reason(self, ride):
        return ride._block.message if ride._block else None

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_has_bookings(self, ride):
        """Only shown to the driver: when true, Remove and the traveller preference are locked."""
        return ride.booked_seats > 0 if self.get_is_own(ride) else None

    @extend_schema_field(PassengerOutSerializer(many=True, allow_null=True))
    def get_passengers(self, ride):
        """Only shown to the driver: who booked, how many seats, and where their trip is.
        Name and phone only for paid, confirmed bookings (see ``contact_visible``); never in search."""
        if ride._passengers is None:
            return None
        from apps.bookings.privacy import contact_visible, identity_visible

        show = bool(self.context.get("contacts"))
        out = []
        for b in ride._passengers:
            known = show and identity_visible(b)
            out.append({
                "booking_id": b.pk,
                "name": (b.passenger.name or "VConnects member") if known else None,
                "phone": b.passenger.phone if known and contact_visible(b, ride) else None,
                "identity_hidden": not known,
                "seats": b.seats,
                "status": b.status,
                "booked_at": int(b.created_at.timestamp() * 1000),
                "passenger_confirmed": any(c.party == "passenger" for c in b.confirmations.all()),
                "you_confirmed": any(c.party == "publisher" for c in b.confirmations.all()),
                "open_problem": next((p.kind for p in b.problems.all() if p.status == "open"), None),
            })
        return out

    @extend_schema_field(RideCompletionOutSerializer(allow_null=True))
    def get_completion(self, ride):
        """Only for the driver: whether they can swipe "ride complete" now."""
        if ride._passengers is None:
            return None
        from django.utils import timezone

        from apps.bookings import completion

        now = timezone.now()
        awaiting = [
            b for b in ride._passengers
            if b.status in ("confirmed", "in_progress") and not any(c.party == "publisher" for c in b.confirmations.all())
            and not any(p.status == "open" and p.kind == "passenger_no_show" for p in b.problems.all())
        ]
        start = completion.no_show_from(ride)
        return {
            "can_complete": bool(awaiting) and completion.ride_started(ride, now),
            "no_show_from": timezone.localtime(start).strftime("%Y-%m-%dT%H:%M"),
            "no_show_open": now >= start,
            "awaiting": len(awaiting),
        }

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_listed(self, ride):
        """Only shown to the driver: false while their verification isn't approved (hidden from search)."""
        return ride.is_listed if self.get_is_own(ride) else None


# ---------------------------------------------------------------- write


class VehicleInSerializer(serializers.Serializer):
    model = serializers.CharField(max_length=80, error_messages={"blank": "Tell passengers what you drive."})
    year = serializers.IntegerField(error_messages={"invalid": "Enter a valid year."})
    features = serializers.ListField(
        child=serializers.ChoiceField(choices=list(VEHICLE_FEATURES)), required=False, default=list
    )


class RideWriteSerializer(FromFieldMixin, serializers.Serializer):
    """Publish (POST) and edit (PATCH) a ride. Field names follow the ride object."""

    origin = CityField(source="origin")
    to = CityField(source="destination")
    depart = serializers.DateTimeField(help_text='Local time, "YYYY-MM-DDTHH:mm".')
    # Per seat. The allowed range depends on the route (see apps.fares); checked in validate().
    price = serializers.IntegerField(min_value=1, max_value=1_000_000)
    seats_total = serializers.IntegerField(min_value=1, max_value=4)
    pickup = serializers.CharField(required=False, allow_blank=True, max_length=120)
    dropoff = serializers.CharField(required=False, allow_blank=True, max_length=120)
    travel_with = serializers.ChoiceField(choices=TravelWith.choices, default=TravelWith.ANYONE)
    vehicle = VehicleInSerializer()
    notes = serializers.CharField(required=False, allow_blank=True, max_length=140, default="")
    ac = serializers.BooleanField(default=True)
    bags = serializers.ChoiceField(choices=Bags.choices, default=Bags.CABIN)

    # -- validation --

    def validate_travel_with(self, value):
        # Field-level, so it is reported together with any other field errors.
        driver = self.instance.driver if self.instance else self.context["request"].user
        msg = policies.driver_travel_with_error(value, driver.gender)
        if msg:
            raise serializers.ValidationError(msg)
        return value

    def validate(self, attrs):
        ride = self.instance
        if ride and ride.has_departed:
            raise serializers.ValidationError("This ride has already left and can no longer be edited.")

        errors = {}
        origin = attrs.get("origin", ride.origin if ride else None)
        destination = attrs.get("destination", ride.destination if ride else None)
        if origin.code == destination.code:
            errors["to"] = "Destination must differ from the start."

        if "depart" in attrs and attrs["depart"] <= timezone.now():
            errors["depart"] = "That time has already passed."

        if "vehicle" in attrs:
            vehicle = self._merged_vehicle(attrs["vehicle"], ride)
            year_max = timezone.localdate().year + 1
            if not MIN_VEHICLE_YEAR <= vehicle["year"] <= year_max:
                errors["vehicle"] = {"year": "Enter a valid year."}
            elif not vehicle["model"].strip():
                errors["vehicle"] = {"model": "Tell passengers what you drive."}
            attrs["vehicle"] = vehicle

        for key, city, old_city in (
            ("pickup", origin, ride.origin if ride else None),
            ("dropoff", destination, ride.destination if ride else None),
        ):
            msg = self._resolve_point(attrs, key, city, city_changed=old_city is not None and old_city != city)
            if msg:
                errors[key] = msg

        if ride:
            errors.update(self._booked_ride_errors(ride, attrs))

        if "to" not in errors and "price" not in errors:
            msg = self._fare_error(ride, attrs, origin, destination)
            if msg:
                errors["price"] = msg

        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    @staticmethod
    def _fare_error(ride, attrs, origin, destination):
        """The fare must sit between the route's minimum and maximum. Checked when publishing, and
        when an edit changes the fare or the route (current fare settings apply). A booked ride's
        fare is locked separately."""
        route_changed = ride is not None and (origin != ride.origin or destination != ride.destination)
        if ride is not None and "price" not in attrs and not route_changed:
            return None
        price = attrs.get("price", ride.price if ride else None)
        km = risk_services.route_between(origin, destination).km
        return fare_range(km).error_for(price)

    @staticmethod
    def _merged_vehicle(data, ride):
        base = (
            {"model": ride.vehicle_model, "year": ride.vehicle_year, "features": ride.vehicle_features}
            if ride
            else {"model": "", "year": 0, "features": []}
        )
        merged = {**base, **data}
        merged["model"] = merged["model"].strip()
        merged["features"] = list(dict.fromkeys(merged["features"]))  # de-duplicate, keep order
        return merged

    def _resolve_point(self, attrs, key, city, city_changed):
        """Pickup / drop-off must be one of the city's meeting points; blank means the first one."""
        points = list(city.meeting_points.order_by("order", "name").values_list("name", flat=True))
        value = attrs.get(key, "")
        if value:
            if value not in points:
                return f"Choose a meeting point in {city.name}."
            return None
        if self.instance is None or city_changed or key in attrs:
            if not points:
                return f"{city.name} has no meeting points yet."
            attrs[key] = points[0]
        return None

    @staticmethod
    def _booked_ride_errors(ride, attrs):
        if not ride.has_bookings():
            return {}
        current = {
            "origin": ride.origin,
            "destination": ride.destination,
            "depart": ride.depart,
            "price": ride.price,
            "travel_with": ride.travel_with,
        }
        error_key = {"origin": "from", "destination": "to"}
        errors = {}
        for field, old in current.items():
            if field in attrs and attrs[field] != old:
                key = error_key.get(field, field)
                errors[key] = policies.LOCKED_WHEN_BOOKED[key]
        if "vehicle" in attrs:
            v = attrs["vehicle"]
            if (v["model"], v["year"], sorted(v["features"])) != (
                ride.vehicle_model,
                ride.vehicle_year,
                sorted(ride.vehicle_features),
            ):
                errors["vehicle"] = policies.LOCKED_WHEN_BOOKED["vehicle"]
        if "seats_total" in attrs:
            booked = ride.count_booked_seats()
            if attrs["seats_total"] < booked:
                errors["seats_total"] = f"{booked} seat{'s are' if booked != 1 else ' is'} already booked."
        return errors

    # -- persistence --

    @staticmethod
    def _apply(ride, data):
        vehicle = data.pop("vehicle", None)
        for field, value in data.items():
            setattr(ride, field, value)
        if vehicle is not None:
            ride.vehicle_model = vehicle["model"]
            ride.vehicle_year = vehicle["year"]
            ride.vehicle_features = vehicle["features"]
        km = risk_services.route_between(ride.origin, ride.destination).km
        ride.km = km
        ride.duration_min = duration_minutes(km)

    def create(self, validated_data):
        ride = Ride(driver=self.context["request"].user)
        self._apply(ride, validated_data)
        ride.save()
        return ride

    def update(self, ride, validated_data):
        self._apply(ride, validated_data)
        ride.save()
        return ride


# ---------------------------------------------------------------- search


class RideSearchSerializer(FromFieldMixin, serializers.Serializer):
    SORTS = ("earliest", "cheapest", "safest")

    origin = CityField()
    to = CityField()
    date = serializers.DateField()
    seats = serializers.IntegerField(min_value=1, max_value=4, default=1)
    sort = serializers.ChoiceField(choices=SORTS, default="earliest")
    verified = serializers.BooleanField(default=False)
    women_only = serializers.BooleanField(default=False)
    travel_with = serializers.ChoiceField(choices=TravelWith.choices, required=False)
    daytime = serializers.BooleanField(default=False)
    max_risk = serializers.IntegerField(min_value=1, max_value=101, required=False)

    def validate(self, attrs):
        if attrs["from"].code == attrs["to"].code:
            raise serializers.ValidationError({"to": "Leaving from and going to must be different cities."})
        if attrs["date"] < timezone.localdate():
            raise serializers.ValidationError({"date": "Choose today or a later date."})
        return attrs
