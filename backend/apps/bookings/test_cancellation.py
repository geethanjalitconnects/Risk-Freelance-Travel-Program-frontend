"""Phase 4: passenger and publisher cancellations, VConnects cancellations, refunds and penalties.

Seat price ₹600 (BookingTestBase): ride amount 60000, platform fee 6000, total 66000 paise,
publisher earning 54000, publisher commission 6000.
"""
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import deactivate
from apps.bookings import services
from apps.bookings.models import Booking, Cancellation
from apps.bookings.tests import BookingTestBase
from apps.payments import ledger
from apps.payments.models import EarningsAccount, FinancialAuditLog, Payment, Refund

TOTAL, EARNING = 66000, 54000


class CancelBase(BookingTestBase):
    def ride_in(self, hours, **over):
        return self.make_ride(depart=timezone.now() + timedelta(hours=hours), **over)

    def booking(self, ride, user=None, paid=True):
        bid = self.book(ride, user or self.woman).json()["id"]
        b = Booking.objects.get(pk=bid)
        if paid:  # what Phase 3 does on a verified payment
            Payment.objects.create(booking=b, amount_paise=b.total_paise, status="captured", idempotency_key=f"pay:{b.pk}")
            ledger.hold_earning(b)
        return b

    def balances(self):
        a = EarningsAccount.objects.filter(user=self.driver).first()
        return (a.held_paise, a.available_paise, a.owed_paise) if a else (0, 0, 0)

    def passenger_cancel(self, b, user=None):
        self.as_user(user or b.passenger)
        return self.action(b.pk, "cancel")

    def quote(self, b):
        self.as_user(b.passenger)
        return self.client.get(reverse("booking-cancel-quote", args=[b.pk]))


class PassengerCancelTests(CancelBase):
    def test_more_than_24h_refunds_85_percent(self):
        b = self.booking(self.ride_in(48))
        q = self.quote(b).json()
        self.assertEqual((q["rule"], q["paid"], q["totalPaid"], q["refund"], q["fee"]), ("passenger_early", True, TOTAL, 56100, 9900))
        self.assertIn("₹561 (85%)", q["message"])

        r = self.passenger_cancel(b).json()
        self.assertEqual(r["status"], "cancelled")
        self.assertEqual(
            {k: r["cancellation"][k] for k in ("by", "rule", "totalPaid", "refund", "fee", "refundStatus")},
            {"by": "passenger", "rule": "passenger_early", "totalPaid": TOTAL, "refund": 56100, "fee": 9900, "refundStatus": "pending"},
        )
        self.assertIn("₹561 will be refunded", r["events"][-1]["text"])
        refund = Refund.objects.get(booking=b)
        self.assertEqual((refund.amount_paise, refund.rule, refund.status), (56100, "passenger_early", "pending"))
        self.assertEqual(self.balances(), (0, 0, 0))  # the held earning is removed
        log = FinancialAuditLog.objects.get(action="booking_settled", booking=b)
        self.assertEqual((log.details["refund"], log.details["vconnects_kept"], log.details["paid"]), (56100, 9900, True))
        self.assertTrue(FinancialAuditLog.objects.filter(action="refund_created", booking=b, amount_paise=56100).exists())

    def test_within_24h_refunds_90_percent(self):
        b = self.booking(self.ride_in(3))
        r = self.passenger_cancel(b).json()
        self.assertEqual((r["cancellation"]["refund"], r["cancellation"]["fee"]), (59400, 6600))
        self.assertEqual(Refund.objects.get(booking=b).amount_paise, 59400)

    def test_rates_frozen_at_booking_time_apply(self):
        b = self.booking(self.ride_in(48))
        from apps.payments.models import PaymentSettings

        s = PaymentSettings.load()
        s.passenger_cancel_early_bps = 5000
        s.save()
        self.assertEqual(self.passenger_cancel(b).json()["cancellation"]["refund"], 56100)

    def test_unpaid_booking_nothing_refunded(self):
        b = self.booking(self.ride_in(48), paid=False)
        self.assertIn("hasn't been paid", self.quote(b).json()["message"])
        r = self.passenger_cancel(b).json()
        self.assertEqual(r["events"][-1]["text"], "Booking cancelled.")
        self.assertIsNone(r["cancellation"]["refundStatus"])
        self.assertFalse(Refund.objects.exists())
        self.assertEqual(Cancellation.objects.get(booking=b).rule, "passenger_early")

    def test_twice_and_started(self):
        b = self.booking(self.ride_in(48))
        self.passenger_cancel(b)
        self.assertEqual(self.passenger_cancel(b).json()["code"], "invalid_state")
        self.assertEqual(self.quote(b).json()["code"], "invalid_state")
        self.assertEqual(Refund.objects.count(), 1)

    def test_amounts_must_always_add_up(self):
        b = self.booking(self.ride_in(48))
        with self.assertRaises(IntegrityError), transaction.atomic():
            Cancellation.objects.create(booking=b, cancelled_by="passenger", minutes_before_departure=1, rule="passenger_late",
                                        total_paid_paise=TOTAL, refund_paise=59400, vconnects_kept_paise=6000)


class PublisherCancelTests(CancelBase):
    def setUp(self):
        super().setUp()
        self.other = User.objects.create_user("+919000000077", name="Kiran", gender="F")

    def cancel_ride(self, ride, reason="My car broke down, sorry."):
        self.as_user(self.driver)
        return self.client.post(reverse("ride-cancel", args=[ride.pk]), {"reason": reason}, format="json")

    def ride_quote(self, ride):
        self.as_user(self.driver)
        return self.client.get(reverse("ride-cancel-quote", args=[ride.pk])).json()

    def test_more_than_24h_full_refunds_no_penalty(self):
        ride = self.ride_in(48)
        b1, b2 = self.booking(ride), self.booking(ride, self.other)
        q = self.ride_quote(ride)
        self.assertEqual((q["passengers"], q["refundTotal"], q["penalty"], q["withinWindow"]), (2, 2 * TOTAL, 0, False))
        self.assertIn("no penalty", q["message"])

        self.assertEqual(self.cancel_ride(ride).status_code, 204)
        ride.refresh_from_db()
        self.assertEqual((ride.status, ride.cancellation_reason), ("cancelled", "My car broke down, sorry."))
        for b in (b1, b2):
            b.refresh_from_db()
            self.assertEqual(b.status, "cancelled")
            self.assertEqual(Refund.objects.get(booking=b).amount_paise, TOTAL)
            self.assertEqual(b.cancellation.rule, "publisher_early")
            self.assertIn("The driver cancelled this ride", b.events.last().text)
        self.assertEqual(self.balances(), (0, 0, 0))

    def test_within_24h_penalty_is_10_percent_of_ride_amount(self):
        # The driver has ₹540 available from an earlier ride: the ₹60 penalty comes out of it.
        earlier = self.booking(self.ride_in(48))
        ledger.release_earning(earlier)  # 54000 available
        ride = self.ride_in(5)
        b = self.booking(ride, self.other)
        q = self.ride_quote(ride)
        self.assertEqual((q["penalty"], q["withinWindow"]), (6000, True))
        self.cancel_ride(ride)
        self.assertEqual(self.balances(), (0, EARNING - 6000, 0))
        self.assertEqual(Cancellation.objects.get(booking=b).publisher_penalty_paise, 6000)
        self.assertEqual(Refund.objects.get(booking=b).amount_paise, TOTAL)

    def test_penalty_without_earnings_is_owed(self):
        ride = self.ride_in(5)
        self.booking(ride)
        self.cancel_ride(ride)
        self.assertEqual(self.balances(), (0, 0, 6000))

    def test_unpaid_bookings_no_penalty(self):
        ride = self.ride_in(5)
        self.booking(ride, paid=False)
        self.assertEqual(self.ride_quote(ride)["penalty"], 0)
        self.cancel_ride(ride)
        self.assertEqual(self.balances(), (0, 0, 0))
        self.assertFalse(Refund.objects.exists())

    def test_refused_cases(self):
        ride = self.ride_in(48)
        b = self.booking(ride)
        self.assertEqual(self.cancel_ride(ride, reason="no").status_code, 400)
        self.as_user(self.man)
        self.assertEqual(self.client.post(reverse("ride-cancel", args=[ride.pk]), {"reason": "Not mine at all"}, format="json").status_code, 404)
        self.as_user(b.passenger)
        self.action(b.pk, "start")  # the trip is under way
        self.assertEqual(self.cancel_ride(ride).json()["code"], "departed")
        self.assertEqual(Booking.objects.get(pk=b.pk).status, "in_progress")

    def test_cancel_after_departure_refused(self):
        ride = self.ride_in(48)
        self.booking(ride)
        ride.__class__.objects.filter(pk=ride.pk).update(depart=timezone.now() - timedelta(minutes=5))
        self.assertEqual(self.cancel_ride(ride).json()["code"], "departed")


class VConnectsCancelTests(CancelBase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser("+919000000099", password="Root-pass-424242", name="Admin")

    def test_admin_cancel_ride_full_refund_no_penalty(self):
        ride = self.ride_in(3)
        b = self.booking(ride)
        self.assertEqual(services.admin_cancel_ride(ride, self.admin, "Safety check failed."), 1)
        b.refresh_from_db()
        self.assertEqual((b.status, b.cancellation.rule, b.cancellation.cancelled_by), ("cancelled", "admin_full_refund", "admin"))
        self.assertEqual(Refund.objects.get(booking=b).amount_paise, TOTAL)
        self.assertEqual(self.balances(), (0, 0, 0))
        self.assertIn("Ride cancelled by VConnects", b.events.last().text)

    def test_deactivated_passenger_full_refund(self):
        b = self.booking(self.ride_in(48))
        self.assertEqual(deactivate(self.woman, self.admin), 1)
        self.assertEqual(Refund.objects.get(booking=b).amount_paise, TOTAL)
