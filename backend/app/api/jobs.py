import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.job import Job
from app.schemas.job import JobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{id}", response_model=JobResponse)
def get_job_status(
    id: uuid.UUID,
    db: Session = Depends(get_db),
) -> JobResponse:
    """Returns the current execution status and errors (if any) of a background job."""
    job = db.query(Job).filter(Job.id == id).first()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {id} not found")
    return JobResponse.model_validate(job)
