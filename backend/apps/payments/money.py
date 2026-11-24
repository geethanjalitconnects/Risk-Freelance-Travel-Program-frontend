"""All VConnects money maths, in one place.

Rules:
- Every amount is an ``int`` number of paise. Every rate is an ``int`` number of basis points
  (100 bps = 1%, 10_000 bps = 100%). No floats anywhere.
- Percentages round half up to the nearest paisa. Every split is built so its parts add up to the
  whole exactly (the remainder goes to the part computed last), so no paisa is created or lost.
- Functions are pure: they take the amounts and the fee policy and return results. Database work
  lives in ``ledger.py`` and the booking services.

Decided rules (client sign-off, 2026-11-20):
- Passenger pays ride amount + platform fee (10% of the ride amount).
- Publisher receives ride amount - publisher commission (10% of the ride amount).
- Passenger cancels more than 24 h before departure: 15% of the total paid is kept, 85% refunded.
  Passenger cancels within 24 h (or later): 10% kept, 90% refunded. All of it stays with VConnects.
- Publisher cancels: the passenger gets 100% back. Penalty on the publisher: 0% of the ride
  amount more than 24 h before departure, 10% within 24 h. All rates are admin-configurable.
- Passenger no-show (upheld): paid out to the publisher like a completed ride, no refund.
- Publisher no-show (upheld): 100% refund and the within-24-hours publisher penalty.
"""
from dataclasses import asdict, dataclass, fields
from datetime import timedelta
from typing import Optional

BPS = 10_000
PAISE_PER_RUPEE = 100


class MoneyError(ValueError):
    """An amount or rate is invalid (negative, not an integer, above 100%, ...)."""


def _check_paise(value, name="amount"):
    if not isinstance(value, int) or isinstance(value, bool):
        raise MoneyError(f"{name} must be an integer number of paise, got {value!r}.")
    if value < 0:
        raise MoneyError(f"{name} can't be negative, got {value}.")
    return value


def _check_bps(value, name="rate"):
    if not isinstance(value, int) or isinstance(value, bool):
        raise MoneyError(f"{name} must be an integer number of basis points, got {value!r}.")
    if not 0 <= value <= BPS:
        raise MoneyError(f"{name} must be between 0 and {BPS} basis points, got {value}.")
    return value


def rupees_to_paise(rupees: int) -> int:
    return _check_paise(rupees, "rupees") * PAISE_PER_RUPEE


def percent_of(amount: int, bps: int) -> int:
    """``amount`` x ``bps`` / 10 000, rounded half up to the paisa."""
    _check_paise(amount)
    _check_bps(bps)
    return (amount * bps + BPS // 2) // BPS


def format_inr(paise: int) -> str:
    """₹1,234.50 style, for messages and the admin. Indian digit grouping."""
    sign = "-" if paise < 0 else ""
    rupees, p = divmod(abs(paise), PAISE_PER_RUPEE)
    s = str(rupees)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    return f"{sign}₹{s}" + (f".{p:02d}" if p else "")


# ---------------------------------------------------------------- policy


@dataclass(frozen=True)
class FeePolicy:
    """The rates that apply to one booking. Snapshotted on the booking when it is made, so a later
    change in the admin never changes what an existing booking costs or refunds."""

    platform_fee_bps: int = 1000
    publisher_commission_bps: int = 1000
    cancel_window_hours: int = 24
    passenger_cancel_early_bps: int = 1500  # cancelled more than cancel_window_hours before departure
    passenger_cancel_late_bps: int = 1000  # cancelled within the window (or after departure)
    publisher_penalty_early_bps: int = 0  # of the ride amount
    publisher_penalty_late_bps: int = 1000  # of the ride amount

    def __post_init__(self):
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name == "cancel_window_hours":
                if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 24 * 30:
                    raise MoneyError(f"cancel_window_hours must be 0 to 720, got {value!r}.")
            else:
                _check_bps(value, f.name)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "FeePolicy":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def is_late(self, time_to_departure: timedelta) -> bool:
        """True within the window: at most ``cancel_window_hours`` before departure, or after it.
        Exactly 24 h before counts as within ("more than 24 hours" is strictly more)."""
        return time_to_departure <= timedelta(hours=self.cancel_window_hours)


# ---------------------------------------------------------------- booking price


@dataclass(frozen=True)
class BookingAmounts:
    """What a booking costs and who gets what, in paise."""

    ride_amount: int  # price per seat x seats: what the publisher set
    platform_fee: int  # added on top, paid by the passenger
    total: int  # what the passenger pays = ride_amount + platform_fee
    publisher_commission: int  # taken from the ride amount
    publisher_earning: int  # ride_amount - publisher_commission

    @property
    def vconnects_revenue(self) -> int:
        """VConnects' gross share of a completed ride (before gateway fees)."""
        return self.platform_fee + self.publisher_commission

    def __post_init__(self):
        for f in fields(self):
            _check_paise(getattr(self, f.name), f.name)
        if self.total != self.ride_amount + self.platform_fee:
            raise MoneyError("total must equal ride_amount + platform_fee.")
        if self.publisher_earning != self.ride_amount - self.publisher_commission:
            raise MoneyError("publisher_earning must equal ride_amount - publisher_commission.")


def price_booking(price_per_seat_rupees: int, seats: int, policy: FeePolicy) -> BookingAmounts:
    if not isinstance(seats, int) or isinstance(seats, bool) or seats < 1:
        raise MoneyError(f"seats must be a positive integer, got {seats!r}.")
    if price_per_seat_rupees < 1:
        raise MoneyError("The seat price must be at least ₹1.")
    ride_amount = rupees_to_paise(price_per_seat_rupees) * seats
    platform_fee = percent_of(ride_amount, policy.platform_fee_bps)
    commission = percent_of(ride_amount, policy.publisher_commission_bps)
    return BookingAmounts(
        ride_amount=ride_amount,
        platform_fee=platform_fee,
        total=ride_amount + platform_fee,
        publisher_commission=commission,
        publisher_earning=ride_amount - commission,
    )


# ---------------------------------------------------------------- outcomes


class Rule:
    """Which rule settled a booking. Stored on the Cancellation record."""

    COMPLETED = "completed"
    PASSENGER_EARLY = "passenger_early"  # passenger cancelled more than the window before departure
    PASSENGER_LATE = "passenger_late"  # passenger cancelled within the window
    PUBLISHER_EARLY = "publisher_early"
    PUBLISHER_LATE = "publisher_late"
    PUBLISHER_NO_SHOW = "publisher_no_show"
    PASSENGER_NO_SHOW = "passenger_no_show"
    SEATS_UNAVAILABLE = "seats_unavailable"  # paid after the seat hold expired and the seats were gone
    ADMIN_FULL_REFUND = "admin_full_refund"  # VConnects cancelled the ride

    CHOICES = [
        (COMPLETED, "Completed"),
        (PASSENGER_EARLY, "Passenger cancelled more than 24 h before"),
        (PASSENGER_LATE, "Passenger cancelled within 24 h"),
        (PUBLISHER_EARLY, "Publisher cancelled more than 24 h before"),
        (PUBLISHER_LATE, "Publisher cancelled within 24 h"),
        (PUBLISHER_NO_SHOW, "Publisher no-show"),
        (PASSENGER_NO_SHOW, "Passenger no-show"),
        (SEATS_UNAVAILABLE, "Seats no longer available"),
        (ADMIN_FULL_REFUND, "Cancelled by VConnects"),
    ]


@dataclass(frozen=True)
class Settlement:
    """How a booking's money ends up. For every outcome:
    refund + vconnects_kept + publisher_earning == total_paid, and the publisher penalty is a
    separate charge on the publisher's earnings (it never comes out of the passenger's money)."""

    rule: str
    total_paid: int
    refund: int  # back to the passenger's original payment method
    vconnects_kept: int  # stays with VConnects out of the passenger's payment
    publisher_earning: int  # credited to the publisher's earnings
    publisher_penalty: int  # charged to the publisher

    def __post_init__(self):
        for name in ("total_paid", "refund", "vconnects_kept", "publisher_earning", "publisher_penalty"):
            _check_paise(getattr(self, name), name)
        if self.refund + self.vconnects_kept + self.publisher_earning != self.total_paid:
            raise MoneyError("refund + vconnects_kept + publisher_earning must equal total_paid.")


def completed(amounts: BookingAmounts) -> Settlement:
    return Settlement(
        rule=Rule.COMPLETED,
        total_paid=amounts.total,
        refund=0,
        vconnects_kept=amounts.total - amounts.publisher_earning,
        publisher_earning=amounts.publisher_earning,
        publisher_penalty=0,
    )


def passenger_cancellation(amounts: BookingAmounts, policy: FeePolicy, time_to_departure: timedelta) -> Settlement:
    late = policy.is_late(time_to_departure)
    bps = policy.passenger_cancel_late_bps if late else policy.passenger_cancel_early_bps
    kept = percent_of(amounts.total, bps)
    return Settlement(
        rule=Rule.PASSENGER_LATE if late else Rule.PASSENGER_EARLY,
        total_paid=amounts.total,
        refund=amounts.total - kept,
        vconnects_kept=kept,
        publisher_earning=0,
        publisher_penalty=0,
    )


def _full_refund(amounts: BookingAmounts, rule: str, penalty: int = 0) -> Settlement:
    return Settlement(
        rule=rule, total_paid=amounts.total, refund=amounts.total, vconnects_kept=0, publisher_earning=0,
        publisher_penalty=penalty,
    )


def publisher_cancellation(amounts: BookingAmounts, policy: FeePolicy, time_to_departure: timedelta) -> Settlement:
    late = policy.is_late(time_to_departure)
    bps = policy.publisher_penalty_late_bps if late else policy.publisher_penalty_early_bps
    return _full_refund(
        amounts, Rule.PUBLISHER_LATE if late else Rule.PUBLISHER_EARLY, percent_of(amounts.ride_amount, bps)
    )


def publisher_no_show(amounts: BookingAmounts, policy: FeePolicy) -> Settlement:
    """Upheld by an admin: full refund, and the within-window penalty."""
    return _full_refund(amounts, Rule.PUBLISHER_NO_SHOW, percent_of(amounts.ride_amount, policy.publisher_penalty_late_bps))


def passenger_no_show(amounts: BookingAmounts) -> Settlement:
    """Upheld: the publisher kept the seat free, so they are paid as for a completed ride."""
    s = completed(amounts)
    return Settlement(**{**asdict(s), "rule": Rule.PASSENGER_NO_SHOW})


def seats_unavailable(amounts: BookingAmounts) -> Settlement:
    """Payment arrived after the seat hold expired and the seats were taken: full refund."""
    return _full_refund(amounts, Rule.SEATS_UNAVAILABLE)


def admin_full_refund(amounts: BookingAmounts) -> Settlement:
    return _full_refund(amounts, Rule.ADMIN_FULL_REFUND)


# ---------------------------------------------------------------- publisher balances


@dataclass(frozen=True)
class PenaltySplit:
    from_available: int  # taken from the publisher's available earnings now
    owed: int  # recorded as owed, recovered from future earnings


def split_penalty(penalty: int, available: int) -> PenaltySplit:
    """A penalty comes out of available earnings first; the rest is owed."""
    _check_paise(penalty, "penalty")
    _check_paise(available, "available")
    take = min(penalty, available)
    return PenaltySplit(from_available=take, owed=penalty - take)


@dataclass(frozen=True)
class Recovery:
    recovered: int  # used to pay off what the publisher owes
    remaining: int  # left over, credited as available


def recover_owed(owed: int, released: int) -> Recovery:
    """Newly released earnings pay off anything owed first."""
    _check_paise(owed, "owed")
    _check_paise(released, "released")
    take = min(owed, released)
    return Recovery(recovered=take, remaining=released - take)


@dataclass(frozen=True)
class WithdrawalLimits:
    min_withdrawal: int = 100 * PAISE_PER_RUPEE
    max_per_day: int = 3


def withdrawal_block(*, available: int, owed: int, frozen: bool, withdrawals_today: int,
                     limits: WithdrawalLimits) -> Optional[tuple]:
    """Why a publisher can't withdraw now, as (code, message), or None. A withdrawal always takes
    the whole available balance (Route releases whole transfers)."""
    if frozen:
        return ("frozen", "Withdrawals are paused on your account. Contact support.")
    if owed > 0:
        return ("owed", f"You owe {format_inr(owed)} in cancellation penalties. It's recovered from your next earnings.")
    if available < limits.min_withdrawal:
        return ("below_minimum", f"You can withdraw once your balance reaches {format_inr(limits.min_withdrawal)}.")
    if withdrawals_today >= limits.max_per_day:
        return ("daily_limit", f"You can withdraw at most {limits.max_per_day} times a day.")
    return None


# ---------------------------------------------------------------- GST (pending CA advice)


def gst_inclusive_split(amount: int, gst_bps: int) -> tuple:
    """Split a GST-inclusive amount into (base, gst). With gst_bps=0 everything is base. Used only
    for reporting until the CA confirms how GST applies; prices never change because of it."""
    _check_paise(amount)
    if not isinstance(gst_bps, int) or gst_bps < 0:
        raise MoneyError("gst_bps must be a non-negative integer.")
    base = (amount * BPS * 2 + (BPS + gst_bps)) // ((BPS + gst_bps) * 2)  # round half up
    return base, amount - base
