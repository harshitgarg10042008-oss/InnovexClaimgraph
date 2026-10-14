"""
Rule engine entry point.

evaluate_claim() runs eligibility, due date, interest and limitation checks
and returns a single unified result.  If eligibility is not_eligible, interest
is set to null with an explicit reason.

No DB access, no network, no LLM, no randomness.  Same input → same output.
"""

from __future__ import annotations

from datetime import date

from app.rules.due_date import compute_due_date
from app.rules.eligibility import check_eligibility
from app.rules.interest import compute_interest
from app.rules.limitation import check_limitation
from app.rules.pack_loader import RulePack
from app.rules.types import (
    AcceptanceBasis,
    ClaimItem,
    ClaimResult,
    EligibilityStatus,
    PartyFacts,
    RateTable,
)


def evaluate_claim(
    party_facts: PartyFacts,
    item: ClaimItem,
    pack: RulePack,
    rate_table: RateTable,
    as_of: date,
) -> ClaimResult:
    """Run the full rule pipeline for a single claim item.

    Args:
        party_facts: Supplier eligibility facts.
        item:        The claim item (invoice/delivery pair with payments).
        pack:        The validated rule pack.
        rate_table:  Bank rate table.
        as_of:       Evaluation date (explicit, never date.today()).

    Returns:
        :class:`ClaimResult` with eligibility, due date, interest, and
        limitation results.  Interest is None if the supplier is not eligible.
    """
    working: list[str] = [
        f"evaluate_claim: item={item.id!r}, as_of={as_of}, "
        f"pack={pack.pack_name} v{pack.version}"
    ]

    # 1. Eligibility
    eligibility = check_eligibility(party_facts, pack, as_of)
    working.append(f"Eligibility: {eligibility.status.value}")

    if eligibility.status == EligibilityStatus.not_eligible:
        working.append(
            "Supplier is not eligible. Interest computation refused. "
            "Reason(s): " + "; ".join(eligibility.reasons)
        )
        return ClaimResult(
            eligibility=eligibility,
            due_date=None,
            interest=None,
            limitation=None,
            interest_refused_reason=(
                "Interest not computed because eligibility check returned not_eligible: "
                + "; ".join(eligibility.reasons)
            ),
            working=working,
        )

    # 2. Due date
    due_date_result = compute_due_date(item, pack, as_of)
    working.append(
        f"Due date: {due_date_result.due_date}, "
        f"basis: {due_date_result.acceptance_basis.value}, "
        f"interest start: {due_date_result.interest_start_date}"
    )

    # 3. Interest (only if there is a valid due date and interest start)
    interest_result = None
    interest_refused_reason = None

    if due_date_result.acceptance_basis == AcceptanceBasis.blocked_by_objection:
        interest_refused_reason = (
            "Interest not computed: goods are under an unresolved written objection "
            "and are not claimable until the objection is removed."
        )
        working.append(interest_refused_reason)
    elif due_date_result.interest_start_date is None:
        interest_refused_reason = "Interest not computed: no interest start date (due date unknown)."
        working.append(interest_refused_reason)
    elif due_date_result.interest_start_date > as_of:
        interest_refused_reason = (
            f"Interest not computed: interest starts on {due_date_result.interest_start_date} "
            f"which is after as_of ({as_of})."
        )
        working.append(interest_refused_reason)
    else:
        interest_result = compute_interest(
            item,
            due_date_result.interest_start_date,
            pack,
            rate_table,
            as_of,
        )
        working.append(
            f"Interest: total={interest_result.total_interest}, "
            f"claimable={interest_result.total_claimable}"
        )

    # 4. Limitation (only if we have a due date)
    limitation_result = None
    if due_date_result.due_date is not None:
        limitation_result = check_limitation(due_date_result.due_date, as_of, pack)
        if limitation_result.is_potentially_time_barred:
            working.append(
                f"LIMITATION WARNING: claim may be time-barred as of {as_of}."
            )

    return ClaimResult(
        eligibility=eligibility,
        due_date=due_date_result,
        interest=interest_result,
        limitation=limitation_result,
        interest_refused_reason=interest_refused_reason,
        working=working,
    )
