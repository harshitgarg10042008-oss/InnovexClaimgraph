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
    value_json: dict
    bbox: list[float] | None = None
    confidence: Decimal | None = None
    status: str
    extractor_version: str | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    created_at: datetime
