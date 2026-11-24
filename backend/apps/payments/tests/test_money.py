"""The money rules, worked through with the client's example (₹500 seat) and checked for exact
splits across many amounts and rates."""
from datetime import timedelta
from itertools import product

from django.test import SimpleTestCase

from apps.payments import money
from apps.payments.money import FeePolicy, MoneyError, Rule

POLICY = FeePolicy()  # the agreed defaults
H = timedelta(hours=1)


def amounts(price=500, seats=1, policy=POLICY):
    return money.price_booking(price, seats, policy)


class PercentTests(SimpleTestCase):
    def test_rounds_half_up_to_the_paisa(self):
        self.assertEqual(money.percent_of(55000, 1500), 8250)
        self.assertEqual(money.percent_of(5, 1000), 1)  # 0.5 paise -> 1
        self.assertEqual(money.percent_of(4, 1000), 0)  # 0.4 paise -> 0
        self.assertEqual(money.percent_of(12345, 333), 411)  # 411.0885
        self.assertEqual(money.percent_of(0, 1000), 0)
        self.assertEqual(money.percent_of(100, money.BPS), 100)

    def test_rejects_bad_inputs(self):
        for amount, bps in [(-1, 100), (1.5, 100), ("10", 100), (True, 100), (100, -1), (100, 10_001), (100, 2.5)]:
            with self.subTest(amount=amount, bps=bps), self.assertRaises(MoneyError):
                money.percent_of(amount, bps)

    def test_format_inr(self):
        self.assertEqual(money.format_inr(55000), "₹550")
        self.assertEqual(money.format_inr(46750), "₹467.50")
        self.assertEqual(money.format_inr(12345678905), "₹12,34,56,789.05")
        self.assertEqual(money.format_inr(-500), "-₹5")


class PriceTests(SimpleTestCase):
    def test_client_example(self):
        a = amounts(500)
        self.assertEqual(
            (a.ride_amount, a.platform_fee, a.total, a.publisher_commission, a.publisher_earning),
            (50000, 5000, 55000, 5000, 45000),
        )
        self.assertEqual(a.vconnects_revenue, 10000)

    def test_multiple_seats_use_the_whole_ride_amount(self):
        a = amounts(560, seats=3)
        self.assertEqual((a.ride_amount, a.platform_fee, a.total, a.publisher_earning), (168000, 16800, 184800, 151200))

    def test_configured_rates_and_rounding(self):
        a = amounts(333, policy=FeePolicy(platform_fee_bps=725, publisher_commission_bps=1250))
        self.assertEqual(a.ride_amount, 33300)
        self.assertEqual(a.platform_fee, 2414)  # 2414.25
        self.assertEqual(a.publisher_commission, 4163)  # 4162.5 -> half up
        self.assertEqual(a.total, 35714)
        self.assertEqual(a.publisher_earning, 29137)

    def test_invalid(self):
        for price, seats in [(0, 1), (500, 0), (500, -1), (500, 1.0)]:
            with self.subTest(price=price, seats=seats), self.assertRaises(MoneyError):
                money.price_booking(price, seats, POLICY)

    def test_amounts_must_add_up(self):
        with self.assertRaises(MoneyError):
            money.BookingAmounts(ride_amount=100, platform_fee=10, total=111, publisher_commission=10, publisher_earning=90)
        with self.assertRaises(MoneyError):
            money.BookingAmounts(ride_amount=100, platform_fee=10, total=110, publisher_commission=10, publisher_earning=91)


class PolicyTests(SimpleTestCase):
    def test_defaults_are_the_agreed_rates(self):
        self.assertEqual(POLICY.to_dict(), {
            "platform_fee_bps": 1000, "publisher_commission_bps": 1000, "cancel_window_hours": 24,
            "passenger_cancel_early_bps": 1500, "passenger_cancel_late_bps": 1000,
            "publisher_penalty_early_bps": 0, "publisher_penalty_late_bps": 1000,
        })

    def test_snapshot_round_trip_ignores_unknown_keys(self):
        p = FeePolicy(platform_fee_bps=800)
        self.assertEqual(FeePolicy.from_dict({**p.to_dict(), "something_new": 1}), p)

    def test_invalid_rates(self):
        for kwargs in [{"platform_fee_bps": 10_001}, {"publisher_commission_bps": -1}, {"cancel_window_hours": -1},
                       {"cancel_window_hours": 721}, {"passenger_cancel_late_bps": "10"}]:
            with self.subTest(**kwargs), self.assertRaises(MoneyError):
                FeePolicy(**kwargs)

    def test_window_boundary(self):
        self.assertFalse(POLICY.is_late(24 * H + timedelta(seconds=1)))
        self.assertTrue(POLICY.is_late(24 * H))  # exactly 24 h is "within"
        self.assertTrue(POLICY.is_late(timedelta(0)))
        self.assertTrue(POLICY.is_late(-H))  # after departure


class PassengerCancellationTests(SimpleTestCase):
    def test_more_than_24h_keeps_15_percent_of_total(self):
        s = money.passenger_cancellation(amounts(), POLICY, 48 * H)
        self.assertEqual((s.rule, s.refund, s.vconnects_kept, s.publisher_earning, s.publisher_penalty),
                         (Rule.PASSENGER_EARLY, 46750, 8250, 0, 0))

    def test_within_24h_keeps_10_percent_of_total(self):
        s = money.passenger_cancellation(amounts(), POLICY, 2 * H)
        self.assertEqual((s.rule, s.refund, s.vconnects_kept), (Rule.PASSENGER_LATE, 49500, 5500))

    def test_exactly_24h_is_within(self):
        self.assertEqual(money.passenger_cancellation(amounts(), POLICY, 24 * H).rule, Rule.PASSENGER_LATE)

    def test_uses_the_booking_policy(self):
        p = FeePolicy(passenger_cancel_early_bps=2000, cancel_window_hours=48)
        self.assertEqual(money.passenger_cancellation(amounts(), p, 47 * H).vconnects_kept, 5500)
        self.assertEqual(money.passenger_cancellation(amounts(), p, 49 * H).vconnects_kept, 11000)


class PublisherOutcomeTests(SimpleTestCase):
    def test_publisher_cancels_more_than_24h_full_refund_no_penalty(self):
        s = money.publisher_cancellation(amounts(), POLICY, 30 * H)
        self.assertEqual((s.rule, s.refund, s.vconnects_kept, s.publisher_penalty), (Rule.PUBLISHER_EARLY, 55000, 0, 0))

    def test_publisher_cancels_within_24h_penalty_is_10_percent_of_ride_amount(self):
        s = money.publisher_cancellation(amounts(), POLICY, 3 * H)
        self.assertEqual((s.rule, s.refund, s.publisher_penalty), (Rule.PUBLISHER_LATE, 55000, 5000))

    def test_publisher_no_show(self):
        s = money.publisher_no_show(amounts(), POLICY)
        self.assertEqual((s.rule, s.refund, s.publisher_penalty), (Rule.PUBLISHER_NO_SHOW, 55000, 5000))

    def test_passenger_no_show_pays_the_publisher(self):
        s = money.passenger_no_show(amounts())
        self.assertEqual((s.rule, s.refund, s.vconnects_kept, s.publisher_earning), (Rule.PASSENGER_NO_SHOW, 0, 10000, 45000))

    def test_completed(self):
        s = money.completed(amounts())
        self.assertEqual((s.refund, s.vconnects_kept, s.publisher_earning), (0, 10000, 45000))

    def test_seats_unavailable_and_admin_full_refund(self):
        for fn, rule in [(money.seats_unavailable, Rule.SEATS_UNAVAILABLE), (money.admin_full_refund, Rule.ADMIN_FULL_REFUND)]:
            s = fn(amounts())
            self.assertEqual((s.rule, s.refund, s.publisher_penalty), (rule, 55000, 0))


class InvariantTests(SimpleTestCase):
    """For every outcome, the passenger's payment is split exactly: no paisa created or lost."""

    def test_every_outcome_adds_up(self):
        prices = [50, 57, 333, 560, 999, 4870]
        rates = [0, 1, 333, 1000, 1500, 5000, 10_000]
        times = [-H, timedelta(0), 24 * H, 25 * H]
        checked = 0
        for price, seats, fee, comm, early, late in product(prices, [1, 3], rates, rates[::2], rates[::3], rates[1::3]):
            policy = FeePolicy(platform_fee_bps=fee, publisher_commission_bps=comm, passenger_cancel_early_bps=early,
                               passenger_cancel_late_bps=late, publisher_penalty_late_bps=late)
            a = money.price_booking(price, seats, policy)
            outcomes = [money.completed(a), money.passenger_no_show(a), money.publisher_no_show(a, policy)]
            for t in times:
                outcomes += [money.passenger_cancellation(a, policy, t), money.publisher_cancellation(a, policy, t)]
            for s in outcomes:
                self.assertEqual(s.refund + s.vconnects_kept + s.publisher_earning, a.total)
                self.assertTrue(0 <= s.refund <= a.total)
                self.assertLessEqual(s.publisher_penalty, a.ride_amount)
                checked += 1
        self.assertGreater(checked, 5000)

    def test_settlement_rejects_amounts_that_do_not_add_up(self):
        with self.assertRaises(MoneyError):
            money.Settlement(rule=Rule.COMPLETED, total_paid=100, refund=10, vconnects_kept=10, publisher_earning=81,
                             publisher_penalty=0)


class BalanceRuleTests(SimpleTestCase):
    def test_penalty_from_available_first_then_owed(self):
        self.assertEqual(money.split_penalty(5000, 8000), money.PenaltySplit(from_available=5000, owed=0))
        self.assertEqual(money.split_penalty(5000, 1200), money.PenaltySplit(from_available=1200, owed=3800))
        self.assertEqual(money.split_penalty(5000, 0), money.PenaltySplit(from_available=0, owed=5000))

    def test_new_earnings_pay_off_owed_first(self):
        self.assertEqual(money.recover_owed(3800, 45000), money.Recovery(recovered=3800, remaining=41200))
        self.assertEqual(money.recover_owed(50000, 45000), money.Recovery(recovered=45000, remaining=0))
        self.assertEqual(money.recover_owed(0, 45000), money.Recovery(recovered=0, remaining=45000))

    def test_withdrawal_rules(self):
        limits = money.WithdrawalLimits()
        ok = dict(available=10000, owed=0, frozen=False, withdrawals_today=2, limits=limits)
        self.assertIsNone(money.withdrawal_block(**ok))
        cases = {
            "frozen": {"frozen": True},
            "owed": {"owed": 1},
            "below_minimum": {"available": 9999},
            "daily_limit": {"withdrawals_today": 3},
        }
        for code, change in cases.items():
            with self.subTest(code):
                self.assertEqual(money.withdrawal_block(**{**ok, **change})[0], code)


class GstTests(SimpleTestCase):
    def test_split(self):
        self.assertEqual(money.gst_inclusive_split(11800, 1800), (10000, 1800))
        self.assertEqual(money.gst_inclusive_split(10000, 0), (10000, 0))
        base, gst = money.gst_inclusive_split(10001, 1800)
        self.assertEqual(base + gst, 10001)
