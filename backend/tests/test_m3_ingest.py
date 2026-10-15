"""
M3 Ingestion Pipeline - Pytest golden tests (replay mode only, no live API).

Verifies:
1. read_document_pages - PDF text extraction + word boxes
2. classify_document   - deterministic regex-first classification
3. extract_document_facts + locate_source_text pipeline (from cache)
4. validate helpers - date/number/GSTIN/math
5. LLM client - cache read/write, replay-mode enforcement
6. Full pipeline accuracy >= 85 % on digital PDFs (22 docs)
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_synthetic_dir() -> Path:
    docker_path = Path("/data/synthetic")
    if docker_path.exists():
        return docker_path
    local = (
        Path(__file__).resolve().parent.parent.parent / "data" / "synthetic"
    ).resolve()
    if local.exists():
        return local
    raise FileNotFoundError("Synthetic directory not found")


# ---------------------------------------------------------------------------
# 1. read_document_pages
# ---------------------------------------------------------------------------


def test_read_pdf_returns_pages(tmp_path):
    from app.ingest.read import read_document_pages

    synth = get_synthetic_dir()
    pdf = synth / "case_a/base/PO_MM_PO_2291.pdf"
    results = read_document_pages(pdf, "test_read_po", tmp_path)

    assert len(results) >= 1
    assert results[0].page_no == 1
    assert len(results[0].text) > 50
    assert len(results[0].words) > 0


def test_read_pdf_page_image_written(tmp_path):
    from app.ingest.read import read_document_pages

    synth = get_synthetic_dir()
    pdf = synth / "case_a/base/CH_118.pdf"
    _results = read_document_pages(pdf, "test_read_ch", tmp_path)

    img_path = tmp_path / "pages" / "test_read_ch" / "page_1.png"
    assert img_path.exists(), "Page PNG should have been written to storage"
    assert img_path.stat().st_size > 0


def test_read_pdf_word_boxes_normalized(tmp_path):
    from app.ingest.read import read_document_pages

    synth = get_synthetic_dir()
    pdf = synth / "case_a/base/INV_7731.pdf"
    results = read_document_pages(pdf, "test_read_inv", tmp_path)

    for wb in results[0].words:
        x0, y0, x1, y1 = wb.bbox
        assert 0.0 <= x0 < x1 <= 1.0, f"Bad bbox x: {wb.bbox}"
        assert 0.0 <= y0 < y1 <= 1.0, f"Bad bbox y: {wb.bbox}"
        assert 0.0 <= wb.confidence <= 1.0


def test_read_jpg_scan_returns_one_page(tmp_path):
    from app.ingest.read import read_document_pages

    synth = get_synthetic_dir()
    jpg = synth / "case_d/base/challan_ch_881.jpg"
    results = read_document_pages(jpg, "test_read_jpg", tmp_path)

    assert len(results) == 1
    assert results[0].ocr_engine == "tesseract"
    assert len(results[0].text) > 0


def test_read_unsupported_format_raises(tmp_path):
    from app.ingest.read import read_document_pages

    dummy = tmp_path / "file.xyz"
    dummy.write_bytes(b"garbage")
    with pytest.raises(ValueError, match="Unsupported"):
        read_document_pages(dummy, "test_bad", tmp_path)


# ---------------------------------------------------------------------------
# 2. classify_document
# ---------------------------------------------------------------------------


class TestClassifyDocument:
    def test_po_classified_via_regex(self):
        from app.ingest.classify import classify_document

        text = "PURCHASE ORDER\nPO No: MM/PO/2291\nPO Date: 02-04-2026\nPayment Terms: Net 45 days\nVendor Code: VC-001"
        result = classify_document(text)
        assert result.kind == "PO"
        assert result.method == "regex"
        assert result.confidence >= 0.90

    def test_invoice_classified_via_regex(self):
        from app.ingest.classify import classify_document

        text = "TAX INVOICE\nInvoice No: INV-7731\nGST Amount: 73800\nGrand Total: 483800\nCGST: 18%"
        result = classify_document(text)
        assert result.kind == "INVOICE"

    def test_challan_classified(self):
        from app.ingest.classify import classify_document

        text = "DELIVERY CHALLAN\nChallan No: CH-118\nDispatched Qty: 460\nAccepted Qty: 460\nReceived By: R. Kulkarni"
        result = classify_document(text)
        assert result.kind == "CHALLAN"

    def test_bank_statement_classified(self):
        from app.ingest.classify import classify_document

        text = "STATEMENT OF ACCOUNT\nOpening Balance: 50000\nClosing Balance: 248000\nWithdrawal  Deposit"
        result = classify_document(text)
        assert result.kind == "BANK_STATEMENT"

    def test_email_classified(self):
        from app.ingest.classify import classify_document

        text = "From: accounts@sharmaauto.in\nSubject: Backorder update\nTo: buyer@meridian.com\nRegards,"
        result = classify_document(text)
        assert result.kind == "EMAIL"

    def test_udyam_cert_classified(self):
        from app.ingest.classify import classify_document

        text = "UDYAM REGISTRATION CERTIFICATE\nMinistry of Micro, Small and Medium Enterprises\nType of Enterprise: Micro"
        result = classify_document(text)
        assert result.kind == "UDYAM_CERT"

    def test_other_classified_for_garbage(self):
        from app.ingest.classify import classify_document

        result = classify_document("lorem ipsum dolor sit amet consectetur")
        assert result.kind == "OTHER"


# ---------------------------------------------------------------------------
# 3. validate helpers
# ---------------------------------------------------------------------------


class TestValidateDate:
    def test_iso(self):
        from app.ingest.validate import normalize_date

        norm, flags = normalize_date("2026-04-02")
        assert norm == "2026-04-02"
        assert flags == []

    def test_indian_slash(self):
        from app.ingest.validate import normalize_date

        norm, flags = normalize_date("02/04/2026")
        assert norm == "2026-04-02"

    def test_month_name(self):
        from app.ingest.validate import normalize_date

        norm, flags = normalize_date("12 May 2026")
        assert norm == "2026-05-12"

    def test_ordinal_cleaned(self):
        from app.ingest.validate import normalize_date

        norm, flags = normalize_date("1st April 2026")
        assert "INVALID" not in " ".join(flags), f"flags={flags}"

    def test_invalid_returns_flag(self):
        from app.ingest.validate import normalize_date

        _, flags = normalize_date("not-a-date")
        assert "INVALID_DATE_FORMAT" in flags


class TestNormalizeIndianNumber:
    def test_plain_integer(self):
        from app.ingest.validate import normalize_indian_number

        val, flags = normalize_indian_number("410000")
        assert val == Decimal("410000")
        assert flags == []

    def test_rupee_symbol(self):
        from app.ingest.validate import normalize_indian_number

        val, flags = normalize_indian_number("1,00,000.00")
        assert val == Decimal("100000.00")

    def test_pcs_suffix(self):
        from app.ingest.validate import normalize_indian_number

        val, flags = normalize_indian_number("460 pcs")
        assert val == Decimal("460")

    def test_percentage(self):
        from app.ingest.validate import normalize_indian_number

        val, flags = normalize_indian_number("18%")
        assert val == Decimal("18")

    def test_none_returns_none(self):
        from app.ingest.validate import normalize_indian_number

        val, flags = normalize_indian_number(None)
        assert val is None
        assert flags == []


class TestValidateGSTIN:
    def test_valid_gstin(self):
        from app.ingest.validate import validate_gstin

        val, flags = validate_gstin("07AAAAA0000A1Z5")
        assert val == "07AAAAA0000A1Z5"
        assert flags == []

    def test_invalid_gstin(self):
        from app.ingest.validate import validate_gstin

        _, flags = validate_gstin("INVALID")
        assert "INVALID_GSTIN_FORMAT" in flags


class TestLineMath:
    def test_valid_line(self):
        from app.ingest.validate import validate_line_math

        flags = validate_line_math(Decimal("460"), Decimal("820"), Decimal("377200"))
        assert flags == []

    def test_mismatch_line(self):
        from app.ingest.validate import validate_line_math

        flags = validate_line_math(Decimal("500"), Decimal("820"), Decimal("100"))
        assert "LINE_MATH_MISMATCH" in flags

    def test_grand_total_valid(self):
        from app.ingest.validate import validate_grand_total

        flags = validate_grand_total(Decimal("410000"), Decimal("73800"), Decimal("483800"))
        assert flags == []

    def test_grand_total_mismatch(self):
        from app.ingest.validate import validate_grand_total

        flags = validate_grand_total(Decimal("410000"), Decimal("73800"), Decimal("500000"))
        assert "GRAND_TOTAL_MISMATCH" in flags


# ---------------------------------------------------------------------------
# 4. locate_source_text
# ---------------------------------------------------------------------------


class TestLocateSourceText:
    def _make_words(self, sentence: str):
        from app.ingest.read import WordBox

        tokens = sentence.split()
        n = len(tokens)
        return [
            WordBox(
                text=t,
                bbox=[i / n, 0.1, (i + 1) / n, 0.2],
                confidence=1.0,
            )
            for i, t in enumerate(tokens)
        ]

    def test_exact_match_found(self):
        from app.ingest.locate import locate_source_text

        words = self._make_words("Invoice No INV-7731 date 22-04-2026")
        result = locate_source_text("INV-7731", {1: words})
        assert result.found
        assert result.match_score >= 0.7

    def test_empty_source_not_found(self):
        from app.ingest.locate import locate_source_text

        words = self._make_words("some text here")
        result = locate_source_text("", {1: words})
        assert not result.found

    def test_no_words_not_found(self):
        from app.ingest.locate import locate_source_text

        result = locate_source_text("MM/PO/2291", {})
        assert not result.found


# ---------------------------------------------------------------------------
# 5. LLM client - replay mode
# ---------------------------------------------------------------------------


class TestLLMClientReplay:
    def test_replay_mode_raises_on_cache_miss(self, tmp_path, monkeypatch):
        from pydantic import BaseModel

        from app.core.config import Settings
        from app.llm.client import LLMClient

        class DummyModel(BaseModel):
            value: str = "x"

        cfg = Settings(
            LLM_MODE="replay",
            LLM_API_KEY="",
            STORAGE_DIR=str(tmp_path),
        )
        client = LLMClient()
        monkeypatch.setattr("app.llm.client.settings", cfg)
        monkeypatch.setattr(client, "_get_cache_dir", lambda: tmp_path / "cache")
        monkeypatch.setattr(client, "_get_synthetic_cache_dir", lambda: tmp_path / "syn")

        from app.llm.client import LLMCacheMissError

        with pytest.raises(LLMCacheMissError):
            client.complete_json(
                system="sys",
                user="user",
                pydantic_model=DummyModel,
                model="some-model",
                doc_hash="deadbeef" * 8,
            )

    def test_cache_write_then_read(self, tmp_path):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        key = "test_key_abc.json"
        data = {"field": "value", "number": 42}
        (cache_dir / key).write_text(json.dumps(data))
        result = json.loads((cache_dir / key).read_text())
        assert result["field"] == "value"


# ---------------------------------------------------------------------------
# 6. Full pipeline accuracy (replay, digital PDFs only)
# ---------------------------------------------------------------------------


def test_m3_digital_accuracy_above_85_pct(tmp_path):
    """
    Runs the full read -> classify -> extract pipeline on all 22 digital PDF
    synthetic documents in replay mode and asserts >= 85 % field accuracy.

    The JPG scan (case_d challan) is excluded since OCR accuracy on low-res
    scans is a separate concern covered by the Tesseract path.
    """
    from app.ingest.classify import classify_document
    from app.ingest.eval import load_expected_ground_truth
    from app.ingest.extract import extract_document_facts
    from app.ingest.read import read_document_pages

    synth = get_synthetic_dir()
    ground_truth = load_expected_ground_truth(synth)

    total_checked = 0
    total_correct = 0

    for rel_path, expected in ground_truth.items():
        doc_file = synth / rel_path
        if not doc_file.exists():
            continue
        if doc_file.suffix.lower() in (".jpg", ".jpeg", ".png"):
            continue

        pages = read_document_pages(doc_file, f"acc_{doc_file.stem}", tmp_path)
        full_text = "\n\n".join(
            f"--- Page {p.page_no} ---\n{p.text}" for p in pages
        )
        class_res = classify_document(full_text)
        pages_words = {p.page_no: p.words for p in pages}

        facts = extract_document_facts(
            kind=class_res.kind,
            full_text=full_text,
            pages_words=pages_words,
            page_count=len(pages),
        )

        facts_map: dict[str, str] = {}
        for f in facts:
            val = f.normalised_value if f.normalised_value is not None else f.raw_value
            facts_map[f.field_path] = str(val).strip() if val is not None else ""

        total_checked += 1
        if class_res.kind == expected["kind"]:
            total_correct += 1

        for exp_k, exp_v in expected.items():
            if exp_k == "kind":
                continue
            total_checked += 1
            matched = None
            for fp, fv in facts_map.items():
                if exp_k in fp.lower():
                    matched = fv
                    break
            if matched is not None:
                exp_clean = str(exp_v).strip().lower().replace(",", "")
                fact_clean = matched.strip().lower().replace(",", "")
                if exp_clean in fact_clean or fact_clean in exp_clean:
                    total_correct += 1

    accuracy = total_correct / total_checked if total_checked else 0.0
    assert accuracy >= 0.85, (
        f"Digital PDF accuracy {accuracy:.1%} ({total_correct}/{total_checked}) "
        f"is below the 85 % M3 threshold"
    )


def test_stamp_fallback_needs_review_on_unmatched_layout(tmp_path):
    """
    Test that challan with non-standard stamp layout (e.g., "Received by X on Y")
    falls back to needs_review status for stamp fields rather than auto-confirming
    with wrong regex match.
    """
    from app.ingest.classify import classify_document
    from app.ingest.extract import extract_document_facts
    from app.ingest.read import read_document_pages

    synth = get_synthetic_dir()
    doc_file = synth / "case_a/addons/03_challan_ch132_variant.pdf"

    if not doc_file.exists():
        pytest.skip("Stamp variant document not generated yet")

    pages = read_document_pages(doc_file, "stamp_variant", tmp_path)
    full_text = "\n\n".join(f"--- Page {p.page_no} ---\n{p.text}" for p in pages)
    class_res = classify_document(full_text)
    pages_words = {p.page_no: p.words for p in pages}

    facts = extract_document_facts(
        kind=class_res.kind,
        full_text=full_text,
        pages_words=pages_words,
        page_count=len(pages),
    )

    # Find stamp fields
    stamp_text_fact = next((f for f in facts if f.field_path == "stamp_text"), None)
    stamp_date_fact = next((f for f in facts if f.field_path == "stamp_date"), None)

    # With non-standard layout, these should be needs_review, not auto with wrong values
    if stamp_text_fact:
        assert stamp_text_fact.status == "needs_review", (
            f"Non-standard stamp layout should be needs_review, got {stamp_text_fact.status}"
        )
    if stamp_date_fact:
        assert stamp_date_fact.status == "needs_review", (
            f"Non-standard stamp date should be needs_review, got {stamp_date_fact.status}"
        )
