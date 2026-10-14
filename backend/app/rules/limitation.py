"""
Limitation flag for MSMED Act claims.

Flags when as_of is more than arbitration_limitation_years after the due date.
This is a warning only — never a verdict.

[VERIFY] the limitation period for MSMED arbitration and the legal effect of
acknowledgments of debt on the limitation clock.
"""

from __future__ import annotations

from datetime import date

from app.rules.pack_loader import RulePack
from app.rules.types import LimitationResult


def check_limitation(
    due_date: date,
    as_of: date,
    pack: RulePack,
) -> LimitationResult:
    """Flag whether the claim may be time-barred for arbitration.

    Args:
        due_date: The computed due date for the invoice.
        as_of:    The evaluation date.
        pack:     The active rule pack.

    Returns:
        :class:`LimitationResult` with a warning flag and working notes.

    Note:
        This is a WARNING only.  Acknowledgments of debt (e.g. part-payments,
        written admissions) may restart the limitation clock.  [VERIFY period
        and acknowledgment effect with a CA or lawyer before the demo.]
    """
    limitation_years = pack.arbitration_limitation_years
    working: list[str] = []

    days_since_due = (as_of - due_date).days

    # Approximate: years * 365 (ignoring leap years for flagging purposes)
    # A more precise cutoff would use dateutil.relativedelta; we flag conservatively.

    def add_years(d: date, years: int) -> date:
        try:
            return d.replace(year=d.year + years)
        except ValueError:
            # Feb 29 -> Feb 28
            return d.replace(year=d.year + years, month=2, day=28)  # noqa: DTZ007

    cutoff = add_years(due_date, limitation_years)
    is_potentially_time_barred = as_of > cutoff

    working.append(
        f"Due date: {due_date}. "
        f"Limitation window: {limitation_years} years. "
        f"Cutoff date: {cutoff}. "
        f"As-of: {as_of}. "
        f"Days since due: {days_since_due}. "
        "[VERIFY limitation period and effect of acknowledgments of debt on the clock]"
    )

    if is_potentially_time_barred:
        working.append(
            f"WARNING: As-of date ({as_of}) is after the {limitation_years}-year limitation "
            f"cutoff ({cutoff}). This claim MAY be time-barred for MSMED arbitration. "
            "Acknowledgments of debt (part-payments, written admissions) may restart "
            "the limitation clock. [VERIFY with a CA or lawyer before relying on this.]"
        )
    else:
        working.append(
            f"No limitation issue as of {as_of}. "
            f"Remaining time before cutoff: {(cutoff - as_of).days} days."
        )

    return LimitationResult(
        due_date=due_date,
        as_of=as_of,
        limitation_years=limitation_years,
        days_since_due=days_since_due,
        is_potentially_time_barred=is_potentially_time_barred,
        working=working,
    )
