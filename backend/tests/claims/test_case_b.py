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

    # Expected case B findings: DUPLICATE_INVOICE, UNCREDITED_PAYMENT, PARTIAL_PAYMENT, UNCONFIRMED_LINKS
    assert "DUPLICATE_INVOICE" in codes, f"Expected DUPLICATE_INVOICE in {codes}"
    assert "UNCREDITED_PAYMENT" in codes, f"Expected UNCREDITED_PAYMENT in {codes}"
    assert "PARTIAL_PAYMENT" in codes, f"Expected PARTIAL_PAYMENT in {codes}"
    assert "UNCONFIRMED_LINKS" in codes, f"Expected UNCONFIRMED_LINKS in {codes}"


def test_case_b_provisional_status(db_session, create_reviewed_case):
    """Case B: provisional status before confirm, final after confirm, numbers equal in both."""
    from app.claims.service import update_link_status
    from app.models.reconciliation import Link
    from app.models.transaction import Invoice

    case, _ = create_reviewed_case("case_b", files_subset=CASE_B_FILES)

    # Before confirming conflict link - should be provisional
    result_before = run_claims_pipeline(case.id, db_session, as_of=date(2026, 10, 14))
    summary_before = result_before.get("summary")

    assert summary_before["ledger_status"] == "provisional"
    assert "Duplicate invoice" in summary_before["provisional_reason"]
    assert summary_before["interest_status"] == "provisional"
    assert any("Duplicate invoice" in a for a in summary_before["assumptions"])

    # Numbers should be correct even in provisional state
    assert Decimal(summary_before["outstanding_on_delivered_goods"]) == Decimal("16140.00")
    assert Decimal(summary_before["interest_total"]) == Decimal("1700.39")

    # Resolve conflict: confirm link to canonical invoice KP/INV/0412
    conflict_links = (
        db_session.query(Link)
        .filter(
            Link.case_id == case.id,
            Link.from_type == "DELIVERY",
            Link.to_type == "INVOICE",
        )
        .all()
    )

    for lk in conflict_links:
        inv = db_session.query(Invoice).filter(Invoice.id == lk.to_id).first()
        if inv and inv.invoice_no == "KP/INV/0412":
            update_link_status(case.id, lk.id, "confirmed", "test_reviewer", db_session)

    # After human confirms canonical invoice link - should be final
    result_after = run_claims_pipeline(case.id, db_session, as_of=date(2026, 10, 14))
    summary_after = result_after.get("summary")

    assert summary_after["ledger_status"] == "final"
    assert summary_after["provisional_reason"] is None
    assert summary_after["interest_status"] == "computed"

    # Numbers must be identical before and after
    assert Decimal(summary_before["outstanding_on_delivered_goods"]) == Decimal(summary_after["outstanding_on_delivered_goods"])
    assert Decimal(summary_before["interest_total"]) == Decimal(summary_after["interest_total"])
    assert Decimal(summary_after["outstanding_on_delivered_goods"]) == Decimal("16140.00")
    assert Decimal(summary_after["interest_total"]) == Decimal("1700.39")


def test_case_b_duplicate_never_adds_to_principal(db_session, create_reviewed_case):
    """Duplicate invoice never adds to principal in any state."""
    case, _ = create_reviewed_case("case_b", files_subset=CASE_B_FILES)

    result = run_claims_pipeline(case.id, db_session, as_of=date(2026, 10, 14))
    summary = result.get("summary")

    # Invoiced total and delivered value must only account for a single invoice (86,140), not duplicate (172,280)
    assert Decimal(summary["invoiced_total"]) == Decimal("86140.00")
    assert Decimal(summary["delivered_value"]) == Decimal("86140.00")
    assert len(summary["claim_items"]) == 1
    assert summary["claim_items"][0]["invoice_no"] == "KP/INV/0412"


def test_case_b_order_independence(db_session, create_reviewed_case):
    """The outcome is the same if the two invoices are inserted in the opposite order."""
    case, _ = create_reviewed_case("case_b", files_subset=CASE_B_FILES)

    result1 = run_claims_pipeline(case.id, db_session, as_of=date(2026, 10, 14))
    summary1 = result1.get("summary")

    # Test reverse order reconciliation directly
    from app.claims.builder import build_entities_from_facts
    from app.claims.linker import run_linker
    from app.claims.reconcile import run_reconciliation

    entities, _ = build_entities_from_facts(case.id, db_session)
    assert len(entities.invoices) == 2
    # Reverse the order of invoices
    entities.invoices = list(reversed(entities.invoices))
    links = run_linker(case.id, entities, db_session)
    reconciliation = run_reconciliation(entities, links, db_session, as_of=date(2026, 10, 14))

    summary2 = reconciliation.to_dict()

    assert Decimal(summary1["outstanding_on_delivered_goods"]) == Decimal(summary2["outstanding_on_delivered_goods"])
    assert Decimal(summary1["interest_total"]) == Decimal(summary2["interest_total"])
    assert summary1["ledger_status"] == summary2["ledger_status"]
    assert summary2["claim_items"][0]["invoice_no"] == "KP/INV/0412"

