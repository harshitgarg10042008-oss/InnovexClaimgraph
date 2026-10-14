import json
from datetime import datetime
from pathlib import Path


def get_synthetic_dir() -> Path:
    candidates = [
        Path("/data/synthetic"),
        (Path(__file__).resolve().parent.parent.parent / "data" / "synthetic").resolve(),
        Path("data/synthetic").resolve(),
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[1]


def parse_iso(d_str: str | None) -> str | None:
    if not d_str:
        return None
    s = str(d_str).split(",")[0].strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return s


def load_truth_for_case(case_dir: Path) -> dict[str, dict]:
    truths = {}
    for p in case_dir.rglob("*.truth.json"):
        with open(p, encoding="utf-8") as f:
            truths[p.name] = json.load(f)
    return truths


def test_truth_consistency_case_a():
    synth = get_synthetic_dir()
    case_dir = synth / "case_a"
    truths = load_truth_for_case(case_dir)

    with open(case_dir / "expected_base.json", encoding="utf-8") as f:
        exp = json.load(f)

    # 1. Supplier / Udyam consistency
    udyam_t = truths["udyam_certificate.truth.json"]
    assert exp["parties"]["supplier"]["udyam_no"] == udyam_t["udyam_no"]
    assert exp["parties"]["supplier"]["udyam_reg_date"] == udyam_t["registration_date"]
    assert exp["parties"]["supplier"]["gstin"] == udyam_t["supplier_gstin"]
    assert exp["parties"]["supplier"]["activity"].lower() == udyam_t["activity_normalised"].lower()

    # 2. PO consistency
    po_t = truths["PO_MM_PO_2291.truth.json"]
    po_exp = exp["purchase_orders"][0]
    assert po_exp["po_no"] == po_t["po_no"]
    assert po_exp["po_date"] == po_t["po_date"]
    assert po_exp["credit_days_written"] == po_t["credit_days"]
    assert po_exp["lines"][0]["qty"] == float(po_t["qty"])
    assert po_exp["lines"][0]["rate"] == float(po_t["rate"])

    # 3. Challan consistency
    ch_t = truths["CH_118.truth.json"]
    deliv_exp = exp["deliveries"][0]
    assert deliv_exp["challan_no"] == ch_t["challan_no"]
    assert deliv_exp["delivery_date"] == ch_t["challan_date"]
    assert deliv_exp["received_by"] == ch_t["received_by"]
    assert deliv_exp["lines"][0]["qty"] == float(ch_t["dispatched_qty"])

    # 4. Invoice consistency
    inv_t = truths["INV_7731.truth.json"]
    inv_exp = exp["invoices"][0]
    assert inv_exp["invoice_no"] == inv_t["invoice_no"]
    assert inv_exp["invoice_date"] == inv_t["invoice_date"]
    assert inv_exp["taxable"] == float(inv_t["taxable_total"])
    assert inv_exp["gst"] == float(inv_t["gst_amount"])
    assert inv_exp["total"] == float(inv_t["grand_total"])

    # 5. Bank statement payment consistency
    bank_t = truths["bank_statement.truth.json"]
    pay_exp = exp["payments"][0]
    assert pay_exp["utr"] == bank_t["utr"]
    assert pay_exp["amount"] == float(bank_t["credit"])


def test_truth_consistency_case_b():
    synth = get_synthetic_dir()
    case_dir = synth / "case_b"
    truths = load_truth_for_case(case_dir)

    with open(case_dir / "expected.json", encoding="utf-8") as f:
        exp = json.load(f)

    # 1. Supplier / Udyam consistency
    udyam_t = truths["udyam_certificate.truth.json"]
    assert exp["parties"]["supplier"]["udyam_no"] == udyam_t["udyam_no"]
    assert exp["parties"]["supplier"]["udyam_reg_date"] == udyam_t["registration_date"]
    assert exp["parties"]["supplier"]["gstin"] == udyam_t["supplier_gstin"]
    assert exp["parties"]["supplier"]["activity"].lower() == udyam_t["activity_normalised"].lower()

    # 2. PO consistency
    po_t = truths["PO_NF_PO_118.truth.json"]
    po_exp = exp["purchase_orders"][0]
    assert po_exp["po_no"] == po_t["po_no"]
    assert po_exp["po_date"] == po_t["po_date"]
    assert po_exp["credit_days_written"] == po_t["credit_days"]
    assert exp["parties"]["buyer"]["gstin"] == po_t["buyer_gstin"]

    # 3. Challan consistency
    ch_t = truths["KP_CH_045.truth.json"]
    deliv_exp = exp["deliveries"][0]
    assert deliv_exp["challan_no"] == ch_t["challan_no"]
    assert deliv_exp["delivery_date"] == ch_t["challan_date"]
    assert deliv_exp["received_by"] == ch_t["received_by"]
    assert deliv_exp["lines"][0]["qty"] == float(ch_t["dispatched_qty"])

    # 4. Invoice consistency
    inv_t = truths["KP_INV_0412.truth.json"]
    inv_exp = exp["invoices"][0]
    assert inv_exp["invoice_no"] == inv_t["invoice_no"]
    assert inv_exp["invoice_date"] == inv_t["invoice_date"]
    assert inv_exp["taxable"] == float(inv_t["taxable_total"])
    assert inv_exp["gst"] == float(inv_t["gst_amount"])
    assert inv_exp["total"] == float(inv_t["grand_total"])

    # 5. Payments in bank statement
    bank_t = truths["bank_statement.truth.json"]
    utrs_in_bank = {e.get("utr"): float(e.get("credit", 0.0)) for e in bank_t["transactions"] if e.get("utr")}
    for p in exp["payments"]:
        assert p["utr"] in utrs_in_bank
        assert p["amount"] == utrs_in_bank[p["utr"]]


def test_truth_consistency_case_c():
    synth = get_synthetic_dir()
    case_dir = synth / "case_c"
    truths = load_truth_for_case(case_dir)

    with open(case_dir / "expected.json", encoding="utf-8") as f:
        exp = json.load(f)

    # 1. Supplier / Udyam consistency
    udyam_t = truths["udyam_certificate.truth.json"]
    assert exp["parties"]["supplier"]["udyam_no"] == udyam_t["udyam_no"]
    assert exp["parties"]["supplier"]["udyam_reg_date"] == udyam_t["registration_date"]
    assert exp["parties"]["supplier"]["gstin"] == udyam_t["supplier_gstin"]
    assert exp["parties"]["supplier"]["activity"].lower() == udyam_t["activity_normalised"].lower()

    # 2. PO consistency
    po_t = truths["PO_AR_PO_771.truth.json"]
    po_exp = exp["purchase_orders"][0]
    assert po_exp["po_no"] == po_t["po_no"]
    assert po_exp["po_date"] == po_t["po_date"]

    # 3. Challan consistency
    ch_t = truths["CH_302.truth.json"]
    deliv_exp = exp["deliveries"][0]
    assert deliv_exp["challan_no"] == ch_t["challan_no"]
    assert deliv_exp["delivery_date"] == ch_t["challan_date"]
    assert deliv_exp["received_by"] == ch_t["received_by"]

    # 4. Invoice consistency
    inv_t = truths["INV_901.truth.json"]
    inv_exp = exp["invoices"][0]
    assert inv_exp["invoice_no"] == inv_t["invoice_no"]
    assert inv_exp["invoice_date"] == inv_t["invoice_date"]
    assert inv_exp["taxable"] == float(inv_t["taxable_total"])
    assert inv_exp["gst"] == float(inv_t["gst_amount"])
    assert inv_exp["total"] == float(inv_t["grand_total"])


def test_truth_consistency_case_d():
    synth = get_synthetic_dir()
    case_dir = synth / "case_d"
    truths = load_truth_for_case(case_dir)

    with open(case_dir / "expected.json", encoding="utf-8") as f:
        exp = json.load(f)

    # 1. Supplier / Udyam consistency
    udyam_t = truths["udyam_certificate.truth.json"]
    assert exp["parties"]["supplier"]["udyam_no"] == udyam_t["udyam_no"]
    assert exp["parties"]["supplier"]["udyam_reg_date"] == udyam_t["registration_date"]
    assert exp["parties"]["supplier"]["gstin"] == udyam_t["supplier_gstin"]
    assert exp["parties"]["supplier"]["activity"].lower() == udyam_t["activity_normalised"].lower()

    # 2. PO consistency
    po_t = truths["PO_OM_PO_5540.truth.json"]
    po_exp = exp["purchase_orders"][0]
    assert po_exp["po_no"] == po_t["po_no"]
    assert po_exp["po_date"] == po_t["po_date"]

    # 3. Challan consistency (messy scan)
    ch_t = truths["challan_ch_881.truth.json"]
    deliv_exp = exp["deliveries"][0]
    assert deliv_exp["challan_no"] == ch_t["challan_no"]
    assert deliv_exp["delivery_date"] == ch_t["challan_date"]
    assert deliv_exp["received_by"] == ch_t["received_by"]
    line_exp = deliv_exp["lines"][0]
    assert line_exp["qty"] == float(ch_t["accepted_qty"])

    # 4. Invoice consistency
    inv_t = truths["INV_1042.truth.json"]
    inv_exp = exp["invoices"][0]
    assert inv_exp["invoice_no"] == inv_t["invoice_no"]
    assert inv_exp["invoice_date"] == inv_t["invoice_date"]
    assert inv_exp["taxable"] == float(inv_t["taxable_total"])
    assert inv_exp["gst"] == float(inv_t["gst_amount"])
    assert inv_exp["total"] == float(inv_t["grand_total"])

    # 5. Bank statement payment consistency
    bank_t = truths["bank_statement.truth.json"]
    pay_exp = exp["payments"][0]
    assert pay_exp["utr"] == bank_t["utr"]
    assert pay_exp["amount"] == float(bank_t["credit"])
