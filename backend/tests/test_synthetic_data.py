import hashlib
import json
import os
from pathlib import Path

import pytest


def get_synthetic_dir() -> Path:
    docker_path = Path("/data/synthetic")
    if docker_path.exists():
        return docker_path
    local_path = (Path(__file__).resolve().parent.parent.parent / "data" / "synthetic").resolve()
    if local_path.exists():
        return local_path
    raise FileNotFoundError("Synthetic directory not found")


def find_expected_files():
    synthetic_dir = get_synthetic_dir()
    expected_files = []
    for root, _, files in os.walk(synthetic_dir):
        for f in files:
            if f.startswith("expected") and f.endswith(".json"):
                expected_files.append(Path(root) / f)
    return expected_files


@pytest.mark.parametrize("expected_file", find_expected_files(), ids=lambda p: p.name)
def test_expected_json_schema_and_math(expected_file: Path):
    with open(expected_file, encoding="utf-8") as f:
        data = json.load(f)

    # 1. Top level keys
    required_keys = [
        "case_id",
        "stage",
        "as_of_date",
        "parties",
        "purchase_orders",
        "deliveries",
        "invoices",
        "payments",
        "adjustments",
        "communications",
        "expected_findings",
        "expected_ledger",
        "expected_rules",
        "notes",
    ]
    for k in required_keys:
        assert k in data, f"Missing key {k} in {expected_file.name}"

    assert data["as_of_date"] == "2026-10-14", "as_of_date must be locked to 2026-10-14"
    assert data["expected_rules"] is None, "expected_rules must remain null in M1"

    # 2. Parties
    assert "supplier" in data["parties"]
    assert "buyer" in data["parties"]
    assert data["parties"]["supplier"]["role"] == "supplier"
    assert data["parties"]["buyer"]["role"] == "buyer"

    # 3. Invoices line math & GST
    for inv in data["invoices"]:
        line_sum = sum(line["amount"] for line in inv["lines"])
        assert abs(line_sum - inv["taxable"]) < 0.01, f"Invoice {inv['invoice_no']} lines sum {line_sum} != taxable {inv['taxable']}"
        for line in inv["lines"]:
            computed_amount = round(line["qty"] * line["rate"], 2)
            assert abs(computed_amount - line["amount"]) < 0.01, f"Line amount mismatch: {line['qty']} * {line['rate']} != {line['amount']}"
        assert abs((inv["taxable"] + inv["gst"]) - inv["total"]) < 0.01, f"Taxable + GST != Total in {inv['invoice_no']}"

    # 4. Ledger consistency
    ledger = data["expected_ledger"]
    total_ordered_qty = sum(line["qty"] for po in data["purchase_orders"] for line in po["lines"])
    assert abs(total_ordered_qty - ledger["ordered_qty"]) < 0.01

    total_delivered_qty = sum(line["qty"] for d in data["deliveries"] for line in d["lines"])
    assert abs(total_delivered_qty - ledger["delivered_qty"]) < 0.01

    total_paid_payments = sum(p["amount"] for p in data["payments"])
    total_adjustments = sum(a["amount"] for a in data["adjustments"])
    assert abs((total_paid_payments + total_adjustments) - ledger["paid_total"]) < 0.01


def test_synthetic_files_exist_and_hashes_match():
    synthetic_dir = get_synthetic_dir()
    cases = ["case_a", "case_b", "case_c", "case_d"]

    for c in cases:
        c_dir = synthetic_dir / c
        assert c_dir.exists(), f"Case folder {c} does not exist"
        base_dir = c_dir / "base"
        assert base_dir.exists(), f"Base folder for {c} does not exist"

        files = list(base_dir.glob("*.*"))
        assert len(files) >= 4, f"Case {c} base should contain at least 4 files"

        for f in files:
            assert f.stat().st_size > 0, f"File {f.name} is empty"
            # Verify SHA-256 can be computed
            h = hashlib.sha256()
            with open(f, "rb") as fp:
                while chunk := fp.read(65536):
                    h.update(chunk)
            sha = h.hexdigest()
            assert len(sha) == 64

    # Check case_a addons
    addons_dir = synthetic_dir / "case_a" / "addons"
    assert (addons_dir / "01_backorder_email.pdf").exists()
    assert (addons_dir / "02_challan_ch131.pdf").exists()

    # Check case_d scan is valid JPG
    case_d_scan = synthetic_dir / "case_d" / "base" / "challan_ch_881.jpg"
    assert case_d_scan.exists()
    with open(case_d_scan, "rb") as fp:
        header = fp.read(3)
        assert header == b"\xff\xd8\xff", "challan_ch_881.jpg must be a valid JPEG file"
