import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class FactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    document_id: uuid.UUID
    page_no: int
    field: str
    value_json: dict | None = None
    original_value_json: dict | None = None
    bbox: list[float] | None = None
    confidence: Decimal | None = None
    status: str
    review_note: str | None = None
    extractor_version: str | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    created_at: datetime
    # UI additions
    label: str | None = None
    group: str | None = None
    reason: str | None = None
    validation_warnings: list[str] | None = None


class FactUpdateRequest(BaseModel):
    action: str  # confirm | edit | mark_not_present | reopen
    value: dict | None = None
    note: str | None = None


class BulkConfirmResponse(BaseModel):
    confirmed_count: int
