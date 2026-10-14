"""
Readiness score engine (section 7.4 of the master plan).

Per-invoice 100-point checklist:

| Check                                            | Points |
|--------------------------------------------------|--------|
| PO found and linked                              |     15 |
| Written credit terms evidenced                   |     10 |
| Delivery proof linked, quantities match          |     20 |
| Acceptance evidence or deemed-acceptance basis   |     15 |
| Invoice fields valid and not a duplicate         |     10 |
| Payments and adjustments reconciled to the paisa |     15 |
| No open blocker findings                         |     15 |

Case score = principal-weighted average of invoice scores.

Case gates (hard stops, shown as blockers, NOT deducted from points):
- eligibility not failed
- Udyam certificate present
- all low-confidence facts reviewed

Inputs are simple booleans/counts in a Pydantic model; no DB access.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.rules.types import InvoiceScore, ScoreInput, ScoreResult

_TWO_DP = Decimal("0.01")
_ZERO = Decimal("0")

# Weights per check (must sum to 100)
_WEIGHTS: dict[str, int] = {
    "po_found_and_linked": 15,
    "written_credit_evidenced": 10,
    "delivery_proof_linked_qty_match": 20,
    "acceptance_evidence_or_deemed_basis": 15,
    "invoice_valid_not_duplicate": 10,
    "payments_reconciled": 15,
    "no_open_blocker_findings": 15,
}

assert sum(_WEIGHTS.values()) == 100, "Score weights must sum to 100"


def _score_invoice(inp: ScoreInput) -> InvoiceScore:
    breakdown: dict[str, int] = {}
    checks: dict[str, bool] = {
        "po_found_and_linked": inp.po_found_and_linked,
        "written_credit_evidenced": inp.written_credit_evidenced,
        "delivery_proof_linked_qty_match": inp.delivery_proof_linked_qty_match,
        "acceptance_evidence_or_deemed_basis": inp.acceptance_evidence_or_deemed_basis,
        "invoice_valid_not_duplicate": inp.invoice_valid_not_duplicate,
        "payments_reconciled": inp.payments_reconciled,
        "no_open_blocker_findings": inp.no_open_blocker_findings,
    }
    total = 0
    for check_name, weight in _WEIGHTS.items():
        awarded = weight if checks[check_name] else 0
        breakdown[check_name] = awarded
        total += awarded
    return InvoiceScore(item_id=inp.item_id, points=total, breakdown=breakdown)


compute_invoice_score = _score_invoice


def compute_case_score(
    invoice_inputs: list[ScoreInput],
    eligibility_not_failed: bool | object = True,
    udyam_certificate_present: bool = True,
    all_low_confidence_facts_reviewed: bool = True,
    **kwargs: object,
) -> ScoreResult:
    """Compute per-invoice and principal-weighted case score. Alias for compute_score."""
    # Allow passing eligibility_status enum or object
    not_failed = (
        eligibility_not_failed.value != "not_eligible"
        if hasattr(eligibility_not_failed, "value")
        else bool(eligibility_not_failed)
    )
    if "eligibility_status" in kwargs:
        stat = kwargs["eligibility_status"]
        not_failed = stat.value != "not_eligible" if hasattr(stat, "value") else bool(stat)
    return compute_score(
        invoice_inputs=invoice_inputs,
        eligibility_not_failed=not_failed,
        udyam_certificate_present=udyam_certificate_present,
        all_low_confidence_facts_reviewed=all_low_confidence_facts_reviewed,
    )


def compute_score(
    invoice_inputs: list[ScoreInput],
    eligibility_not_failed: bool,
    udyam_certificate_present: bool,
    all_low_confidence_facts_reviewed: bool,
) -> ScoreResult:
    """Compute per-invoice and principal-weighted case score.

    Args:
        invoice_inputs:                  One entry per invoice.
        eligibility_not_failed:          True if eligibility is eligible or unknown
                                         (False if explicitly not_eligible).
        udyam_certificate_present:       Whether the Udyam certificate has been uploaded.
        all_low_confidence_facts_reviewed: Whether all low-confidence facts are confirmed.

    Returns:
        :class:`ScoreResult` with invoice scores, case score, and blockers.
    """
    working: list[str] = []

    # -----------------------------------------------------------------------
    # Per-invoice scoring
    # -----------------------------------------------------------------------
    invoice_scores: list[InvoiceScore] = []
    for inp in invoice_inputs:
        score = _score_invoice(inp)
        invoice_scores.append(score)
        working.append(
            f"Invoice {inp.item_id}: {score.points}/100 — {score.breakdown}"
        )

    # -----------------------------------------------------------------------
    # Principal-weighted case score
    # -----------------------------------------------------------------------
    total_principal = sum((inp.principal_amount for inp in invoice_inputs), _ZERO)
    if total_principal == _ZERO:
        case_score = _ZERO
        working.append("No invoices with principal > 0; case score = 0.")
    else:
        weighted_sum = sum(
            (inp.principal_amount * Decimal(str(sc.points)))
            for inp, sc in zip(invoice_inputs, invoice_scores, strict=False)
        )
        case_score = (weighted_sum / total_principal).quantize(_TWO_DP, rounding=ROUND_HALF_UP)
        working.append(
            f"Case score = principal-weighted average = "
            f"{weighted_sum} / {total_principal} = {case_score}"
        )

    # -----------------------------------------------------------------------
    # Case gates — blockers (not points)
    # -----------------------------------------------------------------------
    blockers: list[str] = []
    if not eligibility_not_failed:
        blockers.append(
            "Eligibility check failed: supplier is not eligible under the MSMED Act. "
            "No interest can be claimed."
        )
    if not udyam_certificate_present:
        blockers.append(
            "Udyam certificate is not uploaded. Upload the Udyam registration certificate "
            "to unlock the claim dossier."
        )
    if not all_low_confidence_facts_reviewed:
        blockers.append(
            "There are low-confidence extracted facts that have not been reviewed. "
            "Confirm or edit all flagged fields before generating the dossier."
        )

    if blockers:
        working.append(f"Case gates BLOCKED: {blockers}")
    else:
        working.append("All case gates passed.")

    return ScoreResult(
        invoice_scores=invoice_scores,
        case_score=case_score,
        blockers=blockers,
        working=working,
    )
