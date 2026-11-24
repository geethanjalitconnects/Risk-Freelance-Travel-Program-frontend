"""Phase 7: earnings summary, history, withdrawal requests and the passenger's payments list."""
import uuid
from datetime import timedelta

from cryptography.fernet import Fernet
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.bookings import services as booking_services
from apps.bookings.models import Booking
from apps.geo.models import City
from apps.geo.testing import seed_geo
from apps.payments import ledger
from apps.payments.models import EarningsAccount, FinancialAuditLog, Payment, PayoutAccount, Refund, Transfer, Withdrawal
from apps.rides.models import Ride
from apps.verification.testing import approve_driver

KEY = Fernet.generate_key().decode()
# Withdrawals release Route transfers: Route on, Razorpay calls mocked (see setUp).
ROUTE_ON = dict(PAYOUTS_ENABLED=True, ROUTE_ENABLED=True, RAZORPAY_KEY_ID="rzp_test_unit", RAZORPAY_KEY_SECRET="s")


@override_settings(PAYOUT_ENCRYPTION_KEYS=[KEY])
class WalletBase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        seed_geo()
        cls.driver = approve_driver(User.objects.create_user("+919000000002", name="Meera", gender="F"))
        cls.rider = User.objects.create_user("+919000000003", name="Ravi", gender="M")
        cls.maa, cls.blr = City.objects.get(code="MAA"), City.objects.get(code="BLR")

    def setUp(self):
        cache.clear()  # rate limits are per test
        self.as_user(self.driver)

    def as_user(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")

    def completed_booking(self, price=500):
        ride = Ride.objects.create(
            driver=self.driver, origin=self.maa, destination=self.blr, pickup="A", dropoff="B",
            depart=timezone.now() + timedelta(days=2), duration_min=300, km=370, price=price, seats_total=3,
            vehicle_model="Creta", vehicle_year=2023,
        )
        b = booking_services.create_booking(self.rider, ride.pk, 1)
        Payment.objects.create(booking=b, amount_paise=b.total_paise, status="captured", idempotency_key=f"p{b.pk}")
        ledger.hold_earning(b)
        ledger.release_earning(b)
        return b

    def payout_account(self):
        pa = PayoutAccount(user=self.driver, holder_name="Meera Nair", bank_name="HDFC Bank", ifsc="HDFC0001234")
        pa.set_account_number("50100123456789")
        pa.save()
        return pa

    def held_transfer(self, booking):
        """A completed booking whose transfer Razorpay holds (in the Route tests it is created through the API mock)."""
        Booking.objects.filter(pk=booking.pk).update(status="completed")
        return Transfer.objects.create(
            booking=booking, payment=booking.payments.get(), linked_account_id="acc_x", status="on_hold",
            amount_paise=booking.publisher_earning_paise, razorpay_transfer_id=f"trf_{booking.pk.hex[:10]}",
            idempotency_key=f"booking:{booking.pk}:transfer",
        )

    def withdraw(self, key=None):
        return self.client.post(reverse("withdrawals"), HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()))


class EarningsTests(WalletBase):
    def test_summary(self):
        self.completed_booking()  # ₹450 available
        body = self.client.get(reverse("earnings")).json()
        self.assertEqual((body["held"], body["available"], body["owed"]), (0, 45000, 0))
        self.assertFalse(body["canWithdraw"])
        self.assertEqual(body["block"]["code"], "payouts_unavailable")
        self.assertFalse(body["payoutsEnabled"])
        self.assertTrue(body["isDriver"])
        self.assertEqual((body["minWithdrawal"], body["maxPerDay"]), (10000, 3))
        self.assertIsNone(body["payoutAccount"])

    def test_history_types_amounts_and_pages(self):
        b = self.completed_booking()
        ledger.charge_penalty(b, 1000)
        rows = self.client.get(reverse("earnings-history")).json()
        self.assertEqual(rows["count"], 3)
        newest = rows["results"]
        self.assertEqual([(e["kind"], e["type"], e["amount"], e["status"]) for e in newest], [
            ("penalty", "debit", 1000, "completed"),
            ("earning_released", "credit", 45000, "completed"),
            ("earning_held", "hold", 45000, "held"),
        ])
        self.assertIn("Chennai → Bengaluru", newest[1]["route"])
        self.assertEqual(newest[0]["availableAfter"], 44000)

        for i in range(20):
            ledger.post(self.driver, "adjustment", key=f"adj{i}", available=1, description="test")
        page2 = self.client.get(reverse("earnings-history"), {"page": 2}).json()
        self.assertEqual((page2["page"], page2["pages"], page2["count"], len(page2["results"])), (2, 2, 23, 3))
        self.assertEqual(self.client.get(reverse("earnings-history"), {"page": "x"}).json()["page"], 1)

    def test_other_users_see_only_their_own(self):
        self.completed_booking()
        self.as_user(self.rider)
        body = self.client.get(reverse("earnings")).json()
        self.assertEqual((body["available"], body["isDriver"]), (0, False))
        self.assertEqual(self.client.get(reverse("earnings-history")).json()["count"], 0)


class WithdrawalTests(WalletBase):
    def setUp(self):
        super().setUp()
        from unittest import mock

        from apps.payments import razorpay

        p = mock.patch.object(razorpay, "release_transfer", return_value={})
        p.start()
        self.addCleanup(p.stop)

    def test_disabled_until_payouts_are_approved(self):
        self.completed_booking()
        self.payout_account()
        r = self.withdraw()
        self.assertEqual((r.status_code, r.json()["code"]), (503, "payouts_unavailable"))
        self.assertFalse(Withdrawal.objects.exists())

    @override_settings(**ROUTE_ON)
    def test_full_flow_and_idempotency(self):
        b = self.completed_booking()
        self.assertEqual(self.withdraw().json()["code"], "no_payout_account")
        pa = self.payout_account()
        self.assertEqual(self.client.post(reverse("withdrawals")).json()["code"], "bad_key")
        self.assertEqual(self.withdraw().json()["code"], "payout_account_pending")
        PayoutAccount.objects.filter(pk=pa.pk).update(status="verified", provider_account_id="acc_x")
        self.held_transfer(b)

        key = str(uuid.uuid4())
        r = self.withdraw(key)
        self.assertEqual(r.status_code, 201, r.content)
        w = r.json()
        self.assertEqual((w["amount"], w["status"], w["destination"], w["method"]), (45000, "pending", "HDFC Bank ••••6789", "bank"))
        self.assertNotIn("50100123456789", r.content.decode())
        acct = EarningsAccount.objects.get(user=self.driver)
        self.assertEqual(acct.available_paise, 0)

        again = self.withdraw(key)  # a double swipe / retry with the same key
        self.assertEqual((again.status_code, again.json()["id"]), (200, w["id"]))
        self.assertEqual(Withdrawal.objects.count(), 1)
        self.assertEqual(EarningsAccount.objects.get(user=self.driver).available_paise, 0)

        self.completed_booking()  # more earnings, but one withdrawal is still on its way
        self.assertEqual(self.withdraw().json()["code"], "in_progress")
        self.assertTrue(FinancialAuditLog.objects.filter(action="withdrawal_updated", amount_paise=45000).exists())
        history = self.client.get(reverse("earnings-history")).json()["results"]
        self.assertIn(("withdrawal", "pending"), [(e["type"], e["status"]) for e in history])
        self.assertEqual(self.client.get(reverse("withdrawals")).json()[0]["id"], w["id"])

    @override_settings(**ROUTE_ON)
    def test_rules(self):
        self.payout_account()
        self.assertEqual(self.withdraw().json()["code"], "below_minimum")
        b = self.completed_booking()
        ledger.set_frozen(self.driver, True, actor=None, reason="Chargeback review")
        self.assertEqual(self.withdraw().json()["code"], "frozen")
        ledger.set_frozen(self.driver, False, actor=None)
        ledger.charge_penalty(b, 50000)  # more than available: the rest is owed
        self.assertEqual(self.withdraw().json()["code"], "owed")
        PayoutAccount.objects.filter(user=self.driver).update(status="failed")
        self.assertEqual(self.withdraw().json()["code"], "payout_account_failed")


class PassengerPaymentsTests(WalletBase):
    def test_payments_and_refunds(self):
        b = self.completed_booking()
        Refund.objects.create(payment=b.payments.get(), booking=b, amount_paise=1000, rule="passenger_late",
                              idempotency_key="r1")
        self.as_user(self.rider)
        rows = self.client.get(reverse("my-payments")).json()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["amount"], rows[0]["status"]), (55000, "captured"))
        self.assertEqual(rows[0]["refunds"][0]["amount"], 1000)
        self.assertEqual(rows[0]["refunds"][0]["reason"], "Passenger cancelled within 24 h")
        self.as_user(self.driver)
        self.assertEqual(self.client.get(reverse("my-payments")).json(), [])
