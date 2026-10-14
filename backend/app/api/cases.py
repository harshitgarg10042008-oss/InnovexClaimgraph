import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.db import get_db
from app.models.case import Case
from app.schemas.case import CaseRead

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("", response_model=list[CaseRead])
def list_cases(db: Session = Depends(get_db)) -> list[Case]:
    stmt = (
        select(Case)
        .options(joinedload(Case.supplier), joinedload(Case.buyer))
        .order_by(Case.created_at.desc())
    )
    return list(db.scalars(stmt).all())


@router.get("/{id}", response_model=CaseRead)
def get_case(id: uuid.UUID, db: Session = Depends(get_db)) -> Case:
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
    return case_obj
