import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.party import PartyRead


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
