import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class PartyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    role: str
    gstin: str | None = None
    pan: str | None = None
    udyam_no: str | None = None
    udyam_reg_date: date | None = None
    enterprise_type: str | None = None
    activity: str | None = None
    created_at: datetime
