"""Publisher earnings ledger, booking money snapshot, payout details and the admin."""
from datetime import timedelta
from io import StringIO

from cryptography.fernet import Fernet

from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.bookings import services as booking_services
from apps.bookings.models import Booking, BookingStatus, Cancellation
from apps.geo.models import City
from apps.geo.testing import seed_geo
from apps.payments import ledger, money
from apps.payments.models import (
    EarningEntry,
    EarningsAccount,
    EntryKind,
    FinancialAction,
    FinancialAuditLog,
    ImmutableError,
    PaymentSettings,
    PayoutAccount,
    PayoutMethod,
    Withdrawal,
    WithdrawalStatus,
)
from apps.payments.validators import mask_upi, validate_ifsc
from apps.rides.models import Ride
from apps.verification.testing import approve_driver

TEST_KEY = Fernet.generate_key().decode()
# Management form of the (read-only) ledger inline on the earnings account page.
INLINE = {"entries-TOTAL_FORMS": "0", "entries-INITIAL_FORMS": "0", "entries-MIN_NUM_FORMS": "0", "entries-MAX_NUM_FORMS": "0"}


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_geo()
        cls.root = User.objects.create_superuser("+919000000001", password="Root-pass-424242", name="Root")
        cls.driver = approve_driver(User.objects.create_user("+919000000002", name="Meera", gender="F"))
        cls.rider = User.objects.create_user("+919000000003", name="Ravi", gender="M")
        cls.rider2 = User.objects.create_user("+919000000004", name="Asha", gender="F")
        cls.maa, cls.blr = City.objects.get(code="MAA"), City.objects.get(code="BLR")

    def ride(self, **over):
        fields = dict(
            driver=self.driver, origin=self.maa, destination=self.blr, pickup="Chennai Central",
            dropoff="Bengaluru Central", depart=timezone.now() + timedelta(days=2), duration_min=300, km=370,
            price=500, seats_total=3, vehicle_model="Creta", vehicle_year=2023,
        )
        fields.update(over)
        return Ride.objects.create(**fields)

    def booking(self, ride=None, passenger=None, seats=1):
        return booking_services.create_booking(passenger or self.rider, (ride or self.ride()).pk, seats)

    def account(self, user=None):
        return ledger.account_for(user or self.driver)

    def balances(self, user=None):
        a = self.account(user)
        return a.held_paise, a.available_paise, a.owed_paise


class BookingSnapshotTests(Base):
    def test_booking_freezes_amounts_and_rates(self):
        b = self.booking(seats=2)
        self.assertEqual(
            (b.ride_amount_paise, b.platform_fee_paise, b.total_paise, b.publisher_commission_paise, b.publisher_earning_paise),
            (100000, 10000, 110000, 10000, 90000),
        )
        self.assertEqual(b.total, 1000)  # the old rupee field is unchanged
        self.assertEqual(b.policy(), money.FeePolicy())

        # A later settings change doesn't touch the existing booking.
        s = PaymentSettings.load()
        s.platform_fee_bps = 500
        s.save()
        b.refresh_from_db()
        self.assertEqual(b.amounts().platform_fee, 10000)
        self.assertEqual(b.policy().platform_fee_bps, 1000)
        self.assertEqual(self.booking(passenger=self.rider2).platform_fee_paise, 2500)

    def test_expired_bookings_free_their_seats(self):
        ride = self.ride(seats_total=1)
        b = self.booking(ride)
        with self.assertRaises(booking_services.TripError):
            self.booking(ride, passenger=self.rider2)
        Booking.objects.filter(pk=b.pk).update(status=BookingStatus.EXPIRED)
        self.assertEqual(ride.count_booked_seats(), 0)
        self.booking(ride, passenger=self.rider2)  # the seat is free again
        # The passenger whose booking expired can book the same ride again (once a seat is free).
        Booking.objects.filter(ride=ride, passenger=self.rider2).update(status=BookingStatus.EXPIRED)
        self.booking(ride)

    def test_pending_payment_holds_seats(self):
        ride = self.ride(seats_total=1)
        b = self.booking(ride)
        Booking.objects.filter(pk=b.pk).update(status=BookingStatus.PENDING_PAYMENT)
        self.assertEqual(ride.count_booked_seats(), 1)

    def test_cancellation_record_must_add_up(self):
        b = self.booking()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Cancellation.objects.create(
                booking=b, cancelled_by="passenger", minutes_before_departure=60, rule=money.Rule.PASSENGER_LATE,
                total_paid_paise=55000, refund_paise=49500, vconnects_kept_paise=5000,
            )
        Cancellation.objects.create(
            booking=b, cancelled_by="passenger", minutes_before_departure=60, rule=money.Rule.PASSENGER_LATE,
            total_paid_paise=55000, refund_paise=49500, vconnects_kept_paise=5500,
        )


class LedgerTests(Base):
    def test_hold_release_withdraw(self):
        b = self.booking()
        ledger.hold_earning(b)
        self.assertEqual(self.balances(), (45000, 0, 0))
        ledger.release_earning(b)
        self.assertEqual(self.balances(), (0, 45000, 0))
        w = Withdrawal.objects.create(user=self.driver, amount_paise=45000, method="bank", destination="HDFC ••••1234",
                                      idempotency_key="w1")
        ledger.debit_withdrawal(w)
        self.assertEqual(self.balances(), (0, 0, 0))
        w.status = WithdrawalStatus.FAILED
        w.save()
        ledger.return_withdrawal(w)
        self.assertEqual(self.balances(), (0, 45000, 0))
        self.assertEqual(ledger.reconcile(self.account()), [])
        self.assertEqual(self.account().entries.count(), 4)

    def test_same_event_twice_changes_nothing(self):
        b = self.booking()
        e1, created1 = ledger.hold_earning(b)
        e2, created2 = ledger.hold_earning(b)
        self.assertEqual((created1, created2, e1.pk), (True, False, e2.pk))
        self.assertEqual(self.balances(), (45000, 0, 0))

    def test_key_reused_for_a_different_change_is_refused(self):
        b = self.booking()
        ledger.hold_earning(b)
        with self.assertRaises(ledger.IdempotencyConflict):
            ledger.post(self.driver, EntryKind.ADJUSTMENT, key=f"booking:{b.pk}:held", available=1, description="x")

    def test_balances_never_go_negative(self):
        b = self.booking()
        with self.assertRaises(ledger.InsufficientBalance):
            ledger.release_earning(b)  # nothing held yet
        with self.assertRaises(ledger.InsufficientBalance):
            ledger.post(self.driver, EntryKind.ADJUSTMENT, key="k", available=-1, description="x")
        self.assertEqual(self.balances(), (0, 0, 0))
        self.assertFalse(EarningEntry.objects.exists())

    def test_cancellation_reverses_the_held_earning(self):
        b = self.booking()
        ledger.hold_earning(b)
        ledger.reverse_earning(b)
        self.assertEqual(self.balances(), (0, 0, 0))
        with self.assertRaises(ledger.InsufficientBalance):
            ledger.release_earning(b)

    def test_penalty_then_recovery_from_next_earnings(self):
        b1, b2 = self.booking(), self.booking(passenger=self.rider2)
        ledger.hold_earning(b1)
        ledger.release_earning(b1)  # 450 available
        ledger.charge_penalty(b2, 60000)  # 600 penalty: 450 now, 150 owed
        self.assertEqual(self.balances(), (0, 0, 15000))
        self.assertEqual(ledger.withdrawal_block(self.driver)[0], "owed")

        ledger.hold_earning(b2)
        ledger.release_earning(b2)  # 450 released: 150 pays off the debt, 300 available
        self.assertEqual(self.balances(), (0, 30000, 0))
        self.assertIn("pay off penalties", EarningEntry.objects.filter(kind=EntryKind.EARNING_RELEASED).first().description)
        self.assertIsNone(ledger.withdrawal_block(self.driver))
        self.assertEqual(ledger.reconcile(self.account()), [])

    def test_withdrawal_limits(self):
        b = self.booking()
        ledger.hold_earning(b)
        self.assertEqual(ledger.withdrawal_block(self.driver)[0], "below_minimum")
        ledger.release_earning(b)
        for i in range(3):
            Withdrawal.objects.create(user=self.driver, amount_paise=100, method="bank", destination="x",
                                      idempotency_key=f"w{i}", status=WithdrawalStatus.PAID)
        self.assertEqual(ledger.withdrawal_block(self.driver)[0], "daily_limit")

    def test_only_one_open_withdrawal(self):
        Withdrawal.objects.create(user=self.driver, amount_paise=100, method="bank", destination="x", idempotency_key="a")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Withdrawal.objects.create(user=self.driver, amount_paise=100, method="bank", destination="x", idempotency_key="b")

    def test_freeze_needs_a_reason_and_is_audited(self):
        with self.assertRaises(ledger.LedgerError):
            ledger.set_frozen(self.driver, True, actor=self.root, reason="  ")
        ledger.set_frozen(self.driver, True, actor=self.root, reason="Chargeback under review")
        self.assertEqual(ledger.withdrawal_block(self.driver)[0], "frozen")
        ledger.set_frozen(self.driver, False, actor=self.root)
        self.assertEqual(
            list(FinancialAuditLog.objects.order_by("at", "id").values_list("action", flat=True)),
            [FinancialAction.WITHDRAWALS_FROZEN, FinancialAction.WITHDRAWALS_UNFROZEN],
        )

    def test_adjustment_needs_reason_and_is_audited(self):
        with self.assertRaises(ledger.LedgerError):
            ledger.adjust(self.driver, actor=self.root, reason="", key="adj1", available=100)
        ledger.adjust(self.driver, actor=self.root, reason="Goodwill credit", key="adj1", available=100)
        ledger.adjust(self.driver, actor=self.root, reason="Goodwill credit", key="adj1", available=100)  # repeat
        self.assertEqual(self.balances(), (0, 100, 0))
        self.assertEqual(FinancialAuditLog.objects.filter(action=FinancialAction.LEDGER_POSTED).count(), 1)


class ImmutabilityTests(Base):
    def setUp(self):
        self.entry, _ = ledger.hold_earning(self.booking())

    def test_entries_cannot_be_changed_or_deleted(self):
        self.entry.description = "changed"
        with self.assertRaises(ImmutableError):
            self.entry.save()
        with self.assertRaises(ImmutableError):
            self.entry.delete()
        with self.assertRaises(ImmutableError):
            EarningEntry.objects.filter(pk=self.entry.pk).update(description="x")
        with self.assertRaises(ImmutableError):
            EarningEntry.objects.all().delete()

    def test_audit_rows_cannot_be_changed(self):
        row = FinancialAuditLog.objects.create(actor_label="system", action=FinancialAction.SETTINGS_CHANGED)
        with self.assertRaises(ImmutableError):
            row.save()
        with self.assertRaises(ImmutableError):
            FinancialAuditLog.objects.all().delete()


class ReconcileCommandTests(Base):
    def test_clean_and_tampered(self):
        ledger.hold_earning(self.booking())
        out = StringIO()
        call_command("reconcile_earnings", stdout=out)
        self.assertIn("All 1 earnings accounts reconcile", out.getvalue())

        with connection.cursor() as c:  # someone edits the balance directly in the database
            c.execute("UPDATE payments_earningsaccount SET available_paise = 99999")
        err = StringIO()
        with self.assertRaises(CommandError):
            call_command("reconcile_earnings", stdout=StringIO(), stderr=err)
        self.assertIn("available: balance 99999 but entries add up to 0", err.getvalue())


@override_settings(PAYOUT_ENCRYPTION_KEYS=[TEST_KEY])
class PayoutAccountTests(Base):
    def test_account_number_is_encrypted_and_masked(self):
        pa = PayoutAccount(user=self.driver, holder_name="Meera K", bank_name="HDFC Bank", ifsc="HDFC0001234")
        pa.set_account_number("5010 0123 4567 89")
        pa.full_clean()
        pa.save()
        pa.refresh_from_db()
        self.assertEqual(pa.account_last4, "6789")
        self.assertEqual(pa.display, "HDFC Bank ••••6789")
        self.assertNotIn(b"50100123456789", bytes(pa.account_number_enc))
        self.assertEqual(pa.account_number(), "50100123456789")
        self.assertNotIn("50100123456789", str(pa))

    def test_upi(self):
        pa = PayoutAccount(user=self.driver, holder_name="Meera K", method=PayoutMethod.UPI)
        pa.set_upi_id(" Meera.K@OkAxis ")
        self.assertEqual(pa.upi_masked, "me*****@okaxis")
        self.assertEqual(pa.upi_id(), "meera.k@okaxis")
        self.assertEqual(mask_upi("ab@ybl"), "ab**@ybl")

    def test_validation(self):
        validate_ifsc("SBIN0005943")
        for bad in ["SBIN1005943", "SBI0005943", "sbin000594", ""]:
            with self.subTest(bad), self.assertRaises(ValidationError):
                validate_ifsc(bad)
        pa = PayoutAccount(user=self.driver, holder_name="x")
        for bad in ["12345678", "1234567890123456789", "12AB4567890"]:
            with self.subTest(bad), self.assertRaises(ValidationError):
                pa.set_account_number(bad)
        for bad in ["meera", "meera@", "@okaxis", "me era@okaxis"]:
            with self.subTest(bad), self.assertRaises(ValidationError):
                pa.set_upi_id(bad)


class AdminTests(Base):
    def setUp(self):
        self.client.force_login(self.root)

    def test_settings_change_is_audited(self):
        url = reverse("admin:payments_paymentsettings_change", args=[PaymentSettings.load().pk])
        self.assertEqual(self.client.get(reverse("admin:payments_paymentsettings_changelist")).status_code, 302)
        data = {f: getattr(PaymentSettings.load(), f) for f in [
            "platform_fee_bps", "publisher_commission_bps", "cancel_window_hours", "passenger_cancel_early_bps",
            "passenger_cancel_late_bps", "publisher_penalty_early_bps", "publisher_penalty_late_bps",
            "seat_hold_minutes", "auto_complete_hours", "no_show_after_minutes", "min_withdrawal_paise",
            "max_withdrawals_per_day", "gst_bps"]}
        r = self.client.post(url, {**data, "publisher_penalty_late_bps": 1200})
        self.assertEqual(r.status_code, 302)
        row = FinancialAuditLog.objects.get(action=FinancialAction.SETTINGS_CHANGED)
        self.assertEqual(row.details["changes"], {"publisher_penalty_late_bps": [1000, 1200]})
        self.assertEqual(row.actor, self.root)

        r = self.client.post(url, {**data, "platform_fee_bps": 10_001})
        self.assertEqual(r.status_code, 200)  # rejected by the form

    def test_ledger_is_read_only(self):
        b = self.booking()
        entry, _ = ledger.hold_earning(b)
        self.assertEqual(self.client.get(reverse("admin:payments_earningentry_changelist")).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:payments_earningentry_add")).status_code, 403)
        self.assertEqual(self.client.post(reverse("admin:payments_earningentry_delete", args=[entry.pk])).status_code, 403)
        page = self.client.get(reverse("admin:payments_earningentry_change", args=[entry.pk])).content.decode()
        self.assertNotIn('name="held_delta"', page)
        self.assertEqual(self.client.get(reverse("admin:bookings_booking_change", args=[b.pk])).status_code, 200)

    def test_freeze_from_admin(self):
        ledger.account_for(self.driver)
        acct = self.account()
        url = reverse("admin:payments_earningsaccount_change", args=[acct.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        r = self.client.post(url, {**INLINE, "withdrawals_frozen": "on", "frozen_reason": ""})
        self.assertEqual(r.status_code, 200)  # reason required
        self.assertFalse(self.account().withdrawals_frozen)
        self.client.post(url, {**INLINE, "withdrawals_frozen": "on", "frozen_reason": "Dispute"})
        acct = self.account()
        self.assertTrue(acct.withdrawals_frozen)
        self.assertEqual((acct.frozen_reason, acct.frozen_by), ("Dispute", self.root))

    @override_settings(PAYOUT_ENCRYPTION_KEYS=[TEST_KEY])
    def test_payout_account_page_never_shows_the_number(self):
        pa = PayoutAccount(user=self.driver, holder_name="Meera K", bank_name="HDFC Bank", ifsc="HDFC0001234")
        pa.set_account_number("50100123456789")
        pa.save()
        page = self.client.get(reverse("admin:payments_payoutaccount_change", args=[pa.pk])).content.decode()
        self.assertIn("6789", page)
        self.assertNotIn("50100123456789", page)
        self.assertNotIn("account_number_enc", page)

    def test_every_payments_page_loads(self):
        for name in ["payment", "refund", "webhookevent", "payoutaccount", "earningsaccount", "earningentry",
                     "withdrawal", "financialauditlog"]:
            with self.subTest(name):
                self.assertEqual(self.client.get(reverse(f"admin:payments_{name}_changelist")).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:bookings_problemreport_changelist")).status_code, 200)
