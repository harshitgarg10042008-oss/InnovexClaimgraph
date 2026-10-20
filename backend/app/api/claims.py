"""Claims API endpoints for ClaimGraph M5."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.claims.service import (
    get_case_findings,
    get_case_graph,
    get_case_ledger,
    run_claims_pipeline,
    update_link_status,
)
from app.core.db import get_db
from app.models.case import Case
from app.schemas.claims import (
    FindingsResponse,
    GraphResponse,
    LedgerResponse,
    LinkResponse,
    LinkRunResponse,
)

router = APIRouter(tags=["claims"])


@router.post("/cases/{id}/link/run", response_model=LinkRunResponse)
def run_case_pipeline(
    id: uuid.UUID,
    as_of: date = Query(default=date(2026, 10, 14), description="Evaluation as-of date"),
    x_reviewer: str = Header("system", alias="X-Reviewer"),
    db: Session = Depends(get_db),
) -> LinkRunResponse:
    """Execute M5 build + link + reconcile + findings pipeline."""
    case = db.query(Case).filter(Case.id == id).first()
    if not case:
        raise HTTPException(status_code=404, detail=f"Case {id} not found")

    result = run_claims_pipeline(case_id=id, db=db, as_of=as_of, actor=x_reviewer)
    return LinkRunResponse.model_validate(result)


@router.get("/cases/{id}/graph", response_model=GraphResponse)
def get_graph(
    id: uuid.UUID,
    db: Session = Depends(get_db),
) -> GraphResponse:
    """Retrieve nodes and edges for @xyflow/react graph visualization."""
    case = db.query(Case).filter(Case.id == id).first()
    if not case:
        raise HTTPException(status_code=404, detail=f"Case {id} not found")

    result = get_case_graph(case_id=id, db=db)
    return GraphResponse.model_validate(result)


@router.get("/cases/{id}/ledger", response_model=LedgerResponse)
def get_ledger(
    id: uuid.UUID,
    db: Session = Depends(get_db),
) -> LedgerResponse:
    """Retrieve ledger rows, claim items, allocations, and totals."""
    case = db.query(Case).filter(Case.id == id).first()
    if not case:
        raise HTTPException(status_code=404, detail=f"Case {id} not found")

    result = get_case_ledger(case_id=id, db=db)
    return LedgerResponse.model_validate(result)


@router.get("/cases/{id}/findings", response_model=FindingsResponse)
def get_findings(
    id: uuid.UUID,
    db: Session = Depends(get_db),
) -> FindingsResponse:
    """Retrieve discrepancy detector findings with stale flag."""
    case = db.query(Case).filter(Case.id == id).first()
    if not case:
        raise HTTPException(status_code=404, detail=f"Case {id} not found")

    result = get_case_findings(case_id=id, db=db)
    return FindingsResponse.model_validate(result)


@router.post("/cases/{id}/links/{link_id}/confirm", response_model=LinkResponse)
def confirm_link(
    id: uuid.UUID,
    link_id: uuid.UUID,
    x_reviewer: str = Header("reviewer", alias="X-Reviewer"),
    db: Session = Depends(get_db),
) -> LinkResponse:
    """Confirm a proposed link and record audit log."""
    try:
        updated = update_link_status(
            case_id=id,
            link_id=link_id,
            new_status="confirmed",
            actor=x_reviewer,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return LinkResponse.model_validate(updated)


@router.post("/cases/{id}/links/{link_id}/reject", response_model=LinkResponse)
def reject_link(
    id: uuid.UUID,
    link_id: uuid.UUID,
    x_reviewer: str = Header("reviewer", alias="X-Reviewer"),
    db: Session = Depends(get_db),
) -> LinkResponse:
    """Reject a proposed link and record audit log."""
    try:
        updated = update_link_status(
            case_id=id,
            link_id=link_id,
            new_status="rejected",
            actor=x_reviewer,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return LinkResponse.model_validate(updated)
