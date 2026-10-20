"""Shared fixtures for claims tests."""

import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.api.facts import bulk_confirm_auto_facts, update_fact
from app.core.db import SessionLocal, engine
from app.core.storage import storage
from app.ingest.pipeline import process_document
from app.models.base import Base
from app.models.case import Case
from app.models.document import Document
from app.models.fact import Fact
from app.models.party import Party
from app.schemas.fact import FactUpdateRequest


def get_synthetic_dir() -> Path:
    docker_path = Path("/data/synthetic")
    if docker_path.exists():
        return docker_path
    local_path = (Path(__file__).resolve().parents[3] / "data" / "synthetic").resolve()
    if local_path.exists():
        return local_path
    raise FileNotFoundError("Synthetic directory not found")


@pytest.fixture
def db_session():
    """Create a clean database session for each test."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture
def create_reviewed_case(db_session: Session) -> Callable[..., tuple[Case, list[Document]]]:
    """Helper fixture to ingest and review documents for a case key (case_a, case_b, etc.)."""

    def _setup(
        case_key: str,
        files_subset: list[str] | None = None,
        auto_confirm_needs_review: bool = True,
        actor: str = "test_reviewer",
    ) -> tuple[Case, list[Document]]:
        synth_dir = get_synthetic_dir()
        base_dir = synth_dir / case_key / "base"
        assert base_dir.exists(), f"Synthetic directory {base_dir} missing"

        # Party definitions matching synthetic metadata
        parties_meta = {
            "case_a": {
                "supplier": {"name": "Sharma Auto Components", "role": "supplier", "gstin": "07AAAAA0000A1Z5"},
                "buyer": {"name": "Meridian Motors Pvt Ltd", "role": "buyer", "gstin": "27BBBBB1111B1Z2"},
            },
            "case_b": {
                "supplier": {"name": "Kaveri Packaging Works", "role": "supplier", "gstin": "29CCCCC2222C1Z8"},
                "buyer": {"name": "Northline Foods Ltd", "role": "buyer", "gstin": "06DDDDD3333D1Z1"},
            },
            "case_c": {
                "supplier": {"name": "Tara Textiles", "role": "supplier", "gstin": "24EEEEE4444E1Z4"},
                "buyer": {"name": "Ashoka Retail Pvt Ltd", "role": "buyer", "gstin": "27FFFFF5555F1Z7"},
            },
            "case_d": {
                "supplier": {"name": "Raman Fasteners", "role": "supplier", "gstin": "03GGGGG6666G1Z9"},
                "buyer": {"name": "Orbit Machines Pvt Ltd", "role": "buyer", "gstin": "08HHHHH7777H1Z3"},
            },
        }

        meta = parties_meta.get(case_key, parties_meta["case_a"])
        sup = Party(**meta["supplier"])
        buy = Party(**meta["buyer"])
        db_session.add(sup)
        db_session.add(buy)
        db_session.flush()

        case = Case(
            title=f"Test {case_key.upper()} Run",
            supplier_id=sup.id,
            buyer_id=buy.id,
            status="draft",
        )
        db_session.add(case)
        db_session.commit()
        db_session.refresh(case)

        # Collect files
        all_files = [f for f in base_dir.glob("*.*") if f.suffix in (".pdf", ".jpg", ".png")]
        if files_subset:
            all_files = [f for f in all_files if f.name in files_subset]

        docs: list[Document] = []
        for p in all_files:
            rel = f"test_{case_key}_{uuid.uuid4().hex[:6]}/{p.name}"
            storage.put(p, rel)
            d = Document(
                case_id=case.id,
                kind="OTHER",
                filename=p.name,
                sha256="fake",
                storage_path=rel,
                pages=1,
                status="stored",
            )
            db_session.add(d)
            db_session.flush()
            docs.append(d)
        db_session.commit()

        # Ingestion pipeline (uses replay cache)
        for d in docs:
            try:
                process_document(d.id, db_session)
            except Exception:
                # Some files (like scan without cache) might fail ingestion
                pass

        # Review pipeline: bulk confirm auto facts
        for d in docs:
            bulk_confirm_auto_facts(d.id, x_reviewer=actor, db=db_session)

        # Confirm needs_review items through the review service if requested
        if auto_confirm_needs_review:
            needs = db_session.query(Fact).filter(Fact.case_id == case.id, Fact.status == "needs_review").all()
            for f in needs:
                update_fact(f.id, FactUpdateRequest(action="confirm"), x_reviewer=actor, db=db_session)

        return case, docs

    return _setup
