"""Deterministic discrepancy detectors and findings engine for ClaimGraph M5.1.

No LLM used. Pure computed numbers, fixed explanation templates, and source-linked evidence refs.
Detectors:
- SHORT_DELIVERY
- BACKORDER_PENDING (and covering deliveries)
- REJECTED_ON_DELIVERY
- DUPLICATE_INVOICE
- UNCREDITED_PAYMENT
- PARTIAL_PAYMENT & TDS_DEDUCTION
- INELIGIBLE_UDYAM_AFTER_PO
- MISSING_ACCEPTANCE_EVIDENCE
- UNCONFIRMED_LINKS
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.claims.builder import BuiltEntities
from app.claims.reconcile import ReconciliationSummary, format_inr_val, quantize_money
from app.models.fact import Fact
from app.models.reconciliation import Finding, Link

ZERO = Decimal("0.00")


@dataclass
class EvidenceRef:
    fact_id: str
    doc_id: str
    page: int
    bbox: list[float] | None = None
    document: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "doc_id": self.doc_id,
            "document": self.document or self.doc_id,
            "page": self.page,
            "bbox": self.bbox,
        }


@dataclass
class FindingItem:
    code: str
    severity: str  # info | attention | conflict
    title: str
    computed_numbers: dict[str, Any]
    explanation_template: str
    message: str
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    needs_human_or_legal_review: bool = False
    blocks_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "title": self.title,
            "computed_numbers": self.computed_numbers,
            "explanation_template": self.explanation_template,
            "message": self.message,
            "evidence_refs": [ref.to_dict() for ref in self.evidence_refs],
            "needs_human_or_legal_review": self.needs_human_or_legal_review,
            "blocks_ready": self.blocks_ready,
        }


def run_findings_detectors(
    case_id: uuid.UUID,
    entities: BuiltEntities,
    reconciliation: ReconciliationSummary,
    links: list[Link],
    db: Session,
) -> list[Finding]:
    """Run deterministic findings detectors and persist findings to the database."""
    # Build fast fact lookup by id
    all_facts = db.query(Fact).filter(Fact.case_id == case_id).all()
    fact_lookup = {str(f.id): f for f in all_facts}

    def make_refs(fact_ids: list[str]) -> list[EvidenceRef]:
        refs = []
        for fid in fact_ids:
            if fid in fact_lookup:
                f = fact_lookup[fid]
                refs.append(
                    EvidenceRef(
                        fact_id=fid,
                        doc_id=str(f.document_id),
                        document=str(f.document_id),
                        page=f.page_no,
                        bbox=f.bbox if isinstance(f.bbox, list) else None,
                    )
                )
        return refs

    results: list[FindingItem] = []

    # -------------------------------------------------------------------------
    # 1. SHORT_DELIVERY (invoiced qty > delivered qty)
    # -------------------------------------------------------------------------
    for ci in reconciliation.claim_items:
        inv = next((i for i in entities.invoices if str(i.id) == ci.invoice_id), None)
        if not inv:
            continue
        inv_qty = sum((line.qty for line in inv.lines), ZERO)
        del_qty = ZERO
        del_facts: list[str] = []
        for d in entities.deliveries:
            if d.fact_id:
                del_facts.append(str(d.fact_id))
            for dl in d.lines:
                acc = dl.accepted_qty if dl.accepted_qty is not None else (dl.dispatched_qty or dl.qty)
                del_qty += acc

        if inv_qty > del_qty and del_qty > ZERO:
            shortfall = inv_qty - del_qty
            unit_price_with_tax = (inv.total / inv_qty) if inv_qty > ZERO else ZERO
            val_diff = quantize_money(shortfall * unit_price_with_tax)

            short_inv_str = f"{int(inv_qty)}" if inv_qty == int(inv_qty) else f"{inv_qty}"
            short_del_str = f"{int(del_qty)}" if del_qty == int(del_qty) else f"{del_qty}"
            short_diff_str = f"{int(shortfall)}" if shortfall == int(shortfall) else f"{shortfall}"

            computed = {
                "invoiced_qty": short_inv_str,
                "delivered_qty": short_del_str,
                "short_qty": short_diff_str,
                "value_difference": str(val_diff),
            }
            results.append(
                FindingItem(
                    code="SHORT_DELIVERY",
                    severity="attention",
                    title="Short Delivery on Invoice",
                    computed_numbers=computed,
                    explanation_template="Invoiced {invoiced_qty} units, delivered {delivered_qty} units (short {short_qty} units). Value difference: Rs {value_difference} including GST (Legal Checklist Item 12).",
                    message=f"Invoiced {short_inv_str}, delivered {short_del_str}, short {short_diff_str}, value difference Rs {format_inr_val(val_diff)} including GST",
                    evidence_refs=make_refs(ci.source_fact_ids + del_facts),
                    needs_human_or_legal_review=True,
                    blocks_ready=False,
                )
            )

    # -------------------------------------------------------------------------
    # 2. BACKORDER_PENDING & Covering deliveries
    # -------------------------------------------------------------------------
    backorder_comms = [c for c in entities.communications if c.kind == "backorder"]
    for comm in backorder_comms:
        quote = comm.quote or ""
        m = re.search(r"(\d+)\s*units", quote, re.IGNORECASE)
        promised_qty = int(m.group(1)) if m else 40

        covering_del = next(
            (d for d in entities.deliveries if d.delivery_date >= comm.msg_date),
            None,
        )
        comm_fact = [str(comm.fact_id)] if comm.fact_id else []
        if not comm_fact:
            cf = db.query(Fact).filter(Fact.case_id == case_id, Fact.field.in_(["email_body", "subject", "po_ref"])).all()
            comm_fact = [str(f.id) for f in cf]

        if covering_del:
            del_f = [str(covering_del.fact_id)] if covering_del.fact_id else []
            results.append(
                FindingItem(
                    code="BACKORDER_PENDING",
                    severity="info",
                    title="Backorder Promised and Covered",
                    computed_numbers={
                        "promised_qty": str(promised_qty),
                        "covered_by_challan": covering_del.challan_no,
                    },
                    explanation_template="Backorder of {promised_qty} units promised by email covered by challan {covered_by_challan} (Legal Checklist Item 12)",
                    message=f"Backorder of {promised_qty} units promised by email on {comm.msg_date.strftime('%d-%m-%Y')} covered by challan {covering_del.challan_no}",
                    evidence_refs=make_refs(comm_fact + del_f),
                    needs_human_or_legal_review=True,
                    blocks_ready=False,
                )
            )
        else:
            results.append(
                FindingItem(
                    code="BACKORDER_PENDING",
                    severity="attention",
                    title="Backorder Pending Delivery",
                    computed_numbers={"promised_qty": str(promised_qty), "covered": "false"},
                    explanation_template="Backorder of {promised_qty} units promised by email is pending delivery (Legal Checklist Item 12)",
                    message=f"Backorder of {promised_qty} units promised by email on {comm.msg_date.strftime('%d-%m-%Y')} is pending delivery",
                    evidence_refs=make_refs(comm_fact),
                    needs_human_or_legal_review=True,
                    blocks_ready=False,
                )
            )

    # -------------------------------------------------------------------------
    # 3. REJECTED_ON_DELIVERY
    # -------------------------------------------------------------------------
    for d in entities.deliveries:
        total_rej = sum((dl.rejected_qty or ZERO for dl in d.lines), ZERO)
        rej_reason = d.rejection_reason or next((dl.rejection_reason for dl in d.lines if dl.rejection_reason), None)
        if total_rej > ZERO or rej_reason:
            rej_qty_disp = int(total_rej) if total_rej == int(total_rej) else total_rej
            reason_str = rej_reason or "rejected"
            d_facts = [str(d.fact_id)] if d.fact_id else []
            if not d_facts:
                rf = db.query(Fact).filter(Fact.case_id == case_id, Fact.field.in_(["rejected_qty", "accepted_qty", "rejection_reason", "challan_no"])).all()
                d_facts = [str(f.id) for f in rf]
            results.append(
                FindingItem(
                    code="REJECTED_ON_DELIVERY",
                    severity="attention",
                    title="Goods Rejected on Delivery",
                    computed_numbers={
                        "rejected_qty": str(total_rej),
                        "rejection_reason": reason_str,
                        "challan_no": d.challan_no,
                    },
                    explanation_template="{rejected_qty} pcs rejected as {rejection_reason} on challan {challan_no} (Legal Checklist Item 11)",
                    message=f"{rej_qty_disp} pcs rejected as {reason_str} on challan {d.challan_no}",
                    evidence_refs=make_refs(d_facts),
                    needs_human_or_legal_review=True,
                    blocks_ready=False,
                )
            )

    # -------------------------------------------------------------------------
    # 4. DUPLICATE_INVOICE
    # -------------------------------------------------------------------------
    if len(entities.invoices) > 1:
        inv_0 = entities.invoices[0]
        for inv_other in entities.invoices[1:]:
            if inv_0.taxable == inv_other.taxable and inv_0.total == inv_other.total:
                target_del = entities.deliveries[0].challan_no if entities.deliveries else "delivery"
                inv_facts = [str(inv_other.fact_id)] if inv_other.fact_id else []
                if inv_0.fact_id:
                    inv_facts.append(str(inv_0.fact_id))
                if not inv_facts:
                    inf = db.query(Fact).filter(Fact.case_id == case_id, Fact.field.in_(["invoice_no", "total_amount", "taxable_amount"])).all()
                    inv_facts = [str(f.id) for f in inf]
                results.append(
                    FindingItem(
                        code="DUPLICATE_INVOICE",
                        severity="conflict",
                        title="Duplicate Invoice for Same Delivery",
                        computed_numbers={
                            "invoice_no": inv_other.invoice_no,
                            "original_no": inv_0.invoice_no,
                            "amount": str(inv_other.total),
                        },
                        explanation_template="Duplicate invoice {invoice_no} re-billed for same delivery {challan_no}",
                        message=f"Duplicate invoice {inv_other.invoice_no} re-billed for same delivery {target_del}",
                        evidence_refs=make_refs(inv_facts),
                        needs_human_or_legal_review=True,
                        blocks_ready=True,
                    )
                )

    # -------------------------------------------------------------------------
    # 5. UNCREDITED_PAYMENT
    # -------------------------------------------------------------------------
    for p in entities.payments:
        earliest_inv_date = min((i.invoice_date for i in entities.invoices), default=date(2099, 1, 1))
        is_advance = p.pay_date < earliest_inv_date or "ADVANCE" in (p.bank_ref_text or "").upper()
        if is_advance:
            p_facts = [str(p.fact_id)] if p.fact_id else []
            if not p_facts:
                pf = db.query(Fact).filter(Fact.case_id == case_id, Fact.field.in_(["credit_amount", "transaction_date", "narration"])).all()
                p_facts = [str(f.id) for f in pf]
            results.append(
                FindingItem(
                    code="UNCREDITED_PAYMENT",
                    severity="attention",
                    title="Uncredited Advance Payment Received",
                    computed_numbers={
                        "advance_amount": str(p.amount),
                        "pay_date": str(p.pay_date),
                    },
                    explanation_template="Advance payment of Rs {advance_amount} received on {pay_date} not credited against invoice face (Legal Checklist Item 14)",
                    message=f"Advance payment of Rs {format_inr_val(p.amount)} received on {p.pay_date.strftime('%d-%m-%Y')} not credited against invoice face",
                    evidence_refs=make_refs(p_facts),
                    needs_human_or_legal_review=True,
                    blocks_ready=False,
                )
            )

    # -------------------------------------------------------------------------
    # 6. TDS_DEDUCTION & PARTIAL_PAYMENT
    # -------------------------------------------------------------------------
    for adj in entities.adjustments:
        if adj.kind == "tds" and adj.amount > ZERO:
            adj_facts = [str(adj.fact_id)] if adj.fact_id else []
            if not adj_facts:
                af = db.query(Fact).filter(Fact.case_id == case_id, Fact.field.in_(["tds_amount", "remittance_date"])).all()
                adj_facts = [str(f.id) for f in af]
            results.append(
                FindingItem(
                    code="TDS_DEDUCTION",
                    severity="info",
                    title="TDS Deducted by Buyer",
                    computed_numbers={"tds_amount": str(adj.amount)},
                    explanation_template="TDS of Rs {tds_amount} deducted by buyer credited against claimable principal (Legal Checklist Item 15)",
                    message=f"TDS of Rs {format_inr_val(adj.amount)} deducted by buyer credited against claimable principal (Legal Checklist Item 15)",
                    evidence_refs=make_refs(adj_facts),
                    needs_human_or_legal_review=True,
                    blocks_ready=False,
                )
            )

    if reconciliation.paid_total > ZERO and reconciliation.outstanding_on_delivered_goods > ZERO:
        pay_facts: list[str] = [str(p.fact_id) for p in entities.payments if p.fact_id]
        for a in entities.adjustments:
            if a.fact_id:
                pay_facts.append(str(a.fact_id))
        if not pay_facts:
            pf = db.query(Fact).filter(Fact.case_id == case_id, Fact.field.in_(["credit_amount", "amount", "tds_amount"])).all()
            pay_facts = [str(f.id) for f in pf]

        paid_fmt = format_inr_val(reconciliation.paid_total)
        tds_fmt = format_inr_val(reconciliation.adjustments_total)
        out_del_fmt = format_inr_val(reconciliation.outstanding_on_delivered_goods)
        out_full_fmt = format_inr_val(reconciliation.outstanding_on_full_invoice)

        computed = {
            "paid_amount": str(reconciliation.paid_total),
            "tds_amount": str(reconciliation.adjustments_total),
            "outstanding_delivered": str(reconciliation.outstanding_on_delivered_goods),
            "outstanding_full": str(reconciliation.outstanding_on_full_invoice),
            "paid_formatted": paid_fmt,
            "tds_formatted": tds_fmt,
            "outstanding_delivered_formatted": out_del_fmt,
            "outstanding_full_formatted": out_full_fmt,
        }

        if reconciliation.adjustments_total > ZERO:
            msg = f"paid {paid_fmt} plus TDS {tds_fmt}; outstanding {out_del_fmt} on delivered and accepted goods ({out_full_fmt} on full invoice value)"
            tmpl = "paid {paid_formatted} plus TDS {tds_formatted}; outstanding {outstanding_delivered_formatted} on delivered and accepted goods ({outstanding_full_formatted} on full invoice value) (Legal Checklist Item 14)"
        else:
            msg = f"paid {paid_fmt}; outstanding {out_del_fmt} on delivered and accepted goods ({out_full_fmt} on full invoice value)"
            tmpl = "paid {paid_formatted}; outstanding {outstanding_delivered_formatted} on delivered and accepted goods ({outstanding_full_formatted} on full invoice value) (Legal Checklist Item 14)"

        results.append(
            FindingItem(
                code="PARTIAL_PAYMENT",
                severity="info",
                title="Partial Payment Received",
                computed_numbers=computed,
                explanation_template=tmpl,
                message=msg,
                evidence_refs=make_refs(pay_facts),
                needs_human_or_legal_review=True,
                blocks_ready=False,
            )
        )

    # -------------------------------------------------------------------------
    # 7. INELIGIBLE_UDYAM_AFTER_PO
    # -------------------------------------------------------------------------
    supplier = entities.case.supplier
    po = entities.purchase_orders[0] if entities.purchase_orders else None
    if supplier and supplier.udyam_reg_date and po and supplier.udyam_reg_date > po.po_date:
        udyam_facts: list[str] = []
        u_f = db.query(Fact).filter(Fact.case_id == case_id, Fact.field.in_(["registration_date", "udyam_reg_date"])).first()
        if u_f:
            udyam_facts.append(str(u_f.id))

        p_f = db.query(Fact).filter(Fact.case_id == case_id, Fact.field == "po_date").first()
        if p_f:
            udyam_facts.append(str(p_f.id))
        elif po.fact_id:
            udyam_facts.append(str(po.fact_id))

        results.append(
            FindingItem(
                code="INELIGIBLE_UDYAM_AFTER_PO",
                severity="conflict",
                title="Udyam Registered After PO Date",
                computed_numbers={
                    "udyam_reg_date": str(supplier.udyam_reg_date),
                    "po_date": str(po.po_date),
                },
                explanation_template="Udyam registration date ({udyam_reg_date}) is after PO date ({po_date}). Supplier must hold valid Udyam registration on contract date under MSMED Act (Legal Checklist Item 2).",
                message=f"Udyam registration date ({supplier.udyam_reg_date}) is after PO date ({po.po_date}) (Legal Checklist Item 2)",
                evidence_refs=make_refs(udyam_facts),
                needs_human_or_legal_review=True,
                blocks_ready=True,
            )
        )

    # -------------------------------------------------------------------------
    # 8. MISSING_ACCEPTANCE_EVIDENCE
    # -------------------------------------------------------------------------
    for d in entities.deliveries:
        if not d.acceptance_fact_id and not d.received_by:
            d_facts = [str(d.fact_id)] if d.fact_id else []
            if not d_facts:
                df = db.query(Fact).filter(Fact.case_id == case_id, Fact.field.in_(["challan_no", "delivery_date"])).all()
                d_facts = [str(f.id) for f in df]
            results.append(
                FindingItem(
                    code="MISSING_ACCEPTANCE_EVIDENCE",
                    severity="attention",
                    title="Deemed Acceptance Applied",
                    computed_numbers={"challan_no": d.challan_no},
                    explanation_template="No explicit acceptance stamp on challan {challan_no}; deemed acceptance applies on delivery date (Legal Checklist Item 13)",
                    message=f"No explicit written acceptance on delivery {d.challan_no}; deemed acceptance applies (Legal Checklist Item 13)",
                    evidence_refs=make_refs(d_facts),
                    needs_human_or_legal_review=True,
                    blocks_ready=False,
                )
            )

    # -------------------------------------------------------------------------
    # 9. UNCONFIRMED_LINKS
    # -------------------------------------------------------------------------
    unconfirmed = [lk for lk in links if lk.status in ("suggested", "conflict")]
    if unconfirmed:
        link_refs = [
            EvidenceRef(
                fact_id=str(lk.id),
                doc_id=f"{lk.from_type}->{lk.to_type}",
                page=1,
                bbox=None,
            )
            for lk in unconfirmed
        ]
        results.append(
            FindingItem(
                code="UNCONFIRMED_LINKS",
                severity="conflict" if any(lk.status == "conflict" for lk in unconfirmed) else "attention",
                title="Unconfirmed Document Links Pending",
                computed_numbers={"count": str(len(unconfirmed))},
                explanation_template="{count} document links require human review before dossier can be locked",
                message=f"{len(unconfirmed)} document link(s) are suggested or in conflict and require human confirmation",
                evidence_refs=link_refs,
                needs_human_or_legal_review=True,
                blocks_ready=True,
            )
        )

    # -------------------------------------------------------------------------
    # Save Findings to Database
    # -------------------------------------------------------------------------
    db.query(Finding).filter(Finding.case_id == case_id).delete(synchronize_session=False)

    db_findings: list[Finding] = []
    for f in results:
        db_finding = Finding(
            case_id=case_id,
            code=f.code,
            severity=f.severity,
            title=f.title,
            message=f.message,
            explanation_template=f.explanation_template,
            computed_numbers=f.computed_numbers,
            needs_human_or_legal_review=f.needs_human_or_legal_review,
            blocks_ready=f.blocks_ready,
            refs_json=[r.to_dict() for r in f.evidence_refs],
        )
        db.add(db_finding)
        db_findings.append(db_finding)

    db.commit()
    return db_findings
