import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.case import Case
from app.models.fact import Fact
from app.schemas.fact import FactResponse

router = APIRouter(tags=["facts"])


@router.get("/cases/{id}/facts", response_model=list[FactResponse])
def get_case_facts(
    id: uuid.UUID,
    status: str | None = Query(None, description="Filter by status (auto, needs_review, confirmed, edited)"),
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
    return [FactResponse.model_validate(f) for f in facts]
