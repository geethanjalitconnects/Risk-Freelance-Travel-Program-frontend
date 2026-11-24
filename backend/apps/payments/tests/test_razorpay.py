"""Phase 3 (Razorpay payments, webhooks, refunds) and Phase 8 (Route transfers and releases).

Razorpay is never called from the test suite: every API function is replaced with a mock that
returns what Razorpay's documented responses contain, and the tests check exactly which calls
were made (and that none were made twice).
"""
import hashlib
import hmac
import json
import uuid
from datetime import timedelta
from io import StringIO
from unittest import mock

from cryptography.fernet import Fernet
from django.core.management import call_command
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.bookings.models import Booking
from apps.geo.models import City
from apps.geo.seed import seed_geo
from apps.payments import ledger, razorpay, route
from apps.payments.models import (
    EarningsAccount, FinancialAuditLog, Payment, PayoutAccount, Refund, Transfer, WebhookEvent, Withdrawal,
)
from apps.rides.models import Ride
from apps.verification.testing import approve_driver

SECRET, WH_SECRET = "test_key_secret", "test_webhook_secret"
RZP = dict(PAYMENTS_ENABLED=True, RAZORPAY_KEY_ID="rzp_test_unit", RAZORPAY_KEY_SECRET=SECRET,
           RAZORPAY_WEBHOOK_SECRET=WH_SECRET, PAYOUT_ENCRYPTION_KEYS=[Fernet.generate_key().decode()])
TOTAL, EARNING = 66000, 54000  # ₹600 seat


def sign(order_id, payment_id):
    return hmac.new(SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()


def rp_payment(order_id, pid="pay_1", status="captured", amount=TOTAL):
    return {"id": pid, "order_id": order_id, "amount": amount, "currency": "INR", "status": status, "method": "upi"}


@override_settings(**RZP)
class RazorpayBase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        seed_geo()
        cls.driver = approve_driver(User.objects.create_user("+919000000001", name="Meera", gender="F"))
        cls.rider = User.objects.create_user("+919000000002", name="Ravi", gender="M")
        cls.rider2 = User.objects.create_user("+919000000003", name="Asha", gender="F")
        cls.maa, cls.blr = City.objects.get(code="MAA"), City.objects.get(code="BLR")

    def setUp(self):
        cache.clear()  # rate limits are per test
        self.orders = 0
        p = mock.patch.object(razorpay, "create_order", side_effect=self._order)
        self.create_order = p.start()
        self.addCleanup(p.stop)

    def _order(self, amount, receipt, notes):
        self.orders += 1
        return {"id": f"order_{self.orders}", "amount": amount, "status": "created"}

    def as_user(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")

    def ride(self, hours=48, seats=3):
        return Ride.objects.create(
            driver=self.driver, origin=self.maa, destination=self.blr, pickup="A", dropoff="B",
            depart=timezone.now() + timedelta(hours=hours), duration_min=300, km=370, price=600, seats_total=seats,
            vehicle_model="Creta", vehicle_year=2023,
        )

    def book(self, ride, user=None):
        self.as_user(user or self.rider)
        r = self.client.post(reverse("booking-list"), {"rideId": str(ride.pk), "seats": 1}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def pay(self, bid):
        r = self.client.post(reverse("booking-pay", args=[bid]))
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def verify(self, bid, order_id, pid="pay_1", sig=None, entity=None):
        with mock.patch.object(razorpay, "fetch_payment", return_value=entity or rp_payment(order_id, pid)):
            return self.client.post(reverse("booking-payment-verify", args=[bid]), {
                "razorpayOrderId": order_id, "razorpayPaymentId": pid, "razorpaySignature": sig or sign(order_id, pid),
            }, format="json")

    def paid_booking(self, ride=None, user=None):
        b = self.book(ride or self.ride(), user)
        opts = self.pay(b["id"])
        self.assertEqual(self.verify(b["id"], opts["orderId"], pid=f"pay_{b['id'][:8]}").status_code, 200)
        return Booking.objects.get(pk=b["id"])

    def webhook(self, event, entity_key, entity, event_id=None, signature=None):
        body = json.dumps({"event": event, "payload": {entity_key: {"entity": entity}}, "created_at": 1}).encode()
        sig = signature or hmac.new(WH_SECRET.encode(), body, hashlib.sha256).hexdigest()
        self.client.credentials()
        return self.client.post(reverse("razorpay-webhook"), body, content_type="application/json",
                                HTTP_X_RAZORPAY_SIGNATURE=sig, HTTP_X_RAZORPAY_EVENT_ID=event_id or str(uuid.uuid4()))

    def balances(self):
        a = EarningsAccount.objects.filter(user=self.driver).first()
        return (a.held_paise, a.available_paise, a.owed_paise) if a else (0, 0, 0)


class CheckoutTests(RazorpayBase):
    def test_price_quote(self):
        self.as_user(self.rider)
        q = self.client.get(reverse("booking-quote"), {"rideId": str(self.ride().pk), "seats": 2}).json()
        self.assertEqual((q["rideAmount"], q["platformFee"], q["total"], q["seatHoldMinutes"]), (120000, 12000, 132000, 10))

    def test_booking_waits_for_payment_and_holds_seats(self):
        ride = self.ride(seats=1)
        b = self.book(ride)
        self.assertEqual(b["status"], "pending_payment")
        self.assertIsInstance(b["holdExpiresAt"], int)
        self.as_user(self.rider2)
        r = self.client.post(reverse("booking-list"), {"rideId": str(ride.pk), "seats": 1}, format="json")
        self.assertEqual(r.json()["code"], "full")

    def test_one_order_per_booking(self):
        b = self.book(self.ride())
        o1, o2 = self.pay(b["id"]), self.pay(b["id"])
        self.assertEqual((o1["orderId"], o2["orderId"], o1["amount"], o1["keyId"]), ("order_1", "order_1", TOTAL, "rzp_test_unit"))
        self.assertEqual(self.create_order.call_count, 1)
        self.assertNotIn(SECRET, json.dumps(o1))

    def test_verified_and_captured_confirms_once(self):
        b = self.book(self.ride())
        opts = self.pay(b["id"])
        r = self.verify(b["id"], opts["orderId"])
        self.assertEqual(r.json()["status"], "confirmed")
        self.assertIn("Payment of ₹660 received", r.json()["events"][-1]["text"])
        p = Payment.objects.get()
        self.assertEqual((p.status, p.razorpay_payment_id, p.method), ("captured", "pay_1", "upi"))
        self.assertEqual(self.balances(), (EARNING, 0, 0))
        # The webhook for the same payment arrives too: nothing happens twice.
        self.assertEqual(self.webhook("payment.captured", "payment", rp_payment("order_1")).json()["status"], "ok")
        self.assertEqual(self.balances(), (EARNING, 0, 0))
        self.assertEqual(FinancialAuditLog.objects.filter(action="payment_captured").count(), 1)

    def test_bad_signature_never_confirms(self):
        b = self.book(self.ride())
        opts = self.pay(b["id"])
        r = self.verify(b["id"], opts["orderId"], sig="0" * 64)
        self.assertEqual((r.status_code, r.json()["code"]), (400, "invalid_signature"))
        self.assertEqual(Booking.objects.get(pk=b["id"]).status, "pending_payment")
        self.assertTrue(FinancialAuditLog.objects.filter(action="payment_failed").exists())

    def test_signature_ok_but_razorpay_says_not_captured(self):
        b = self.book(self.ride())
        opts = self.pay(b["id"])
        r = self.verify(b["id"], opts["orderId"], entity=rp_payment(opts["orderId"], status="failed"))
        self.assertEqual(r.json()["status"], "pending_payment")
        self.assertEqual(Payment.objects.get().status, "failed")

    def test_wrong_amount_is_not_accepted(self):
        b = self.book(self.ride())
        opts = self.pay(b["id"])
        r = self.verify(b["id"], opts["orderId"], entity=rp_payment(opts["orderId"], amount=100))
        self.assertEqual(r.json()["status"], "pending_payment")


class WebhookTests(RazorpayBase):
    def test_signature_and_duplicates(self):
        b = self.book(self.ride())
        self.pay(b["id"])
        bad = self.webhook("payment.captured", "payment", rp_payment("order_1"), signature="f" * 64)
        self.assertEqual(bad.status_code, 400)
        self.assertFalse(WebhookEvent.objects.exists())
        self.assertEqual(self.webhook("payment.captured", "payment", rp_payment("order_1"), event_id="evt_1").json()["status"], "ok")
        self.assertEqual(Booking.objects.get(pk=b["id"]).status, "confirmed")
        self.assertEqual(self.webhook("payment.captured", "payment", rp_payment("order_1"), event_id="evt_1").json()["status"], "duplicate")
        self.assertEqual(WebhookEvent.objects.count(), 1)
        self.assertEqual(self.webhook("customer.created", "customer", {}).json()["status"], "ok")
        self.assertEqual(WebhookEvent.objects.latest("received_at").status, "ignored")

    def test_payment_failed_keeps_the_hold(self):
        b = self.book(self.ride())
        self.pay(b["id"])
        self.webhook("payment.failed", "payment", {**rp_payment("order_1", status="failed"), "error_code": "BAD_REQUEST_ERROR"})
        self.assertEqual(Payment.objects.get().status, "failed")
        self.assertEqual(Booking.objects.get(pk=b["id"]).status, "pending_payment")


class HoldExpiryTests(RazorpayBase):
    def expire(self, bid):
        Booking.objects.filter(pk=bid).update(hold_expires_at=timezone.now() - timedelta(seconds=1))
        out = StringIO()
        call_command("expire_payment_holds", stdout=out)
        return out.getvalue()

    def test_expiry_frees_seats_then_late_payment_confirms_if_free(self):
        ride = self.ride(seats=1)
        b = self.book(ride)
        self.pay(b["id"])
        self.assertIn("Expired 1", self.expire(b["id"]))
        self.assertEqual(Booking.objects.get(pk=b["id"]).status, "expired")
        self.webhook("payment.captured", "payment", rp_payment("order_1"))
        self.assertEqual(Booking.objects.get(pk=b["id"]).status, "confirmed")

    def test_late_payment_after_seats_taken_is_refunded_in_full(self):
        ride = self.ride(seats=1)
        b = self.book(ride)
        self.pay(b["id"])
        self.expire(b["id"])
        self.book(ride, self.rider2)  # someone else takes the seat
        with mock.patch.object(razorpay, "create_refund", return_value={"id": "rfnd_1", "status": "processed"}) as cr, \
                self.captureOnCommitCallbacks(execute=True):
            self.webhook("payment.captured", "payment", rp_payment("order_1"))
        booking = Booking.objects.get(pk=b["id"])
        self.assertEqual((booking.status, booking.cancellation.rule), ("cancelled", "seats_unavailable"))
        cr.assert_called_once()
        self.assertEqual(cr.call_args.args[:2], ("pay_1", TOTAL))
        self.assertEqual(Refund.objects.get().status, "processed")


class RefundTests(RazorpayBase):
    def test_cancel_sends_the_refund_once_and_webhook_completes_it(self):
        b = self.paid_booking()
        with mock.patch.object(razorpay, "create_refund", return_value={"id": "rfnd_9", "status": "pending"}) as cr, \
                self.captureOnCommitCallbacks(execute=True):
            self.as_user(self.rider)
            r = self.client.post(reverse("booking-cancel", args=[b.pk]))
        self.assertEqual(r.json()["cancellation"]["refund"], 56100)  # 85%, more than 24 h before
        cr.assert_called_once()
        self.assertEqual(cr.call_args.kwargs["idempotency_key"], f"booking:{b.pk}:refund:passenger_early")
        refund = Refund.objects.get()
        self.assertEqual((refund.status, refund.razorpay_refund_id), ("processing", "rfnd_9"))
        from apps.payments import refunds

        refunds.send(refund.pk)  # a repeat send is refused locally
        cr.assert_called_once()
        self.webhook("refund.processed", "refund", {"id": "rfnd_9", "status": "processed"})
        self.assertEqual(Refund.objects.get().status, "processed")

    def test_gateway_down_then_retried(self):
        b = self.paid_booking()
        down = razorpay.RazorpayError("Couldn't reach Razorpay.")
        with mock.patch.object(razorpay, "create_refund", side_effect=down), self.captureOnCommitCallbacks(execute=True):
            self.as_user(self.rider)
            self.client.post(reverse("booking-cancel", args=[b.pk]))
        refund = Refund.objects.get()
        self.assertEqual((refund.status, refund.attempts), ("pending", 1))
        with mock.patch.object(razorpay, "create_refund", return_value={"id": "rfnd_2", "status": "processed"}):
            call_command("process_refunds", stdout=StringIO())
        self.assertEqual(Refund.objects.get().status, "processed")


# ---------------------------------------------------------------- Route (Phase 8)


@override_settings(ROUTE_ENABLED=True, PAYOUTS_ENABLED=True)
class RouteTests(RazorpayBase):
    def setUp(self):
        super().setUp()
        pa = PayoutAccount(user=self.driver, holder_name="Meera Nair", bank_name="HDFC Bank", ifsc="HDFC0001234",
                           status="verified", provider_account_id="acc_meera")
        pa.set_account_number("50100123456789")
        pa.save()
        self.calls = []
        for name in ("create_transfer", "release_transfer", "reverse_transfer", "create_refund"):
            p = mock.patch.object(razorpay, name, side_effect=getattr(self, "_" + name))
            p.start()
            self.addCleanup(p.stop)

    def _create_transfer(self, payment_id, account, amount, notes, idempotency_key):
        self.calls.append(("transfer", account, amount, idempotency_key))
        return {"items": [{"id": f"trf_{len(self.calls)}", "on_hold": True, "settlement_status": "on_hold"}]}

    def _release_transfer(self, tid):
        self.calls.append(("release", tid))
        return {"id": tid, "on_hold": False}

    def _reverse_transfer(self, tid, amount=None, idempotency_key=None):
        self.calls.append(("reverse", tid, amount, idempotency_key))
        return {"id": "rvrsl_1", "amount": amount}

    def _create_refund(self, pid, amount, notes, idempotency_key=None, reverse_all=False):
        self.calls.append(("refund", amount))
        return {"id": f"rfnd_{len(self.calls)}", "status": "processed"}

    def captured(self, ride=None, user=None):
        with self.captureOnCommitCallbacks(execute=True):
            return self.paid_booking(ride, user)

    def complete(self, b):
        from apps.bookings.completion import auto_complete

        Ride.objects.filter(pk=b.ride_id).update(depart=timezone.now() - timedelta(hours=40), arrive=timezone.now() - timedelta(hours=30))
        self.assertTrue(auto_complete(b.pk))

    def test_transfer_on_hold_for_90_percent_of_ride_amount(self):
        b = self.captured()
        t = Transfer.objects.get(booking=b)
        self.assertEqual((t.status, t.amount_paise, t.linked_account_id), ("on_hold", EARNING, "acc_meera"))
        self.assertEqual(self.calls, [("transfer", "acc_meera", EARNING, f"booking:{b.pk}:transfer")])
        route.send_transfer(t.pk)  # repeat: no second transfer
        self.assertEqual(len(self.calls), 1)

    def test_unverified_linked_account_waits(self):
        PayoutAccount.objects.filter(user=self.driver).update(status="pending")
        b = self.captured()
        self.assertEqual(Transfer.objects.get(booking=b).status, "queued")
        self.assertEqual(self.calls, [])
        PayoutAccount.objects.filter(user=self.driver).update(status="verified", transfers_allowed_at=timezone.now() + timedelta(hours=5))
        call_command("process_route", stdout=StringIO())
        self.assertEqual(self.calls, [])  # still in the cooling period
        PayoutAccount.objects.filter(user=self.driver).update(transfers_allowed_at=timezone.now() - timedelta(minutes=1))
        call_command("process_route", stdout=StringIO())
        self.assertEqual(Transfer.objects.get(booking=b).status, "on_hold")

    def test_cancellation_reverses_before_refunding(self):
        b = self.captured()
        with self.captureOnCommitCallbacks(execute=True):
            self.as_user(self.rider)
            self.client.post(reverse("booking-cancel", args=[b.pk]))
        self.assertEqual([c[0] for c in self.calls], ["transfer", "reverse", "refund"])
        self.assertEqual(self.calls[1][2], EARNING)
        self.assertEqual(Transfer.objects.get(booking=b).status, "reversed")
        self.assertEqual(self.balances(), (0, 0, 0))

    def test_withdraw_releases_once_and_webhook_marks_paid(self):
        b = self.captured()
        self.complete(b)
        self.as_user(self.driver)
        key = str(uuid.uuid4())
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(reverse("withdrawals"), HTTP_IDEMPOTENCY_KEY=key)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["amount"], EARNING)
        with self.captureOnCommitCallbacks(execute=True):
            again = self.client.post(reverse("withdrawals"), HTTP_IDEMPOTENCY_KEY=key)
        self.assertEqual(again.status_code, 200)
        self.assertEqual([c[0] for c in self.calls].count("release"), 1)
        w = Withdrawal.objects.get()
        self.assertEqual(w.status, "processing")
        t = Transfer.objects.get(booking=b)
        self.assertEqual((t.status, t.withdrawal_id), ("released", w.pk))
        self.assertEqual(self.balances(), (0, 0, 0))

        self.webhook("transfer.processed", "transfer", {"id": t.razorpay_transfer_id, "settlement_status": "settled"})
        w.refresh_from_db()
        self.assertEqual(w.status, "paid")

    def test_penalty_recovered_by_partial_reversal_before_release(self):
        b1 = self.captured()
        b2 = self.captured(user=self.rider2)
        self.complete(b1)
        self.complete(b2)
        ledger.charge_penalty(b1, 6000)  # e.g. from a late cancellation of another ride
        self.as_user(self.driver)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(reverse("withdrawals"), HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        self.assertEqual(r.json()["amount"], 2 * EARNING - 6000)
        reversals = [c for c in self.calls if c[0] == "reverse"]
        self.assertEqual([c[2] for c in reversals], [6000])
        self.assertEqual([c[0] for c in self.calls].count("release"), 2)
        self.assertEqual(sum(t.releasable_paise for t in Transfer.objects.all()), r.json()["amount"])

    def test_nothing_released_before_completion(self):
        self.captured()
        ledger.adjust(self.driver, actor=None, reason="Goodwill", key="g1", available=20000)
        self.as_user(self.driver)
        r = self.client.post(reverse("withdrawals"), HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        self.assertEqual(r.json()["code"], "nothing_to_release")
        self.assertFalse([c for c in self.calls if c[0] == "release"])


@override_settings(**RZP)
class RouteDisabledTests(RazorpayBase):
    def test_no_transfers_and_no_withdrawals(self):
        with mock.patch.object(razorpay, "create_transfer") as ct, self.captureOnCommitCallbacks(execute=True):
            self.paid_booking()
        ct.assert_not_called()
        self.assertFalse(Transfer.objects.exists())
        self.as_user(self.driver)
        self.assertEqual(self.client.get(reverse("earnings")).json()["block"]["code"], "payouts_unavailable")
