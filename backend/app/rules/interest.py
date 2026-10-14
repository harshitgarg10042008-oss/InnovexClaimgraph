"""
Interest computation engine for MSMED Act claims.

Algorithm (exact implementation):

1.  Periods are monthly from interest_start_date.
    Period k: starts at interest_start + k months (clamped to month end),
              ends at interest_start + (k+1) months - 1 day.
    days_in_period = (end - start).days + 1.

2.  Annual rate for a day = interest_multiplier × bank_rate_pct_on_that_day / 100.
    Monthly rate = annual_rate / 12.

3.  Within a period, balance = outstanding_principal + capitalised_interest.
    Payments reduce outstanding_principal from their date (on that day, before
    that day's accrual).  Payments before interest_start reduce principal
    before accrual begins.  If a payment exceeds outstanding_principal, the
    remainder reduces capitalised_interest.

4.  Per-period accrual is "daily_weighted":
    period_interest = Σ_slices  balance_at_slice_start × (annual_rate/12) × (slice_days / days_in_period)
    where slices are defined by payment dates and rate-change dates inside the period.

5.  At the end of each FULL period: round interest to 2 dp (ROUND_HALF_UP) and
    capitalise it (add to capitalised_interest, NOT to outstanding_principal).
    The final partial period (as_of inside it): rounded but NOT capitalised.

6.  total_claimable = outstanding_principal + capitalised_interest + total_interest_accrued
    (the last term is only the final partial period interest if not capitalised yet,
    plus any already-capitalised interest already included in capitalised_interest).

NOTE: No call to date.today() anywhere; every function takes an explicit as_of.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.rules.pack_loader import RulePack
from app.rules.types import ClaimItem, InterestResult, Payment, PeriodRow, RateTable

_TWO_DP = Decimal("0.01")
_ZERO = Decimal("0")


def _clamp_to_month_end(year: int, month: int, day: int) -> date:
    """Return a date clamped to the end of the month if *day* exceeds it."""
    max_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, max_day))


def _add_months_clamped(d: date, months: int) -> date:
    """Add *months* to *d* with clamping to month end (computed from *d*, not iteratively)."""
    total_months = d.month - 1 + months
    year = d.year + total_months // 12
    month = total_months % 12 + 1
    return _clamp_to_month_end(year, month, d.day)


def _round2(v: Decimal) -> Decimal:
    return v.quantize(_TWO_DP, rounding=ROUND_HALF_UP)


def _apply_payment(amount: Decimal, outstanding_principal: Decimal, capitalised_interest: Decimal) -> tuple[Decimal, Decimal]:
    """Apply *amount* to principal first; remainder reduces capitalised interest."""
    if amount <= outstanding_principal:
        return outstanding_principal - amount, capitalised_interest
    remainder = amount - outstanding_principal
    new_cap = max(_ZERO, capitalised_interest - remainder)
    return _ZERO, new_cap


def compute_interest(
    item: ClaimItem,
    interest_start_date: date,
    pack: RulePack,
    rate_table: RateTable,
    as_of: date,
) -> InterestResult:
    """Compute interest on *item* from *interest_start_date* to *as_of* inclusive.

    Args:
        item:                The claim item (principal + payments).
        interest_start_date: Day interest begins (day after due date).
        pack:                The active rule pack.
        rate_table:          Bank rate table for rate lookups.
        as_of:               Last day of interest accrual (inclusive).

    Returns:
        :class:`InterestResult` with per-period rows and summary figures.
    """
    working: list[str] = []
    multiplier = Decimal(str(pack.interest_multiplier))

    working.append(
        f"Interest start: {interest_start_date}. "
        f"As-of: {as_of}. "
        f"Multiplier: {multiplier}x bank rate. "
        f"Compounding: {pack.compounding}. "
        f"Payment application: {pack.payment_application}."
    )

    if as_of < interest_start_date:
        working.append("as_of is before interest_start_date; interest = 0.")
        return InterestResult(
            interest_start_date=interest_start_date,
            as_of=as_of,
            total_interest=_ZERO,
            outstanding_principal=item.principal_amount,
            capitalised_interest=_ZERO,
            total_claimable=item.principal_amount,
            periods=[],
            working=working,
        )

    # ------------------------------------------------------------------
    # Sort and apply payments that pre-date interest_start_date
    # ------------------------------------------------------------------
    # Build a dict: date -> list of payments
    payments_by_date: dict[date, list[Payment]] = {}
    for p in item.payments:
        if pack.tds_counts_as_payment or p.kind.value != "tds":
            payments_by_date.setdefault(p.pay_date, []).append(p)
        else:
            working.append(f"Payment on {p.pay_date} kind=tds skipped (tds_counts_as_payment=False).")

    outstanding_principal = item.principal_amount
    capitalised_interest = _ZERO
    working.append(f"Opening principal: {outstanding_principal}")

    # Apply payments before interest_start_date
    for pay_date in sorted(payments_by_date):
        if pay_date < interest_start_date:
            for pmt in payments_by_date[pay_date]:
                outstanding_principal, capitalised_interest = _apply_payment(
                    pmt.amount, outstanding_principal, capitalised_interest
                )
                working.append(
                    f"Pre-interest payment {pmt.amount} on {pay_date} (kind={pmt.kind.value}): "
                    f"principal -> {outstanding_principal}"
                )

    working.append(f"Principal after pre-interest payments: {outstanding_principal}")

    # ------------------------------------------------------------------
    # Build period list
    # ------------------------------------------------------------------
    periods: list[PeriodRow] = []
    period_idx = 0
    period_start = interest_start_date

    while period_start <= as_of:
        # Period end: start + 1 month - 1 day (clamped)
        next_anniversary = _add_months_clamped(interest_start_date, period_idx + 1)
        period_end = next_anniversary - timedelta(days=1)

        is_full_period = period_end <= as_of
        effective_end = period_end if is_full_period else as_of

        # days_in_period is the length of this full monthly period (start to period_end)
        days_in_period = (period_end - period_start).days + 1
        accrued_days = (effective_end - period_start).days + 1
        working.append(
            f"\nPeriod {period_idx}: {period_start} to {effective_end} "
            f"({accrued_days}/{days_in_period} days, {'full' if is_full_period else 'PARTIAL'})"
        )

        # ---------------------------------------------------------------
        # Build sub-slices within the period
        # Each slice boundary is a payment date or a rate-change date
        # that falls in [period_start, effective_end].
        # ---------------------------------------------------------------
        # Collect all boundary dates within this period
        boundary_dates: set[date] = set()

        # Rate change boundaries
        for row in rate_table.rows:
            if period_start < row.effective_from <= effective_end:
                boundary_dates.add(row.effective_from)

        # Payment boundaries (only payments in [interest_start, effective_end])
        for pay_date in payments_by_date:
            if interest_start_date <= pay_date and period_start <= pay_date <= effective_end:
                boundary_dates.add(pay_date)

        # Build ordered slice starts
        slice_starts = sorted([period_start] + [d for d in boundary_dates])

        # Running balance at start of this period
        balance = outstanding_principal + capitalised_interest

        period_interest = _ZERO
        rate_slices: list[tuple[Decimal, int]] = []  # (annual_rate_pct, days)
        slice_principal = outstanding_principal
        slice_capitalised = capitalised_interest

        for i, sl_start in enumerate(slice_starts):
            sl_end = (slice_starts[i + 1] - timedelta(days=1)) if i + 1 < len(slice_starts) else effective_end

            # Apply payments on sl_start before computing this slice's accrual
            if sl_start in payments_by_date and sl_start >= interest_start_date:
                for pmt in payments_by_date[sl_start]:
                    slice_principal, slice_capitalised = _apply_payment(
                        pmt.amount, slice_principal, slice_capitalised
                    )
                    working.append(
                        f"  Payment {pmt.amount} on {sl_start} (kind={pmt.kind.value}): "
                        f"principal -> {slice_principal}, cap_interest -> {slice_capitalised}"
                    )

            slice_balance = slice_principal + slice_capitalised
            slice_days = (sl_end - sl_start).days + 1

            # Annual rate for this slice (rate in force at sl_start)
            bank_rate = rate_table.rate_on(sl_start)
            annual_rate = multiplier * bank_rate / Decimal("100")

            # Slice interest: balance × (annual_rate / 12) × (slice_days / days_in_period)
            slice_interest = (
                slice_balance
                * (annual_rate / Decimal("12"))
                * Decimal(str(slice_days))
                / Decimal(str(days_in_period))
            )
            period_interest += slice_interest

            annual_rate_pct = multiplier * bank_rate
            rate_slices.append((annual_rate_pct, slice_days))

            working.append(
                f"  Slice {sl_start}–{sl_end}: {slice_days} days, "
                f"balance={slice_balance}, bank_rate={bank_rate}%, "
                f"annual_rate_pct={annual_rate_pct}%, "
                f"slice_interest={slice_interest:.6f}"
            )

        # Round period interest to 2 dp (ROUND_HALF_UP)
        period_interest_rounded = _round2(period_interest)
        working.append(
            f"Period {period_idx} total interest (before rounding): {period_interest:.6f} "
            f"-> rounded: {period_interest_rounded}"
        )

        # Capitalise at end of full period
        if is_full_period:
            capitalised_interest += period_interest_rounded
            working.append(
                f"Period {period_idx} capitalised: capitalised_interest -> {capitalised_interest}"
            )

        # Update outstanding_principal to reflect ALL payments in this period
        # (already applied slice-by-slice in slice_principal; sync back)
        outstanding_principal = slice_principal
        capitalised_interest_after_payments = slice_capitalised
        if is_full_period:
            # Rebuild with capitalisation added
            capitalised_interest = capitalised_interest_after_payments + period_interest_rounded
        else:
            capitalised_interest = capitalised_interest_after_payments

        opening_base_for_row = balance
        periods.append(
            PeriodRow(
                period_index=period_idx,
                start=period_start,
                end=effective_end,
                days_in_period=days_in_period,
                opening_base=opening_base_for_row,
                rate_slices=rate_slices,
                interest=period_interest_rounded,
                capitalised=is_full_period,
            )
        )

        if not is_full_period:
            break

        period_start = next_anniversary
        period_idx += 1

    # ------------------------------------------------------------------
    # Totals
    # ------------------------------------------------------------------
    total_interest = sum((p.interest for p in periods), _ZERO)
    total_claimable = outstanding_principal + capitalised_interest + (
        periods[-1].interest if periods and not periods[-1].capitalised else _ZERO
    )

    working.append(
        f"\nSummary: outstanding_principal={outstanding_principal}, "
        f"capitalised_interest={capitalised_interest}, "
        f"total_interest={total_interest}, "
        f"total_claimable={total_claimable}"
    )

    return InterestResult(
        interest_start_date=interest_start_date,
        as_of=as_of,
        total_interest=total_interest,
        outstanding_principal=outstanding_principal,
        capitalised_interest=capitalised_interest,
        total_claimable=total_claimable,
        periods=periods,
        working=working,
    )
