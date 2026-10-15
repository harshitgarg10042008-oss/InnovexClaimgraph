import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.db import get_db
from app.ingest.extract import REQUIRED_FIELDS_BY_KIND
from app.models.audit import AuditLog
from app.models.case import Case
from app.models.document import Document
from app.models.fact import Fact
from app.models.party import Party
from app.schemas.case import CaseCreate, CaseRead, ReviewSummary

router = APIRouter(prefix="/cases", tags=["cases"])


@router.post("", response_model=CaseRead, status_code=status.HTTP_201_CREATED)
def create_case(request: CaseCreate, db: Session = Depends(get_db)) -> Case:
    """Create a new case with supplier and buyer parties."""
    # Create supplier party
    supplier = Party(
        name=request.supplier.name,
        gstin=request.supplier.gstin,
        pan=request.supplier.pan,
        udyam_no=request.supplier.udyam_no,
        udyam_reg_date=request.supplier.udyam_reg_date,
        enterprise_type=request.supplier.enterprise_type,
        activity=request.supplier.activity,
        role="supplier",
    )
    db.add(supplier)
    db.flush()

    # Create buyer party
    buyer = Party(
        name=request.buyer.name,
        gstin=request.buyer.gstin,
        pan=request.buyer.pan,
        udyam_no=request.buyer.udyam_no,
        udyam_reg_date=request.buyer.udyam_reg_date,
        enterprise_type=request.buyer.enterprise_type,
        activity=request.buyer.activity,
        role="buyer",
    )
    db.add(buyer)
    db.flush()

    # Create case
    case = Case(
        title=request.title,
        supplier_id=supplier.id,
        buyer_id=buyer.id,
        status="draft",
    )
    db.add(case)
    db.commit()
    db.refresh(case)

    # Load relationships for response
    case = db.get(Case, case.id)
    return case


@router.get("", response_model=list[CaseRead])
def list_cases(db: Session = Depends(get_db)) -> list[Case]:
    """List all cases with document and review counts."""
    stmt = (
        select(Case)
        .options(joinedload(Case.supplier), joinedload(Case.buyer))
        .order_by(Case.created_at.desc())
    )
    cases = list(db.scalars(stmt).all())

    # Enrich with counts
    for case in cases:
        doc_count = db.query(func.count(Document.id)).filter(Document.case_id == case.id).scalar() or 0
        needs_review = db.query(func.count(Fact.id)).filter(
            Fact.case_id == case.id,
            Fact.status == "needs_review"
        ).scalar() or 0
        case.documents_count = doc_count
        case.needs_review_count = needs_review

    return cases


@router.get("/{id}", response_model=CaseRead)
def get_case(id: uuid.UUID, db: Session = Depends(get_db)) -> Case:
    """Get a case by ID."""
    stmt = (
        select(Case)
        .options(joinedload(Case.supplier), joinedload(Case.buyer))
        .where(Case.id == id)
    )
    case_obj = db.scalars(stmt).first()
    if not case_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case with id {id} not found",
        )

    # Enrich with counts
    doc_count = db.query(func.count(Document.id)).filter(Document.case_id == id).scalar() or 0
    needs_review = db.query(func.count(Fact.id)).filter(
        Fact.case_id == id,
        Fact.status == "needs_review"
    ).scalar() or 0
    case_obj.documents_count = doc_count
    case_obj.needs_review_count = needs_review

    return case_obj


@router.get("/{id}/review-summary", response_model=ReviewSummary)
def get_review_summary(id: uuid.UUID, db: Session = Depends(get_db)) -> ReviewSummary:
    """Get review summary for a case."""
    # Check case exists
    case = db.get(Case, id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Overall status counts
    status_counts = {}
    for stat in ["auto", "needs_review", "confirmed", "edited", "not_present"]:
        count = db.query(func.count(Fact.id)).filter(
            Fact.case_id == id,
            Fact.status == stat
        ).scalar() or 0
        status_counts[stat] = count

    # Per-document status counts
    documents = db.query(Document).filter(Document.case_id == id).all()
    document_status_counts = {}
    for doc in documents:
        doc_counts = {}
        for stat in ["auto", "needs_review", "confirmed", "edited", "not_present"]:
            count = db.query(func.count(Fact.id)).filter(
                Fact.document_id == doc.id,
                Fact.status == stat
            ).scalar() or 0
            doc_counts[stat] = count
        document_status_counts[str(doc.id)] = doc_counts

    # Count required fields still needing review
    required_needs_review = 0
    for doc in documents:
        required_fields = REQUIRED_FIELDS_BY_KIND.get(doc.kind, [])
        for req_field in required_fields:
            count = db.query(func.count(Fact.id)).filter(
                Fact.document_id == doc.id,
                Fact.field == req_field,
                Fact.status == "needs_review"
            ).scalar() or 0
            required_needs_review += count

    # Ready for linking: no required field is needs_review
    ready_for_linking = required_needs_review == 0

    return ReviewSummary(
        status_counts=status_counts,
        document_status_counts=document_status_counts,
        required_fields_needing_review=required_needs_review,
        ready_for_linking=ready_for_linking,
    )


@router.get("/{id}/audit-log")
def get_audit_log(
    id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    cursor: datetime | None = None,
    db: Session = Depends(get_db),
):
    """Get audit log for a case, newest first with cursor pagination."""
    # Check case exists
    case = db.get(Case, id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    query = db.query(AuditLog).filter(AuditLog.case_id == id)

    if cursor:
        query = query.filter(AuditLog.at < cursor)

    query = query.order_by(AuditLog.at.desc()).limit(limit)

    logs = query.all()

    # Convert to dict for JSON response
    return [
        {
            "id": str(log.id),
            "actor": log.actor,
            "action": log.action,
            "target": log.target,
            "before_json": log.before_json,
            "after_json": log.after_json,
            "at": log.at.isoformat(),
        }
        for log in logs
    ]
