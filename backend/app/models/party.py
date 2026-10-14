import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Party(Base):
    __tablename__ = "parties"
    __table_args__ = (
        CheckConstraint("role IN ('supplier', 'buyer')", name="ck_parties_role"),
        CheckConstraint(
            "enterprise_type IS NULL OR enterprise_type IN ('micro', 'small', 'medium')",
            name="ck_parties_enterprise_type",
        ),
        CheckConstraint(
            "activity IS NULL OR activity IN ('manufacturer', 'service', 'trader')",
            name="ck_parties_activity",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    pan: Mapped[str | None] = mapped_column(String(10), nullable=True)
    udyam_no: Mapped[str | None] = mapped_column(String(30), nullable=True)
    udyam_reg_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    enterprise_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    activity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
