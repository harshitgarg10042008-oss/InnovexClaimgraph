import logging
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

    # If this is an image or scan with low confidence, attempt vision fallback first
    if is_image_or_low_conf and page_images:
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

    # NO SILENT MISSING FIELDS: Check all required fields for this document type
    req_fields = REQUIRED_FIELDS_BY_KIND.get(kind, [])
    fallback_extractor = (
        f"vision:{settings.LLM_VISION_MODEL}"
        if used_vision
        else f"{PROMPT_VERSION}:{settings.LLM_EXTRACT_MODEL}"
    )

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
                if ef.raw_value is None or str(ef.raw_value).strip() in ("", "None", "null", "-"):
                    ef.raw_value = None
                    ef.normalised_value = None
                    ef.status = "needs_review"
                    if not any("REQUIRED_FIELD_MISSING" in flg for flg in ef.validation_flags):
                        ef.validation_flags.append("REQUIRED_FIELD_MISSING: not found")
                    ef.confidence = Decimal("0.00")

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

        # 1. Locate source text on pages
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
            if not loc.found:
                val_flags.append("SOURCE_NOT_FOUND")

            base_conf = loc.match_score * ocr_avg_conf
            if val_flags:
                base_conf *= 0.7  # Penalty for validation flags
            final_conf = Decimal(str(round(max(0.0, min(1.0, base_conf)), 4)))

            if final_conf < Decimal("0.85") or val_flags or not loc.found:
                status = "needs_review"
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
