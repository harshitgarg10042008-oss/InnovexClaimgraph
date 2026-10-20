"""Test Case A golden numbers and pipeline."""

from datetime import date
from decimal import Decimal

from app.api.facts import bulk_confirm_auto_facts, update_fact
from app.claims.service import run_claims_pipeline
from app.core.storage import storage
from app.ingest.pipeline import process_document
from app.models.document import Document
from app.models.fact import Fact
from app.schemas.fact import FactUpdateRequest
from tests.claims.conftest import get_synthetic_dir


def test_case_a_base_golden_numbers(db_session, create_reviewed_case):
    """Case A base: due 2026-06-04; delivered value 4,45,096; outstanding 2,45,096; interest 17,349.26."""
    case, _ = create_reviewed_case(
        "case_a",
        files_subset=[
            "PO_MM_PO_2291.pdf",
            "CH_118.pdf",
            "INV_7731.pdf",
            "bank_statement.pdf",
            "remittance_advice.pdf",
            "udyam_certificate.pdf",
        ],
    )

    result = run_claims_pipeline(case.id, db_session, as_of=date(2026, 10, 14))

    assert result["status"] == "ready"
    assert result["blockers"] == []
    summary = result["summary"]

    assert Decimal(summary["invoiced_total"]) == Decimal("483800.00")
    assert Decimal(summary["delivered_value"]) == Decimal("445096.00")
    assert Decimal(summary["outstanding_on_delivered_goods"]) == Decimal("245096.00")
    assert Decimal(summary["outstanding_on_full_invoice"]) == Decimal("283800.00")
    assert Decimal(summary["paid_total"]) == Decimal("198000.00")
    assert Decimal(summary["adjustments_total"]) == Decimal("2000.00")
    assert Decimal(summary["interest_total"]) == Decimal("17349.26")
    assert summary["due_date"] == "2026-06-04"

    # Findings
    codes = [f["code"] for f in result["findings"]]
    assert "QTY_MISMATCH" in codes
    assert "TDS_DEDUCTION" in codes


def test_case_a_with_backorder_and_ch131(db_session, create_reviewed_case):
    """Case A with email and later delivery CH-131 evidences covering backorder."""
    case, _ = create_reviewed_case(
        "case_a",
        files_subset=[
            "PO_MM_PO_2291.pdf",
            "CH_118.pdf",
            "INV_7731.pdf",
            "bank_statement.pdf",
            "remittance_advice.pdf",
            "udyam_certificate.pdf",
        ],
    )

    # Ingest email and CH-131 from addons
    synth = get_synthetic_dir()
    addons = [
        synth / "case_a/addons/01_backorder_email.pdf",
        synth / "case_a/addons/02_challan_ch131.pdf",
    ]
    for p in addons:
        rel = f"test_case_a_addons/{p.name}"
        storage.put(p, rel)
        d = Document(
            case_id=case.id,
            kind="OTHER",
            filename=p.name,
            sha256="fake",
            storage_path=rel,
            pages=1,
            status="stored",
        )
        db_session.add(d)
        db_session.flush()
        process_document(d.id, db_session)
        bulk_confirm_auto_facts(d.id, x_reviewer="test_reviewer", db=db_session)

    # Confirm any needs review facts
    needs = db_session.query(Fact).filter(Fact.case_id == case.id, Fact.status == "needs_review").all()
    for f in needs:
        update_fact(f.id, FactUpdateRequest(action="confirm"), x_reviewer="test_reviewer", db=db_session)

    result = run_claims_pipeline(case.id, db_session, as_of=date(2026, 10, 14))

    codes = [f["code"] for f in result["findings"]]
    assert "BACKORDER_PENDING" in codes

    # With CH-131 covering remaining 40 units, all 500 units are delivered!
    summary = result["summary"]
    assert Decimal(summary["delivered_value"]) == Decimal("483800.00")
    assert Decimal(summary["outstanding_on_delivered_goods"]) == Decimal("283800.00")
