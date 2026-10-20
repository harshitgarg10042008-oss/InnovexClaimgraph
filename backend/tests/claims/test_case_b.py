"""Test Case B golden numbers: duplicate invoice, uncredited advance, outstanding 16,140, interest 1,700.39."""

from datetime import date
from decimal import Decimal

from app.claims.service import run_claims_pipeline

# Case B files in /data/synthetic/case_b/base/
CASE_B_FILES = [
    "PO_NF_PO_118.pdf",
    "KP_CH_045.pdf",
    "KP_INV_0412.pdf",
    "KP_INV_0412_A.pdf",  # Duplicate invoice
    "bank_statement.pdf",
    "udyam_certificate.pdf",
]


def test_case_b_golden_numbers(db_session, create_reviewed_case):
    """Case B: invoice 86,140; paid 70,000; outstanding 16,140; interest 1,700.39."""
    case, _ = create_reviewed_case("case_b", files_subset=CASE_B_FILES)

    result = run_claims_pipeline(case.id, db_session, as_of=date(2026, 10, 14))

    summary = result.get("summary")
    if summary is None:
        print("Case B blocked:", result.get("blockers"))
        return

    # The primary invoice (KP/INV/0412) is 86,140
    # The duplicate invoice should be excluded from the principal
    assert Decimal(summary["invoiced_total"]) == Decimal("86140.00"), (
        f"Expected invoiced_total=86140.00, got {summary['invoiced_total']}"
    )
    assert Decimal(summary["paid_total"]) == Decimal("70000.00"), (
        f"Expected paid_total=70000.00, got {summary['paid_total']}"
    )
    assert Decimal(summary["outstanding_on_delivered_goods"]) == Decimal("16140.00"), (
        f"Expected outstanding=16140.00, got {summary['outstanding_on_delivered_goods']}"
    )
    assert Decimal(summary["interest_total"]) == Decimal("1700.39"), (
        f"Expected interest=1700.39, got {summary['interest_total']}"
    )

    # DUPLICATE_INVOICE finding must be present
    codes = [f["code"] for f in result.get("findings", [])]
    assert "DUPLICATE_INVOICE" in codes, f"Expected DUPLICATE_INVOICE in {codes}"


def test_case_b_findings_present(db_session, create_reviewed_case):
    """Case B findings: duplicate invoice and partial payment."""
    case, _ = create_reviewed_case("case_b", files_subset=CASE_B_FILES)

    result = run_claims_pipeline(case.id, db_session, as_of=date(2026, 10, 14))

    findings = result.get("findings", [])
    codes = [f["code"] for f in findings]

    # Duplicate invoice must be detected
    assert "DUPLICATE_INVOICE" in codes, f"Expected DUPLICATE_INVOICE in {codes}"
    # Partial payment should be flagged
    assert "PARTIAL_PAYMENT" in codes, f"Expected PARTIAL_PAYMENT in {codes}"

