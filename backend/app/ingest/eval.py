import logging
from decimal import Decimal, InvalidOperation
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
    """Builds ground truth mapping for all 23 synthetic documents across Cases A-D.

    Values are taken verbatim from the PDFs (not the expected_*.json ledger files,
    which track M1/M2 business logic rather than per-document raw extraction).
    All Type-E corrections are documented inline.
    """
    ground_truth: dict[str, dict[str, Any]] = {}

    # -----------------------------------------------------------------------
    # Case A Base
    # -----------------------------------------------------------------------
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
    # PDF A/C 10492810029: Date 01-06-2026 to 10-07-2026
    # credit 1,98,000.00 | UTR UTRB26181049281
    ground_truth["case_a/base/bank_statement.pdf"] = {
        "kind": "BANK_STATEMENT",
        "period_from": "2026-06-01",   # corrected from 2026-04-01 (Type E)
        "period_to": "2026-07-10",     # corrected from 2026-06-30 (Type E)
        "credit": "198000",
        "utr": "UTRB26181049281",
    }
    # PDF says "Major Activity: Manufacturer" – eval was wrong to expect "Manufacturing"
    ground_truth["case_a/base/udyam_certificate.pdf"] = {
        "kind": "UDYAM_CERT",
        "udyam_no": "UDYAM-DL-01-0012345",
        "registration_date": "2024-03-12",
        "enterprise_type": "Micro",
        "activity": "Manufacturer",    # corrected from "Manufacturing" (Type E)
    }

    # -----------------------------------------------------------------------
    # Case A Addons
    # -----------------------------------------------------------------------
    # communication_kind maps to communications[n].kind in the EmailExtraction schema
    ground_truth["case_a/addons/01_backorder_email.pdf"] = {
        "kind": "EMAIL",
        "communication_kind": "backorder",  # matched via "kind" in field path
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

    # -----------------------------------------------------------------------
    # Case B Base
    # PDF date "05-03-2026"; PDF buyer GSTIN "06DDDDD3333D1Z1"
    # -----------------------------------------------------------------------
    ground_truth["case_b/base/PO_NF_PO_118.pdf"] = {
        "kind": "PO",
        "po_no": "NF/PO/118",
        "po_date": "2026-03-05",       # corrected from 2026-02-20 (Type E)
        "credit_days": 30,
        "supplier_gstin": "29CCCCC2222C1Z8",
        "buyer_gstin": "06DDDDD3333D1Z1",  # corrected from 27DDDDD3333D1Z1 (Type E)
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
        "buyer_gstin": "06DDDDD3333D1Z1",  # corrected from 27DDDDD3333D1Z1 (Type E)
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
        "buyer_gstin": "06DDDDD3333D1Z1",  # corrected from 27DDDDD3333D1Z1 (Type E)
        "taxable_total": "73000",
        "grand_total": "86140",
    }
    # PDF: 01-03-2026 to 15-05-2026; credit 50,000 (RTGS); UTR UTRNF2612204891
    ground_truth["case_b/base/bank_statement.pdf"] = {
        "kind": "BANK_STATEMENT",
        "period_from": "2026-03-01",
        "period_to": "2026-05-15",    # corrected from 2026-05-31 (Type E – PDF date)
        "credit": "50000",
        "utr": "UTRNF2612204891",     # corrected from UTRB26071018274 (Type E)
    }
    # PDF UDYAM-KA-02-0054321 | activity: Manufacturer
    ground_truth["case_b/base/udyam_certificate.pdf"] = {
        "kind": "UDYAM_CERT",
        "udyam_no": "UDYAM-KA-02-0054321",  # corrected from UDYAM-KR-03-0098765 (Type E)
        "registration_date": "2023-08-01",
        "enterprise_type": "Small",
        "activity": "Manufacturer",    # corrected from "Manufacturing" (Type E)
    }

    # -----------------------------------------------------------------------
    # Case C Base
    # -----------------------------------------------------------------------
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
    # PDF stamp: "Stores Officer" not "M. Joshi"
    ground_truth["case_c/base/CH_302.pdf"] = {
        "kind": "CHALLAN",
        "challan_no": "CH-302",
        "challan_date": "2026-03-25",
        "po_ref": "AR/PO/771",
        "dispatched_qty": "1200",
        "accepted_qty": "1200",
        "received_by": "Stores Officer",  # corrected from "M. Joshi" (Type E)
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
    # PDF UDYAM-GJ-03-0098765 | activity: Manufacturer
    ground_truth["case_c/base/udyam_certificate.pdf"] = {
        "kind": "UDYAM_CERT",
        "udyam_no": "UDYAM-GJ-03-0098765",  # corrected from UDYAM-GJ-01-0077889 (Type E)
        "registration_date": "2026-05-20",
        "enterprise_type": "Micro",
        "activity": "Manufacturer",    # corrected from "Manufacturing" (Type E)
    }

    # -----------------------------------------------------------------------
    # Case D Base
    # -----------------------------------------------------------------------
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
    # PDF: 01-07-2026 to 31-07-2026; credit 10,000; UTR UTRORB261960012
    ground_truth["case_d/base/bank_statement.pdf"] = {
        "kind": "BANK_STATEMENT",
        "period_from": "2026-07-01",   # corrected: PDF says 01-07-2026
        "period_to": "2026-07-31",
        "credit": "10000",
        "utr": "UTRORB261960012",      # corrected from UTRB26197089123 (Type E)
    }
    ground_truth["case_d/base/udyam_certificate.pdf"] = {
        "kind": "UDYAM_CERT",
        "udyam_no": "UDYAM-PB-04-0043210",
        "registration_date": "2022-11-04",
        "enterprise_type": "Micro",
        "activity": "Manufacturer",    # corrected from "Manufacturing" (Type E)
    }

    return ground_truth


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------

_MONEY_KEYS = frozenset({
    "qty", "rate", "amount", "total", "taxable", "gst", "credit", "debit",
    "gross", "net", "tds", "credit_days",
})
_DATE_KEYS = frozenset({"date", "period_from", "period_to"})
_CRITICAL_KEYS = _MONEY_KEYS | _DATE_KEYS


def _is_critical(field_name: str) -> bool:
    return any(k in field_name.lower() for k in _CRITICAL_KEYS)


def _values_match(exp_v: Any, fact_v: str) -> bool:
    """Flexible comparison: try numeric equality first, then substring."""
    exp_s = str(exp_v).strip().lower().replace(",", "")
    fact_s = str(fact_v).strip().lower().replace(",", "")
    # Numeric equality
    try:
        return Decimal(exp_s) == Decimal(fact_s)
    except InvalidOperation:
        pass
    # Substring
    return exp_s in fact_s or fact_s in exp_s or exp_s == fact_s


def _match_field(
    exp_k: str,
    exp_v: Any,
    facts_map: dict[str, str],
    facts_status: dict[str, str],
) -> tuple[str | None, str, str]:
    """Find the best fact entry for an expected key.

    Special cases:
    - communication_kind -> look for paths containing 'kind' inside 'communications'
    - message_date -> look for paths containing 'date' inside 'communications'
    - multiple candidates (e.g. transactions[] or lines[]) -> pick candidate matching exp_v
    """
    lower_key = exp_k.lower()

    # Special email mappings
    if lower_key == "communication_kind":
        for fp, fv in facts_map.items():
            if "communications" in fp.lower() and fp.lower().endswith(".kind"):
                return fv, facts_status.get(fp, "auto"), fp
        return None, "auto", ""

    if lower_key == "message_date":
        for fp, fv in facts_map.items():
            if "communications" in fp.lower() and "date" in fp.lower():
                return fv, facts_status.get(fp, "auto"), fp
        for fp, fv in facts_map.items():
            if "messages" in fp.lower() and "date" in fp.lower():
                return fv, facts_status.get(fp, "auto"), fp
        return None, "auto", ""

    # Find all candidates where lower_key is part of the path
    candidates = []
    for fp, fv in facts_map.items():
        if lower_key in fp.lower():
            candidates.append((fv, facts_status.get(fp, "auto"), fp))

    if not candidates:
        return None, "auto", ""

    # 1. If any candidate matches exp_v, prefer it
    for fv, status, fp in candidates:
        if fv and _values_match(exp_v, fv):
            return fv, status, fp

    # 2. Otherwise return first candidate with a meaningful value (not dash/empty)
    for fv, status, fp in candidates:
        if fv and fv not in ("-", "None", ""):
            return fv, status, fp

    return candidates[0]


# ---------------------------------------------------------------------------
# Main evaluator
# ---------------------------------------------------------------------------

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
    scan_failures: list[str] = []

    # For trust metric
    wrong_fields: list[dict] = []

    digital_auto_total = 0
    digital_auto_correct = 0

    for rel_path, expected in ground_truth.items():
        doc_file = synth_dir / rel_path
        if not doc_file.exists():
            print(f"File not found: {doc_file}")
            continue

        doc_name = doc_file.name
        is_scan = doc_file.suffix.lower() in (".jpg", ".jpeg", ".png")

        # 1. Read
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

        # 3. Extract
        pages_words = {p.page_no: p.words for p in page_results}
        facts = extract_document_facts(
            kind=class_res.kind,
            full_text=full_text,
            pages_words=pages_words,
            page_count=len(page_results),
        )

        # Build fact maps
        facts_map: dict[str, str] = {}
        facts_status: dict[str, str] = {}
        for f in facts:
            val = f.normalised_value if f.normalised_value is not None else f.raw_value
            facts_map[f.field_path] = str(val).strip() if val is not None else ""
            facts_status[f.field_path] = f.status

        # Evaluate
        doc_checked = 0
        doc_correct = 0
        doc_wrong = 0
        doc_review = 0

        # Kind check
        doc_checked += 1
        kind_ok = (class_res.kind == expected_kind)
        if kind_ok:
            doc_correct += 1
            if not is_scan:
                digital_auto_total += 1
                digital_auto_correct += 1
        else:
            doc_wrong += 1
            if not is_scan:
                digital_auto_total += 1
            msg = f"{doc_name}: kind expected {expected_kind}, got {class_res.kind}"
            if is_scan:
                scan_failures.append(msg)
            else:
                wrong_fields.append(dict(doc=doc_name, field="kind", expected=expected_kind,
                                         extracted=class_res.kind, status="auto", critical=False))

        for exp_k, exp_v in expected.items():
            if exp_k == "kind":
                continue
            doc_checked += 1

            matched_val, matched_status, matched_path = _match_field(exp_k, exp_v, facts_map, facts_status)

            if matched_status == "needs_review":
                doc_review += 1

            ok = matched_val is not None and _values_match(exp_v, matched_val)

            if not is_scan and matched_status == "auto":
                digital_auto_total += 1
                if ok:
                    digital_auto_correct += 1

            if ok:
                doc_correct += 1
            else:
                doc_wrong += 1
                extracted_disp = matched_val if matched_val is not None else "(missing)"
                if is_scan:
                    scan_failures.append(
                        f"{doc_name}: field {exp_k} expected '{exp_v}', got '{extracted_disp}'"
                    )
                else:
                    wrong_fields.append(dict(
                        doc=doc_name, field=exp_k, expected=str(exp_v),
                        extracted=str(extracted_disp), status=matched_status,
                        critical=_is_critical(exp_k),
                    ))

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

    # -----------------------------------------------------------------------
    # Print per-document table
    # -----------------------------------------------------------------------
    header_fmt = "{:<30} | {:<14} | {:<9} | {:<9} | {:<9} | {:<12}"
    row_fmt    = "{:<30} | {:<14} | {:<9} | {:<9} | {:<9} | {:<12}"
    sep = "-" * 96

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
    scan_acc    = (scan_correct / scan_checked * 100.0) if scan_checked else 0.0
    trust       = (digital_auto_correct / digital_auto_total * 100.0) if digital_auto_total else 100.0

    print("\n" + "=" * 96)
    print("SEPARATE ACCURACY SUMMARY")
    print("=" * 96)
    print(f"Digital PDFs Accuracy:  {digital_acc:.1f}% ({digital_correct}/{digital_checked} fields correct)")
    print(f"  Target: >= 95.0%   {'PASS' if digital_acc >= 95.0 else 'FAIL'}")
    print(f"Digital PDFs in Review: {digital_needs_review} fields flagged for review")
    print(f"Trust Metric (precision of auto): {trust:.1f}% ({digital_auto_correct}/{digital_auto_total} auto facts correct)")
    print(f"  Target: >= 98.0%   {'PASS' if trust >= 98.0 else 'FAIL'}")
    print(f"Case D Scan Accuracy:   {scan_acc:.1f}% ({scan_correct}/{scan_checked} fields correct)")
    print(f"Case D Scan in Review:  {scan_needs_review} fields flagged for review")

    if scan_failures:
        print("\nCase D Scan Discrepancies / Unextracted Fields:")
        for sf in scan_failures:
            print(f"  - {sf}")

    # -----------------------------------------------------------------------
    # Trust metric table
    # -----------------------------------------------------------------------
    print("\n" + "=" * 96)
    print("TRUST METRIC: WRONG / MISSING FIELDS - DIGITAL PDFs")
    print("=" * 96)
    if wrong_fields:
        flagged    = [f for f in wrong_fields if f["status"] == "needs_review"]
        silent     = [f for f in wrong_fields if f["status"] != "needs_review" and f["status"] != "N/A"]
        flag_rate  = len(flagged) / len(wrong_fields) * 100.0 if wrong_fields else 0.0
        crit_silent = [f for f in silent if f["critical"]]

        tm_fmt = "{:<30} | {:<25} | {:<22} | {:<22} | {:<14}"
        print(tm_fmt.format("Document", "Field", "Expected", "Extracted", "Status"))
        print("-" * 115)
        for f in wrong_fields:
            print(tm_fmt.format(
                f["doc"][:30], f["field"][:25], f["expected"][:22],
                f["extracted"][:22], f["status"][:14]
            ))
        print("-" * 115)
        print(f"Total wrong/missing fields:           {len(wrong_fields)}")
        print(f"  Flagged needs_review:               {len(flagged)}")
        print(f"  Silent (auto):                      {len(silent)}")
        print(f"  Flag rate:                          {flag_rate:.0f}%  (target >= 90%)")
        print(f"  Silent errors on money/qty/dates:   {len(crit_silent)}  (target = 0)")
        if crit_silent:
            print("  SILENT CRITICAL ERRORS:")
            for f in crit_silent:
                print(f"    {f['doc']:<30} {f['field']:<22} exp={f['expected']:<15} got={f['extracted']}")
    else:
        print("No wrong fields on digital PDFs.  Perfect score!")

    print("=" * 96 + "\n")


if __name__ == "__main__":
    evaluate_synthetic_documents()
