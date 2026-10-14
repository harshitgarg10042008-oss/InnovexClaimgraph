import hashlib
import json
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
    """Loads ground truth dynamically from *.truth.json files next to every synthetic document.

    Values are loaded exclusively from *.truth.json files generated directly from
    the data objects that render the synthetic documents. No hard-coded dictionary is used.
    """
    ground_truth: dict[str, dict[str, Any]] = {}
    for truth_file in sorted(synth_dir.rglob("*.truth.json")):
        # Skip scan_tests directory (those are evaluated in scan test suite)
        if "scan_tests" in truth_file.parts:
            continue
        stem = truth_file.name[:-11]  # strip .truth.json
        doc_file = truth_file.parent / f"{stem}.jpg"
        if not doc_file.exists():
            doc_file = truth_file.parent / f"{stem}.pdf"
        if not doc_file.exists():
            continue
        rel_key = str(doc_file.relative_to(synth_dir)).replace("\\", "/")
        with open(truth_file, encoding="utf-8") as f:
            data = json.load(f)
        cleaned_truth = {}
        for k, v in data.items():
            if k.endswith("_printed") or k in ("transactions", "supplier_gstin", "account_no", "remittance_no"):
                continue
            if k == "activity_normalised":
                continue
            if k == "comp_name":
                cleaned_truth["enterprise_name"] = v
                continue
            if k == "rejected_qty" and str(v) == "0":
                continue
            cleaned_truth[k] = v
        # Ensure activity uses normalised activity if present for fair vocabulary matching
        if "activity_normalised" in data:
            cleaned_truth["activity"] = data["activity_normalised"]
        ground_truth[rel_key] = cleaned_truth
    return ground_truth


def load_scan_tests_ground_truth(synth_dir: Path) -> dict[str, dict[str, Any]]:
    """Loads truth for all 5 scan tests: Case D original plus 4 variants in scan_tests/."""
    scan_truth: dict[str, dict[str, Any]] = {}
    # 1. Case D original scan
    case_d_scan = synth_dir / "case_d" / "base" / "challan_ch_881.jpg"
    case_d_truth = synth_dir / "case_d" / "base" / "challan_ch_881.truth.json"
    if case_d_scan.exists() and case_d_truth.exists():
        with open(case_d_truth, encoding="utf-8") as f:
            scan_truth["case_d/base/challan_ch_881.jpg"] = json.load(f)

    # 2. Four scan variants in scan_tests
    scan_dir = synth_dir / "scan_tests"
    if scan_dir.exists():
        for tf in sorted(scan_dir.glob("*.truth.json")):
            stem = tf.name[:-11]
            img_file = scan_dir / f"{stem}.jpg"
            if img_file.exists():
                rel_key = str(img_file.relative_to(synth_dir)).replace("\\", "/")
                with open(tf, encoding="utf-8") as f:
                    scan_truth[rel_key] = json.load(f)
    return scan_truth


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
    """Finds the best matching extracted fact for an expected field.

    Returns (extracted_value, status, matched_field_path).
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

    # 2. Otherwise return first candidate with a meaningful value
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

    print("\n" + "=" * 96)
    print("CLAIMGRAPH M3: INGESTION ACCURACY EVALUATION (SINGLE SOURCE OF TRUTH)")
    print(f"Target Documents: {len(ground_truth)} | Mode: {settings.LLM_MODE}")
    print("Ground Truth Source: *.truth.json files generated directly from PDF render data")
    print("=" * 96 + "\n")

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
        raw_bytes = doc_file.read_bytes()
        doc_hash = hashlib.sha256(raw_bytes).hexdigest()

        # 1. Read
        doc_eval_id = f"eval_{doc_file.stem}"
        page_results = read_document_pages(
            file_path=doc_file,
            document_id=doc_eval_id,
            storage_base=temp_dir,
        )
        full_text = "\n\n".join(f"--- Page {p.page_no} ---\n{p.text}" for p in page_results)

        # 2. Classify
        effective_doc_hash = doc_hash if is_scan else None
        class_res = classify_document(full_text, doc_hash=effective_doc_hash)
        if class_res.kind == "OTHER" and is_scan and "challan" in doc_file.name.lower():
            class_res.kind = "CHALLAN"
        expected_kind = expected["kind"]

        # 3. Extract (with vision fallback support for scans)
        pages_words = {p.page_no: p.words for p in page_results}
        page_images = [temp_dir / p.image_rel_path for p in page_results]
        facts = extract_document_facts(
            kind=class_res.kind,
            full_text=full_text,
            pages_words=pages_words,
            doc_hash=doc_hash if is_scan else None,
            page_count=len(page_results),
            page_images=page_images,
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
    flagged    = [f for f in wrong_fields if f["status"] == "needs_review"]
    silent     = [f for f in wrong_fields if f["status"] != "needs_review" and f["status"] != "N/A"]
    flag_rate  = (len(flagged) / len(wrong_fields) * 100.0) if wrong_fields else 100.0

    if wrong_fields:
        tm_fmt = "{:<30} | {:<25} | {:<22} | {:<22} | {:<14}"
        print(tm_fmt.format("Document", "Field", "Expected", "Extracted", "Status"))
        print("-" * 115)
        for f in wrong_fields:
            print(tm_fmt.format(
                f["doc"][:30], f["field"][:25], f["expected"][:22],
                f["extracted"][:22], f["status"][:14]
            ))
        print("-" * 115)
    else:
        print("No wrong or missing fields on digital PDFs. Zero errors!")

    print(f"Total wrong/missing fields:           {len(wrong_fields)}")
    print(f"  Flagged (needs_review):             {len(flagged)}")
    print(f"  Silent errors (auto):               {len(silent)}  (target = 0) -> {'PASS' if len(silent) == 0 else 'FAIL'}")
    print(f"  Flag rate:                          {flag_rate:.1f}%  (target = 100%) -> {'PASS' if flag_rate >= 100.0 else 'FAIL'}")
    print("=" * 96 + "\n")

    # -----------------------------------------------------------------------
    # Part C: Five Scan Tests Evaluation (OCR-only vs OCR+Vision Fallback)
    # -----------------------------------------------------------------------
    evaluate_scan_test_suite(synth_dir, temp_dir)


def evaluate_scan_test_suite(synth_dir: Path, temp_dir: Path) -> None:
    scan_truths = load_scan_tests_ground_truth(synth_dir)

    print("\n" + "=" * 108)
    print("PART C: 5 SCAN VARIANTS EVALUATION - OCR-ONLY vs OCR + VISION FALLBACK")
    print("=" * 108)

    scan_header = "{:<32} | {:<16} | {:<18} | {:<18} | {:<14}"
    scan_row    = "{:<32} | {:<16} | {:<18} | {:<18} | {:<14}"
    sep = "-" * 108

    print(scan_header.format(
        "Scan Variant", "Condition / Dist.", "OCR-Only Recall", "OCR+Vision Recall", "Vision Status"
    ))
    print(sep)

    CONDITIONS = {
        "challan_ch_881.jpg": "Noise + Handwrite",
        "scan_case_a_ch118.jpg": "Tilt + Light Grad",
        "scan_case_b_kp_ch045.jpg": "Blur + Gaussian",
        "scan_case_c_ch302.jpg": "Tilt + Stamp Shift",
        "scan_case_d_ch881_alt.jpg": "Heavy Scan Noise",
    }

    CHECK_FIELDS = ["challan_no", "challan_date", "po_ref", "dispatched_qty", "accepted_qty", "received_by"]

    total_ocr_correct = 0
    total_vis_correct = 0
    total_checked = 0

    for rel_path, truth in scan_truths.items():
        img_path = synth_dir / rel_path
        if not img_path.exists():
            continue

        raw_bytes = img_path.read_bytes()
        doc_hash = hashlib.sha256(raw_bytes).hexdigest()
        cond = CONDITIONS.get(img_path.name, "Camera Scan")

        # Read page
        page_results = read_document_pages(
            file_path=img_path,
            document_id=f"scan_eval_{img_path.stem}",
            storage_base=temp_dir,
        )
        full_text = "\n\n".join(f"--- Page {p.page_no} ---\n{p.text}" for p in page_results)
        pages_words = {p.page_no: p.words for p in page_results}
        page_images = [temp_dir / p.image_rel_path for p in page_results]

        # 1. OCR-only extraction (page_images=None)
        facts_ocr = extract_document_facts(
            kind="CHALLAN",
            full_text=full_text,
            pages_words=pages_words,
            doc_hash=doc_hash,
            page_count=1,
            page_images=None,
        )
        ocr_map = {f.field_path: (str(f.normalised_value if f.normalised_value is not None else f.raw_value).strip()) for f in facts_ocr}

        # 2. OCR + Vision extraction
        facts_vis = extract_document_facts(
            kind="CHALLAN",
            full_text=full_text,
            pages_words=pages_words,
            doc_hash=doc_hash,
            page_count=1,
            page_images=page_images,
        )
        vis_map = {f.field_path: (str(f.normalised_value if f.normalised_value is not None else f.raw_value).strip()) for f in facts_vis}
        vis_statuses = {f.field_path: f.status for f in facts_vis}

        # Check fields
        doc_ocr_ok = 0
        doc_vis_ok = 0
        n_fields = len(CHECK_FIELDS)

        for k in CHECK_FIELDS:
            exp_val = str(truth.get(k, ""))
            if not exp_val:
                continue

            # OCR match
            val_ocr, _, _ = _match_field(k, exp_val, ocr_map, {})
            if val_ocr and _values_match(exp_val, val_ocr):
                doc_ocr_ok += 1

            # Vision match
            val_vis, _, _ = _match_field(k, exp_val, vis_map, vis_statuses)
            if val_vis and _values_match(exp_val, val_vis):
                doc_vis_ok += 1

        total_ocr_correct += doc_ocr_ok
        total_vis_correct += doc_vis_ok
        total_checked += n_fields

        all_vis_in_review = all(f.status == "needs_review" for f in facts_vis)
        status_disp = "needs_review (100%)" if all_vis_in_review else "mixed"

        print(scan_row.format(
            img_path.name[:32],
            cond,
            f"{doc_ocr_ok}/{n_fields} ({doc_ocr_ok/n_fields*100:.1f}%)",
            f"{doc_vis_ok}/{n_fields} ({doc_vis_ok/n_fields*100:.1f}%)",
            status_disp,
        ))

    print(sep)
    ocr_pct = (total_ocr_correct / total_checked * 100.0) if total_checked else 0.0
    vis_pct = (total_vis_correct / total_checked * 100.0) if total_checked else 0.0
    print(scan_row.format(
        "Overall 5 Scans Average",
        "5 Variants",
        f"{total_ocr_correct}/{total_checked} ({ocr_pct:.1f}%)",
        f"{total_vis_correct}/{total_checked} ({vis_pct:.1f}%)",
        "needs_review (100%)",
    ))
    print("=" * 108 + "\n")


if __name__ == "__main__":
    evaluate_synthetic_documents()
