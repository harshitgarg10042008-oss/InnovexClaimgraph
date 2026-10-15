import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.party import PartyRead


class PartyCreate(BaseModel):
    name: str
    gstin: str | None = None
    pan: str | None = None
    udyam_no: str | None = None
    udyam_reg_date: str | None = None
    enterprise_type: str | None = None  # micro, small, medium
    activity: str | None = None  # manufacturer, service, trader


class CaseCreate(BaseModel):
    title: str
    supplier: PartyCreate
    buyer: PartyCreate


class CaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    supplier_id: uuid.UUID
    buyer_id: uuid.UUID
    status: str
    created_at: datetime
    updated_at: datetime
    supplier: PartyRead | None = None
    buyer: PartyRead | None = None
    documents_count: int = 0
    needs_review_count: int = 0


class ReviewSummary(BaseModel):
    status_counts: dict[str, int]  # auto, needs_review, confirmed, edited, not_present
    document_status_counts: dict[str, dict[str, int]]  # {doc_id: {status: count}}
    required_fields_needing_review: int
    ready_for_linking: bool
