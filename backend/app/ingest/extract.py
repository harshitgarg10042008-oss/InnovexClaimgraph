import logging
import re as _re
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ingest.locate import locate_source_text
from app.ingest.read import WordBox
from app.ingest.validate import (
    normalize_activity,
    normalize_date,
    normalize_indian_number,
    validate_grand_total,
    validate_gstin,
    validate_line_math,
    validate_lines_sum,
)
from app.llm.client import llm_client
from app.llm.prompts import PROMPT_VERSION, SYSTEM_INJECTION_DEFENSE
from app.models.fact import Fact
from app.schemas.extraction import (
    BankStatementExtraction,
    ChallanExtraction,
    EmailExtraction,
    Extracted,
    InvoiceExtraction,
    POExtraction,
    RemittanceExtraction,
    UdyamCertExtraction,
)

logger = logging.getLogger("claimgraph.ingest.extract")

KIND_SCHEMA_MAP: dict[str, type[BaseModel]] = {
    "PO": POExtraction,
    "CHALLAN": ChallanExtraction,
    "INVOICE": InvoiceExtraction,
    "BANK_STATEMENT": BankStatementExtraction,
    "REMITTANCE": RemittanceExtraction,
    "EMAIL": EmailExtraction,
    "UDYAM_CERT": UdyamCertExtraction,
}

REQUIRED_FIELDS_BY_KIND: dict[str, list[str]] = {
    "CHALLAN": [
        "challan_no",
        "challan_date",
        "po_ref",
        "lines[0].dispatched_qty",
        "lines[0].accepted_qty",
    ],
    "INVOICE": [
        "invoice_no",
        "invoice_date",
        "taxable_total",
        "grand_total",
        "lines[0].qty",
        "lines[0].rate",
    ],
    "PO": [
        "po_no",
        "po_date",
        "credit_days",
        "taxable_total",
        "grand_total",
        "lines[0].qty",
        "lines[0].rate",
    ],
    "BANK_STATEMENT": [
        "period_from",
        "period_to",
        "transactions[0].date",
    ],
    "UDYAM_CERT": [
        "udyam_no",
        "registration_date",
        "enterprise_type",
        "activity",
    ],
    "REMITTANCE": [
        "remittance_date",
        "gross_amount",
        "net_amount",
        "utr",
    ],
    "EMAIL": [
        "communications[0].kind",
        "communications[0].message_date",
    ],
}

# Optional fields: absent value is normal (not an error). Do NOT emit null facts for these.
OPTIONAL_FIELDS_BY_KIND: dict[str, list[str]] = {
    "CHALLAN": [
        "lines[0].rejected_qty",
        "lines[0].item_code",
        "rejection_reason",
        "remarks",
        "stamp_date",
    ],
    "INVOICE": [
        "lines[0].hsn",
        "purchase_order_ref",
        "eway_bill",
    ],
    "PO": [
        "remarks",
        "special_conditions",
    ],
    "BANK_STATEMENT": [
        "transactions[0].credit",
        "transactions[0].debit",
        "transactions[0].balance",
    ],
}


class ExtractedFactItem(BaseModel):
    field_path: str
    raw_value: Any = None
    normalised_value: Any = None
    source_text: str | None = None
    page_no: int = 1
    bbox: list[float] | None = None
    confidence: Decimal = Decimal("0.90")
    status: str = "auto"  # 'auto' or 'needs_review'
    validation_flags: list[str] = []
    extractor_version: str = f"{PROMPT_VERSION}:{settings.LLM_EXTRACT_MODEL}"


def extract_document_facts(
    kind: str,
    full_text: str,
    pages_words: dict[int, list[WordBox]],
    doc_hash: str | None = None,
    page_count: int = 1,
    page_images: list[Path | str | bytes] | None = None,
) -> list[ExtractedFactItem]:
    """Runs LLM extraction for the document kind, locates each field on the page,

    validates types/math, computes confidence, handles vision fallback for scans,
    and produces ExtractedFactItem list with no silent missing required fields.
    """
    schema_cls = KIND_SCHEMA_MAP.get(kind)
    if not schema_cls:
        logger.warning(f"No extraction schema registered for document kind: {kind}")
        return []

    # Collect average OCR confidence across words
    all_words = [wb for word_list in pages_words.values() for wb in word_list]
    ocr_avg_conf = (
        sum(w.confidence for w in all_words) / len(all_words) if all_words else 1.0
    )

    is_image_or_low_conf = (
        ocr_avg_conf < 0.65
        or len(full_text.strip()) < 80
        or (page_images and any(str(p).lower().endswith((".jpg", ".jpeg", ".png")) for p in page_images))
    )

    used_vision = False
    extracted_obj: Any = None

    # Vision fallback: only if explicitly enabled via LLM_VISION_ENABLED=true
    if is_image_or_low_conf and page_images and settings.LLM_VISION_ENABLED:
        try:
            vision_prompt = (
                f"Document Type: {kind}\n"
                f"Extract all facts from this document image according to the schema.\n"
                f"OCR hint text:\n{full_text}"
            )
            extracted_obj = llm_client.complete_vision_json(
                system=SYSTEM_INJECTION_DEFENSE,
                user=vision_prompt,
                image_bytes_or_path=page_images[0],
                pydantic_model=schema_cls,
                model=settings.LLM_VISION_MODEL,
                doc_hash=doc_hash,
                page_no=1,
            )
            if extracted_obj is not None:
                used_vision = True
        except Exception as e:
            logger.info(f"Vision call not used or failed ({e}); falling back to text extraction.")

    # Standard text extraction if vision not used or not available
    if extracted_obj is None:
        user_prompt = (
            f"Document Type: {kind}\n"
            f"Number of Pages: {page_count}\n\n"
            f"Document Text:\n"
            f"---\n{full_text}\n---"
        )
        try:
            extracted_obj = llm_client.complete_json(
                system=SYSTEM_INJECTION_DEFENSE,
                user=user_prompt,
                pydantic_model=schema_cls,
                model=settings.LLM_EXTRACT_MODEL,
                doc_hash=doc_hash,
                page_range=f"1-{page_count}",
            )
        except Exception as e:
            logger.warning(f"Text LLM extraction failed: {e}")

    facts: list[ExtractedFactItem] = []

    if extracted_obj is not None:
        _traverse_and_build_facts(
            data=extracted_obj,
            prefix="",
            pages_words=pages_words,
            ocr_avg_conf=ocr_avg_conf,
            facts=facts,
            is_vision=used_vision,
        )
        # Perform cross-field mathematical validations on document
        _apply_document_math_validations(extracted_obj, facts)

    # Deterministic regex fallback for challan stamp fields the LLM misses.
    # The PDF text layer contains "DATE: DD-MM-YYYY | SIGN: Name" — always prefer this over null.
    if kind == "CHALLAN" and not used_vision:
        _apply_challan_stamp_fallback(full_text, pages_words, ocr_avg_conf, facts)
        _apply_challan_quantity_fallback(full_text, pages_words, ocr_avg_conf, facts)

    # Deterministic fallback for bank statement transaction dates split across PDF table lines.
    if kind == "BANK_STATEMENT" and not used_vision:
        _apply_bank_date_dewrap_fallback(full_text, pages_words, facts)

    # NO SILENT MISSING FIELDS: Check all required fields for this document type
    # Note: Optional fields (rejected_qty, remarks, etc.) must NOT be emitted as null facts.
    req_fields = REQUIRED_FIELDS_BY_KIND.get(kind, [])
    fallback_extractor = (
        f"vision:{settings.LLM_VISION_MODEL}"
        if used_vision
        else f"{PROMPT_VERSION}:{settings.LLM_EXTRACT_MODEL}"
    )

    def _is_required(fp: str) -> bool:
        for rf in req_fields:
            if fp == rf or (rf.startswith("lines[") and fp.endswith(rf.split(".")[-1])):
                return True
        return False

    for rf in req_fields:
        # Match exact path or subfield path (e.g. lines[0].dispatched_qty)
        existing = [
            f for f in facts
            if f.field_path == rf or (rf.startswith("lines[") and f.field_path.endswith(rf.split(".")[-1]))
        ]
        if not existing:
            # Emit missing fact with value null, status needs_review, reason "not found"
            facts.append(
                ExtractedFactItem(
                    field_path=rf,
                    raw_value=None,
                    normalised_value=None,
                    source_text=None,
                    page_no=1,
                    bbox=None,
                    confidence=Decimal("0.00"),
                    status="needs_review",
                    validation_flags=["REQUIRED_FIELD_MISSING: not found"],
                    extractor_version=fallback_extractor,
                )
            )
        else:
            for ef in existing:
                if ef.raw_value is None or str(ef.raw_value).strip() in ("", "None", "null", "-", "—", "–", "N/A", "nil"):
                    ef.raw_value = None
                    ef.normalised_value = None
                    ef.status = "needs_review"
                    if not any("REQUIRED_FIELD_MISSING" in flg for flg in ef.validation_flags):
                        ef.validation_flags.append("REQUIRED_FIELD_MISSING: not found")
                    ef.confidence = Decimal("0.00")

    # Remove any extracted facts for optional fields that have null/empty values
    # (absent optional fields are normal; do not pollute the review queue)
    facts = [
        f for f in facts
        if (f.raw_value is not None and str(f.raw_value).strip() not in ("", "None", "null", "-", "—", "–", "N/A", "nil"))
        or _is_required(f.field_path)
    ]

    return facts


def _traverse_and_build_facts(
    data: Any,
    prefix: str,
    pages_words: dict[int, list[WordBox]],
    ocr_avg_conf: float,
    facts: list[ExtractedFactItem],
    is_vision: bool = False,
) -> None:
    if isinstance(data, Extracted):
        path = prefix.rstrip(".")
        raw_val = data.value
        src_text = data.source_text

        # Standalone dash or empty indicator means absent / null cell
        if raw_val is not None and str(raw_val).strip() in ("-", "—", "–", "N/A", "n/a", "nil", "NIL", "None", "null", ""):
            raw_val = None
            src_text = None

        # 1. Locate source text on pages
        # Avoid bbox sharing for compound ranges like 'Date: 01-06-2026 to 10-07-2026'
        loc_target = src_text
        if raw_val and src_text and "period_" in path.lower() and " to " in src_text.lower():
            loc_target = str(raw_val).strip()
        elif raw_val and src_text and "credit_days" in path.lower():
            loc_target = f"{raw_val} days"

        if raw_val is None or not loc_target:
            loc = locate_source_text(None, pages_words)
        else:
            loc = locate_source_text(loc_target, pages_words)
            if not loc.found and loc_target != src_text:
                loc = locate_source_text(src_text, pages_words)

        # 2. Normalisation and validation
        normalised, val_flags = _normalise_and_validate_field(path, raw_val)

        # 3. Vision vs OCR rules
        if is_vision:
            # Rules: every fact that came from vision model has extractor "vision",
            # is ALWAYS status needs_review, and provenance is whole page (bbox null)
            # unless the quoted text can be located in the OCR words. Never auto-confirm.
            val_flags.append("VISION_EXTRACTED_REVIEW_REQUIRED")
            status = "needs_review"
            bbox = loc.bbox if loc.found else None
            final_conf = Decimal("0.85")
            extractor_ver = f"vision:{settings.LLM_VISION_MODEL}"
        else:
            if not loc.found and raw_val is not None:
                val_flags.append("SOURCE_NOT_FOUND")

            base_conf = loc.match_score * ocr_avg_conf if raw_val is not None else 0.0
            if val_flags:
                base_conf *= 0.7  # Penalty for validation flags
            final_conf = Decimal(str(round(max(0.0, min(1.0, base_conf)), 4)))

            if raw_val is None:
                status = "auto"
                bbox = None
            elif final_conf < Decimal("0.85") or val_flags or not loc.found:
                status = "needs_review"
                bbox = loc.bbox
            else:
                status = "auto"
                bbox = loc.bbox
            extractor_ver = f"{PROMPT_VERSION}:{settings.LLM_EXTRACT_MODEL}"

        facts.append(
            ExtractedFactItem(
                field_path=path,
                raw_value=raw_val,
                normalised_value=normalised,
                source_text=src_text,
                page_no=loc.page_no,
                bbox=bbox,
                confidence=final_conf,
                status=status,
                validation_flags=val_flags,
                extractor_version=extractor_ver,
            )
        )

    elif isinstance(data, BaseModel):
        for field_name, field_val in data:
            new_prefix = f"{prefix}{field_name}." if prefix else f"{field_name}."
            _traverse_and_build_facts(
                data=field_val,
                prefix=new_prefix,
                pages_words=pages_words,
                ocr_avg_conf=ocr_avg_conf,
                facts=facts,
                is_vision=is_vision,
            )

    elif isinstance(data, list):
        for idx, item in enumerate(data):
            base_prefix = prefix.rstrip(".")
            new_prefix = f"{base_prefix}[{idx}]."
            _traverse_and_build_facts(
                data=item,
                prefix=new_prefix,
                pages_words=pages_words,
                ocr_avg_conf=ocr_avg_conf,
                facts=facts,
                is_vision=is_vision,
            )


def _normalise_and_validate_field(
    path: str, raw_val: Any
) -> tuple[Any, list[str]]:
    flags: list[str] = []
    if raw_val is None:
        return None, []

    s_val = str(raw_val).strip()
    if s_val in ("-", "—", "–", "N/A", "n/a", "nil", "NIL", "None", "null", ""):
        return None, []

    p_lower = path.lower()

    # Activity normalisation to fixed vocabulary (manufacturer, service, trader)
    if "activity" in p_lower:
        norm_act, a_flags = normalize_activity(raw_val)
        flags.extend(a_flags)
        return norm_act, flags

    # Dates
    if any(k in p_lower for k in ("date", "period_from", "period_to")):
        norm_date, d_flags = normalize_date(raw_val)
        flags.extend(d_flags)
        return norm_date, flags

    # GSTIN
    if "gstin" in p_lower:
        norm_gstin, g_flags = validate_gstin(raw_val)
        flags.extend(g_flags)
        return norm_gstin, flags

    # Numbers / Amounts / Qty / Rate / Totals
    if any(
        k in p_lower
        for k in (
            "qty",
            "rate",
            "amount",
            "total",
            "gross",
            "net",
            "tds",
            "credit",
            "debit",
            "pct",
        )
    ):
        norm_num, n_flags = normalize_indian_number(raw_val)
        flags.extend(n_flags)
        return (str(norm_num) if norm_num is not None else None), flags

    # Credit days
    if "credit_days" in p_lower:
        try:
            return int(str(raw_val)), []
        except (ValueError, TypeError):
            return None, ["INVALID_INTEGER"]

    return raw_val, []


def _apply_document_math_validations(
    extracted_obj: BaseModel, facts: list[ExtractedFactItem]
) -> None:
    """Performs line math and total reconciliation checks.

    Any amount or quantity failing line math or outside document totals is needs_review.
    """
    if isinstance(extracted_obj, InvoiceExtraction):
        line_amounts: list[Decimal] = []
        for idx, line in enumerate(extracted_obj.lines):
            q, _ = normalize_indian_number(line.qty.value)
            r, _ = normalize_indian_number(line.rate.value)
            a, _ = normalize_indian_number(line.amount.value)
            if q is not None and r is not None and a is not None:
                line_amounts.append(a)
                lm_flags = validate_line_math(q, r, a)
                if lm_flags:
                    _add_flag_to_fact(facts, f"lines[{idx}].amount", lm_flags)
                    _add_flag_to_fact(facts, f"lines[{idx}].qty", lm_flags)
                    _add_flag_to_fact(facts, f"lines[{idx}].rate", lm_flags)

        taxable, _ = normalize_indian_number(extracted_obj.taxable_total.value)
        gst, _ = normalize_indian_number(extracted_obj.gst_amount.value)
        grand, _ = normalize_indian_number(extracted_obj.grand_total.value)

        if taxable is not None and line_amounts:
            sum_flags = validate_lines_sum(line_amounts, taxable)
            if sum_flags:
                _add_flag_to_fact(facts, "taxable_total", sum_flags)
                for idx in range(len(line_amounts)):
                    _add_flag_to_fact(facts, f"lines[{idx}].amount", sum_flags)

        if taxable is not None and gst is not None and grand is not None:
            gt_flags = validate_grand_total(taxable, gst, grand)
            if gt_flags:
                _add_flag_to_fact(facts, "grand_total", gt_flags)
                _add_flag_to_fact(facts, "taxable_total", gt_flags)
                _add_flag_to_fact(facts, "gst_amount", gt_flags)

    elif isinstance(extracted_obj, POExtraction):
        line_amounts: list[Decimal] = []
        for _idx, line in enumerate(extracted_obj.lines):
            q, _ = normalize_indian_number(line.qty.value)
            r, _ = normalize_indian_number(line.rate.value)
            if q is not None and r is not None:
                line_amounts.append(q * r)

        taxable, _ = normalize_indian_number(extracted_obj.taxable_total.value)
        if taxable is not None and line_amounts:
            sum_flags = validate_lines_sum(line_amounts, taxable)
            if sum_flags:
                _add_flag_to_fact(facts, "taxable_total", sum_flags)


def _add_flag_to_fact(
    facts: list[ExtractedFactItem], field_path: str, flags: list[str]
) -> None:
    for fact in facts:
        if fact.field_path == field_path:
            fact.validation_flags.extend(flags)
            fact.status = "needs_review"
            fact.confidence = Decimal(str(round(float(fact.confidence) * 0.7, 4)))


def _apply_challan_stamp_fallback(
    full_text: str,
    pages_words: dict[int, list[WordBox]],
    ocr_avg_conf: float,
    facts: list[ExtractedFactItem],
) -> None:
    """Deterministic regex fallback: reads 'DATE: DD-MM-YYYY | SIGN: Name' from text layer.

    Only fills stamp_text / stamp_date when the LLM returned null for those fields.
    Source of truth is the PDF text, not any LLM output.
    """
    # Pattern: DATE: 20-04-2026 | SIGN: R. Kulkarni
    stamp_pat = _re.compile(
        r"DATE:\s*(\d{2}[-/]\d{2}[-/]\d{4})\s*\|?\s*SIGN:\s*(.+?)(?:\n|$)",
        _re.IGNORECASE,
    )
    m = stamp_pat.search(full_text)
    if not m:
        return

    raw_date = m.group(1).strip()
    raw_sign = m.group(2).strip()

    norm_date, _ = normalize_date(raw_date)

    # stamp_text: fill if null
    stamp_text_fact = next((f for f in facts if f.field_path == "stamp_text"), None)
    if stamp_text_fact is None or stamp_text_fact.raw_value is None:
        loc = locate_source_text(raw_sign, pages_words)
        if stamp_text_fact is None:
            facts.append(ExtractedFactItem(
                field_path="stamp_text",
                raw_value=raw_sign,
                normalised_value=raw_sign,
                source_text=m.group(0).strip(),
                page_no=loc.page_no,
                bbox=loc.bbox,
                confidence=Decimal("0.95"),
                status="auto",
                extractor_version=f"{PROMPT_VERSION}:regex_stamp_fallback",
            ))
        else:
            stamp_text_fact.raw_value = raw_sign
            stamp_text_fact.normalised_value = raw_sign
            stamp_text_fact.source_text = m.group(0).strip()
            stamp_text_fact.confidence = Decimal("0.95")
            stamp_text_fact.status = "auto"
            stamp_text_fact.validation_flags = []
            stamp_text_fact.extractor_version = f"{PROMPT_VERSION}:regex_stamp_fallback"

    # Ensure stamp_date is located in the stamp area (closest to sign vertically), never the header challan_date
    stamp_date_fact = next((f for f in facts if f.field_path == "stamp_date"), None)
    if norm_date and (stamp_date_fact is None or stamp_date_fact.raw_value is None or (stamp_date_fact.bbox and stamp_date_fact.bbox[1] < 0.25)):
        sign_loc = locate_source_text(raw_sign, pages_words)
        all_date_boxes = [w for w_list in pages_words.values() for w in w_list if raw_date in w.text]
        if all_date_boxes and sign_loc.found and sign_loc.bbox:
            stamp_date_box = min(all_date_boxes, key=lambda w: abs(w.bbox[1] - sign_loc.bbox[1]))
            date_bbox = stamp_date_box.bbox
            date_page = sign_loc.page_no
        else:
            loc = locate_source_text(f"DATE: {raw_date}", pages_words)
            date_bbox = loc.bbox if loc.found else None
            date_page = loc.page_no

        if stamp_date_fact is None:
            facts.append(ExtractedFactItem(
                field_path="stamp_date",
                raw_value=raw_date,
                normalised_value=norm_date,
                source_text=m.group(0).strip(),
                page_no=date_page,
                bbox=date_bbox,
                confidence=Decimal("0.95"),
                status="auto",
                extractor_version=f"{PROMPT_VERSION}:regex_stamp_fallback",
            ))
        else:
            stamp_date_fact.raw_value = raw_date
            stamp_date_fact.normalised_value = norm_date
            stamp_date_fact.source_text = m.group(0).strip()
            stamp_date_fact.page_no = date_page
            stamp_date_fact.bbox = date_bbox
            stamp_date_fact.confidence = Decimal("0.95")
            stamp_date_fact.status = "auto"
            stamp_date_fact.validation_flags = []
            stamp_date_fact.extractor_version = f"{PROMPT_VERSION}:regex_stamp_fallback"


def _apply_challan_quantity_fallback(
    full_text: str,
    pages_words: dict[int, list[WordBox]],
    ocr_avg_conf: float,
    facts: list[ExtractedFactItem],
) -> None:
    """Deterministic regex fallback: extracts quantities from 'Supplied Qty: X' and 'RECEIVED (X PCS)' patterns.

    Only fills dispatched_qty and accepted_qty when the LLM returned null for those fields.
    Source of truth is the PDF text, not any LLM output.
    """
    # Pattern 1: Find quantity in table row - ordered qty followed by supplied qty followed by unit
    # E.g., "500\n40\npcs" or "500 40 pcs"
    supplied_pat = _re.compile(r"\d{2,}\s+[\s\r\n]*?(\d+)[\s\r\n]+(?:pcs|units?)", _re.IGNORECASE | _re.MULTILINE)
    # Pattern 2: RECEIVED (40 PCS) - may have line breaks
    received_pat = _re.compile(r"RECEIVED\s*\(\s*(\d+)\s*(?:PCS\s*\)?)", _re.IGNORECASE | _re.MULTILINE)

    supplied_m = supplied_pat.search(full_text)
    received_m = received_pat.search(full_text)

    dispatched_qty_fact = next((f for f in facts if f.field_path == "lines[0].dispatched_qty"), None)
    accepted_qty_fact = next((f for f in facts if f.field_path == "lines[0].accepted_qty"), None)

    if supplied_m and (dispatched_qty_fact is None or dispatched_qty_fact.raw_value is None):
        raw_qty = supplied_m.group(1).strip()
        loc = locate_source_text(raw_qty, pages_words)
        if dispatched_qty_fact is None:
            facts.append(ExtractedFactItem(
                field_path="lines[0].dispatched_qty",
                raw_value=raw_qty,
                normalised_value=raw_qty,
                source_text=supplied_m.group(0).strip(),
                page_no=loc.page_no,
                bbox=loc.bbox,
                confidence=Decimal("0.95"),
                status="auto",
                extractor_version=f"{PROMPT_VERSION}:regex_quantity_fallback",
            ))
        else:
            dispatched_qty_fact.raw_value = raw_qty
            dispatched_qty_fact.normalised_value = raw_qty
            dispatched_qty_fact.source_text = supplied_m.group(0).strip()
            dispatched_qty_fact.confidence = Decimal("0.95")
            dispatched_qty_fact.status = "auto"
            dispatched_qty_fact.validation_flags = []
            dispatched_qty_fact.extractor_version = f"{PROMPT_VERSION}:regex_quantity_fallback"

    if received_m and (accepted_qty_fact is None or accepted_qty_fact.raw_value is None):
        raw_qty = received_m.group(1).strip()
        loc = locate_source_text(raw_qty, pages_words)
        if accepted_qty_fact is None:
            facts.append(ExtractedFactItem(
                field_path="lines[0].accepted_qty",
                raw_value=raw_qty,
                normalised_value=raw_qty,
                source_text=received_m.group(0).strip(),
                page_no=loc.page_no,
                bbox=loc.bbox,
                confidence=Decimal("0.95"),
                status="auto",
                extractor_version=f"{PROMPT_VERSION}:regex_quantity_fallback",
            ))
        else:
            accepted_qty_fact.raw_value = raw_qty
            accepted_qty_fact.normalised_value = raw_qty
            accepted_qty_fact.source_text = received_m.group(0).strip()
            accepted_qty_fact.confidence = Decimal("0.95")
            accepted_qty_fact.status = "auto"
            accepted_qty_fact.validation_flags = []
            accepted_qty_fact.extractor_version = f"{PROMPT_VERSION}:regex_quantity_fallback"


def _apply_bank_date_dewrap_fallback(
    full_text: str,
    pages_words: dict[int, list[WordBox]],
    facts: list[ExtractedFactItem],
) -> None:
    """Re-parses transaction dates that got PDF-wrapped (e.g. '05-06-202' with year on next line).

    The source of truth is the full document text, checking for wrapped trailing year digits.
    """
    for fact in facts:
        if "transaction" in fact.field_path and "date" in fact.field_path:
            raw_s = str(fact.raw_value or "").strip()
            # If 3-digit year like '05-06-202'
            if _re.match(r"^\d{2}[-/]\d{2}[-/]\d{3}$", raw_s):
                m = _re.search(_re.escape(raw_s) + r"\s*\n?\s*(\d)\b", full_text)
                if m:
                    repaired = raw_s + m.group(1)
                    norm, flags = normalize_date(repaired)
                    if norm and "INVALID_DATE_FORMAT" not in flags:
                        fact.raw_value = repaired
                        fact.normalised_value = norm
                        fact.source_text = repaired
                        fact.validation_flags = [f for f in fact.validation_flags if f != "INVALID_DATE_FORMAT"]
                        fact.validation_flags.extend(flags)
                        # Locate exact row in wordboxes
                        for p_no, w_list in pages_words.items():
                            w_idx = next((i for i, w in enumerate(w_list) if w.text.startswith(raw_s)), None)
                            if w_idx is not None:
                                w_obj = w_list[w_idx]
                                next_w = w_list[w_idx + 1] if w_idx + 1 < len(w_list) else w_obj
                                fact.page_no = p_no
                                fact.bbox = [
                                    min(w_obj.bbox[0], next_w.bbox[0]),
                                    min(w_obj.bbox[1], next_w.bbox[1]),
                                    max(w_obj.bbox[2], next_w.bbox[2]),
                                    max(w_obj.bbox[3], next_w.bbox[3]),
                                ]
                                break
                        if not fact.validation_flags:
                            fact.status = "auto"
                            fact.confidence = Decimal("0.90")
            elif fact.raw_value:
                # If transaction date was located in statement header (y < 0.18), re-locate to table row (y >= 0.18)
                if fact.bbox and fact.bbox[1] < 0.18:
                    for p_no, w_list in pages_words.items():
                        match_w = next((w for w in w_list if fact.raw_value in w.text and w.bbox[1] >= 0.18), None)
                        if match_w:
                            fact.page_no = p_no
                            fact.bbox = match_w.bbox


def save_facts_to_db(
    db: Session,
    case_id: Any,
    document_id: Any,
    facts: list[ExtractedFactItem],
) -> list[Fact]:
    """Deletes old facts for document_id and persists new facts into database."""
    db.query(Fact).filter(Fact.document_id == document_id).delete()

    db_facts: list[Fact] = []
    for f in facts:
        val_json = {
            "raw": f.raw_value,
            "normalised": f.normalised_value,
            "source_text": f.source_text,
            "validation_flags": f.validation_flags,
        }
        db_fact = Fact(
            case_id=case_id,
            document_id=document_id,
            page_no=f.page_no,
            field=f.field_path,
            value_json=val_json,
            bbox=f.bbox,
            confidence=f.confidence,
            status=f.status,
            extractor_version=f.extractor_version,
        )
        db.add(db_fact)
        db_facts.append(db_fact)

    db.commit()
    return db_facts
