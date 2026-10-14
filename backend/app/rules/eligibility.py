"""
Eligibility gate for MSMED Act claims.

Rules implemented:
- medium/large enterprise -> not_eligible
- trader -> not_eligible
- Udyam reg date after contract/PO date -> not_eligible
- missing reg date or certificate -> unknown
- otherwise -> eligible

Legal basis marked [VERIFY] in working text.
"""

from __future__ import annotations

from datetime import date

from app.rules.pack_loader import RulePack
from app.rules.types import EligibilityResult, EligibilityStatus, PartyFacts


def check_eligibility(
    facts: PartyFacts,
    pack: RulePack,
    as_of: date,  # noqa: ARG001  kept for uniform signature convention
) -> EligibilityResult:
    """Determine whether the supplier is eligible under the MSMED Act.

    Args:
        facts: Supplier party facts.
        pack:  The active rule pack.
        as_of: The evaluation date (not used for eligibility itself but
               required so every engine function carries an explicit date —
               never call date.today()).

    Returns:
        :class:`EligibilityResult` with status, reasons, and working notes.
    """
    working: list[str] = []
    reasons: list[str] = []

    # 1. Enterprise type gate
    # [VERIFY] exact wording of MSMED Act sections 7 to 9; micro/small are
    # defined by investment and turnover ceilings in the 2020 amendment.
    etype = facts.enterprise_type.lower().strip()
    allowed_types = [t.lower() for t in pack.eligible_enterprise_types]
    working.append(
        f"Enterprise type: {facts.enterprise_type!r}. "
        f"Eligible types per pack {pack.pack_name} v{pack.version}: {pack.eligible_enterprise_types}. "
        "[VERIFY exact wording of MSMED Act sections 7-9]"
    )
    if etype not in allowed_types:
        reasons.append(
            f"Enterprise type '{facts.enterprise_type}' is not covered by the MSMED Act "
            f"(only {pack.eligible_enterprise_types} are eligible). "
            "[VERIFY exact wording of MSMED Act]"
        )
        working.append(f"RESULT: not_eligible — enterprise type {facts.enterprise_type!r} not in {pack.eligible_enterprise_types}")
        return EligibilityResult(
            status=EligibilityStatus.not_eligible,
            reasons=reasons,
            working=working,
        )

    # 2. Activity gate — pure traders excluded
    # [VERIFY] definition of "trader" and case law on mixed-activity suppliers.
    activity = facts.activity.lower().strip()
    excluded = [a.lower() for a in pack.excluded_activities]
    working.append(
        f"Activity: {facts.activity!r}. "
        f"Excluded activities per pack: {pack.excluded_activities}. "
        "[VERIFY definition of 'trader' and applicable case law]"
    )
    if activity in excluded:
        reasons.append(
            f"Activity '{facts.activity}' is excluded under the MSMED Act "
            f"(excluded: {pack.excluded_activities}). "
            "[VERIFY]"
        )
        working.append(f"RESULT: not_eligible — activity {facts.activity!r} is excluded")
        return EligibilityResult(
            status=EligibilityStatus.not_eligible,
            reasons=reasons,
            working=working,
        )

    # 3. Udyam registration date vs contract date
    # [VERIFY] larger-bench reference pending; current reading requires Udyam
    # registration to pre-date the contract/PO date.
    working.append(
        f"Udyam reg date: {facts.udyam_reg_date}. "
        f"Contract/PO date: {facts.contract_date}. "
        "[VERIFY Udyam timing requirement — larger-bench reference pending]"
    )
    if facts.udyam_reg_date is not None:
        if facts.udyam_reg_date > facts.contract_date:
            reason = (
                "Udyam registration date is after the PO date "
                f"({facts.udyam_reg_date} > {facts.contract_date}). "
                "[VERIFY]"
            )
            reasons.append(reason)
            working.append(f"RESULT: not_eligible — {reason}")
            return EligibilityResult(
                status=EligibilityStatus.not_eligible,
                reasons=reasons,
                working=working,
            )
        working.append(
            f"Udyam reg date {facts.udyam_reg_date} is on or before contract date {facts.contract_date}. OK."
        )
    else:
        # Missing reg date — cannot confirm eligibility
        working.append("Udyam registration date is missing. Cannot confirm eligibility.")
        reasons.append("Udyam registration date is missing; eligibility cannot be confirmed.")
        return EligibilityResult(
            status=EligibilityStatus.unknown,
            reasons=reasons,
            working=working,
        )

    # 4. Udyam certificate
    if not facts.udyam_certificate_present:
        working.append("Udyam certificate is not present — eligibility cannot be confirmed.")
        reasons.append("Udyam certificate is missing; upload to confirm eligibility.")
        return EligibilityResult(
            status=EligibilityStatus.unknown,
            reasons=reasons,
            working=working,
        )

    # 5. All checks passed
    working.append(
        f"Eligible: enterprise_type={facts.enterprise_type!r}, activity={facts.activity!r}, "
        f"Udyam reg {facts.udyam_reg_date} <= contract {facts.contract_date}, certificate present."
    )
    return EligibilityResult(
        status=EligibilityStatus.eligible,
        reasons=["Supplier meets all eligibility criteria checked by the rule engine."],
        working=working,
    )
