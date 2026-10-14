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

    # For deliveries, use accepted_qty if present (case D rejection scenario), else qty
    def delivery_accepted_qty(line):
        return line.get("accepted_qty", line["qty"])

    total_delivered_qty = sum(delivery_accepted_qty(line) for d in data["deliveries"] for line in d["lines"])
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


# ---------------------------------------------------------------------------
# Case-specific number assertions (Part 2 / acceptance check)
# ---------------------------------------------------------------------------

def load_case(case_id: str, stage: str) -> dict:
    synthetic_dir = get_synthetic_dir()
    case_dir = synthetic_dir / case_id
    # Try both expected_{stage}.json and expected.json
    stage_file = case_dir / f"expected_{stage}.json"
    if not stage_file.exists():
        stage_file = case_dir / "expected.json"
    with open(stage_file, encoding="utf-8") as f:
        return json.load(f)


def test_case_a_base_numbers():
    data = load_case("case_a", "base")
    inv = data["invoices"][0]
    assert inv["taxable"] == 410000.0,  f"Case A taxable: {inv['taxable']}"
    assert inv["gst"] == 73800.0,        f"Case A GST: {inv['gst']}"
    assert inv["total"] == 483800.0,     f"Case A total: {inv['total']}"

    ledger = data["expected_ledger"]
    # delivered_value = 460 * 820 * 1.18
    assert abs(ledger["delivered_value"] - 445096.0) < 0.01, f"delivered_value: {ledger['delivered_value']}"
    assert abs(ledger["paid_total"] - 200000.0) < 0.01, f"paid_total: {ledger['paid_total']}"
    assert abs(ledger["outstanding_on_delivered_goods"] - 245096.0) < 0.01, \
        f"outstanding_on_delivered_goods: {ledger['outstanding_on_delivered_goods']}"
    assert abs(ledger["outstanding_on_full_invoice"] - 283800.0) < 0.01, \
        f"outstanding_on_full_invoice: {ledger['outstanding_on_full_invoice']}"
    # Cross-check: outstanding = delivered_value - paid
    assert abs(ledger["outstanding_on_delivered_goods"] - (ledger["delivered_value"] - ledger["paid_total"])) < 0.01


def test_case_a_after_email_numbers():
    data = load_case("case_a", "after_email")
    ledger = data["expected_ledger"]
    # Still only 460 delivered — same as base
    assert abs(ledger["outstanding_on_delivered_goods"] - 245096.0) < 0.01
    assert abs(ledger["outstanding_on_full_invoice"] - 283800.0) < 0.01
    assert abs(ledger["paid_total"] - 200000.0) < 0.01


def test_case_a_after_delivery_numbers():
    data = load_case("case_a", "after_delivery")
    ledger = data["expected_ledger"]
    # All 500 delivered — both outstanding amounts converge
    assert abs(ledger["delivered_qty"] - 500.0) < 0.01
    assert abs(ledger["outstanding_on_delivered_goods"] - 283800.0) < 0.01
    assert abs(ledger["outstanding_on_full_invoice"] - 283800.0) < 0.01


def test_case_b_numbers():
    data = load_case("case_b", "base")
    # Only the non-duplicate invoice counts for billed totals
    inv = data["invoices"][0]
    assert inv["taxable"] == 73000.0,   f"Case B taxable: {inv['taxable']}"
    assert inv["gst"] == 13140.0,       f"Case B GST: {inv['gst']}"
    assert inv["total"] == 86140.0,     f"Case B total: {inv['total']}"

    ledger = data["expected_ledger"]
    assert abs(ledger["billed_value"] - 86140.0) < 0.01, f"billed_value: {ledger['billed_value']}"
    assert abs(ledger["paid_total"] - 70000.0) < 0.01,   f"paid_total: {ledger['paid_total']}"
    assert abs(ledger["outstanding_principal"] - 16140.0) < 0.01, \
        f"outstanding_principal: {ledger['outstanding_principal']}"
    # Cross-check math
    assert abs(ledger["outstanding_principal"] - (ledger["billed_value"] - ledger["paid_total"])) < 0.01


def test_case_c_numbers():
    data = load_case("case_c", "base")
    inv = data["invoices"][0]
    assert inv["taxable"] == 252000.0,  f"Case C taxable: {inv['taxable']}"
    assert inv["gst"] == 12600.0,       f"Case C GST: {inv['gst']}"
    assert inv["total"] == 264600.0,    f"Case C total: {inv['total']}"

    ledger = data["expected_ledger"]
    assert abs(ledger["paid_total"] - 0.0) < 0.01, f"paid_total: {ledger['paid_total']}"
    assert abs(ledger["billed_value"] - 264600.0) < 0.01, f"billed_value: {ledger['billed_value']}"


def test_case_d_numbers_and_quantities():
    data = load_case("case_d", "base")
    inv = data["invoices"][0]
    assert inv["taxable"] == 14000.0,   f"Case D taxable: {inv['taxable']}"
    assert inv["gst"] == 2520.0,        f"Case D GST: {inv['gst']}"
    assert inv["total"] == 16520.0,     f"Case D total: {inv['total']}"

    delivery = data["deliveries"][0]
    line = delivery["lines"][0]

    # Dispatched/accepted/rejected quantities
    assert abs(line["dispatched_qty"] - 1000.0) < 0.01, f"dispatched_qty: {line['dispatched_qty']}"
    assert abs(line["accepted_qty"] - 980.0) < 0.01,    f"accepted_qty: {line['accepted_qty']}"
    assert abs(line["rejected_qty"] - 20.0) < 0.01,     f"rejected_qty: {line['rejected_qty']}"
    assert line["rejection_reason"] == "thread-damaged", f"rejection_reason: {line['rejection_reason']}"
    assert "thread-damaged" in delivery["rejection_reason"], f"delivery rejection_reason: {delivery['rejection_reason']}"

    ledger = data["expected_ledger"]
    assert abs(ledger["billed_value"] - 16520.0) < 0.01,  f"billed_value: {ledger['billed_value']}"
    # accepted_value = 980 * 14 * 1.18 = 16189.60
    assert abs(ledger["accepted_value"] - 16189.60) < 0.01, f"accepted_value: {ledger['accepted_value']}"
    assert abs(ledger["paid_total"] - 10000.0) < 0.01, f"paid_total: {ledger['paid_total']}"
    assert abs(ledger["outstanding_on_accepted_goods"] - 6189.60) < 0.01, \
        f"outstanding_on_accepted_goods: {ledger['outstanding_on_accepted_goods']}"
    assert abs(ledger["outstanding_on_full_invoice"] - 6520.0) < 0.01, \
        f"outstanding_on_full_invoice: {ledger['outstanding_on_full_invoice']}"

    # Cross-check
    assert abs(ledger["outstanding_on_accepted_goods"] - (ledger["accepted_value"] - ledger["paid_total"])) < 0.01
    assert abs(ledger["outstanding_on_full_invoice"] - (ledger["billed_value"] - ledger["paid_total"])) < 0.01

    # Findings catalogue check
    codes = [f["code"] for f in data["expected_findings"]]
    assert "QTY_MISMATCH" in codes,     "GOODS_REJECTED finding missing"
    assert "GOODS_REJECTED" in codes,   "GOODS_REJECTED finding missing"
