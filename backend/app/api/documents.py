import hashlib
import json
import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.jobs.ingest import run_ingest_job
from app.models.case import Case
from app.models.document import Document, Page
from app.models.job import Job
from app.schemas.document import (
    DocumentResponse,
    DocumentUploadResponse,
    PageDetailResponse,
    WordBoxSchema,
)
from app.schemas.job import JobResponse

router = APIRouter(tags=["documents"])


@router.post("/cases/{id}/documents", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
def upload_case_documents(
    id: uuid.UUID,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> DocumentUploadResponse:
    """Uploads one or more documents for a case, computes SHA-256, stores files, and queues ingestion."""
    case_obj = db.query(Case).filter(Case.id == id).first()
    if not case_obj:
        raise HTTPException(status_code=404, detail=f"Case {id} not found")

    created_docs: list[Document] = []
    storage_base = Path(settings.STORAGE_DIR).resolve()

    for upload_file in files:
        file_bytes = upload_file.file.read()
        sha256_hash = hashlib.sha256(file_bytes).hexdigest()

        doc_id = uuid.uuid4()
        dest_filename = f"{doc_id}_{upload_file.filename}"
        rel_storage_path = f"raw_documents/{dest_filename}"
        full_dest_path = storage_base / rel_storage_path
        full_dest_path.parent.mkdir(parents=True, exist_ok=True)

        with open(full_dest_path, "wb") as f:
            f.write(file_bytes)

        db_doc = Document(
            id=doc_id,
            case_id=id,
            kind="OTHER",  # Will be classified during ingestion
            filename=upload_file.filename or "uploaded_file",
            sha256=sha256_hash,
            storage_path=rel_storage_path,
            pages=1,
            status="stored",
        )
        db.add(db_doc)
        created_docs.append(db_doc)

    # Create background job
    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        case_id=id,
        kind="document_ingest",
        status="pending",
    )
    db.add(job)
    db.commit()

    for doc in created_docs:
        db.refresh(doc)

    background_tasks.add_task(
        run_ingest_job, job_id, [d.id for d in created_docs]
    )

    return DocumentUploadResponse(
        job_id=job_id,
        documents=[DocumentResponse.model_validate(d) for d in created_docs],
    )


@router.get("/cases/{id}/documents", response_model=list[DocumentResponse])
def list_case_documents(
    id: uuid.UUID,
    db: Session = Depends(get_db),
) -> list[DocumentResponse]:
    """Lists all documents belonging to a case with their current kind and processing status."""
    case_obj = db.query(Case).filter(Case.id == id).first()
    if not case_obj:
        raise HTTPException(status_code=404, detail=f"Case {id} not found")

    docs = (
        db.query(Document)
        .filter(Document.case_id == id)
        .order_by(Document.uploaded_at.desc())
        .all()
    )
    return [DocumentResponse.model_validate(d) for d in docs]


@router.post("/documents/{id}/process", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def reprocess_document(
    id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> JobResponse:
    """Re-runs reading, classification, extraction and validation on an already stored document."""
    doc = db.query(Document).filter(Document.id == id).first()
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {id} not found")

    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        case_id=doc.case_id,
        kind="single_document_ingest",
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(run_ingest_job, job_id, [doc.id])
    return JobResponse.model_validate(job)


@router.post("/cases/{id}/process", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def reprocess_case_documents(
    id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> JobResponse:
    """Re-runs ingestion for all documents belonging to a case."""
    case_obj = db.query(Case).filter(Case.id == id).first()
    if not case_obj:
        raise HTTPException(status_code=404, detail=f"Case {id} not found")

    docs = db.query(Document).filter(Document.case_id == id).all()
    if not docs:
        raise HTTPException(status_code=400, detail="Case has no documents to process")

    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        case_id=id,
        kind="case_documents_ingest",
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(run_ingest_job, job_id, [d.id for d in docs])
    return JobResponse.model_validate(job)


@router.get("/documents/{id}/pages/{page_no}", response_model=PageDetailResponse)
def get_document_page(
    id: uuid.UUID,
    page_no: int,
    db: Session = Depends(get_db),
) -> PageDetailResponse:
    """Returns page text, word boxes with normalized coordinates, and image URL."""
    doc = db.query(Document).filter(Document.id == id).first()
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {id} not found")

    page = (
        db.query(Page)
        .filter(Page.document_id == id, Page.page_no == page_no)
        .first()
    )
    if not page:
        raise HTTPException(
            status_code=404,
            detail=f"Page {page_no} not found for document {id}",
        )

    # Load word boxes JSON from storage
    storage_base = Path(settings.STORAGE_DIR).resolve()
    boxes_path = storage_base / f"pages/{id}/page_{page_no}_boxes.json"
    word_boxes: list[WordBoxSchema] = []
    if boxes_path.exists():
        try:
            with open(boxes_path, encoding="utf-8") as f:
                raw_boxes = json.load(f)
                word_boxes = [WordBoxSchema(**wb) for wb in raw_boxes]
        except Exception:
            pass

    return PageDetailResponse(
        document_id=id,
        page_no=page_no,
        text=page.text,
        image_url=f"/documents/{id}/pages/{page_no}/image",
        ocr_engine=page.ocr_engine,
        words=word_boxes,
    )


@router.head("/documents/{id}/pages/{page_no}/image")
@router.get("/documents/{id}/pages/{page_no}/image")
def get_document_page_image(
    id: uuid.UUID,
    page_no: int,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Serves the rendered 150 DPI page image as PNG."""
    storage_base = Path(settings.STORAGE_DIR).resolve()
    img_path = storage_base / f"pages/{id}/page_{page_no}.png"
    if not img_path.exists():
        raise HTTPException(status_code=404, detail="Page image not found")
    return FileResponse(img_path, media_type="image/png")
