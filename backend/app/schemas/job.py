import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    kind: str
    status: str
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
