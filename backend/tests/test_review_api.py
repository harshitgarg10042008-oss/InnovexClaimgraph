"""Tests for M4a Review API endpoints."""
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.audit import AuditLog
from app.models.case import Case
from app.models.document import Document
from app.models.fact import Fact
from app.models.party import Party
from app.schemas.case import CaseCreate

client = TestClient(app)


@pytest.fixture
def db_session():
    """Create a fresh database session for each test."""
    from app.core.db import SessionLocal, engine
    from app.models.base import Base

    # Create all tables
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()
        # Clean up audit logs for this test
        db = SessionLocal()
        db.query(AuditLog).delete()
        db.commit()
        db.close()


@pytest.fixture
def test_case(db_session):
    """Create a test case with facts."""
    # Create parties
    supplier = Party(
        name="Test Supplier",
        gstin="07AAAAA0000A1Z5",
        role="supplier",
    )
    db_session.add(supplier)
    db_session.flush()

    buyer = Party(
        name="Test Buyer",
        gstin="27BBBBB1111B1Z2",
        role="buyer",
    )
    db_session.add(buyer)
    db_session.flush()

    # Create case
    case = Case(
        title="Test Case",
        supplier_id=supplier.id,
        buyer_id=buyer.id,
        status="draft",
    )
    db_session.add(case)
    db_session.flush()

    # Create document
    doc = Document(
        id=uuid.uuid4(),
        case_id=case.id,
        kind="CHALLAN",
        filename="test.pdf",
        sha256="abc123",
        storage_path="raw_documents/test.pdf",
        pages=1,
        status="completed",
    )
    db_session.add(doc)
    db_session.flush()

    # Create facts
    fact1 = Fact(
        id=uuid.uuid4(),
        case_id=case.id,
        document_id=doc.id,
        page_no=1,
        field="challan_no",
        value_json={"value": "CH-118"},
        status="auto",
        confidence=0.95,
    )
    db_session.add(fact1)

    fact2 = Fact(
        id=uuid.uuid4(),
        case_id=case.id,
        document_id=doc.id,
        page_no=1,
        field="dispatched_qty",
        value_json={"value": "460"},
        status="needs_review",
        confidence=0.75,
    )
    db_session.add(fact2)

    fact3 = Fact(
        id=uuid.uuid4(),
        case_id=case.id,
        document_id=doc.id,
        page_no=1,
        field="challan_date",
        value_json={"value": "2026-04-20"},
        status="auto",
        confidence=0.95,
    )
    db_session.add(fact3)

    db_session.commit()
    db_session.refresh(case)

    return case, doc, [fact1, fact2, fact3]


class TestFactUpdate:
    def test_confirm_fact(self, db_session, test_case):
        case, doc, facts = test_case
        fact = facts[1]  # needs_review fact

        response = client.patch(
            f"/facts/{fact.id}",
            json={"action": "confirm"},
            headers={"X-Reviewer": "TestUser"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "confirmed"
        assert data["confirmed_by"] == "TestUser"
        assert data["confirmed_at"] is not None

        # Check audit log
        audit = db_session.query(AuditLog).filter(AuditLog.target == str(fact.id)).first()
        assert audit is not None
        assert audit.actor == "TestUser"
        assert audit.action == "confirm"

    def test_edit_fact_with_validation(self, db_session, test_case):
        case, doc, facts = test_case
        fact = facts[1]

        response = client.patch(
            f"/facts/{fact.id}",
            json={"action": "edit", "value": {"value": "500"}},
            headers={"X-Reviewer": "TestUser"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "edited"
        assert data["value_json"]["value"] == "500"
        assert data["original_value_json"]["value"] == "460"
        assert data["confirmed_by"] == "TestUser"

        # Check audit log
        audit = db_session.query(AuditLog).filter(AuditLog.target == str(fact.id)).first()
        assert audit is not None
        assert audit.action == "edit"
        assert audit.before_json["value_json"]["value"] == "460"
        assert audit.after_json["value_json"]["value"] == "500"

    def test_mark_not_present(self, db_session, test_case):
        case, doc, facts = test_case
        fact = facts[1]

        response = client.patch(
            f"/facts/{fact.id}",
            json={"action": "mark_not_present", "note": "Not on this page"},
            headers={"X-Reviewer": "TestUser"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "not_present"
        assert data["value_json"] is None
        assert data["review_note"] == "Not on this page"

    def test_reopen_fact(self, db_session, test_case):
        case, doc, facts = test_case
        fact = facts[0]  # auto fact

        # First confirm it
        fact.status = "confirmed"
        db_session.commit()

        response = client.patch(
            f"/facts/{fact.id}",
            json={"action": "reopen"},
            headers={"X-Reviewer": "TestUser"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "needs_review"

    def test_default_reviewer_header(self, db_session, test_case):
        case, doc, facts = test_case
        fact = facts[1]

        response = client.patch(
            f"/facts/{fact.id}",
            json={"action": "confirm"},
            # No X-Reviewer header
        )

        assert response.status_code == 200
        data = response.json()
        assert data["confirmed_by"] == "Reviewer"


class TestBulkConfirm:
    def test_bulk_confirm_auto_only(self, db_session, test_case):
        case, doc, facts = test_case

        response = client.post(
            f"/documents/{doc.id}/facts/confirm-auto",
            headers={"X-Reviewer": "TestUser"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["confirmed_count"] == 2  # Only auto facts, not needs_review

        # Verify needs_review fact was not touched
        db_session.refresh(facts[1])
        assert facts[1].status == "needs_review"

    def test_bulk_confirm_writes_audit(self, db_session, test_case):
        case, doc, facts = test_case

        # Clear previous audit logs for this case
        db_session.query(AuditLog).filter(AuditLog.case_id == case.id).delete()
        db_session.commit()

        client.post(
            f"/documents/{doc.id}/facts/confirm-auto",
            headers={"X-Reviewer": "TestUser"},
        )

        # Check audit logs were written
        audits = db_session.query(AuditLog).filter(
            AuditLog.case_id == case.id,
            AuditLog.action == "bulk_confirm"
        ).all()
        assert len(audits) == 2  # One per auto fact


class TestReviewSummary:
    def test_review_summary_counts(self, db_session, test_case):
        case, doc, facts = test_case

        response = client.get(f"/cases/{case.id}/review-summary")

        assert response.status_code == 200
        data = response.json()
        assert data["status_counts"]["auto"] == 2
        assert data["status_counts"]["needs_review"] == 1
        assert data["required_fields_needing_review"] >= 0
        assert "ready_for_linking" in data

    def test_document_status_counts(self, db_session, test_case):
        case, doc, facts = test_case

        response = client.get(f"/cases/{case.id}/review-summary")

        assert response.status_code == 200
        data = response.json()
        assert str(doc.id) in data["document_status_counts"]
        doc_counts = data["document_status_counts"][str(doc.id)]
        assert doc_counts["auto"] == 2
        assert doc_counts["needs_review"] == 1


class TestAuditLog:
    def test_audit_log_endpoint_exists(self, db_session, test_case):
        case, doc, facts = test_case

        response = client.get(f"/cases/{case.id}/audit-log")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_audit_log_limit_param(self, db_session, test_case):
        case, doc, facts = test_case

        response = client.get(f"/cases/{case.id}/audit-log?limit=10")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestCaseCreate:
    def test_create_case_with_parties(self, db_session):
        response = client.post(
            "/cases",
            json={
                "title": "New Test Case",
                "supplier": {
                    "name": "New Supplier",
                    "gstin": "07CCCCC0000C1Z5",
                    "enterprise_type": "micro",
                    "activity": "manufacturer",
                },
                "buyer": {
                    "name": "New Buyer",
                    "gstin": "27DDDDD1111D1Z2",
                },
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "New Test Case"
        assert data["supplier"]["name"] == "New Supplier"
        assert data["buyer"]["name"] == "New Buyer"

    def test_list_cases_with_counts(self, db_session, test_case):
        case, doc, facts = test_case

        response = client.get("/cases")

        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        case_data = next((c for c in data if c["id"] == str(case.id)), None)
        assert case_data is not None
        assert case_data["documents_count"] >= 1
        assert case_data["needs_review_count"] >= 1


class TestFactEnrichment:
    def test_fact_has_label_and_group(self, db_session, test_case):
        case, doc, facts = test_case

        response = client.get(f"/cases/{case.id}/facts")

        assert response.status_code == 200
        data = response.json()
        fact_data = next((f for f in data if f["field"] == "challan_no"), None)
        assert fact_data is not None
        assert fact_data["label"] == "Challan number"
        assert fact_data["group"] == "Header"

    def test_needs_review_fact_has_reason(self, db_session, test_case):
        case, doc, facts = test_case

        response = client.get(f"/cases/{case.id}/facts?status=needs_review")

        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        # At least one should have a reason
        has_reason = any(f.get("reason") for f in data)
        assert has_reason
