import logging
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.ingest.classify import classify_document
from app.ingest.extract import extract_document_facts
from app.ingest.read import read_document_pages

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("claimgraph.ingest.eval")


def get_synthetic_dir() -> Path:
    candidates = [
        Path("/data/synthetic"),
        Path(__file__).resolve().parents[3] / "data" / "synthetic",
        Path("data/synthetic").resolve(),
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[1]


def load_expected_ground_truth(synth_dir: Path) -> dict[str, dict[str, Any]]:
    """Builds ground truth mapping for all 23 synthetic documents across Cases A, B, C, D."""
    ground_truth: dict[str, dict[str, Any]] = {}

    # Case A Base
    ground_truth["case_a/base/PO_MM_PO_2291.pdf"] = {
        "kind": "PO",
        "po_no": "MM/PO/2291",
        "po_date": "2026-04-02",
        "credit_days": 45,
        "supplier_gstin": "07AAAAA0000A1Z5",
        "buyer_gstin": "27BBBBB1111B1Z2",
        "qty": "500",
        "rate": "820",
        "taxable_total": "410000",
        "grand_total": "483800",
    }
    ground_truth["case_a/base/CH_118.pdf"] = {
        "kind": "CHALLAN",
        "challan_no": "CH-118",
        "challan_date": "2026-04-20",
        "po_ref": "MM/PO/2291",
        "dispatched_qty": "460",
        "accepted_qty": "460",
        "received_by": "R. Kulkarni",
    }
    ground_truth["case_a/base/INV_7731.pdf"] = {
        "kind": "INVOICE",
        "invoice_no": "INV-7731",
        "invoice_date": "2026-04-22",
        "po_ref": "MM/PO/2291",
        "challan_ref": "CH-118",
        "supplier_gstin": "07AAAAA0000A1Z5",
        "buyer_gstin": "27BBBBB1111B1Z2",
        "taxable_total": "410000",
        "gst_amount": "73800",
        "grand_total": "483800",
        "qty": "500",
        "rate": "820",
        "amount": "410000",
    }
    ground_truth["case_a/base/remittance_advice.pdf"] = {
        "kind": "REMITTANCE",
        "remittance_date": "2026-06-30",
        "gross_amount": "200000",
        "tds_amount": "2000",
        "net_amount": "198000",
        "utr": "UTRB26181049281",
    }
    ground_truth["case_a/base/bank_statement.pdf"] = {
        "kind": "BANK_STATEMENT",
        "period_from": "2026-04-01",
        "period_to": "2026-06-30",
        "credit": "198000",
        "utr": "UTRB26181049281",
    }
    ground_truth["case_a/base/udyam_certificate.pdf"] = {
        "kind": "UDYAM_CERT",
        "udyam_no": "UDYAM-DL-01-0012345",
        "registration_date": "2024-03-12",
        "enterprise_type": "Micro",
        "activity": "Manufacturing",
    }

    # Case A Addons
    ground_truth["case_a/addons/01_backorder_email.pdf"] = {
        "kind": "EMAIL",
        "communication_kind": "backorder",
        "message_date": "2026-04-25",
    }
    ground_truth["case_a/addons/02_challan_ch131.pdf"] = {
        "kind": "CHALLAN",
        "challan_no": "CH-131",
        "challan_date": "2026-05-09",
        "po_ref": "MM/PO/2291",
        "dispatched_qty": "40",
        "accepted_qty": "40",
        "received_by": "R. Kulkarni",
    }

    # Case B Base
    ground_truth["case_b/base/PO_NF_PO_118.pdf"] = {
        "kind": "PO",
        "po_no": "NF/PO/118",
        "po_date": "2026-02-20",
        "credit_days": 30,
        "supplier_gstin": "29CCCCC2222C1Z8",
        "buyer_gstin": "27DDDDD3333D1Z1",
        "qty": "2000",
        "rate": "36.5",
        "taxable_total": "73000",
        "grand_total": "86140",
    }
    ground_truth["case_b/base/KP_CH_045.pdf"] = {
        "kind": "CHALLAN",
        "challan_no": "KP/CH/045",
        "challan_date": "2026-03-18",
        "po_ref": "NF/PO/118",
        "dispatched_qty": "2000",
        "accepted_qty": "2000",
        "received_by": "S. Murthy",
    }
    ground_truth["case_b/base/KP_INV_0412.pdf"] = {
        "kind": "INVOICE",
        "invoice_no": "KP/INV/0412",
        "invoice_date": "2026-03-19",
        "po_ref": "NF/PO/118",
        "challan_ref": "KP/CH/045",
        "supplier_gstin": "29CCCCC2222C1Z8",
        "buyer_gstin": "27DDDDD3333D1Z1",
        "taxable_total": "73000",
        "gst_amount": "13140",
        "grand_total": "86140",
        "qty": "2000",
        "rate": "36.5",
    }
    ground_truth["case_b/base/KP_INV_0412_A.pdf"] = {
        "kind": "INVOICE",
        "invoice_no": "KP/INV/0412-A",
        "invoice_date": "2026-03-28",
        "po_ref": "NF/PO/118",
        "challan_ref": "KP/CH/045",
        "supplier_gstin": "29CCCCC2222C1Z8",
        "buyer_gstin": "27DDDDD3333D1Z1",
        "taxable_total": "73000",
        "grand_total": "86140",
    }
    ground_truth["case_b/base/bank_statement.pdf"] = {
        "kind": "BANK_STATEMENT",
        "period_from": "2026-03-01",
        "period_to": "2026-05-31",
        "credit": "50000",
        "utr": "UTRB26071018274",
    }
    ground_truth["case_b/base/udyam_certificate.pdf"] = {
        "kind": "UDYAM_CERT",
        "udyam_no": "UDYAM-KR-03-0098765",
        "registration_date": "2023-08-01",
        "enterprise_type": "Small",
        "activity": "Manufacturing",
    }

    # Case C Base
    ground_truth["case_c/base/PO_AR_PO_771.pdf"] = {
        "kind": "PO",
        "po_no": "AR/PO/771",
        "po_date": "2026-03-10",
        "credit_days": 30,
        "supplier_gstin": "24EEEEE4444E1Z4",
        "buyer_gstin": "27FFFFF5555F1Z7",
        "qty": "1200",
        "rate": "210",
        "taxable_total": "252000",
        "grand_total": "264600",
    }
    ground_truth["case_c/base/CH_302.pdf"] = {
        "kind": "CHALLAN",
        "challan_no": "CH-302",
        "challan_date": "2026-03-25",
        "po_ref": "AR/PO/771",
        "dispatched_qty": "1200",
        "accepted_qty": "1200",
        "received_by": "M. Joshi",
    }
    ground_truth["case_c/base/INV_901.pdf"] = {
        "kind": "INVOICE",
        "invoice_no": "INV-901",
        "invoice_date": "2026-03-26",
        "po_ref": "AR/PO/771",
        "challan_ref": "CH-302",
        "supplier_gstin": "24EEEEE4444E1Z4",
        "buyer_gstin": "27FFFFF5555F1Z7",
        "taxable_total": "252000",
        "gst_amount": "12600",
        "grand_total": "264600",
        "qty": "1200",
        "rate": "210",
    }
    ground_truth["case_c/base/udyam_certificate.pdf"] = {
        "kind": "UDYAM_CERT",
        "udyam_no": "UDYAM-GJ-01-0077889",
        "registration_date": "2026-05-20",
        "enterprise_type": "Micro",
        "activity": "Manufacturing",
    }

    # Case D Base
    ground_truth["case_d/base/PO_OM_PO_5540.pdf"] = {
        "kind": "PO",
        "po_no": "OM/PO/5540",
        "po_date": "2026-05-06",
        "credit_days": 30,
        "supplier_gstin": "03GGGGG6666G1Z9",
        "buyer_gstin": "08HHHHH7777H1Z3",
        "qty": "1000",
        "rate": "14",
        "taxable_total": "14000",
        "grand_total": "16520",
    }
    ground_truth["case_d/base/challan_ch_881.jpg"] = {
        "kind": "CHALLAN",
        "challan_no": "CH-881",
        "challan_date": "2026-05-12",
        "po_ref": "OM/PO/5540",
        "dispatched_qty": "1000",
        "accepted_qty": "980",
        "rejected_qty": "20",
        "rejection_reason": "thread-damaged",
    }
    ground_truth["case_d/base/INV_1042.pdf"] = {
        "kind": "INVOICE",
        "invoice_no": "INV-1042",
        "invoice_date": "2026-05-22",
        "po_ref": "OM/PO/5540",
        "challan_ref": "CH-881",
        "supplier_gstin": "03GGGGG6666G1Z9",
        "buyer_gstin": "08HHHHH7777H1Z3",
        "taxable_total": "14000",
        "gst_amount": "2520",
        "grand_total": "16520",
        "qty": "1000",
        "rate": "14",
    }
    ground_truth["case_d/base/bank_statement.pdf"] = {
        "kind": "BANK_STATEMENT",
        "period_from": "2026-05-01",
        "period_to": "2026-07-31",
        "credit": "10000",
        "utr": "UTRB26197089123",
    }
    ground_truth["case_d/base/udyam_certificate.pdf"] = {
        "kind": "UDYAM_CERT",
        "udyam_no": "UDYAM-PB-04-0043210",
        "registration_date": "2022-11-04",
        "enterprise_type": "Micro",
        "activity": "Manufacturing",
    }

    return ground_truth


def evaluate_synthetic_documents() -> None:
    synth_dir = get_synthetic_dir()
    ground_truth = load_expected_ground_truth(synth_dir)

    storage_base = Path(settings.STORAGE_DIR).resolve()
    temp_dir = storage_base / "eval_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 90)
    print("CLAIMGRAPH M3: INGESTION ACCURACY EVALUATION (REPLAY MODE)")
    print(f"Target Documents: {len(ground_truth)} | Mode: {settings.LLM_MODE}")
    print("=" * 90 + "\n")

    results_table = []
    digital_checked = 0
    digital_correct = 0
    digital_needs_review = 0

    scan_checked = 0
    scan_correct = 0
    scan_needs_review = 0
    scan_failures = []

    for rel_path, expected in ground_truth.items():
        doc_file = synth_dir / rel_path
        if not doc_file.exists():
            print(f"File not found: {doc_file}")
            continue

        doc_name = doc_file.name
        is_scan = doc_file.suffix.lower() in (".jpg", ".jpeg", ".png")

        # 1. Read document
        doc_eval_id = f"eval_{doc_file.stem}"
        page_results = read_document_pages(
            file_path=doc_file,
            document_id=doc_eval_id,
            storage_base=temp_dir,
        )
        full_text = "\n\n".join(f"--- Page {p.page_no} ---\n{p.text}" for p in page_results)

        # 2. Classify
        class_res = classify_document(full_text)
        expected_kind = expected["kind"]

        # 3. Extract Facts
        pages_words = {p.page_no: p.words for p in page_results}
        facts = extract_document_facts(
            kind=class_res.kind,
            full_text=full_text,
            pages_words=pages_words,
            page_count=len(page_results),
        )

        # Build fact dictionary by field path
        facts_map: dict[str, Any] = {}
        facts_status: dict[str, str] = {}
        for f in facts:
            val = f.normalised_value if f.normalised_value is not None else f.raw_value
            facts_map[f.field_path] = str(val).strip() if val is not None else ""
            facts_status[f.field_path] = f.status

        # Evaluate against expected fields
        doc_checked = 0
        doc_correct = 0
        doc_wrong = 0
        doc_review = 0

        # Kind check
        doc_checked += 1
        if class_res.kind == expected_kind:
            doc_correct += 1
        else:
            doc_wrong += 1
            if is_scan:
                scan_failures.append(f"{doc_name}: kind expected {expected_kind}, got {class_res.kind}")

        for exp_k, exp_v in expected.items():
            if exp_k == "kind":
                continue
            doc_checked += 1

            # Match against facts map keys
            matched_fact_val = None
            matched_status = "auto"
            for f_path, f_val in facts_map.items():
                if exp_k in f_path.lower():
                    matched_fact_val = f_val
                    matched_status = facts_status.get(f_path, "auto")
                    break

            if matched_status == "needs_review":
                doc_review += 1

            if matched_fact_val is not None:
                # Normalize values for fair comparison
                exp_clean = str(exp_v).strip().lower().replace(",", "")
                fact_clean = str(matched_fact_val).strip().lower().replace(",", "")

                if exp_clean in fact_clean or fact_clean in exp_clean or exp_clean == fact_clean:
                    doc_correct += 1
                else:
                    doc_wrong += 1
                    if is_scan:
                        scan_failures.append(f"{doc_name}: field {exp_k} expected '{exp_v}', got '{matched_fact_val}'")
            else:
                doc_wrong += 1
                if is_scan:
                    scan_failures.append(f"{doc_name}: field {exp_k} not found in extracted facts")

        results_table.append({
            "doc": doc_name,
            "type": class_res.kind,
            "is_scan": is_scan,
            "checked": doc_checked,
            "correct": doc_correct,
            "wrong": doc_wrong,
            "review": doc_review,
        })

        if is_scan:
            scan_checked += doc_checked
            scan_correct += doc_correct
            scan_needs_review += doc_review
        else:
            digital_checked += doc_checked
            digital_correct += doc_correct
            digital_needs_review += doc_review

    # Print Report
    header_fmt = "{:<30} | {:<12} | {:<9} | {:<9} | {:<9} | {:<12}"
    row_fmt = "{:<30} | {:<12} | {:<9} | {:<9} | {:<9} | {:<12}"
    sep = "-" * 90

    print(header_fmt.format("Document", "Type", "Checked", "Correct", "Wrong", "Needs Review"))
    print(sep)
    for r in results_table:
        print(row_fmt.format(
            r["doc"],
            r["type"],
            str(r["checked"]),
            str(r["correct"]),
            str(r["wrong"]),
            str(r["review"]),
        ))
    print(sep)

    digital_acc = (digital_correct / digital_checked * 100.0) if digital_checked else 0.0
    scan_acc = (scan_correct / scan_checked * 100.0) if scan_checked else 0.0

    print("\n" + "=" * 90)
    print("SEPARATE ACCURACY SUMMARY")
    print("=" * 90)
    print(f"Digital PDFs Accuracy:  {digital_acc:.1f}% ({digital_correct}/{digital_checked} fields correct)")
    print(f"Digital PDFs in Review: {digital_needs_review} fields flagged for review")
    print(f"Case D Scan Accuracy:   {scan_acc:.1f}% ({scan_correct}/{scan_checked} fields correct)")
    print(f"Case D Scan in Review:  {scan_needs_review} fields flagged for review")
    if scan_failures:
        print("\nCase D Scan Discrepancies / Unextracted Fields:")
        for sf in scan_failures:
            print(f"  - {sf}")
    print("=" * 90 + "\n")


if __name__ == "__main__":
    evaluate_synthetic_documents()
