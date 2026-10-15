import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.ingest.validate import (
    normalize_date,
    normalize_indian_number,
    validate_gstin,
)
from app.models.audit import AuditLog
from app.models.case import Case
from app.models.fact import Fact
from app.schemas.fact import BulkConfirmResponse, FactResponse, FactUpdateRequest

router = APIRouter(tags=["facts"])


# Field label map for human-readable display
FIELD_LABEL_MAP = {
    # PO fields
    "po_no": "PO number",
    "po_date": "PO date",
    "buyer_name": "Buyer name",
    "supplier_name": "Supplier name",
    "buyer_gstin": "Buyer GSTIN",
    "supplier_gstin": "Supplier GSTIN",
    "payment_terms_text": "Payment terms",
    "credit_days": "Credit days",
    "taxable_total": "Taxable total",
    "grand_total": "Grand total",
    # Challan fields
    "challan_no": "Challan number",
    "challan_date": "Challan date",
    "po_ref": "PO reference",
    "dispatched_qty": "Quantity dispatched",
    "accepted_qty": "Quantity accepted",
    "rejected_qty": "Quantity rejected",
    "received_by": "Received by",
    "rejection_reason": "Rejection reason",
    "stamp_text": "Stamp text",
    "stamp_date": "Stamp date",
    # Invoice fields
    "invoice_no": "Invoice number",
    "invoice_date": "Invoice date",
    "challan_ref": "Challan reference",
    "gst_amount": "GST amount",
    # Bank statement
    "account_holder": "Account holder",
    "period_from": "Period from",
    "period_to": "Period to",
    # Payment
    "utr": "UTR",
    "pay_date": "Payment date",
    "amount": "Amount",
    # Udyam
    "udyam_no": "Udyam number",
    "enterprise_name": "Enterprise name",
    "enterprise_type": "Enterprise type",
    "activity": "Activity",
    "registration_date": "Registration date",
}

# Field group map
FIELD_GROUP_MAP = {
    "po_no": "Header",
    "po_date": "Header",
    "buyer_name": "Header",
    "supplier_name": "Header",
    "buyer_gstin": "Header",
    "supplier_gstin": "Header",
    "payment_terms_text": "Header",
    "credit_days": "Header",
    "taxable_total": "Header",
    "grand_total": "Header",
    "challan_no": "Header",
    "challan_date": "Header",
    "po_ref": "Header",
    "invoice_no": "Header",
    "invoice_date": "Header",
    "qty": "Line 1",
    "rate": "Line 1",
    "amount": "Line 1",
    "description": "Line 1",
    "hsn": "Line 1",
}


def _humanise_field(field_path: str) -> str:
    """Convert field path to human-readable label."""
    # Extract base field name (remove lines[X]. prefix)
    base_field = field_path.split(".")[-1] if "." in field_path else field_path
    return FIELD_LABEL_MAP.get(base_field, base_field.replace("_", " ").title())


def _get_field_group(field_path: str) -> str:
    """Get group for a field."""
    base_field = field_path.split(".")[-1] if "." in field_path else field_path
    return FIELD_GROUP_MAP.get(base_field, "Other")


def _get_review_reason(fact: Fact) -> str | None:
    """Generate plain-language reason for needs_review status."""
    if fact.status != "needs_review":
        return None

    # Check confidence
    if fact.confidence and fact.confidence < 0.85:
        return "Low extraction confidence"

    # Check if value is null (missing field)
    if fact.value_json is None or (isinstance(fact.value_json, dict) and not fact.value_json.get("value")):
        return "Value not found on the page"

    return "Manual review required"


@router.get("/cases/{id}/facts", response_model=list[FactResponse])
def get_case_facts(
    id: uuid.UUID,
    status: str | None = Query(None, description="Filter by status (auto, needs_review, confirmed, edited, not_present)"),
    document_id: uuid.UUID | None = Query(None, description="Filter by document id"),
    db: Session = Depends(get_db),
) -> list[FactResponse]:
    """Returns extracted facts for a case, optionally filtered by status and/or document ID."""
    case_obj = db.query(Case).filter(Case.id == id).first()
    if not case_obj:
        raise HTTPException(status_code=404, detail=f"Case {id} not found")

    query = db.query(Fact).filter(Fact.case_id == id)
    if status:
        query = query.filter(Fact.status == status)
    if document_id:
        query = query.filter(Fact.document_id == document_id)

    facts = query.order_by(Fact.created_at.asc(), Fact.page_no.asc()).all()

    # Enrich with UI fields
    responses = []
    for f in facts:
        response = FactResponse.model_validate(f)
        response.label = _humanise_field(f.field)
        response.group = _get_field_group(f.field)
        response.reason = _get_review_reason(f)
        responses.append(response)

    return responses


@router.patch("/facts/{id}", response_model=FactResponse)
def update_fact(
    id: uuid.UUID,
    request: FactUpdateRequest,
    x_reviewer: str = Header("Reviewer", alias="X-Reviewer"),
    db: Session = Depends(get_db),
) -> FactResponse:
    """Update a fact: confirm, edit, mark_not_present, or reopen."""
    fact = db.query(Fact).filter(Fact.id == id).first()
    if not fact:
        raise HTTPException(status_code=404, detail="Fact not found")

    # Capture before state for audit
    before_state = {
        "value_json": fact.value_json,
        "status": fact.status,
        "review_note": fact.review_note,
    }

    validation_warnings = []

    if request.action == "confirm":
        fact.status = "confirmed"
        fact.confirmed_by = x_reviewer
        fact.confirmed_at = datetime.utcnow()

    elif request.action == "edit":
        if request.value is None:
            raise HTTPException(status_code=400, detail="value required for edit action")
        # Store original value if not already stored
        if fact.original_value_json is None:
            fact.original_value_json = fact.value_json
        fact.value_json = request.value
        fact.status = "edited"
        fact.review_note = request.note
        fact.confirmed_by = x_reviewer
        fact.confirmed_at = datetime.utcnow()
        # Re-run validation
        norm_val, flags = _validate_field_value(fact.field, request.value)
        validation_warnings = flags

    elif request.action == "mark_not_present":
        fact.value_json = None
        fact.status = "not_present"
        fact.review_note = request.note
        fact.confirmed_by = x_reviewer
        fact.confirmed_at = datetime.utcnow()

    elif request.action == "reopen":
        fact.status = "needs_review"
        fact.review_note = request.note

    else:
        raise HTTPException(status_code=400, detail=f"Invalid action: {request.action}")

    # Capture after state for audit
    after_state = {
        "value_json": fact.value_json,
        "status": fact.status,
        "review_note": fact.review_note,
    }

    # Write audit log
    audit = AuditLog(
        case_id=fact.case_id,
        actor=x_reviewer,
        action=request.action,
        target=str(fact.id),
        before_json=before_state,
        after_json=after_state,
    )
    db.add(audit)
    db.commit()
    db.refresh(fact)

    # Enrich response
    response = FactResponse.model_validate(fact)
    response.label = _humanise_field(fact.field)
    response.group = _get_field_group(fact.field)
    response.reason = _get_review_reason(fact)

    # Add validation warnings to response if any
    if validation_warnings:
        response.model_extra = {"validation_warnings": validation_warnings}

    return response


@router.post("/documents/{id}/facts/confirm-auto", response_model=BulkConfirmResponse)
def bulk_confirm_auto_facts(
    id: uuid.UUID,
    x_reviewer: str = Header("Reviewer", alias="X-Reviewer"),
    db: Session = Depends(get_db),
) -> BulkConfirmResponse:
    """Bulk-confirm only facts with status='auto' for a document."""
    facts = db.query(Fact).filter(
        Fact.document_id == id,
        Fact.status == "auto"
    ).all()

    confirmed_count = 0
    for fact in facts:
        before_state = {"value_json": fact.value_json, "status": fact.status}
        fact.status = "confirmed"
        fact.confirmed_by = x_reviewer
        fact.confirmed_at = datetime.utcnow()
        after_state = {"value_json": fact.value_json, "status": fact.status}

        audit = AuditLog(
            case_id=fact.case_id,
            actor=x_reviewer,
            action="bulk_confirm",
            target=str(fact.id),
            before_json=before_state,
            after_json=after_state,
        )
        db.add(audit)
        confirmed_count += 1

    db.commit()
    return BulkConfirmResponse(confirmed_count=confirmed_count)


def _validate_field_value(field_path: str, value: dict) -> tuple[dict, list[str]]:
    """Re-run validation on an edited value."""
    flags = []
    norm_val = value

    field_lower = field_path.lower()

    # Date validation
    if any(k in field_lower for k in ("date", "period_from", "period_to")):
        raw_val = value.get("value") if isinstance(value, dict) else value
        norm_date, d_flags = normalize_date(raw_val)
        flags.extend(d_flags)
        norm_val = norm_date

    # GSTIN validation
    elif "gstin" in field_lower:
        raw_val = value.get("value") if isinstance(value, dict) else value
        norm_gstin, g_flags = validate_gstin(raw_val)
        flags.extend(g_flags)
        norm_val = norm_gstin

    # Number validation
    elif any(k in field_lower for k in ("qty", "rate", "amount", "total", "gross", "net", "tds")):
        raw_val = value.get("value") if isinstance(value, dict) else value
        norm_num, n_flags = normalize_indian_number(raw_val)
        flags.extend(n_flags)
        norm_val = norm_num

    return norm_val, flags
