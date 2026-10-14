"""
Due-date computation for MSMED Act claims.

Corrected acceptance rule (applied per master-plan section 7.2 update):
  The day of acceptance is the day of ACTUAL DELIVERY.
  - If the buyer raises a written objection within 15 days of delivery,
    acceptance is the day the supplier removes the objection.
  - Goods under an unresolved objection are NOT claimable (blocked).
  - If there is NO written objection within 15 days, acceptance = delivery day.
  - The 15-day window is only the objection window; it does NOT shift the
    acceptance date.  [VERIFY]

Due date: acceptance_date + credit_days, where credit_days excludes the
acceptance day (i.e. the day AFTER acceptance is day 1).

Interest starts: day after due_date.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from app.rules.pack_loader import RulePack
from app.rules.types import AcceptanceBasis, ClaimItem, DueDateResult


def _add_months(d: date, months: int) -> date:
    """Add *months* to *d*, clamping to month end when needed."""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return d.replace(year=year, month=month, day=day)


def compute_due_date(
    item: ClaimItem,
    pack: RulePack,
    as_of: date,
) -> DueDateResult:
    """Compute acceptance date, due date and interest start date.

    Args:
        item:  A single claim item (invoice/delivery pair).
        pack:  The active rule pack.
        as_of: The evaluation date (used to compute days_overdue).

    Returns:
        :class:`DueDateResult` with all computed dates and the working log.
    """
    working: list[str] = []

    objection_window = pack.objection_window_days  # typically 15

    # ------------------------------------------------------------------
    # Step 1 – determine acceptance date and basis
    # ------------------------------------------------------------------
    working.append(
        f"Delivery date: {item.delivery_date}. "
        f"Objection window: {objection_window} days."
    )

    if item.written_acceptance_date is not None:
        # Explicit written acceptance by buyer (challan stamp, email, etc.)
        acceptance_date: date | None = item.written_acceptance_date
        acceptance_basis = AcceptanceBasis.actual
        working.append(
            f"Written acceptance found: {acceptance_date}. "
            "Basis: actual. [VERIFY that this date is supported by the source document]"
        )

    elif item.objection is not None:
        obj = item.objection
        working.append(
            f"Buyer raised a written objection on {obj.raised_on}. "
            f"Objection removed: {obj.removed_on}."
        )

        # Check if the objection was raised within the window
        window_end = item.delivery_date + timedelta(days=objection_window)
        working.append(
            f"Objection window ends: {window_end} "
            f"({item.delivery_date} + {objection_window} days). "
            "[VERIFY objection window convention]"
        )

        if obj.raised_on <= window_end:
            # Objection is valid (within window)
            if obj.removed_on is None:
                # Unresolved — goods not claimable
                working.append(
                    "Objection is unresolved. Goods are not claimable under the MSMED Act. "
                    "Acceptance is BLOCKED until the objection is removed."
                )
                return DueDateResult(
                    acceptance_date=None,
                    acceptance_basis=AcceptanceBasis.blocked_by_objection,
                    credit_days=0,
                    credit_days_capped=False,
                    due_date=None,
                    interest_start_date=None,
                    days_overdue=None,
                    working=working,
                )
            else:
                acceptance_date = obj.removed_on
                acceptance_basis = AcceptanceBasis.objection_removed
                working.append(
                    f"Objection removed on {obj.removed_on}. "
                    "Acceptance date = objection removal date. [VERIFY]"
                )
        else:
            # Objection raised after the window — treat as no objection
            working.append(
                f"Objection raised on {obj.raised_on} is outside the "
                f"{objection_window}-day window (window ended {window_end}). "
                "Treating as no valid objection — deemed acceptance applies."
            )
            acceptance_date = item.delivery_date
            acceptance_basis = AcceptanceBasis.deemed
            working.append(
                f"Deemed acceptance on delivery day: {acceptance_date}. [VERIFY]"
            )

    else:
        # No written objection within the window — deemed accepted on delivery day
        acceptance_date = item.delivery_date
        acceptance_basis = AcceptanceBasis.deemed
        working.append(
            f"No written objection. Deemed accepted on delivery day: {acceptance_date}. "
            "The 15-day objection window has no effect on the acceptance date "
            "when no objection is raised. [VERIFY]"
        )

    # ------------------------------------------------------------------
    # Step 2 – credit days
    # ------------------------------------------------------------------
    max_cd = pack.max_credit_days
    default_cd = pack.default_credit_days_without_written_agreement
    credit_days_capped = False

    if item.credit_days_written is not None:
        raw_cd = item.credit_days_written
        working.append(f"Written credit period: {raw_cd} days.")
        if raw_cd > max_cd:
            working.append(
                f"Written credit period {raw_cd} exceeds maximum {max_cd} days. "
                f"Capping to {max_cd}. [VERIFY cap applies regardless of contract wording]"
            )
            credit_days = max_cd
            credit_days_capped = True
        else:
            credit_days = raw_cd
    else:
        credit_days = default_cd
        working.append(
            f"No written credit agreement. Using default: {credit_days} days. "
            "[VERIFY default applies only when no written agreement exists]"
        )

    working.append(f"Credit days used: {credit_days} (capped={credit_days_capped}).")

    # ------------------------------------------------------------------
    # Step 3 – due date and interest start
    # ------------------------------------------------------------------
    # due_date_rule = "acceptance_date_plus_credit_days" (acceptance day excluded)
    due_date: date = acceptance_date + timedelta(days=credit_days)
    interest_start_date: date = due_date + timedelta(days=1)

    working.append(
        f"Due date: {acceptance_date} + {credit_days} days = {due_date}. "
        "(Day of acceptance excluded from the count.) [VERIFY day-count convention]"
    )
    working.append(f"Interest start date: {due_date} + 1 day = {interest_start_date}.")

    # ------------------------------------------------------------------
    # Step 4 – days overdue as of as_of
    # ------------------------------------------------------------------
    if as_of >= interest_start_date:
        days_overdue: int | None = (as_of - interest_start_date).days + 1
        working.append(f"Days overdue as of {as_of}: {days_overdue}.")
    else:
        days_overdue = 0
        working.append(f"Interest has not yet started as of {as_of}; days overdue = 0.")

    return DueDateResult(
        acceptance_date=acceptance_date,
        acceptance_basis=acceptance_basis,
        credit_days=credit_days,
        credit_days_capped=credit_days_capped,
        due_date=due_date,
        interest_start_date=interest_start_date,
        days_overdue=days_overdue,
        working=working,
    )
