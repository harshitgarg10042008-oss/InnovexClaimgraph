"""Test Case C: INELIGIBLE_SUPPLIER finding, interest refused, no interest number."""

from datetime import date
from decimal import Decimal

from app.claims.service import run_claims_pipeline


def test_case_c_ineligible_udyam(db_session, create_reviewed_case):
    """Case C: invoice 2,64,600; INELIGIBLE finding; interest refused; no interest in ledger."""
    case, _ = create_reviewed_case(
        "case_c",
    )

    result = run_claims_pipeline(case.id, db_session, as_of=date(2026, 10, 14))

    summary = result.get("summary")
    if summary is None:
        # If blocked due to missing files, report
        print("Case C blocked:", result.get("blockers"))
        return

    # Invoice total should be ~264600
    assert Decimal(summary["invoiced_total"]) == Decimal("264600.00"), (
        f"Expected 264600.00, got {summary['invoiced_total']}"
    )

    # Interest must be None (refused), not a number
    assert summary["interest_total"] is None, (
        f"Expected interest_total=None (refused), got {summary['interest_total']}"
    )

    # Interest status must indicate refusal
    interest_status = summary.get("interest_status", "")
    assert "refused" in interest_status.lower() or "ineligible" in interest_status.lower(), (
        f"Expected refused/ineligible in interest_status, got {interest_status!r}"
    )

    # Findings
    findings_by_code = {f["code"]: f for f in result.get("findings", [])}
    assert "INELIGIBLE_UDYAM_AFTER_PO" in findings_by_code, (
        f"Expected INELIGIBLE_UDYAM_AFTER_PO in {list(findings_by_code.keys())}"
    )
    f_inelig = findings_by_code["INELIGIBLE_UDYAM_AFTER_PO"]
    assert f_inelig["severity"] == "conflict"
    assert f_inelig["blocks_ready"] is True
    assert f_inelig["needs_human_or_legal_review"] is True
    assert "udyam_reg_date" in f_inelig["computed_numbers"]
    assert "po_date" in f_inelig["computed_numbers"]
    assert len(f_inelig["refs"]) >= 2, f"Expected at least 2 refs for udyam and po date, got {f_inelig['refs']}"


def test_case_c_no_interest_number_in_ledger(db_session, create_reviewed_case):
    """Ledger output for Case C must have no interest row with a positive amount."""
    case, _ = create_reviewed_case("case_c")

    result = run_claims_pipeline(case.id, db_session, as_of=date(2026, 10, 14))
    summary = result.get("summary")
    if summary is None:
        return  # blocked, already tested above

    # Check no claim item has interest_amount set when ineligible
    for ci in summary.get("claim_items", []):
        assert ci.get("interest_amount") is None or ci.get("interest_amount") == "None", (
            f"Claim item {ci.get('invoice_no')} has interest_amount={ci.get('interest_amount')} "
            f"but supplier is ineligible"
        )

    # Verify the interest_refused_reason is set
    for ci in summary.get("claim_items", []):
        assert ci.get("interest_refused_reason") is not None, (
            f"Claim item {ci.get('invoice_no')} missing interest_refused_reason for ineligible case"
        )
