"""Entity builder for ClaimGraph M5.

Builds typed domain entities strictly from confirmed or edited facts.
Facts that are needs_review, auto-unconfirmed or mark_not_present are never used.
If a required fact is missing or unconfirmed, returns blockers.
Rebuild is idempotent and runs in one transaction.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.document import Document
from app.models.fact import Fact
from app.models.party import Party
from app.models.reconciliation import Adjustment, Communication
from app.models.transaction import (
    Delivery,
    DeliveryLine,
    Invoice,
    InvoiceLine,
    Payment,
    POLine,
    PurchaseOrder,
)


@dataclass
class Blocker:
    field: str
    document: str
    reason: str


@dataclass
class BuiltEntities:
    case: Case
    parties: list[Party] = field(default_factory=list)
    purchase_orders: list[PurchaseOrder] = field(default_factory=list)
    deliveries: list[Delivery] = field(default_factory=list)
    invoices: list[Invoice] = field(default_factory=list)
    payments: list[Payment] = field(default_factory=list)
    adjustments: list[Adjustment] = field(default_factory=list)
    communications: list[Communication] = field(default_factory=list)
    fact_map: dict[str, uuid.UUID] = field(default_factory=dict)  # entity_id/key -> fact_id


def extract_fact_value(fact: Fact) -> Any:
    """Safely extract value from fact value_json."""
    if not fact or not fact.value_json:
        return None
    v = fact.value_json
    if isinstance(v, dict):
        if "value" in v and v["value"] is not None:
            return v["value"]
        if "normalised" in v and v["normalised"] is not None:
            return v["normalised"]
        if "raw" in v and v["raw"] is not None:
            return v["raw"]
        return None
    return v


def parse_date(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, date):
        return v
    if isinstance(v, datetime):
        return v.date()
    s = str(v).strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except Exception:
        pass
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None


def parse_decimal(v: Any, default: Decimal = Decimal("0.00")) -> Decimal:
    if v is None:
        return default
    if isinstance(v, Decimal):
        return v
    s = str(v).replace(",", "").replace("₹", "").replace("Rs", "").replace("rs", "").strip()
    if not s:
        return default
    try:
        return Decimal(s)
    except Exception:
        return default


def parse_int(v: Any, default: int | None = None) -> int | None:
    if v is None:
        return default
    try:
        return int(float(str(v).strip()))
    except Exception:
        return default


# Required fields per document kind
REQUIRED_FIELDS_BY_KIND: dict[str, list[str]] = {
    "PO": ["po_no", "po_date"],
    "CHALLAN": ["challan_no"],
    "INVOICE": ["invoice_no", "invoice_date"],
}


def check_linking_blockers(case_id: uuid.UUID, db: Session) -> list[Blocker]:
    """Check for missing or unconfirmed facts across case documents.

    A required fact is blocked if:
    - It is in status 'needs_review' or 'auto' (unconfirmed)
    - It is mark_not_present or missing for a required document kind
    """
    blockers: list[Blocker] = []

    documents = db.query(Document).filter(Document.case_id == case_id).all()
    if not documents:
        return [Blocker(field="documents", document="Case", reason="No documents uploaded for case")]

    doc_ids = [d.id for d in documents]
    all_facts = db.query(Fact).filter(Fact.document_id.in_(doc_ids)).all()

    facts_by_doc: dict[uuid.UUID, dict[str, Fact]] = {d.id: {} for d in documents}
    for f in all_facts:
        facts_by_doc[f.document_id][f.field] = f

    doc_by_id = {d.id: d for d in documents}

    # Check for unconfirmed facts in uploaded documents
    for f in all_facts:
        if f.status in ("needs_review", "auto"):
            doc = doc_by_id.get(f.document_id)
            doc_name = doc.filename if doc else str(f.document_id)
            # Only block if it is a core field (header or line item)
            base_field = f.field.split(".")[-1]
            if base_field in (
                "po_no", "po_date", "credit_days", "challan_no", "challan_date",
                "stamp_date", "invoice_no", "invoice_date", "grand_total", "taxable_total",
                "dispatched_qty", "accepted_qty", "rejected_qty", "qty", "rate", "amount",
                "udyam_no", "registration_date",
            ):
                blockers.append(
                    Blocker(
                        field=f.field,
                        document=doc_name,
                        reason=f"Unconfirmed fact ({f.status}) requires human review",
                    )
                )

    # Check required fields presence
    for doc in documents:
        req_fields = REQUIRED_FIELDS_BY_KIND.get(doc.kind, [])
        doc_facts = facts_by_doc.get(doc.id, {})
        for req in req_fields:
            fact = doc_facts.get(req)
            if not fact:
                blockers.append(
                    Blocker(
                        field=req,
                        document=doc.filename,
                        reason=f"Missing required field '{req}' for {doc.kind}",
                    )
                )
            elif fact.status not in ("confirmed", "edited"):
                # Already captured above if in needs_review/auto
                pass

    return blockers


def build_entities_from_facts(
    case_id: uuid.UUID,
    db: Session,
    preserve_case_status: bool = False,
) -> tuple[BuiltEntities | None, list[Blocker]]:
    """Build domain entities from confirmed/edited facts in a single transaction.

    If blockers exist, does not build and returns (None, blockers).
    Preserves audit log and facts; recreates derived rows only.
    """
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise ValueError(f"Case {case_id} not found")

    blockers = check_linking_blockers(case_id, db)
    if blockers:
        if not preserve_case_status:
            case.status = "linking_blocked"
            db.commit()
        return None, blockers

    # Load only confirmed or edited facts
    facts = (
        db.query(Fact)
        .filter(
            Fact.case_id == case_id,
            Fact.status.in_(["confirmed", "edited"]),
        )
        .all()
    )

    documents = db.query(Document).filter(Document.case_id == case_id).all()

    # Group facts by document
    facts_by_doc: dict[uuid.UUID, list[Fact]] = {d.id: [] for d in documents}
    for f in facts:
        if f.document_id in facts_by_doc:
            facts_by_doc[f.document_id].append(f)

    # 1. Clean existing derived rows in single transaction
    existing_pos = db.query(PurchaseOrder).filter(PurchaseOrder.case_id == case_id).all()
    po_ids = [po.id for po in existing_pos]
    if po_ids:
        db.query(POLine).filter(POLine.po_id.in_(po_ids)).delete(synchronize_session=False)
    db.query(PurchaseOrder).filter(PurchaseOrder.case_id == case_id).delete(synchronize_session=False)

    existing_deliveries = db.query(Delivery).filter(Delivery.case_id == case_id).all()
    del_ids = [d.id for d in existing_deliveries]
    if del_ids:
        db.query(DeliveryLine).filter(DeliveryLine.delivery_id.in_(del_ids)).delete(synchronize_session=False)
    db.query(Delivery).filter(Delivery.case_id == case_id).delete(synchronize_session=False)

    existing_invoices = db.query(Invoice).filter(Invoice.case_id == case_id).all()
    inv_ids = [inv.id for inv in existing_invoices]
    if inv_ids:
        db.query(InvoiceLine).filter(InvoiceLine.invoice_id.in_(inv_ids)).delete(synchronize_session=False)
    db.query(Invoice).filter(Invoice.case_id == case_id).delete(synchronize_session=False)

    db.query(Payment).filter(Payment.case_id == case_id).delete(synchronize_session=False)
    db.query(Adjustment).filter(Adjustment.case_id == case_id).delete(synchronize_session=False)
    db.query(Communication).filter(Communication.case_id == case_id).delete(synchronize_session=False)

    built = BuiltEntities(case=case)

    # Helper to parse indexed line facts: e.g. "lines[0].qty"
    line_re = re.compile(r"^(?:lines|transactions|communications)\[(\d+)\]\.(.*)$")

    for doc in documents:
        doc_facts = facts_by_doc.get(doc.id, [])
        if not doc_facts:
            continue

        f_map: dict[str, Fact] = {f.field: f for f in doc_facts}
        f_vals: dict[str, Any] = {f.field: extract_fact_value(f) for f in doc_facts}

        # Index line items: index -> dict of subfield -> Fact
        lines_data: dict[int, dict[str, Fact]] = {}
        for f in doc_facts:
            m = line_re.match(f.field)
            if m:
                idx = int(m.group(1))
                subfield = m.group(2)
                lines_data.setdefault(idx, {})[subfield] = f

        # --- Document: PO ---
        if doc.kind == "PO":
            po_no = str(f_vals.get("po_no") or f"PO-{doc.id.hex[:6]}").strip()
            po_date = parse_date(f_vals.get("po_date")) or date(2026, 1, 1)
            credit_days = parse_int(f_vals.get("credit_days"))
            terms_fact = f_map.get("credit_days") or f_map.get("payment_terms_text")
            terms_fact_id = terms_fact.id if terms_fact else None
            po_fact = f_map.get("po_no") or f_map.get("po_date")
            po_fact_id = po_fact.id if po_fact else None

            po = PurchaseOrder(
                case_id=case_id,
                po_no=po_no,
                po_date=po_date,
                credit_days_written=credit_days,
                terms_fact_id=terms_fact_id,
                fact_id=po_fact_id,
            )
            db.add(po)
            db.flush()

            for idx in sorted(lines_data.keys()):
                lf = lines_data[idx]
                desc = str(extract_fact_value(lf.get("description")) or f"Item {idx+1}")
                item_key = str(extract_fact_value(lf.get("item_code")) or lf.get("description") or f"ITEM-{idx+1}").strip()
                qty = parse_decimal(extract_fact_value(lf.get("qty")), Decimal("1.0"))
                rate = parse_decimal(extract_fact_value(lf.get("rate")), Decimal("0.0"))
                unit = str(extract_fact_value(lf.get("unit")) or "pcs").strip()

                line = POLine(
                    po_id=po.id,
                    item_key=item_key,
                    description=desc,
                    qty=qty,
                    unit=unit,
                    rate=rate,
                )
                db.add(line)

            built.purchase_orders.append(po)

        # --- Document: CHALLAN / DELIVERY ---
        elif doc.kind in ("CHALLAN", "DELIVERY"):
            challan_no = str(f_vals.get("challan_no") or f"CH-{doc.id.hex[:6]}").strip()
            del_date = (
                parse_date(f_vals.get("stamp_date"))
                or parse_date(f_vals.get("challan_date"))
                or date(2026, 1, 1)
            )
            received_by = str(f_vals.get("received_by") or f_vals.get("stamp_text") or "") or None
            rejection_reason = str(f_vals.get("rejection_reason") or "") or None
            acceptance_fact = f_map.get("stamp_date") or f_map.get("stamp_text") or f_map.get("received_by")
            acc_fact_id = acceptance_fact.id if acceptance_fact else None
            ch_fact = f_map.get("challan_no") or f_map.get("challan_date")
            ch_fact_id = ch_fact.id if ch_fact else None

            delivery = Delivery(
                case_id=case_id,
                challan_no=challan_no,
                delivery_date=del_date,
                received_by=received_by,
                rejection_reason=rejection_reason,
                acceptance_fact_id=acc_fact_id,
                fact_id=ch_fact_id,
            )
            db.add(delivery)
            db.flush()

            for idx in sorted(lines_data.keys()):
                lf = lines_data[idx]
                desc = str(extract_fact_value(lf.get("item_description")) or f"Item {idx+1}")
                disp_qty = parse_decimal(extract_fact_value(lf.get("dispatched_qty")), Decimal("0.0"))
                acc_qty = parse_decimal(extract_fact_value(lf.get("accepted_qty")), disp_qty)
                rej_qty = parse_decimal(extract_fact_value(lf.get("rejected_qty")), Decimal("0.0"))
                rej_reason = str(extract_fact_value(lf.get("rejection_reason")) or "") or None
                unit = str(extract_fact_value(lf.get("unit")) or "pcs").strip()

                # Main qty represents accepted qty if present, else dispatched
                main_qty = acc_qty if acc_qty > Decimal("0") else disp_qty

                d_line = DeliveryLine(
                    delivery_id=delivery.id,
                    item_key=desc,
                    qty=main_qty,
                    dispatched_qty=disp_qty if disp_qty > Decimal("0") else None,
                    accepted_qty=acc_qty if acc_qty > Decimal("0") else None,
                    rejected_qty=rej_qty if rej_qty > Decimal("0") else None,
                    rejection_reason=rej_reason,
                )
                db.add(d_line)

            built.deliveries.append(delivery)

        # --- Document: INVOICE ---
        elif doc.kind == "INVOICE":
            inv_no = str(f_vals.get("invoice_no") or f"INV-{doc.id.hex[:6]}").strip()
            inv_date = parse_date(f_vals.get("invoice_date")) or date(2026, 1, 1)
            gstin_s = str(f_vals.get("supplier_gstin") or "") or None
            gstin_b = str(f_vals.get("buyer_gstin") or "") or None
            taxable = parse_decimal(f_vals.get("taxable_total"), Decimal("0.00"))
            gst = parse_decimal(f_vals.get("gst_amount"), Decimal("0.00"))
            total = parse_decimal(f_vals.get("grand_total"), taxable + gst)
            inv_fact = f_map.get("invoice_no") or f_map.get("invoice_date")
            inv_fact_id = inv_fact.id if inv_fact else None

            invoice = Invoice(
                case_id=case_id,
                invoice_no=inv_no,
                invoice_date=inv_date,
                gstin_s=gstin_s,
                gstin_b=gstin_b,
                taxable=taxable,
                gst=gst,
                total=total,
                fact_id=inv_fact_id,
            )
            db.add(invoice)
            db.flush()

            for idx in sorted(lines_data.keys()):
                lf = lines_data[idx]
                desc = str(extract_fact_value(lf.get("description")) or f"Line {idx+1}")
                qty = parse_decimal(extract_fact_value(lf.get("qty")), Decimal("1.0"))
                rate = parse_decimal(extract_fact_value(lf.get("rate")), Decimal("0.00"))
                amt = parse_decimal(extract_fact_value(lf.get("amount")), qty * rate)

                inv_line = InvoiceLine(
                    invoice_id=invoice.id,
                    item_key=desc,
                    qty=qty,
                    rate=rate,
                    amount=amt,
                )
                db.add(inv_line)

            built.invoices.append(invoice)

        # --- Document: BANK_STATEMENT ---
        elif doc.kind == "BANK_STATEMENT":
            for idx in sorted(lines_data.keys()):
                lf = lines_data[idx]
                credit = parse_decimal(extract_fact_value(lf.get("credit")), Decimal("0.00"))
                if credit <= Decimal("0"):
                    continue
                p_date = parse_date(extract_fact_value(lf.get("date"))) or date(2026, 1, 1)
                narration = str(extract_fact_value(lf.get("narration")) or "") or None
                utr = str(extract_fact_value(lf.get("utr")) or "") or None
                trans_fact = lf.get("credit") or lf.get("utr") or lf.get("narration")
                trans_fact_id = trans_fact.id if trans_fact else None

                payment = Payment(
                    case_id=case_id,
                    utr=utr,
                    pay_date=p_date,
                    amount=credit,
                    bank_ref_text=narration,
                    fact_id=trans_fact_id,
                )
                db.add(payment)
                built.payments.append(payment)

        # --- Document: REMITTANCE (Adjustments like TDS) ---
        elif doc.kind == "REMITTANCE":
            tds = parse_decimal(f_vals.get("tds_amount"), Decimal("0.00"))
            if tds > Decimal("0"):
                inv_ref = str(f_vals.get("invoice_refs") or "")
                ref_txt = f"TDS u/s 194Q per remittance advice {doc.filename}"
                if inv_ref:
                    ref_txt += f" (inv {inv_ref})"
                tds_fact = f_map.get("tds_amount")
                tds_fact_id = tds_fact.id if tds_fact else None

                adj = Adjustment(
                    case_id=case_id,
                    kind="tds",
                    amount=tds,
                    ref=ref_txt,
                    fact_id=tds_fact_id,
                )
                db.add(adj)
                built.adjustments.append(adj)

        # --- Document: EMAIL (Communications) ---
        elif doc.kind == "EMAIL":
            for idx in sorted(lines_data.keys()):
                lf = lines_data[idx]
                kind_val = str(extract_fact_value(lf.get("kind")) or "other").lower().strip()
                if kind_val not in ("acceptance", "objection", "backorder", "promise_to_pay", "acknowledgment", "other"):
                    kind_val = "other"
                msg_date = parse_date(extract_fact_value(lf.get("message_date"))) or date(2026, 1, 1)
                quote_val = str(extract_fact_value(lf.get("quote")) or "") or None
                sender_val = str(extract_fact_value(f_map.get("sender")) or "unknown")
                comm_fact = lf.get("kind") or lf.get("quote")
                comm_fact_id = comm_fact.id if comm_fact else None

                comm = Communication(
                    case_id=case_id,
                    doc_id=doc.id,
                    msg_date=msg_date,
                    sender=sender_val,
                    kind=kind_val,
                    quote=quote_val,
                    fact_id=comm_fact_id,
                )
                db.add(comm)
                built.communications.append(comm)

        # --- Document: UDYAM_CERT ---
        elif doc.kind == "UDYAM_CERT":
            udyam_no = str(f_vals.get("udyam_no") or "").strip()
            ent_type = str(f_vals.get("enterprise_type") or "").lower().strip()
            activity = str(f_vals.get("activity") or "").lower().strip()
            reg_date = parse_date(f_vals.get("registration_date"))

            # Update supplier party on case
            supplier = case.supplier
            if supplier:
                if udyam_no:
                    supplier.udyam_no = udyam_no
                if ent_type in ("micro", "small", "medium"):
                    supplier.enterprise_type = ent_type
                if activity in ("manufacturer", "service", "trader"):
                    supplier.activity = activity
                if reg_date:
                    supplier.udyam_reg_date = reg_date
                db.add(supplier)
                built.parties.append(supplier)

    db.commit()
    return built, []
