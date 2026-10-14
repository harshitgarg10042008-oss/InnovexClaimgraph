import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.ingest.pipeline import process_document
from app.models.job import Job

logger = logging.getLogger("claimgraph.jobs.ingest")


def run_ingest_job(job_id: uuid.UUID, document_ids: list[uuid.UUID]) -> None:
    """Executes document ingestion as a background job and tracks progress in the jobs table."""
    db: Session = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error(f"Job {job_id} not found")
            return

        job.status = "processing"
        job.started_at = datetime.now(UTC)
        db.commit()

        for doc_id in document_ids:
            try:
                process_document(document_id=doc_id, db=db)
            except Exception as e:
                logger.error(f"Failed processing document {doc_id} in job {job_id}: {e}")

        job.status = "completed"
        job.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as e:
        logger.error(f"Job {job_id} failed with error: {e}")
        db.rollback()
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = "failed"
            job.error = str(e)
            job.finished_at = datetime.now(UTC)
            db.commit()
    finally:
        db.close()
