#!/usr/bin/env python3
"""
Deterministically generates synthetic demo documents and expected JSON data for ClaimGraph M1.
Cases:
- Case A: Main demo (mismatch, TDS deduction, backorder addons)
- Case B: Duplicates & advance payment uncredited
- Case C: Ineligible supplier (Udyam registered after PO date)
- Case D: Messy phone scan of challan with quantity gap
"""

import json
import math
import os
from pathlib import Path
import random
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

# Set deterministic seed
random.seed(42)

BASE_DIR = Path(__file__).resolve().parent
STYLE_SHEET = getSampleStyleSheet()

# Reusable custom styles
TITLE_STYLE = ParagraphStyle(
    "DocTitle",
    parent=STYLE_SHEET["Heading1"],
    fontSize=18,
    leading=22,
    textColor=colors.HexColor("#16282B"),
    spaceAfter=6,
)

SUBTITLE_STYLE = ParagraphStyle(
    "DocSubtitle",
    parent=STYLE_SHEET["Normal"],
    fontSize=10,
    leading=14,
    textColor=colors.HexColor("#5B6B73"),
    spaceAfter=12,
)

BODY_STYLE = ParagraphStyle(
    "DocBody",
    parent=STYLE_SHEET["Normal"],
    fontSize=9,
    leading=13,
    textColor=colors.HexColor("#16282B"),
)

BOLD_STYLE = ParagraphStyle(
    "DocBold",
    parent=BODY_STYLE,
    fontName="Helvetica-Bold",
)


def format_inr(val: float) -> str:
    """Format float into Indian Rupee representation without symbol."""
    s = f"{val:.2f}"
    parts = s.split(".")
    integer_part = parts[0]
    decimal_part = parts[1]
    if len(integer_part) > 3:
        last3 = integer_part[-3:]
        rest = integer_part[:-3]
        groups = []
        while len(rest) > 2:
            groups.append(rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.append(rest)
        groups.reverse()
        integer_part = ",".join(groups) + "," + last3
    return f"{integer_part}.{decimal_part}"


def create_pdf(filename: Path, story: list):
    filename.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(filename),
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    doc.build(story)


def make_header(company_name: str, subtitle: str, doc_type: str, doc_no: str, doc_date: str):
    data = [
        [
            Paragraph(f"<b>{company_name}</b><br/>{subtitle}", BODY_STYLE),
            Paragraph(f"<b><font size='14'>{doc_type}</font></b><br/><b>No:</b> {doc_no}<br/><b>Date:</b> {doc_date}", BODY_STYLE),
        ]
    ]
    t = Table(data, colWidths=[3.5 * inch, 3.5 * inch])
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ]
        )
    )
    return t


def make_party_box(buyer_title: str, buyer_info: str, supplier_title: str, supplier_info: str):
    data = [
        [
            Paragraph(f"<b>{buyer_title}:</b><br/>{buyer_info}", BODY_STYLE),
            Paragraph(f"<b>{supplier_title}:</b><br/>{supplier_info}", BODY_STYLE),
        ]
    ]
    t = Table(data, colWidths=[3.5 * inch, 3.5 * inch])
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F6F7F4")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D9DDD6")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D9DDD6")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return t


def make_items_table(headers: list[str], rows: list[list[str]], col_widths: list[float]):
    table_data = [[Paragraph(f"<b>{h}</b>", BOLD_STYLE) for h in headers]]
    for row in rows:
        table_data.append([Paragraph(cell, BODY_STYLE) for cell in row])
    t = Table(table_data, colWidths=col_widths)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F6F7F4")),
                ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#16282B")),
                ("LINEBELOW", (0, 1), (-1, -1), 0.5, colors.HexColor("#D9DDD6")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return t


def make_stamp_box(text: str, border_color="#1E6B57"):
    return Table(
        [[Paragraph(f"<font color='{border_color}'><b>{text}</b></font>", BODY_STYLE)]],
        colWidths=[2.5 * inch],
        style=[
            ("BOX", (0, 0), (-1, -1), 1.5, colors.HexColor(border_color)),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFFFFF")),
        ],
    )


# ==============================================================================
# Document Generation Functions
# ==============================================================================


def gen_udyam_cert(out_path: Path, comp_name: str, udyam_no: str, reg_date: str, ent_type: str, activity: str, gstin: str):
    story = [
        Paragraph("MINISTRY OF MICRO, SMALL & MEDIUM ENTERPRISES", SUBTITLE_STYLE),
        Paragraph("UDYAM REGISTRATION CERTIFICATE", TITLE_STYLE),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#16282B"), spaceAfter=12),
        Paragraph(f"<b>UDYAM REGISTRATION NUMBER:</b> {udyam_no}", BOLD_STYLE),
        Spacer(1, 10),
        make_items_table(
            ["Field", "Details"],
            [
                ["Name of Enterprise", comp_name],
                ["Type of Enterprise", ent_type.capitalize()],
                ["Major Activity", activity.capitalize()],
                ["Date of Registration", reg_date],
                ["GSTIN", gstin],
                ["National Industry Classification (NIC)", "2819 - Manufacture of other general-purpose machinery"],
                ["Official Address", "Plot 42, Industrial Area, Sector 58, India"],
            ],
            [2.5 * inch, 4.5 * inch],
        ),
        Spacer(1, 25),
        Paragraph("<i>* This is a computer generated certificate under MSMED Act 2006. Verification can be done at udyamregistration.gov.in</i>", SUBTITLE_STYLE),
    ]
    create_pdf(out_path, story)


def gen_bank_statement(out_path: Path, comp_name: str, acc_no: str, period: str, entries: list[dict]):
    story = [
        make_header("STATE BANK OF COMMERCE", "Branch: Industrial Estate, Main Road<br/>IFSC: SBOC0001429", "ACCOUNT STATEMENT", acc_no, period),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#16282B"), spaceAfter=10),
        Paragraph(f"<b>Account Holder:</b> {comp_name}<br/><b>Currency:</b> INR", BODY_STYLE),
        Spacer(1, 10),
    ]
    rows = []
    for e in entries:
        rows.append([
            e["date"],
            f"{e['narration']}<br/><font size='7' color='#5B6B73'>Ref/UTR: {e.get('utr', '-')}</font>",
            e.get("chq", "-"),
            format_inr(e.get("debit", 0.0)) if e.get("debit") else "-",
            format_inr(e.get("credit", 0.0)) if e.get("credit") else "-",
            format_inr(e["balance"]),
        ])
    t = make_items_table(
        ["Date", "Narration", "Chq No", "Withdrawal (Dr)", "Deposit (Cr)", "Balance"],
        rows,
        [0.8 * inch, 2.6 * inch, 0.7 * inch, 1.0 * inch, 1.0 * inch, 1.0 * inch],
    )
    story.append(t)
    create_pdf(out_path, story)


# ==============================================================================
# CASE A BUILDER
# ==============================================================================


def build_case_a():
    case_dir = BASE_DIR / "case_a"
    base_dir = case_dir / "base"
    addons_dir = case_dir / "addons"
    base_dir.mkdir(parents=True, exist_ok=True)
    addons_dir.mkdir(parents=True, exist_ok=True)

    supplier_info = "Sharma Auto Components<br/>GSTIN: 07AAAAA0000A1Z5 | PAN: AAAAA0000A<br/>Plot 12, Mayapuri Industrial Area Phase II, New Delhi"
    buyer_info = "Meridian Motors Pvt Ltd<br/>GSTIN: 27BBBBB1111B1Z2 | PAN: BBBBB1111B<br/>Gat 204, Chakan MIDC Phase 3, Pune, Maharashtra"

    # 1. Udyam Certificate
    gen_udyam_cert(
        base_dir / "udyam_certificate.pdf",
        "Sharma Auto Components",
        "UDYAM-DL-01-0012345",
        "12-03-2024",
        "micro",
        "manufacturer",
        "07AAAAA0000A1Z5",
    )

    # 2. Purchase Order MM/PO/2291
    story = [
        make_header("MERIDIAN MOTORS PVT LTD", "Works: Chakan MIDC, Pune<br/>CIN: U34100MH2012PTC229810", "PURCHASE ORDER", "MM/PO/2291", "02-04-2026"),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#16282B"), spaceAfter=10),
        make_party_box("Buyer / Delivery To", buyer_info, "Vendor / Supplier", supplier_info),
        Spacer(1, 12),
        make_items_table(
            ["Item", "Description", "HSN/SAC", "Qty", "Unit", "Rate (Rs)", "Amount (Rs)"],
            [["1", "Brake bracket BB-210 (High tensile steel)", "87082900", "500", "pcs", "820.00", "4,10,000.00"]],
            [0.5 * inch, 2.5 * inch, 0.9 * inch, 0.6 * inch, 0.5 * inch, 0.9 * inch, 1.1 * inch],
        ),
        Spacer(1, 10),
        make_items_table(
            ["Summary", "Amount (Rs)"],
            [
                ["Taxable Value", "4,10,000.00"],
                ["IGST (18.0%)", "73,800.00"],
                ["Total PO Value", "4,83,800.00"],
            ],
            [5.4 * inch, 1.6 * inch],
        ),
        Spacer(1, 15),
        Paragraph("<b>Terms & Conditions:</b><br/>1. Delivery: To Chakan Works within 20 days.<br/>2. Payment Terms: <b>45 days from receipt of goods</b>.<br/>3. Delivery Challan and Test Certificate must accompany consignment.", BODY_STYLE),
    ]
    create_pdf(base_dir / "PO_MM_PO_2291.pdf", story)

    # 3. Delivery Challan CH-118
    story = [
        make_header("SHARMA AUTO COMPONENTS", "Delhi Works: Mayapuri Phase II<br/>Ph: +91-11-28114500", "DELIVERY CHALLAN", "CH-118", "20-04-2026"),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#16282B"), spaceAfter=10),
        make_party_box("Consignee / Buyer", buyer_info, "Consignor / Supplier", supplier_info),
        Spacer(1, 12),
        Paragraph("<b>PO Reference:</b> MM/PO/2291 dated 02-04-2026<br/><b>Vehicle No:</b> DL-1MA-4821 | <b>E-Way Bill:</b> 241088492019", BODY_STYLE),
        Spacer(1, 8),
        make_items_table(
            ["Item", "Description", "HSN", "Ordered Qty", "Supplied Qty", "Unit"],
            [["1", "Brake bracket BB-210", "87082900", "500", "460", "pcs"]],
            [0.5 * inch, 3.0 * inch, 1.0 * inch, 1.0 * inch, 1.0 * inch, 0.5 * inch],
        ),
        Spacer(1, 10),
        Paragraph("<b>Note:</b> Partial shipment of 460 units dispatched. Balance 40 units in machining.", BODY_STYLE),
        Spacer(1, 30),
        make_stamp_box("MERIDIAN MOTORS PVT LTD<br/>SECURITY & STORES CHAKAN<br/>RECEIVED IN GOOD CONDITION (460 PCS)<br/>DATE: 20-04-2026 | SIGN: R. Kulkarni", "#1E6B57"),
    ]
    create_pdf(base_dir / "CH_118.pdf", story)

    # 4. Tax Invoice INV-7731
    story = [
        make_header("SHARMA AUTO COMPONENTS", "Mayapuri Phase II, New Delhi - 110064<br/>Email: accounts@sharmaauto.in", "TAX INVOICE", "INV-7731", "22-04-2026"),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#16282B"), spaceAfter=10),
        make_party_box("Billed To (Buyer)", buyer_info, "Supplier Details", supplier_info),
        Spacer(1, 12),
        Paragraph("<b>PO No:</b> MM/PO/2291 dt. 02-04-2026 | <b>Challan Ref:</b> CH-118 dt. 20-04-2026<br/><b>Payment Due Date:</b> 45 days from delivery", BODY_STYLE),
        Spacer(1, 8),
        make_items_table(
            ["Item", "Description", "HSN", "Qty", "Rate (Rs)", "Taxable (Rs)", "IGST 18%", "Total (Rs)"],
            [["1", "Brake bracket BB-210", "87082900", "500 pcs", "820.00", "4,10,000.00", "73,800.00", "4,83,800.00"]],
            [0.4 * inch, 2.2 * inch, 0.8 * inch, 0.8 * inch, 0.8 * inch, 1.0 * inch, 0.9 * inch, 1.1 * inch],
        ),
        Spacer(1, 10),
        make_items_table(
            ["Total Summary", "Amount (INR)"],
            [
                ["Total Taxable Value", "4,10,000.00"],
                ["Total IGST Amount", "73,800.00"],
                ["Total Invoice Value (in figures)", "4,83,800.00"],
                ["Total Invoice Value (in words)", "Rupees Four Lakh Eighty Three Thousand Eight Hundred Only"],
            ],
            [4.5 * inch, 2.5 * inch],
        ),
        Spacer(1, 20),
        Paragraph("<b>Bank Details for NEFT/RTGS:</b><br/>Bank: State Bank of Commerce | A/C No: 10492810029 | IFSC: SBOC0001429", BODY_STYLE),
    ]
    create_pdf(base_dir / "INV_7731.pdf", story)

    # 5. Bank Statement
    gen_bank_statement(
        base_dir / "bank_statement.pdf",
        "Sharma Auto Components",
        "A/C 10492810029",
        "01-06-2026 to 10-07-2026",
        [
            {"date": "05-06-2026", "narration": "OPENING BALANCE", "balance": 142500.00},
            {"date": "15-06-2026", "narration": "NEFT-RAW MATERIAL STEEL-RAW/881", "debit": 85000.00, "balance": 57500.00},
            {"date": "30-06-2026", "narration": "CMS/PART PAY INV-7731/MERIDIAN MOTORS PVT LTD", "utr": "UTRB26181049281", "credit": 198000.00, "balance": 255500.00},
            {"date": "05-07-2026", "narration": "ELECTRICITY BILL TPDDL", "debit": 18200.00, "balance": 237300.00},
        ],
    )

    # 6. Remittance Advice
    story = [
        make_header("MERIDIAN MOTORS PVT LTD", "Finance & Accounts Department, Chakan MIDC", "PAYMENT REMITTANCE ADVICE", "REM-2026-0881", "30-06-2026"),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#16282B"), spaceAfter=10),
        Paragraph(f"<b>To:</b> Sharma Auto Components<br/><b>Vendor Code:</b> V-4019<br/><b>Payment Mode:</b> RTGS / CMS | <b>UTR:</b> UTRB26181049281 | <b>Date:</b> 30-06-2026", BODY_STYLE),
        Spacer(1, 12),
        make_items_table(
            ["Invoice No", "Invoice Date", "Invoice Total (Rs)", "Gross Passed (Rs)", "TDS Sec 194Q 1% (Rs)", "Net Paid (Rs)"],
            [["INV-7731", "22-04-2026", "4,83,800.00", "2,00,000.00", "2,000.00", "1,98,000.00"]],
            [1.0 * inch, 1.0 * inch, 1.3 * inch, 1.3 * inch, 1.3 * inch, 1.1 * inch],
        ),
        Spacer(1, 15),
        Paragraph("<b>Remarks:</b> Part payment approved against accepted material. TDS Form 16A will be issued quarterly.", BODY_STYLE),
    ]
    create_pdf(base_dir / "remittance_advice.pdf", story)

    # ADDONS 1: Email Thread PDF
    story = [
        Paragraph("<b>From:</b> accounts@sharmaauto.in<br/><b>To:</b> purchase.chakan@meridianmotors.com<br/><b>Date:</b> 25 Apr 2026, 11:42 AM<br/><b>Subject:</b> Re: Partial Delivery Challan CH-118 against PO MM/PO/2291", BODY_STYLE),
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#D9DDD6"), spaceAfter=10),
        Paragraph("""Dear Mr. Kulkarni,<br/><br/>
Thank you for confirming receipt of 460 units of Brake bracket BB-210 under Challan CH-118 on 20-04-2026.<br/>
As discussed, our induction furnace was under scheduled maintenance, so the balance 40 units were held up.<br/>
We confirm that the remaining 40 units are on backorder and will be dispatched by 10-05-2026 without fail.<br/><br/>
Regards,<br/>
Rakesh Sharma<br/>
Sharma Auto Components
""", BODY_STYLE),
        Spacer(1, 15),
        Paragraph("""<i>--- Original Message ---<br/>
From: purchase.chakan@meridianmotors.com<br/>
Date: 24 Apr 2026, 04:15 PM<br/>
To: accounts@sharmaauto.in<br/>
Subject: Partial Delivery Challan CH-118 against PO MM/PO/2291<br/><br/>
We have verified delivery of 460 pcs against PO MM/PO/2291. Please update status on remaining 40 units.</i>
""", SUBTITLE_STYLE),
    ]
    create_pdf(addons_dir / "01_backorder_email.pdf", story)

    # ADDONS 2: Challan CH-131 PDF
    story = [
        make_header("SHARMA AUTO COMPONENTS", "Delhi Works: Mayapuri Phase II<br/>Ph: +91-11-28114500", "DELIVERY CHALLAN", "CH-131", "09-05-2026"),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#16282B"), spaceAfter=10),
        make_party_box("Consignee / Buyer", buyer_info, "Consignor / Supplier", supplier_info),
        Spacer(1, 12),
        Paragraph("<b>PO Reference:</b> MM/PO/2291 dated 02-04-2026<br/><b>Delivery Note:</b> Balance consignment against Backorder<br/><b>Vehicle No:</b> DL-1MA-2201", BODY_STYLE),
        Spacer(1, 8),
        make_items_table(
            ["Item", "Description", "HSN", "Ordered Qty", "Supplied Qty", "Unit"],
            [["1", "Brake bracket BB-210 (Balance backorder qty)", "87082900", "500", "40", "pcs"]],
            [0.5 * inch, 3.0 * inch, 1.0 * inch, 1.0 * inch, 1.0 * inch, 0.5 * inch],
        ),
        Spacer(1, 30),
        make_stamp_box("MERIDIAN MOTORS PVT LTD<br/>STORES CHAKAN - RECEIVED (40 PCS)<br/>TOTAL PO FULFILLED (500/500)<br/>DATE: 09-05-2026 | SIGN: R. Kulkarni", "#1E6B57"),
    ]
    create_pdf(addons_dir / "02_challan_ch131.pdf", story)

    # JSON 1: expected_base.json
    base_json = {
        "case_id": "case_a",
        "stage": "base",
        "as_of_date": "2026-10-14",
        "parties": {
            "supplier": {
                "name": "Sharma Auto Components",
                "role": "supplier",
                "gstin": "07AAAAA0000A1Z5",
                "pan": "AAAAA0000A",
                "udyam_no": "UDYAM-DL-01-0012345",
                "udyam_reg_date": "2024-03-12",
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
        "purchase_orders": [
            {
                "po_no": "MM/PO/2291",
                "po_date": "2026-04-02",
                "credit_days_written": 45,
                "lines": [{"item_key": "BB-210", "description": "Brake bracket BB-210", "qty": 500.0, "unit": "pcs", "rate": 820.00}],
            }
        ],
        "deliveries": [
            {
                "challan_no": "CH-118",
                "delivery_date": "2026-04-20",
                "received_by": "R. Kulkarni",
                "lines": [{"item_key": "BB-210", "qty": 460.0}],
            }
        ],
        "invoices": [
            {
                "invoice_no": "INV-7731",
                "invoice_date": "2026-04-22",
                "gstin_s": "07AAAAA0000A1Z5",
                "gstin_b": "27BBBBB1111B1Z2",
                "taxable": 410000.00,
                "gst": 73800.00,
                "total": 483800.00,
                "lines": [{"item_key": "BB-210", "qty": 500.0, "rate": 820.00, "amount": 410000.00}],
            }
        ],
        "payments": [
            {
                "utr": "UTRB26181049281",
                "pay_date": "2026-06-30",
                "amount": 198000.00,
                "bank_ref_text": "CMS/PART PAY INV-7731/MERIDIAN MOTORS PVT LTD",
            }
        ],
        "adjustments": [
            {
                "kind": "tds",
                "amount": 2000.00,
                "ref": "TDS u/s 194Q per remittance advice REM-2026-0881",
            }
        ],
        "communications": [],
        "expected_findings": [
            {
                "code": "QTY_MISMATCH",
                "severity": "warn",
                "message": "Delivered 460 of 500 billed units (shortfall of 40 units)",
            },
            {
                "code": "TDS_DEDUCTION",
                "severity": "info",
                "message": "TDS of Rs 2,000.00 deducted by buyer credited against claimable principal",
            },
        ],
        "expected_ledger": {
            "ordered_qty": 500.0,
            "delivered_qty": 460.0,
            "billed_qty": 500.0,
            "billed_value": 483800.00,
            "paid_total": 200000.00,
            "outstanding_principal": 245096.00,
        },
        "expected_rules": None,
        "notes": "Base scenario: 460 of 500 units delivered; claimable delivered value is 4,45,096.00. Paid 1,98,000 + 2,000 TDS = 2,00,000. Outstanding principal = 2,45,096.00.",
    }
    with open(case_dir / "expected_base.json", "w", encoding="utf-8") as f:
        json.dump(base_json, f, indent=2)

    # JSON 2: expected_after_email.json
    email_json = json.loads(json.dumps(base_json))
    email_json["stage"] = "after_email"
    email_json["communications"] = [
        {
            "msg_date": "2026-04-25",
            "sender": "accounts@sharmaauto.in",
            "kind": "backorder",
            "quote": "We confirm that the remaining 40 units are on backorder and will be dispatched by 10-05-2026 without fail.",
        }
    ]
    email_json["expected_findings"].append({
        "code": "BACKORDER_PENDING",
        "severity": "warn",
        "message": "40 units promised on backorder by 10-05-2026; delivery proof pending",
    })
    email_json["notes"] = "Email confirms 40 units on backorder but NOT yet delivered; claimable principal remains on 460 delivered units: 2,45,096.00."
    with open(case_dir / "expected_after_email.json", "w", encoding="utf-8") as f:
        json.dump(email_json, f, indent=2)

    # JSON 3: expected_after_delivery.json
    deliv_json = json.loads(json.dumps(email_json))
    deliv_json["stage"] = "after_delivery"
    deliv_json["deliveries"].append({
        "challan_no": "CH-131",
        "delivery_date": "2026-05-09",
        "received_by": "R. Kulkarni",
        "lines": [{"item_key": "BB-210", "qty": 40.0}],
    })
    # Remove QTY_MISMATCH and BACKORDER_PENDING
    deliv_json["expected_findings"] = [
        f for f in deliv_json["expected_findings"]
        if f["code"] not in ("QTY_MISMATCH", "BACKORDER_PENDING")
    ]
    deliv_json["expected_ledger"]["delivered_qty"] = 500.0
    deliv_json["expected_ledger"]["outstanding_principal"] = 283800.00
    deliv_json["notes"] = "All 500 units delivered and evidenced. Outstanding principal recomputed on full invoice: 4,83,800.00 - 2,00,000.00 = 2,83,800.00."
    with open(case_dir / "expected_after_delivery.json", "w", encoding="utf-8") as f:
        json.dump(deliv_json, f, indent=2)


# ==============================================================================
# CASE B BUILDER
# ==============================================================================


def build_case_b():
    case_dir = BASE_DIR / "case_b"
    base_dir = case_dir / "base"
    base_dir.mkdir(parents=True, exist_ok=True)

    supplier_info = "Kaveri Packaging Works<br/>GSTIN: 29CCCCC2222C1Z8 | PAN: CCCCC2222C<br/>Peenya Industrial Area 2nd Stage, Bengaluru, Karnataka"
    buyer_info = "Northline Foods Ltd<br/>GSTIN: 06DDDDD3333D1Z1 | PAN: DDDDD3333D<br/>Plot 14, Kundli Food Park, Sonipat, Haryana"

    # Udyam Certificate
    gen_udyam_cert(
        base_dir / "udyam_certificate.pdf",
        "Kaveri Packaging Works",
        "UDYAM-KA-02-0054321",
        "01-08-2023",
        "small",
        "manufacturer",
        "29CCCCC2222C1Z8",
    )

    # PO NF/PO/118
    story = [
        make_header("NORTHLINE FOODS LTD", "Procurement Division, Kundli, Haryana<br/>CIN: L15100HR2015PLC044120", "PURCHASE ORDER", "NF/PO/118", "05-03-2026"),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#16282B"), spaceAfter=10),
        make_party_box("Buyer / Billed To", buyer_info, "Supplier", supplier_info),
        Spacer(1, 12),
        make_items_table(
            ["Item", "Description", "HSN/SAC", "Qty", "Unit", "Rate (Rs)", "Amount (Rs)"],
            [["1", "Corrugated master cartons 5-ply (food grade)", "48191010", "2000", "pcs", "36.50", "73,000.00"]],
            [0.5 * inch, 2.7 * inch, 0.9 * inch, 0.6 * inch, 0.5 * inch, 0.7 * inch, 1.1 * inch],
        ),
        Spacer(1, 10),
        make_items_table(
            ["Summary", "Amount (Rs)"],
            [
                ["Taxable Value", "73,000.00"],
                ["IGST (18.0%)", "13,140.00"],
                ["Total PO Amount", "86,140.00"],
            ],
            [5.4 * inch, 1.6 * inch],
        ),
        Spacer(1, 15),
        Paragraph("<b>Terms:</b><br/>1. Payment: <b>30 days credit</b> from delivery date.<br/>2. Advance of Rs 20,000.00 payable with order against proforma.", BODY_STYLE),
    ]
    create_pdf(base_dir / "PO_NF_PO_118.pdf", story)

    # Challan KP/CH/045
    story = [
        make_header("KAVERI PACKAGING WORKS", "Peenya Industrial Area, Bengaluru<br/>Tel: +91-80-28394411", "DELIVERY CHALLAN", "KP/CH/045", "18-03-2026"),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#16282B"), spaceAfter=10),
        make_party_box("Consignee", buyer_info, "Consignor", supplier_info),
        Spacer(1, 12),
        Paragraph("<b>Against PO:</b> NF/PO/118 dt. 05-03-2026 | <b>Transporter:</b> VRL Logistics (LR-881920)", BODY_STYLE),
        Spacer(1, 8),
        make_items_table(
            ["Item", "Description", "HSN", "Qty Supplied", "Unit"],
            [["1", "Corrugated master cartons 5-ply", "48191010", "2000", "pcs"]],
            [0.5 * inch, 3.5 * inch, 1.0 * inch, 1.0 * inch, 1.0 * inch],
        ),
        Spacer(1, 30),
        make_stamp_box("NORTHLINE FOODS LTD<br/>CENTRAL WAREHOUSE KUNDLI<br/>VERIFIED & STAMPED (2000 PCS)<br/>DATE: 18-03-2026 | STAMP: VERIFIED", "#1E6B57"),
    ]
    create_pdf(base_dir / "KP_CH_045.pdf", story)

    # Invoice KP/INV/0412
    story = [
        make_header("KAVERI PACKAGING WORKS", "Peenya Phase 2, Bengaluru - 560058", "TAX INVOICE", "KP/INV/0412", "19-03-2026"),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#16282B"), spaceAfter=10),
        make_party_box("Buyer (Bill To)", buyer_info, "Supplier Details", supplier_info),
        Spacer(1, 12),
        Paragraph("<b>PO Ref:</b> NF/PO/118 | <b>Challan Ref:</b> KP/CH/045 dt. 18-03-2026", BODY_STYLE),
        Spacer(1, 8),
        make_items_table(
            ["Item", "Description", "HSN", "Qty", "Rate (Rs)", "Taxable (Rs)", "IGST 18%", "Total (Rs)"],
            [["1", "Corrugated master cartons 5-ply", "48191010", "2000 pcs", "36.50", "73,000.00", "13,140.00", "86,140.00"]],
            [0.4 * inch, 2.2 * inch, 0.8 * inch, 0.8 * inch, 0.8 * inch, 1.0 * inch, 0.9 * inch, 1.1 * inch],
        ),
        Spacer(1, 10),
        make_items_table(
            ["Total", "Amount (Rs)"],
            [
                ["Total Taxable", "73,000.00"],
                ["Total IGST", "13,140.00"],
                ["Net Payable", "86,140.00"],
            ],
            [5.0 * inch, 2.0 * inch],
        ),
        Spacer(1, 15),
        Paragraph("<i>Note: Advance of Rs 20,000.00 received on 01-03-2026 not deducted on invoice face.</i>", SUBTITLE_STYLE),
    ]
    create_pdf(base_dir / "KP_INV_0412.pdf", story)

    # Duplicate Invoice KP/INV/0412-A
    story_dup = [
        make_header("KAVERI PACKAGING WORKS", "Peenya Phase 2, Bengaluru - 560058", "TAX INVOICE", "KP/INV/0412-A", "28-03-2026"),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#16282B"), spaceAfter=10),
        make_party_box("Buyer (Bill To)", buyer_info, "Supplier Details", supplier_info),
        Spacer(1, 12),
        Paragraph("<b>PO Ref:</b> NF/PO/118 | <b>Challan Ref:</b> KP/CH/045 dt. 18-03-2026", BODY_STYLE),
        Spacer(1, 8),
        make_items_table(
            ["Item", "Description", "HSN", "Qty", "Rate (Rs)", "Taxable (Rs)", "IGST 18%", "Total (Rs)"],
            [["1", "Corrugated master cartons 5-ply", "48191010", "2000 pcs", "36.50", "73,000.00", "13,140.00", "86,140.00"]],
            [0.4 * inch, 2.2 * inch, 0.8 * inch, 0.8 * inch, 0.8 * inch, 1.0 * inch, 0.9 * inch, 1.1 * inch],
        ),
        Spacer(1, 10),
        make_items_table(
            ["Total", "Amount (Rs)"],
            [
                ["Total Taxable", "73,000.00"],
                ["Total IGST", "13,140.00"],
                ["Net Payable", "86,140.00"],
            ],
            [5.0 * inch, 2.0 * inch],
        ),
    ]
    create_pdf(base_dir / "KP_INV_0412_A.pdf", story_dup)

    # Bank statement showing advance and part payment
    gen_bank_statement(
        base_dir / "bank_statement.pdf",
        "Kaveri Packaging Works",
        "A/C 22910048102",
        "01-03-2026 to 15-05-2026",
        [
            {"date": "01-03-2026", "narration": "NEFT ADVANCE FOR PO NF/PO/118 - NORTHLINE FOODS", "utr": "UTRNF2606010029", "credit": 20000.00, "balance": 45000.00},
            {"date": "15-04-2026", "narration": "WAGES PEENYA FACTORY", "debit": 25000.00, "balance": 20000.00},
            {"date": "02-05-2026", "narration": "RTGS PART PAYMENT INV KP/INV/0412 - NORTHLINE FOODS", "utr": "UTRNF2612204891", "credit": 50000.00, "balance": 70000.00},
        ],
    )

    # expected.json for Case B
    expected_b = {
        "case_id": "case_b",
        "stage": "base",
        "as_of_date": "2026-10-14",
        "parties": {
            "supplier": {
                "name": "Kaveri Packaging Works",
                "role": "supplier",
                "gstin": "29CCCCC2222C1Z8",
                "pan": "CCCCC2222C",
                "udyam_no": "UDYAM-KA-02-0054321",
                "udyam_reg_date": "2023-08-01",
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
        "purchase_orders": [
            {
                "po_no": "NF/PO/118",
                "po_date": "2026-03-05",
                "credit_days_written": 30,
                "lines": [{"item_key": "CTN-5PLY", "description": "Corrugated master cartons 5-ply", "qty": 2000.0, "unit": "pcs", "rate": 36.50}],
            }
        ],
        "deliveries": [
            {
                "challan_no": "KP/CH/045",
                "delivery_date": "2026-03-18",
                "received_by": "Stores Kundli",
                "lines": [{"item_key": "CTN-5PLY", "qty": 2000.0}],
            }
        ],
        "invoices": [
            {
                "invoice_no": "KP/INV/0412",
                "invoice_date": "2026-03-19",
                "gstin_s": "29CCCCC2222C1Z8",
                "gstin_b": "06DDDDD3333D1Z1",
                "taxable": 73000.00,
                "gst": 13140.00,
                "total": 86140.00,
                "lines": [{"item_key": "CTN-5PLY", "qty": 2000.0, "rate": 36.50, "amount": 73000.00}],
            },
            {
                "invoice_no": "KP/INV/0412-A",
                "invoice_date": "2026-03-28",
                "gstin_s": "29CCCCC2222C1Z8",
                "gstin_b": "06DDDDD3333D1Z1",
                "taxable": 73000.00,
                "gst": 13140.00,
                "total": 86140.00,
                "lines": [{"item_key": "CTN-5PLY", "qty": 2000.0, "rate": 36.50, "amount": 73000.00}],
            },
        ],
        "payments": [
            {
                "utr": "UTRNF2606010029",
                "pay_date": "2026-03-01",
                "amount": 20000.00,
                "bank_ref_text": "NEFT ADVANCE FOR PO NF/PO/118 - NORTHLINE FOODS",
            },
            {
                "utr": "UTRNF2612204891",
                "pay_date": "2026-05-02",
                "amount": 50000.00,
                "bank_ref_text": "RTGS PART PAYMENT INV KP/INV/0412 - NORTHLINE FOODS",
            },
        ],
        "adjustments": [],
        "communications": [],
        "expected_findings": [
            {
                "code": "DUPLICATE_INVOICE",
                "severity": "blocker",
                "message": "Duplicate invoice KP/INV/0412-A re-billed for same delivery KP/CH/045",
            },
            {
                "code": "UNCREDITED_PAYMENT",
                "severity": "warn",
                "message": "Advance payment of Rs 20,000.00 received on 01-03-2026 not credited against invoice face",
            },
        ],
        "expected_ledger": {
            "ordered_qty": 2000.0,
            "delivered_qty": 2000.0,
            "billed_qty": 2000.0,
            "billed_value": 86140.00,
            "paid_total": 70000.00,
            "outstanding_principal": 16140.00,
        },
        "expected_rules": None,
        "notes": "Case B: Duplicate invoice flagged. Advance payment Rs 20,000 + part payment Rs 50,000 = Rs 70,000 credited against undisputed invoice total Rs 86,140. Outstanding principal = Rs 16,140.00.",
    }
    with open(case_dir / "expected.json", "w", encoding="utf-8") as f:
        json.dump(expected_b, f, indent=2)


# ==============================================================================
# CASE C BUILDER (Ineligible Supplier)
# ==============================================================================


def build_case_c():
    case_dir = BASE_DIR / "case_c"
    base_dir = case_dir / "base"
    base_dir.mkdir(parents=True, exist_ok=True)

    supplier_info = "Tara Textiles<br/>GSTIN: 24EEEEE4444E1Z4 | PAN: EEEEE4444E<br/>GIDC Industrial Estate, Surat, Gujarat"
    buyer_info = "Ashoka Retail Pvt Ltd<br/>GSTIN: 27FFFFF5555F1Z7 | PAN: FFFFF5555F<br/>Lower Parel, Mumbai, Maharashtra"

    # Udyam Certificate showing date 20-05-2026 (AFTER PO date 10-03-2026!)
    gen_udyam_cert(
        base_dir / "udyam_certificate.pdf",
        "Tara Textiles",
        "UDYAM-GJ-03-0098765",
        "20-05-2026",
        "micro",
        "manufacturer",
        "24EEEEE4444E1Z4",
    )

    # PO AR/PO/771 dated 10-03-2026
    story = [
        make_header("ASHOKA RETAIL PVT LTD", "Corporate Sourcing, Lower Parel, Mumbai", "PURCHASE ORDER", "AR/PO/771", "10-03-2026"),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#16282B"), spaceAfter=10),
        make_party_box("Buyer", buyer_info, "Supplier", supplier_info),
        Spacer(1, 12),
        make_items_table(
            ["Item", "Description", "HSN", "Qty", "Unit", "Rate (Rs)", "Amount (Rs)"],
            [["1", "Premium cotton shirting fabric (60s count)", "52081190", "1200", "metres", "210.00", "2,52,000.00"]],
            [0.5 * inch, 2.7 * inch, 0.9 * inch, 0.6 * inch, 0.6 * inch, 0.7 * inch, 1.0 * inch],
        ),
        Spacer(1, 10),
        make_items_table(
            ["Summary", "Amount (Rs)"],
            [
                ["Taxable Value", "2,52,000.00"],
                ["IGST (5.0%)", "12,600.00"],
                ["Total PO Value", "2,64,600.00"],
            ],
            [5.0 * inch, 2.0 * inch],
        ),
        Spacer(1, 15),
        Paragraph("<b>Credit Period:</b> 30 days from delivery.", BODY_STYLE),
    ]
    create_pdf(base_dir / "PO_AR_PO_771.pdf", story)

    # Challan CH-302 dated 25-03-2026
    story = [
        make_header("TARA TEXTILES", "Surat Mills: GIDC, Surat, Gujarat", "DELIVERY CHALLAN", "CH-302", "25-03-2026"),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#16282B"), spaceAfter=10),
        make_party_box("Consignee", buyer_info, "Consignor", supplier_info),
        Spacer(1, 12),
        Paragraph("<b>PO Reference:</b> AR/PO/771 dated 10-03-2026", BODY_STYLE),
        Spacer(1, 8),
        make_items_table(
            ["Item", "Description", "HSN", "Qty Supplied", "Unit"],
            [["1", "Premium cotton shirting fabric (60s count)", "52081190", "1200", "metres"]],
            [0.5 * inch, 3.5 * inch, 1.0 * inch, 1.0 * inch, 1.0 * inch],
        ),
        Spacer(1, 30),
        make_stamp_box("ASHOKA RETAIL CENTRAL WAREHOUSE BHIWANDI<br/>RECEIVED IN FULL (1200 M)<br/>DATE: 25-03-2026 | SIGN: Stores Officer", "#1E6B57"),
    ]
    create_pdf(base_dir / "CH_302.pdf", story)

    # Invoice INV-901 dated 26-03-2026
    story = [
        make_header("TARA TEXTILES", "Surat Mills: GIDC, Surat - 395023", "TAX INVOICE", "INV-901", "26-03-2026"),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#16282B"), spaceAfter=10),
        make_party_box("Buyer", buyer_info, "Supplier", supplier_info),
        Spacer(1, 12),
        Paragraph("<b>PO Ref:</b> AR/PO/771 dt. 10-03-2026 | <b>Challan:</b> CH-302 dt. 25-03-2026", BODY_STYLE),
        Spacer(1, 8),
        make_items_table(
            ["Item", "Description", "HSN", "Qty", "Rate (Rs)", "Taxable (Rs)", "IGST 5%", "Total (Rs)"],
            [["1", "Premium cotton shirting fabric", "52081190", "1200 m", "210.00", "2,52,000.00", "12,600.00", "2,64,600.00"]],
            [0.4 * inch, 2.3 * inch, 0.8 * inch, 0.7 * inch, 0.8 * inch, 1.0 * inch, 0.8 * inch, 1.2 * inch],
        ),
        Spacer(1, 10),
        make_items_table(
            ["Summary", "Amount (Rs)"],
            [
                ["Taxable Amount", "2,52,000.00"],
                ["IGST (5%)", "12,600.00"],
                ["Total Payable", "2,64,600.00"],
            ],
            [5.0 * inch, 2.0 * inch],
        ),
    ]
    create_pdf(base_dir / "INV_901.pdf", story)

    # expected.json for Case C
    expected_c = {
        "case_id": "case_c",
        "stage": "base",
        "as_of_date": "2026-10-14",
        "parties": {
            "supplier": {
                "name": "Tara Textiles",
                "role": "supplier",
                "gstin": "24EEEEE4444E1Z4",
                "pan": "EEEEE4444E",
                "udyam_no": "UDYAM-GJ-03-0098765",
                "udyam_reg_date": "2026-05-20",
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
        "purchase_orders": [
            {
                "po_no": "AR/PO/771",
                "po_date": "2026-03-10",
                "credit_days_written": 30,
                "lines": [{"item_key": "FAB-COTTON-60", "description": "Premium cotton shirting fabric (60s count)", "qty": 1200.0, "unit": "metres", "rate": 210.00}],
            }
        ],
        "deliveries": [
            {
                "challan_no": "CH-302",
                "delivery_date": "2026-03-25",
                "received_by": "Stores Officer Bhiwandi",
                "lines": [{"item_key": "FAB-COTTON-60", "qty": 1200.0}],
            }
        ],
        "invoices": [
            {
                "invoice_no": "INV-901",
                "invoice_date": "2026-03-26",
                "gstin_s": "24EEEEE4444E1Z4",
                "gstin_b": "27FFFFF5555F1Z7",
                "taxable": 252000.00,
                "gst": 12600.00,
                "total": 264600.00,
                "lines": [{"item_key": "FAB-COTTON-60", "qty": 1200.0, "rate": 210.00, "amount": 252000.00}],
            }
        ],
        "payments": [],
        "adjustments": [],
        "communications": [],
        "expected_findings": [
            {
                "code": "INELIGIBLE_SUPPLIER",
                "severity": "blocker",
                "message": "Udyam registration date is after the PO date",
            }
        ],
        "expected_ledger": {
            "ordered_qty": 1200.0,
            "delivered_qty": 1200.0,
            "billed_qty": 1200.0,
            "billed_value": 264600.00,
            "paid_total": 0.00,
            "outstanding_principal": 264600.00,
        },
        "expected_rules": None,
        "notes": "Case C: Ineligible under MSMED Act due to Udyam registration (20-05-2026) postdating contract/PO date (10-03-2026). Blocker prevents readiness.",
    }
    with open(case_dir / "expected.json", "w", encoding="utf-8") as f:
        json.dump(expected_c, f, indent=2)


# ==============================================================================
# CASE D BUILDER (Messy Scan Challan)
# ==============================================================================


def gen_messy_scan_jpg(out_path: Path):
    """Generates a realistic photo-style scanned delivery note with noise, blur, tilt, and compression."""
    width, height = 1240, 1754  # ~150 DPI A4
    img = Image.new("RGB", (width, height), color=(248, 247, 243))
    draw = ImageDraw.Draw(img)

    # Header
    draw.text((60, 60), "RAMAN FASTENERS", fill=(30, 30, 30))
    draw.text((60, 90), "Industrial Area-B, Ludhiana, Punjab | Ph: 0161-2531099", fill=(90, 90, 90))
    draw.text((width - 380, 60), "DELIVERY CHALLAN", fill=(30, 30, 30))
    draw.text((width - 380, 90), "Challan No: CH-881", fill=(30, 30, 30))
    draw.text((width - 380, 115), "Date: 12-05-2026", fill=(30, 30, 30))

    # Divider
    draw.line([(50, 150), (width - 50, 150)], fill=(50, 50, 50), width=2)

    # Consignee box
    draw.rectangle([(50, 170), (width - 50, 290)], outline=(180, 180, 180), width=1)
    draw.text((65, 185), "Consignee / Buyer: Orbit Machines Pvt Ltd", fill=(30, 30, 30))
    draw.text((65, 210), "Plot 88, Phase 2, Industrial Focal Point, Jaipur, Rajasthan", fill=(60, 60, 60))
    draw.text((65, 235), "GSTIN: 08HHHHH7777H1Z3", fill=(60, 60, 60))
    draw.text((65, 260), "PO Ref: OM/PO/5540 dated 06-05-2026", fill=(30, 30, 30))

    # Items table
    y_table = 330
    draw.rectangle([(50, y_table), (width - 50, y_table + 40)], fill=(235, 235, 230), outline=(100, 100, 100))
    draw.text((65, y_table + 12), "Item", fill=(20, 20, 20))
    draw.text((150, y_table + 12), "Description", fill=(20, 20, 20))
    draw.text((550, y_table + 12), "HSN Code", fill=(20, 20, 20))
    draw.text((750, y_table + 12), "Dispatched Qty", fill=(20, 20, 20))
    draw.text((950, y_table + 12), "Accepted Qty", fill=(20, 20, 20))

    y_row = y_table + 50
    draw.text((65, y_row), "1", fill=(30, 30, 30))
    draw.text((150, y_row), "Hex Bolt M12 x 50mm (Grade 8.8)", fill=(30, 30, 30))
    draw.text((550, y_row), "73181500", fill=(30, 30, 30))
    draw.text((750, y_row), "1000 pcs", fill=(30, 30, 30))
    draw.text((950, y_row), "980 pcs", fill=(180, 30, 30))

    draw.line([(50, y_row + 35), (width - 50, y_row + 35)], fill=(200, 200, 200), width=1)
    draw.text((65, y_row + 55), "Note: 20 pcs found thread-damaged during unboxing; rejected at gate.", fill=(90, 50, 50))

    # Tilted Blue Stamp overlapping text
    stamp_img = Image.new("RGBA", (450, 150), (255, 255, 255, 0))
    sdraw = ImageDraw.Draw(stamp_img)
    sdraw.rectangle([(5, 5), (440, 140)], outline=(25, 60, 160, 220), width=4)
    sdraw.text((30, 25), "ORBIT MACHINES PVT LTD", fill=(25, 60, 160, 240))
    sdraw.text((30, 50), "GOODS INWARD GATE 2 - STORES", fill=(25, 60, 160, 240))
    sdraw.text((30, 75), "VERIFIED & ACCEPTED: 980 PCS ONLY", fill=(25, 60, 160, 255))
    sdraw.text((30, 100), "DATE: 12-05-2026 | SIGN: K. S. Verma", fill=(25, 60, 160, 240))

    stamp_rot = stamp_img.rotate(4.5, expand=True, resample=Image.BICUBIC)
    img.paste(stamp_rot, (720, y_table + 40), stamp_rot)

    # Paper noise & lighting gradient
    pixels = img.load()
    for y in range(0, height, 4):
        for x in range(0, width, 4):
            noise = random.randint(-8, 8)
            r, g, b = pixels[x, y]
            grad = int((x / width) * 12 - (y / height) * 10)
            nr = max(0, min(255, r + noise + grad))
            ng = max(0, min(255, g + noise + grad))
            nb = max(0, min(255, b + noise + grad))
            pixels[x, y] = (nr, ng, nb)

    # Slight rotation to simulate tilted phone snapshot (~3 degrees)
    img = img.rotate(2.8, expand=True, fillcolor=(230, 228, 220))

    # Mild blur
    img = img.filter(ImageFilter.GaussianBlur(radius=0.7))

    # Mild contrast adjustment
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.05)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, format="JPEG", quality=75)


def build_case_d():
    case_dir = BASE_DIR / "case_d"
    base_dir = case_dir / "base"
    base_dir.mkdir(parents=True, exist_ok=True)

    supplier_info = "Raman Fasteners<br/>GSTIN: 03GGGGG6666G1Z9 | PAN: GGGGG6666G<br/>Industrial Area B, Ludhiana, Punjab"
    buyer_info = "Orbit Machines Pvt Ltd<br/>GSTIN: 08HHHHH7777H1Z3 | PAN: HHHHH7777H<br/>Phase 2, Industrial Focal Point, Jaipur, Rajasthan"

    # Udyam Certificate
    gen_udyam_cert(
        base_dir / "udyam_certificate.pdf",
        "Raman Fasteners",
        "UDYAM-PB-04-0043210",
        "04-11-2022",
        "micro",
        "manufacturer",
        "03GGGGG6666G1Z9",
    )

    # PO OM/PO/5540 dated 06-05-2026
    story = [
        make_header("ORBIT MACHINES PVT LTD", "Jaipur Works, Rajasthan<br/>CIN: U29253RJ2016PTC051280", "PURCHASE ORDER", "OM/PO/5540", "06-05-2026"),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#16282B"), spaceAfter=10),
        make_party_box("Buyer", buyer_info, "Supplier", supplier_info),
        Spacer(1, 12),
        make_items_table(
            ["Item", "Description", "HSN", "Qty", "Unit", "Rate (Rs)", "Amount (Rs)"],
            [["1", "Hex bolt M12 x 50mm (Grade 8.8)", "73181500", "1000", "pcs", "14.00", "14,000.00"]],
            [0.5 * inch, 2.7 * inch, 0.9 * inch, 0.6 * inch, 0.5 * inch, 0.7 * inch, 1.1 * inch],
        ),
        Spacer(1, 10),
        make_items_table(
            ["Summary", "Amount (Rs)"],
            [
                ["Taxable Value", "14,000.00"],
                ["IGST (18.0%)", "2,520.00"],
                ["Total PO Value", "16,520.00"],
            ],
            [5.0 * inch, 2.0 * inch],
        ),
        Spacer(1, 15),
        Paragraph("<b>Terms:</b> 30 days credit from receipt of materials.", BODY_STYLE),
    ]
    create_pdf(base_dir / "PO_OM_PO_5540.pdf", story)

    # Messy Scan Challan JPG
    gen_messy_scan_jpg(base_dir / "challan_ch_881.jpg")

    # Clean Invoice INV-1042 dated 22-05-2026 for 1000 pcs (total 16,520.00)
    story = [
        make_header("RAMAN FASTENERS", "Ludhiana, Punjab - 141003", "TAX INVOICE", "INV-1042", "22-05-2026"),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#16282B"), spaceAfter=10),
        make_party_box("Buyer", buyer_info, "Supplier", supplier_info),
        Spacer(1, 12),
        Paragraph("<b>PO Ref:</b> OM/PO/5540 | <b>Challan Ref:</b> CH-881", BODY_STYLE),
        Spacer(1, 8),
        make_items_table(
            ["Item", "Description", "HSN", "Qty", "Rate (Rs)", "Taxable (Rs)", "IGST 18%", "Total (Rs)"],
            [["1", "Hex bolt M12 x 50mm", "73181500", "1000 pcs", "14.00", "14,000.00", "2,520.00", "16,520.00"]],
            [0.4 * inch, 2.3 * inch, 0.8 * inch, 0.7 * inch, 0.8 * inch, 1.0 * inch, 0.8 * inch, 1.2 * inch],
        ),
        Spacer(1, 10),
        make_items_table(
            ["Summary", "Amount (Rs)"],
            [
                ["Taxable Amount", "14,000.00"],
                ["IGST (18%)", "2,520.00"],
                ["Total Invoice Value", "16,520.00"],
            ],
            [5.0 * inch, 2.0 * inch],
        ),
    ]
    create_pdf(base_dir / "INV_1042.pdf", story)

    # Bank statement: Payment of Rs 10,000 on 15-07-2026
    gen_bank_statement(
        base_dir / "bank_statement.pdf",
        "Raman Fasteners",
        "A/C 88192001928",
        "01-07-2026 to 31-07-2026",
        [
            {"date": "01-07-2026", "narration": "OPENING BALANCE", "balance": 42000.00},
            {"date": "15-07-2026", "narration": "NEFT PART PAY INV-1042 - ORBIT MACHINES", "utr": "UTRORB261960012", "credit": 10000.00, "balance": 52000.00},
        ],
    )

    # expected.json for Case D
    expected_d = {
        "case_id": "case_d",
        "stage": "base",
        "as_of_date": "2026-10-14",
        "parties": {
            "supplier": {
                "name": "Raman Fasteners",
                "role": "supplier",
                "gstin": "03GGGGG6666G1Z9",
                "pan": "GGGGG6666G",
                "udyam_no": "UDYAM-PB-04-0043210",
                "udyam_reg_date": "2022-11-04",
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
        "purchase_orders": [
            {
                "po_no": "OM/PO/5540",
                "po_date": "2026-05-06",
                "credit_days_written": 30,
                "lines": [{"item_key": "BOLT-M12-50", "description": "Hex bolt M12 x 50mm", "qty": 1000.0, "unit": "pcs", "rate": 14.00}],
            }
        ],
        "deliveries": [
            {
                "challan_no": "CH-881",
                "delivery_date": "2026-05-12",
                "received_by": "K. S. Verma Gate 2",
                "lines": [{"item_key": "BOLT-M12-50", "qty": 980.0}],
            }
        ],
        "invoices": [
            {
                "invoice_no": "INV-1042",
                "invoice_date": "2026-05-22",
                "gstin_s": "03GGGGG6666G1Z9",
                "gstin_b": "08HHHHH7777H1Z3",
                "taxable": 14000.00,
                "gst": 2520.00,
                "total": 16520.00,
                "lines": [{"item_key": "BOLT-M12-50", "qty": 1000.0, "rate": 14.00, "amount": 14000.00}],
            }
        ],
        "payments": [
            {
                "utr": "UTRORB261960012",
                "pay_date": "2026-07-15",
                "amount": 10000.00,
                "bank_ref_text": "NEFT PART PAY INV-1042 - ORBIT MACHINES",
            }
        ],
        "adjustments": [],
        "communications": [],
        "expected_findings": [
            {
                "code": "QTY_MISMATCH",
                "severity": "warn",
                "message": "Billed 1000 pcs but challan CH-881 evidences delivery of 980 pcs (shortfall of 20 pcs)",
            }
        ],
        "expected_ledger": {
            "ordered_qty": 1000.0,
            "delivered_qty": 980.0,
            "billed_qty": 1000.0,
            "billed_value": 16520.00,
            "paid_total": 10000.00,
            "outstanding_principal": 6189.60,
        },
        "expected_rules": None,
        "notes": "Case D: Challan is a noisy scan with buyer stamp indicating 980 pcs accepted. Delivered taxable value: 980 * 14 = 13,720.00 + 18% GST (2,469.60) = 16,189.60. Less payment Rs 10,000 = claimable principal Rs 6,189.60 (or Rs 6,520.00 on billed).",
    }
    with open(case_dir / "expected.json", "w", encoding="utf-8") as f:
        json.dump(expected_d, f, indent=2)


def main():
    print("Generating synthetic demo cases (A, B, C, D)...")
    build_case_a()
    print("✓ Case A generated (base + addons + 3 expected json states)")
    build_case_b()
    print("✓ Case B generated (base + expected.json)")
    build_case_c()
    print("✓ Case C generated (base + expected.json)")
    build_case_d()
    print("✓ Case D generated (base + messy scan JPG + expected.json)")
    print("All synthetic data generated successfully.")


if __name__ == "__main__":
    main()
