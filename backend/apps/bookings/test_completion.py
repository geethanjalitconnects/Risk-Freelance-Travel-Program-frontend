"""Phase 5: two-sided completion, no-shows, problem reports, admin decisions and auto-complete."""
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.bookings.models import Booking, Cancellation, ProblemReport
from apps.bookings.tests import BookingTestBase
from apps.payments import ledger
from apps.payments.models import EarningsAccount, FinancialAuditLog, Payment, Refund
from apps.rides.models import Ride

EARNING = 54000  # ₹600 seat - 10% commission, in paise


class CompletionBase(BookingTestBase):
    def setUp(self):
        super().setUp()
        self.ride = self.make_ride()
        self.bid = self.book(self.ride, self.woman).json()["id"]
        self.booking = Booking.objects.get(pk=self.bid)

    def depart(self, minutes_ago=60, duration=300):
        """Move the ride into the past (bookings can only be made before departure)."""
        depart = timezone.now() - timedelta(minutes=minutes_ago)
        Ride.objects.filter(pk=self.ride.pk).update(depart=depart, arrive=depart + timedelta(minutes=duration))
        self.ride.refresh_from_db()

    def paid(self, booking=None):
        """What Phase 3 will do on a verified payment: record it and hold the publisher's earning."""
        b = booking or Booking.objects.get(pk=self.bid)
        Payment.objects.create(booking=b, amount_paise=b.total_paise, status="captured", idempotency_key=f"pay:{b.pk}")
        ledger.hold_earning(b)

    def passenger(self, action, body=None, booking_id=None):
        self.as_user(self.woman)
        return self.action(booking_id or self.bid, action, body)

    def publisher_complete(self, **body):
        self.as_user(self.driver)
        return self.client.post(reverse("ride-complete", args=[self.ride.pk]), body, format="json")

    def balances(self):
        a = EarningsAccount.objects.get(user=self.driver)
        return a.held_paise, a.available_paise, a.owed_paise

    def status(self):
        return Booking.objects.get(pk=self.bid).status


class SwipeTests(CompletionBase):
    def test_passenger_cannot_confirm_before_departure(self):
        self.assertEqual(self.passenger("complete").json()["code"], "not_departed")

    def test_both_swipes_complete_and_release_the_earning(self):
        self.paid()
        self.depart()
        r = self.passenger("complete").json()
        self.assertEqual(r["status"], "confirmed")  # waiting for the driver
        self.assertIsNotNone(r["completion"]["passengerConfirmedAt"])
        self.assertEqual(self.balances(), (EARNING, 0, 0))

        ride = self.publisher_complete().json()
        self.assertEqual(ride["passengers"][0]["status"], "completed")
        self.assertFalse(ride["completion"]["canComplete"])
        self.assertEqual(self.status(), "completed")
        self.assertEqual(self.balances(), (0, EARNING, 0))
        self.assertTrue(FinancialAuditLog.objects.filter(action="booking_settled", booking=self.booking).exists())

    def test_driver_first_then_passenger(self):
        self.depart()
        ride = self.publisher_complete().json()
        self.assertTrue(ride["passengers"][0]["youConfirmed"])
        self.assertEqual(self.status(), "confirmed")
        self.assertEqual(self.passenger("complete").json()["status"], "completed")

    def test_completion_without_payment_releases_nothing(self):
        self.depart()
        self.passenger("complete")
        self.publisher_complete()
        self.assertEqual(self.status(), "completed")
        self.assertFalse(EarningsAccount.objects.filter(user=self.driver, available_paise__gt=0).exists())

    def test_driver_needs_the_ride_to_have_started(self):
        self.assertEqual(self.publisher_complete().json()["code"], "not_departed")
        self.passenger("start")  # a passenger started their trip: the ride is under way
        self.assertEqual(self.publisher_complete().status_code, 200)

    def test_driver_swipe_is_idempotent_and_others_cannot(self):
        self.depart()
        self.publisher_complete()
        r = self.publisher_complete()
        self.assertEqual(r.status_code, 200)  # still awaiting the passenger: nothing changes
        self.assertEqual(self.booking.confirmations.count(), 1)
        self.as_user(self.man)
        self.assertEqual(self.client.post(reverse("ride-complete", args=[self.ride.pk]), {}, format="json").status_code, 404)

    def test_driver_view_shows_completion_state(self):
        self.as_user(self.driver)
        ride = self.client.get(reverse("ride-detail", args=[self.ride.pk])).json()
        self.assertEqual(ride["completion"]["awaiting"], 1)
        self.assertFalse(ride["completion"]["canComplete"])
        p = ride["passengers"][0]
        self.assertEqual((p["passengerConfirmed"], p["youConfirmed"], p["openProblem"]), (False, False, None))
        self.as_user(self.man)
        self.assertIsNone(self.client.get(reverse("ride-detail", args=[self.ride.pk])).json()["completion"])


class NoShowTests(CompletionBase):
    def test_too_early_then_reported_and_frozen(self):
        self.paid()
        self.depart(minutes_ago=10)
        r = self.publisher_complete(noShow=[self.bid])
        self.assertEqual(r.json()["code"], "too_early")
        self.depart(minutes_ago=31)
        ride = self.publisher_complete(noShow=[self.bid], note="Waited 20 minutes at the pickup").json()
        self.assertEqual(ride["passengers"][0]["openProblem"], "passenger_no_show")
        report = ProblemReport.objects.get(booking=self.booking)
        self.assertIn("Waited 20 minutes", report.details)

        # The passenger disputes by swiping complete: recorded, but nothing completes or is paid.
        r = self.passenger("complete").json()
        self.assertEqual(r["status"], "confirmed")
        self.assertEqual(r["completion"]["openProblem"]["kind"], "passenger_no_show")
        self.assertEqual(self.balances(), (EARNING, 0, 0))

    def test_unknown_passenger(self):
        self.depart(minutes_ago=40)
        r = self.publisher_complete(noShow=["00000000-0000-0000-0000-000000000000"])
        self.assertEqual((r.status_code, r.json()["code"]), (400, "unknown_booking"))


class ProblemReportTests(CompletionBase):
    def test_passenger_reports_driver_no_show_and_it_freezes_the_ride(self):
        r = self.passenger("problems", {"kind": "publisher_no_show", "details": "Driver never came to the pickup."})
        self.assertEqual(r.json()["code"], "invalid_kind")  # before departure
        self.depart()
        self.assertEqual(self.passenger("problems", {"kind": "other", "details": "short"}).status_code, 400)
        r = self.passenger("problems", {"kind": "publisher_no_show", "details": "Driver never came to the pickup."}).json()
        self.assertEqual(r["completion"]["openProblem"]["kind"], "publisher_no_show")
        self.assertFalse(r["completion"]["canConfirm"])
        self.assertEqual([k["value"] for k in r["completion"]["reportKinds"]], ["other"])
        self.assertEqual(r["events"][-1]["type"], "problem")
        self.assertEqual(self.passenger("complete").json()["code"], "problem_open")
        self.publisher_complete()
        self.assertEqual(self.status(), "confirmed")  # frozen


class AdminDecisionTests(CompletionBase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser("+919000000099", password="Root-pass-424242", name="Admin")

    def report(self, kind="passenger_no_show"):
        self.paid()
        if kind == "passenger_no_show":
            self.depart(minutes_ago=40)
            self.publisher_complete(noShow=[self.bid])
        else:
            self.depart()
            self.passenger("problems", {"kind": kind, "details": "Driver never came to the pickup."})
        return ProblemReport.objects.get(booking=self.booking)

    def decide(self, report, decision, note="Checked the trip log and call records."):
        self.client.force_login(self.admin)
        url = reverse("admin:bookings_problemreport_change", args=[report.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        return self.client.post(url, {"decision": decision, "note": note})

    def test_note_is_required(self):
        report = self.report()
        self.assertEqual(self.decide(report, "uphold", note="  ").status_code, 200)  # form error
        report.refresh_from_db()
        self.assertEqual(report.status, "open")

    def test_passenger_no_show_upheld_pays_the_driver(self):
        self.assertEqual(self.decide(self.report(), "uphold").status_code, 302)
        self.assertEqual(self.status(), "cancelled")
        c = Cancellation.objects.get(booking=self.booking)
        self.assertEqual((c.rule, c.refund_paise, c.publisher_earning_paise), ("passenger_no_show", 0, EARNING))
        self.assertEqual(self.balances(), (0, EARNING, 0))
        self.assertFalse(Refund.objects.exists())

    def test_passenger_no_show_dismissed_completes_when_passenger_confirmed(self):
        report = self.report()
        self.passenger("complete")
        self.decide(report, "dismiss")
        self.assertEqual(self.status(), "completed")
        self.assertEqual(self.balances(), (0, EARNING, 0))

    def test_driver_no_show_upheld_refunds_in_full_and_charges_the_penalty(self):
        self.decide(self.report("publisher_no_show"), "uphold")
        self.assertEqual(self.status(), "cancelled")
        refund = Refund.objects.get(booking=self.booking)
        self.assertEqual((refund.amount_paise, refund.rule, refund.status), (66000, "publisher_no_show", "pending"))
        self.assertEqual(self.balances(), (0, 0, 6000))  # earning reversed; ₹60 penalty owed

    def test_other_upheld_full_refund_no_penalty(self):
        self.decide(self.report("other"), "uphold")
        self.assertEqual(Refund.objects.get(booking=self.booking).amount_paise, 66000)
        self.assertEqual(self.balances(), (0, 0, 0))

    def test_decided_reports_are_read_only(self):
        report = self.report()
        self.decide(report, "dismiss")
        self.assertEqual(
            self.client.post(reverse("admin:bookings_problemreport_change", args=[report.pk]), {"decision": "uphold", "note": "x"}).status_code,
            403,
        )


class AutoCompleteTests(CompletionBase):
    def run_command(self):
        out = StringIO()
        call_command("auto_complete_bookings", stdout=out)
        return out.getvalue()

    def test_completes_24h_after_arrival(self):
        self.paid()
        self.depart(minutes_ago=60 * 24 + 60, duration=30)  # arrived 24.5 h ago
        self.assertIn("Auto-completed 1", self.run_command())
        b = Booking.objects.get(pk=self.bid)
        self.assertEqual(b.status, "completed")
        self.assertEqual(set(b.confirmations.values_list("source", flat=True)), {"auto"})
        self.assertEqual(self.balances(), (0, EARNING, 0))
        self.assertIn("Auto-completed 0", self.run_command())

    def test_not_yet_and_not_when_a_problem_is_open(self):
        self.depart(minutes_ago=60 * 20, duration=30)  # arrived 19.5 h ago
        self.assertIn("Auto-completed 0", self.run_command())
        self.depart(minutes_ago=60 * 26, duration=30)
        self.passenger("problems", {"kind": "other", "details": "The car broke down on the way."})
        self.assertIn("Auto-completed 0", self.run_command())
        self.assertEqual(self.status(), "confirmed")
