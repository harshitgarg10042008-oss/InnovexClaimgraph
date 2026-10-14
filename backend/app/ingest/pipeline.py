import logging
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.storage import storage
from app.ingest.classify import classify_document
from app.ingest.extract import extract_document_facts, save_facts_to_db
from app.ingest.read import WordBox, read_document_pages
from app.models.document import Document, Page

logger = logging.getLogger("claimgraph.ingest.pipeline")


def process_document(document_id: uuid.UUID, db: Session) -> Document:
    """End-to-end ingestion pipeline for a stored document:

    1. Read (PyMuPDF / OCR) -> generates pages & word boxes
    2. Classify (deterministic rules -> LLM fallback) -> updates document.kind
    3. Extract & Validate -> writes facts with bounding boxes and confidence
    4. Sets final document status: ready or needs_review (or failed)
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise ValueError(f"Document with id {document_id} not found")

    file_path = storage.get_path(doc.storage_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Underlying storage file not found: {file_path}")

    storage_base = Path(settings.STORAGE_DIR).resolve()

    try:
        # Step 1: Read
        doc.status = "read"
        doc.error = None
        db.commit()

        # Delete old pages if reprocessing
        db.query(Page).filter(Page.document_id == doc.id).delete()
        db.commit()

        page_results = read_document_pages(
            file_path=file_path,
            document_id=str(doc.id),
            storage_base=storage_base,
        )

        for pr in page_results:
            db_page = Page(
                document_id=doc.id,
                page_no=pr.page_no,
                text=pr.text,
                image_path=pr.image_rel_path,
                ocr_engine=pr.ocr_engine,
            )
            db.add(db_page)

        doc.pages = len(page_results)
        db.commit()

        # Step 2: Classify
        doc.status = "classified"
        db.commit()

        full_doc_text = "\n\n".join(
            f"--- Page {pr.page_no} ---\n{pr.text}" for pr in page_results
        )

        is_scan = file_path.suffix.lower() in (".jpg", ".jpeg", ".png")
        effective_doc_hash = doc.sha256 if is_scan else None

        class_res = classify_document(full_doc_text, doc_hash=effective_doc_hash)
        doc.kind = class_res.kind
        db.commit()

        # Step 3: Extract & Validate
        doc.status = "extracted"
        db.commit()

        pages_words: dict[int, list[WordBox]] = {
            pr.page_no: pr.words for pr in page_results
        }

        page_image_paths = [storage_base / pr.image_rel_path for pr in page_results]
        extracted_facts = extract_document_facts(
            kind=doc.kind,
            full_text=full_doc_text,
            pages_words=pages_words,
            doc_hash=effective_doc_hash,
            page_count=len(page_results),
            page_images=page_image_paths,
        )

        db_facts = save_facts_to_db(
            db=db,
            case_id=doc.case_id,
            document_id=doc.id,
            facts=extracted_facts,
        )

        # Step 4: Final Status
        has_needs_review = any(f.status == "needs_review" for f in db_facts)
        doc.status = "needs_review" if has_needs_review else "ready"
        db.commit()
        db.refresh(doc)
        return doc

    except Exception as err:
        logger.error(f"Error processing document {document_id}: {err}", exc_info=True)
        db.rollback()
        doc.status = "failed"
        doc.error = str(err)
        db.commit()
        db.refresh(doc)
        raise err
