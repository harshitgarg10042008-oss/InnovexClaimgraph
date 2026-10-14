from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.rule import RateTable
from app.schemas.rate_table import RateTableRead

router = APIRouter(prefix="/rate-table", tags=["rate-table"])


@router.get("", response_model=list[RateTableRead])
def get_rate_table(db: Session = Depends(get_db)) -> list[RateTable]:
    stmt = select(RateTable).order_by(RateTable.effective_from.desc())
    return list(db.scalars(stmt).all())
