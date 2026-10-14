# Synthetic Demo Data

This directory contains reproducible, deterministic synthetic test cases for ClaimGraph.
All documents are generated programmatically via `python generate.py` using ReportLab and Pillow. All company names, GSTINs, and UTRs are fictional representations modeled on authentic Indian commercial conventions.

The anchor evaluation date for all cases is **14 Oct 2026** (`as_of_date = "2026-10-14"`).

---

## Cases Overview

### Case A: Sharma Auto Components vs Meridian Motors Pvt Ltd (Main Demo)
- **Supplier:** Sharma Auto Components (micro manufacturer, Udyam registered 12-03-2024).
- **Buyer:** Meridian Motors Pvt Ltd.
- **Story:**
  1. PO `MM/PO/2291` ordered 500 units of "Brake bracket BB-210" at ₹820/unit + 18% GST (Total: ₹4,83,800.00).
  2. Challan `CH-118` delivered 460 units on 20-04-2026 with verified buyer inward stamp.
  3. Invoice `INV-7731` billed for full 500 units (₹4,83,800.00) on 22-04-2026.
  4. Payment: Buyer paid ₹1,98,000.00 net on 30-06-2026 after deducting ₹2,000.00 TDS (gross ₹2,00,000.00 credited).
- **Stages & Expected JSONs:**
  - `expected_base.json`: 460 delivered vs 500 billed. Finding `QTY_MISMATCH` and `TDS_DEDUCTION`. Claimable principal: ₹2,45,096.00 based on delivered goods.
  - `expected_after_email.json`: Backorder email added (`01_backorder_email.pdf`) promising 40 units by 10-05-2026. Finding `BACKORDER_PENDING`. Claimable principal remains ₹2,45,096.00 until delivery.
  - `expected_after_delivery.json`: Challan `CH-131` added (`02_challan_ch131.pdf`) proving delivery of balance 40 units on 09-05-2026. `QTY_MISMATCH` and `BACKORDER_PENDING` cleared. Outstanding principal recomputed on full invoice: ₹2,83,800.00.

### Case B: Kaveri Packaging Works vs Northline Foods Ltd (Duplicates & Uncredited Advance)
- **Supplier:** Kaveri Packaging Works (small manufacturer, Udyam registered 01-08-2023).
- **Buyer:** Northline Foods Ltd.
- **Story:**
  1. PO `NF/PO/118` ordered 2,000 cartons at ₹36.50/unit + 18% GST (Total: ₹86,140.00).
  2. Delivery `KP/CH/045` delivered full 2,000 cartons on 18-03-2026.
  3. Invoice `KP/INV/0412` billed ₹86,140.00 on 19-03-2026.
  4. Duplicate invoice `KP/INV/0412-A` issued on 28-03-2026 for the same delivery.
  5. Payments: ₹20,000.00 advance on 01-03-2026 referencing the PO, and ₹50,000.00 part payment on 02-05-2026 (Total: ₹70,000.00).
- **Expected Findings (`expected.json`):**
  - `DUPLICATE_INVOICE`: Blocker flag identifying duplicate billing.
  - `UNCREDITED_PAYMENT`: Advance payment received but omitted from invoice face.
  - **Outstanding Principal:** ₹86,140.00 - ₹70,000.00 = ₹16,140.00.

### Case C: Tara Textiles vs Ashoka Retail Pvt Ltd (Ineligibility Gate)
- **Supplier:** Tara Textiles (Udyam registration date: 20-05-2026).
- **Buyer:** Ashoka Retail Pvt Ltd.
- **Story:**
  1. Contract / PO `AR/PO/771` issued on 10-03-2026 for 1,200 metres fabric at ₹210/metre + 5% GST (Total: ₹2,64,600.00).
  2. Material delivered on 25-03-2026 and invoiced on 26-03-2026.
  3. However, supplier's Udyam registration is dated 20-05-2026, which is **after** the contract/PO date.
- **Expected Findings (`expected.json`):**
  - `INELIGIBLE_SUPPLIER`: Blocker preventing dossier readiness under Section 18 of the MSMED Act.

### Case D: Raman Fasteners vs Orbit Machines Pvt Ltd (Messy Photo Scan)
- **Supplier:** Raman Fasteners (micro manufacturer, Udyam registered 04-11-2022).
- **Buyer:** Orbit Machines Pvt Ltd.
- **Story:**
  1. PO `OM/PO/5540` ordered 1,000 pcs bolts at ₹14/unit + 18% GST (Total: ₹16,520.00).
  2. Delivery note `CH-881` is a camera photograph with 2.8° tilt, uneven lighting, paper grain, and a blue buyer stamp stating "VERIFIED & ACCEPTED: 980 PCS ONLY" (20 pcs rejected at gate).
  3. Invoice `INV-1042` billed for 1,000 pcs (₹16,520.00).
  4. Payment of ₹10,000.00 received on 15-07-2026.
- **Expected Findings (`expected.json`):**
  - `QTY_MISMATCH`: Billed 1,000 vs delivered 980 pcs.
  - **Claimable Delivered Principal:** ₹16,189.60 - ₹10,000.00 = ₹6,189.60.

---

## Regenerating Data

Run the generator script at any time:
```bash
python generate.py
```
Or via Docker:
```bash
docker compose exec backend python /data/synthetic/generate.py
```
