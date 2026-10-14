import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    pages: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="stored", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    case = relationship("Case")
    doc_pages = relationship("Page", back_populates="document", cascade="all, delete-orphan")


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ocr_engine: Mapped[str | None] = mapped_column(String(50), nullable=True)

    document = relationship("Document", back_populates="doc_pages")
