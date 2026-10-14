import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    kind: str
    filename: str
    sha256: str
    storage_path: str
    pages: int
    status: str
    error: str | None = None
    uploaded_at: datetime


class WordBoxSchema(BaseModel):
    text: str
    bbox: list[float]
    confidence: float


class PageDetailResponse(BaseModel):
    document_id: uuid.UUID
    page_no: int
    text: str | None = None
    image_url: str | None = None
    ocr_engine: str | None = None
    words: list[WordBoxSchema] = []


class DocumentUploadResponse(BaseModel):
    job_id: uuid.UUID
    documents: list[DocumentResponse]
