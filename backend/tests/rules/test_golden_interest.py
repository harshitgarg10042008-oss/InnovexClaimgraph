"""
Golden tests for the interest engine (G1, G2, G3).

These numbers were computed by an independent implementation.
If the engine disagrees, we print per-period working and stop.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.rules.interest import compute_interest
from app.rules.pack_loader import load_pack
from app.rules.types import ClaimItem, Payment, PaymentKind, RateRow, RateTable

PACK = load_pack("msmed_v1")


def _const_rate_table(bank_rate_pct: str) -> RateTable:
    """Rate table with a single constant rate starting from a very early date."""
    return RateTable(
        rows=[RateRow(effective_from=date(2000, 1, 1), bank_rate_pct=Decimal(bank_rate_pct))]
    )


def _item(principal: str, payments: list[Payment] | None = None) -> ClaimItem:
    return ClaimItem(
        id="test",
        label="test",
        principal_amount=Decimal(principal),
        delivery_date=date(2026, 1, 1),  # delivery date not used by interest engine
        payments=payments or [],
    )


# ---------------------------------------------------------------------------
# G1: three full months, constant rate 5.75%
#     Period 1 (Feb): 28 days -> 100000 * 0.1725/12 = 1437.50
#     Period 2 (Mar): 31 days -> 101437.50 * 0.1725/12 = 1458.16
#     Period 3 (Apr): 30 days -> 102895.66 * 0.1725/12 = 1479.13
#     Total interest: 4374.79  claimable: 104374.79
# ---------------------------------------------------------------------------


class TestG1:
    interest_start = date(2026, 2, 1)
    as_of = date(2026, 4, 30)
    rate_table = _const_rate_table("5.75")
    item = _item("100000.00")

    EXPECTED_PERIODS = [
        Decimal("1437.50"),
        Decimal("1458.16"),
        Decimal("1479.13"),
    ]
    EXPECTED_TOTAL = Decimal("4374.79")
    EXPECTED_CLAIMABLE = Decimal("104374.79")

    def _run(self):
        return compute_interest(
            self.item, self.interest_start, PACK, self.rate_table, self.as_of
        )

    def test_period_count(self):
        result = self._run()
        assert len(result.periods) == 3, (
            f"Expected 3 periods, got {len(result.periods)}.\n"
            + "\n".join(result.working)
        )

    def test_period_interests(self):
        result = self._run()
        for i, (expected, period) in enumerate(
            zip(self.EXPECTED_PERIODS, result.periods, strict=False)
        ):
            assert period.interest == expected, (
                f"G1 Period {i} interest: expected {expected}, got {period.interest}.\n"
                f"Per-period working:\n" + "\n".join(result.working)
            )

    def test_total_interest(self):
        result = self._run()
        assert result.total_interest == self.EXPECTED_TOTAL, (
            f"G1 total interest: expected {self.EXPECTED_TOTAL}, "
            f"got {result.total_interest}.\n" + "\n".join(result.working)
        )

    def test_claimable(self):
        result = self._run()
        assert result.total_claimable == self.EXPECTED_CLAIMABLE, (
            f"G1 claimable: expected {self.EXPECTED_CLAIMABLE}, "
            f"got {result.total_claimable}.\n" + "\n".join(result.working)
        )

    def test_outstanding_principal_unchanged(self):
        result = self._run()
        assert result.outstanding_principal == Decimal("100000.00"), (
            f"G1 outstanding principal should be 100000, got {result.outstanding_principal}"
        )


# ---------------------------------------------------------------------------
# G2: one period, 31 days, rate change mid-period
#     due_date 2026-09-30 -> interest starts 2026-10-01
#     as_of 2026-10-31 (31 days, one period)
#     6 days at 5.50 (Oct 1-6), 25 days at 5.75 (Oct 7-31)
#     Slice 1: 100000 * (3*5.50/100/12) * (6/31) = 100000 * 0.1375 * 6/31/12
#             = 100000 * 0.001375/12 * ... let me recompute precisely:
#             annual_rate_1 = 3 * 5.50 / 100 = 0.165
#             monthly_weight_1 = 6/31
#             slice1 = 100000 * (0.165/12) * (6/31)
#                    = 100000 * 0.01375 * 0.193548... = 266.129...
#     Slice 2: annual_rate_2 = 3 * 5.75 / 100 = 0.1725
#             slice2 = 100000 * (0.1725/12) * (25/31)
#                    = 100000 * 0.014375 * 0.806452 = 1159.274...
#     total = 266.129 + 1159.274 = 1425.403 -> rounded 1425.40
# ---------------------------------------------------------------------------


class TestG2:
    interest_start = date(2026, 10, 1)
    as_of = date(2026, 10, 31)
    rate_table = RateTable(
        rows=[
            RateRow(effective_from=date(2000, 1, 1), bank_rate_pct=Decimal("5.50")),
            RateRow(effective_from=date(2026, 10, 7), bank_rate_pct=Decimal("5.75")),
        ]
    )
    item = _item("100000.00")

    EXPECTED_INTEREST = Decimal("1425.40")

    def _run(self):
        return compute_interest(
            self.item, self.interest_start, PACK, self.rate_table, self.as_of
        )

    def test_period_count(self):
        result = self._run()
        # as_of is exactly one month anniversary (Oct 31 = Oct 1 + 1 month - 1 day? No:
        # Oct 1 + 1 month = Nov 1; period end = Oct 31. So as_of Oct 31 = period end -> FULL period
        assert len(result.periods) == 1, (
            f"G2 expected 1 period, got {len(result.periods)}.\n"
            + "\n".join(result.working)
        )

    def test_interest(self):
        result = self._run()
        assert result.total_interest == self.EXPECTED_INTEREST, (
            f"G2 interest: expected {self.EXPECTED_INTEREST}, "
            f"got {result.total_interest}.\n"
            f"Period rows:\n"
            + "\n".join(
                f"  period {p.period_index}: {p.interest} (slices={p.rate_slices})"
                for p in result.periods
            )
            + "\nWorking:\n"
            + "\n".join(result.working)
        )

    def test_rate_slices(self):
        result = self._run()
        period = result.periods[0]
        assert len(period.rate_slices) == 2, (
            f"G2 expected 2 rate slices, got {period.rate_slices}"
        )
        # First slice: 3*5.50=16.50 for 6 days
        assert period.rate_slices[0] == (Decimal("16.50"), 6), (
            f"G2 slice 0: {period.rate_slices[0]}"
        )
        # Second slice: 3*5.75=17.25 for 25 days
        assert period.rate_slices[1] == (Decimal("17.25"), 25), (
            f"G2 slice 1: {period.rate_slices[1]}"
        )


# ---------------------------------------------------------------------------
# G3: payment mid-period
#     principal 100000, interest start 2026-02-01, payment 40000 on 2026-02-15
#     as_of 2026-02-28 (28 days, partial/full period)
#     Slice 1: Feb 1-14 (14 days): 100000 * (0.1725/12) * (14/28) = 718.75
#     Slice 2: Feb 15-28 (14 days): 60000  * (0.1725/12) * (14/28) = 431.25
#     Total = 1150.00; outstanding principal = 60000
# ---------------------------------------------------------------------------


class TestG3:
    interest_start = date(2026, 2, 1)
    as_of = date(2026, 2, 28)
    rate_table = _const_rate_table("5.75")
    payment = Payment(
        pay_date=date(2026, 2, 15), amount=Decimal("40000.00"), kind=PaymentKind.cash
    )
    item = _item("100000.00", payments=[payment])

    EXPECTED_INTEREST = Decimal("1150.00")
    EXPECTED_OUTSTANDING = Decimal("60000.00")

    def _run(self):
        return compute_interest(
            self.item, self.interest_start, PACK, self.rate_table, self.as_of
        )

    def test_interest(self):
        result = self._run()
        assert result.total_interest == self.EXPECTED_INTEREST, (
            f"G3 interest: expected {self.EXPECTED_INTEREST}, "
            f"got {result.total_interest}.\n" + "\n".join(result.working)
        )

    def test_outstanding_principal(self):
        result = self._run()
        assert result.outstanding_principal == self.EXPECTED_OUTSTANDING, (
            f"G3 outstanding principal: expected {self.EXPECTED_OUTSTANDING}, "
            f"got {result.outstanding_principal}.\n" + "\n".join(result.working)
        )
