from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    time: str
    db: str


@router.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    db_status = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    overall_status = "ok" if db_status == "ok" else "degraded"

    return HealthResponse(
        status=overall_status,
        service="claimgraph-api",
        version="0.1.0",
        time=datetime.now(UTC).isoformat(),
        db=db_status,
    )
