"""
Idempotent database seeder for ClaimGraph M1.
Loads:
1. rate_table seed rows (effective 2026-10-07 at 5.75%, 2025-12-06 at 5.50%)
2. Parties and Cases for synthetic Cases A, B, C, D
3. Documents rows and copies document files to Storage
"""

import hashlib
import os
import re
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.storage import storage
from app.models.case import Case
from app.models.document import Document
from app.models.party import Party
from app.models.rule import RateTable

NAMESPACE_CLAIMGRAPH = uuid.UUID("c1a1394a-7000-4000-8000-000000000001")


def deterministic_uuid(key: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE_CLAIMGRAPH, key)


def get_synthetic_dir() -> Path:
    docker_path = Path("/data/synthetic")
    if docker_path.exists():
        return docker_path
    local_path = (Path(__file__).resolve().parent.parent.parent / "data" / "synthetic").resolve()
    if local_path.exists():
        return local_path
    raise FileNotFoundError("Synthetic data directory not found in /data/synthetic or data/synthetic")


def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def count_pages(filepath: Path) -> int:
    if filepath.suffix.lower() != ".pdf":
        return 1
    try:
        with open(filepath, "rb") as f:
            content = f.read()
        matches = re.findall(rb"/Type\s*/Page\b", content)
        return max(1, len(matches))
    except Exception:
        return 1


def seed_rate_table(db) -> int:
    rate_entries = [
        {
            "effective_from": date(2026, 10, 7),
            "bank_rate_pct": Decimal("5.75"),
            "source_note": "Seed value, verify against RBI before demo",
        },
        {
            "effective_from": date(2025, 12, 6),
            "bank_rate_pct": Decimal("5.50"),
            "source_note": "Seed value, verify against RBI before demo",
        },
    ]

    count = 0
    for r in rate_entries:
        existing = db.scalars(
            select(RateTable).where(RateTable.effective_from == r["effective_from"])
        ).first()
        if existing:
            existing.bank_rate_pct = r["bank_rate_pct"]
            existing.source_note = r["source_note"]
        else:
            obj = RateTable(
                id=deterministic_uuid(f"rate_table:{r['effective_from']}"),
                effective_from=r["effective_from"],
                bank_rate_pct=r["bank_rate_pct"],
                source_note=r["source_note"],
            )
            db.add(obj)
            count += 1
    db.commit()
    return count


def seed_parties_and_cases(db, synthetic_dir: Path):
    cases_meta = [
        {
            "key": "case_a",
            "title": "Case A: Sharma Auto Components vs Meridian Motors Pvt Ltd",
            "supplier": {
                "name": "Sharma Auto Components",
                "role": "supplier",
                "gstin": "07AAAAA0000A1Z5",
                "pan": "AAAAA0000A",
                "udyam_no": "UDYAM-DL-01-0012345",
                "udyam_reg_date": date(2024, 3, 12),
                "enterprise_type": "micro",
                "activity": "manufacturer",
            },
            "buyer": {
                "name": "Meridian Motors Pvt Ltd",
                "role": "buyer",
                "gstin": "27BBBBB1111B1Z2",
                "pan": "BBBBB1111B",
            },
        },
        {
            "key": "case_b",
            "title": "Case B: Kaveri Packaging Works vs Northline Foods Ltd",
            "supplier": {
                "name": "Kaveri Packaging Works",
                "role": "supplier",
                "gstin": "29CCCCC2222C1Z8",
                "pan": "CCCCC2222C",
                "udyam_no": "UDYAM-KA-02-0054321",
                "udyam_reg_date": date(2023, 8, 1),
                "enterprise_type": "small",
                "activity": "manufacturer",
            },
            "buyer": {
                "name": "Northline Foods Ltd",
                "role": "buyer",
                "gstin": "06DDDDD3333D1Z1",
                "pan": "DDDDD3333D",
            },
        },
        {
            "key": "case_c",
            "title": "Case C: Tara Textiles vs Ashoka Retail Pvt Ltd",
            "supplier": {
                "name": "Tara Textiles",
                "role": "supplier",
                "gstin": "24EEEEE4444E1Z4",
                "pan": "EEEEE4444E",
                "udyam_no": "UDYAM-GJ-03-0098765",
                "udyam_reg_date": date(2026, 5, 20),
                "enterprise_type": "micro",
                "activity": "manufacturer",
            },
            "buyer": {
                "name": "Ashoka Retail Pvt Ltd",
                "role": "buyer",
                "gstin": "27FFFFF5555F1Z7",
                "pan": "FFFFF5555F",
            },
        },
        {
            "key": "case_d",
            "title": "Case D: Raman Fasteners vs Orbit Machines Pvt Ltd",
            "supplier": {
                "name": "Raman Fasteners",
                "role": "supplier",
                "gstin": "03GGGGG6666G1Z9",
                "pan": "GGGGG6666G",
                "udyam_no": "UDYAM-PB-04-0043210",
                "udyam_reg_date": date(2022, 11, 4),
                "enterprise_type": "micro",
                "activity": "manufacturer",
            },
            "buyer": {
                "name": "Orbit Machines Pvt Ltd",
                "role": "buyer",
                "gstin": "08HHHHH7777H1Z3",
                "pan": "HHHHH7777H",
            },
        },
    ]

    for cm in cases_meta:
        # Supplier Party
        sup_data = cm["supplier"]
        sup_id = deterministic_uuid(f"party:{sup_data['gstin']}")
        sup = db.get(Party, sup_id)
        if not sup:
            sup = Party(
                id=sup_id,
                name=sup_data["name"],
                role=sup_data["role"],
                gstin=sup_data.get("gstin"),
                pan=sup_data.get("pan"),
                udyam_no=sup_data.get("udyam_no"),
                udyam_reg_date=sup_data.get("udyam_reg_date"),
                enterprise_type=sup_data.get("enterprise_type"),
                activity=sup_data.get("activity"),
            )
            db.add(sup)

        # Buyer Party
        buy_data = cm["buyer"]
        buy_id = deterministic_uuid(f"party:{buy_data['gstin']}")
        buy = db.get(Party, buy_id)
        if not buy:
            buy = Party(
                id=buy_id,
                name=buy_data["name"],
                role=buy_data["role"],
                gstin=buy_data.get("gstin"),
                pan=buy_data.get("pan"),
            )
            db.add(buy)

        db.flush()

        # Case
        case_id = deterministic_uuid(f"case:{cm['key']}")
        case_obj = db.get(Case, case_id)
        if not case_obj:
            case_obj = Case(
                id=case_id,
                title=cm["title"],
                supplier_id=sup_id,
                buyer_id=buy_id,
                status="draft",
            )
            db.add(case_obj)
        else:
            case_obj.title = cm["title"]

        db.flush()

        # Seed Documents for this case
        case_path = synthetic_dir / cm["key"]
        doc_files = []
        for root, _, files in os.walk(case_path):
            for file in files:
                if file.endswith((".pdf", ".jpg", ".png", ".jpeg")):
                    doc_files.append(Path(root) / file)

        for fpath in doc_files:
            filename = fpath.name
            sha = compute_sha256(fpath)
            pages = count_pages(fpath)

            # Determine kind
            fl = filename.lower()
            if "po" in fl:
                kind = "purchase_order"
            elif "ch" in fl or "challan" in fl:
                kind = "delivery_challan"
            elif "inv" in fl:
                kind = "invoice"
            elif "bank" in fl:
                kind = "bank_statement"
            elif "remittance" in fl:
                kind = "remittance_advice"
            elif "udyam" in fl:
                kind = "udyam_certificate"
            elif "email" in fl:
                kind = "communication"
            else:
                kind = "other"

            # Storage copy
            rel_storage_path = f"cases/{cm['key']}/{filename}"
            storage.put(fpath, rel_storage_path)

            doc_id = deterministic_uuid(f"document:{cm['key']}:{filename}")
            doc = db.get(Document, doc_id)
            if not doc:
                doc = Document(
                    id=doc_id,
                    case_id=case_id,
                    kind=kind,
                    filename=filename,
                    sha256=sha,
                    storage_path=rel_storage_path,
                    pages=pages,
                )
                db.add(doc)
            else:
                doc.sha256 = sha
                doc.pages = pages
                doc.kind = kind
                doc.storage_path = rel_storage_path

    db.commit()


def main():
    print("Starting ClaimGraph seed...")
    synthetic_dir = get_synthetic_dir()
    print(f"Using synthetic data directory: {synthetic_dir}")

    with SessionLocal() as db:
        seed_rate_table(db)
        seed_parties_and_cases(db, synthetic_dir)

        # Print row counts to verify
        parties_count = db.query(Party).count()
        cases_count = db.query(Case).count()
        docs_count = db.query(Document).count()
        rate_count = db.query(RateTable).count()

        print("\nSeed completed successfully!")
        print(f"Parties count:    {parties_count}")
        print(f"Cases count:      {cases_count}")
        print(f"Documents count:  {docs_count}")
        print(f"RateTable count:  {rate_count}")


if __name__ == "__main__":
    main()
