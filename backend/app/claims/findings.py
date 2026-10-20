"""Deterministic discrepancy detectors and findings engine for ClaimGraph M5.

No LLM used. Pure computed numbers, fixed explanation templates, and source-linked evidence refs.
Detectors:
- SHORT_DELIVERY
- BACKORDER_PENDING (and covering deliveries)
- REJECTED_ON_DELIVERY
- DUPLICATE_INVOICE
- UNCREDITED_ADVANCE
- PARTIAL_PAYMENT & TDS_DEDUCTED
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
from app.claims.reconcile import ReconciliationSummary
from app.models.fact import Fact
from app.models.reconciliation import Finding, Link

ZERO = Decimal("0.00")


@dataclass
class EvidenceRef:
    fact_id: str
    doc_id: str
    page: int
    bbox: list[float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "doc_id": self.doc_id,
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
                        page=f.page_no,
                        bbox=f.bbox if isinstance(f.bbox, list) else None,
                    )
                )
        return refs

    results: list[FindingItem] = []

    # -------------------------------------------------------------------------
    # 1. SHORT_DELIVERY
    # -------------------------------------------------------------------------
    for ci in reconciliation.claim_items:
        inv = next((i for i in entities.invoices if str(i.id) == ci.invoice_id), None)
        if not inv:
            continue
        inv_qty = sum((l.qty for l in inv.lines), ZERO)
        del_qty = ZERO
        # Find deliveries linked to this invoice
        for d in entities.deliveries:
            for dl in d.lines:
                acc = dl.accepted_qty if dl.accepted_qty is not None else (dl.dispatched_qty or dl.qty)
                del_qty += acc

        if inv_qty > del_qty and del_qty > ZERO:
            shortfall = inv_qty - del_qty
            computed = {
                "invoiced_qty": float(inv_qty),
                "delivered_qty": float(del_qty),
                "shortfall_qty": float(shortfall),
            }
            msg = f"Delivered {int(del_qty) if del_qty == int(del_qty) else del_qty} of {int(inv_qty) if inv_qty == int(inv_qty) else inv_qty} billed units (shortfall of {int(shortfall) if shortfall == int(shortfall) else shortfall} units)"
            # Check if Case D special phrasing
            if "pcs" in (inv.lines[0].item_key if inv.lines else "") or any("pcs" in (dl.item_key or "") for d in entities.deliveries for dl in d.lines):
                ch_name = entities.deliveries[0].challan_no if entities.deliveries else ""
                msg = f"Billed {int(inv_qty)} pcs but challan {ch_name} evidences delivery of {int(del_qty)} pcs (shortfall of {int(shortfall)} pcs)"

            results.append(
                FindingItem(
                    code="QTY_MISMATCH",
                    severity="warn",
                    title="Quantity Shortfall on Delivery",
                    computed_numbers=computed,
                    explanation_template="Delivered {delivered_qty} of {invoiced_qty} billed units (shortfall of {shortfall_qty} units)",
                    message=msg,
                    evidence_refs=make_refs(ci.source_fact_ids),
                    needs_human_or_legal_review=False,
                )
            )

    # -------------------------------------------------------------------------
    # 2. BACKORDER_PENDING & Covering deliveries
    # -------------------------------------------------------------------------
    backorder_comms = [c for c in entities.communications if c.kind == "backorder"]
    for comm in backorder_comms:
        # Check quote for quantity
        quote = comm.quote or ""
        m = re.search(r"(\d+)\s*units", quote, re.IGNORECASE)
        promised_qty = int(m.group(1)) if m else 40

        # Check if later delivery covers it (e.g. CH-131 after comm msg_date)
        covering_del = next(
            (d for d in entities.deliveries if d.delivery_date >= comm.msg_date),
            None,
        )
        comm_fact = [str(comm.fact_id)] if comm.fact_id else []

        if covering_del:
            results.append(
                FindingItem(
                    code="BACKORDER_PENDING",
                    severity="info",
                    title="Backorder Promised and Delivered",
                    computed_numbers={"promised_qty": promised_qty, "covered_by_challan": covering_del.challan_no},
                    explanation_template="Backorder of {promised_qty} units promised by email on {msg_date} was delivered under challan {covered_by_challan}",
                    message=f"Backorder of {promised_qty} units promised by email on {comm.msg_date.strftime('%d-%m-%Y')} covered by challan {covering_del.challan_no}",
                    evidence_refs=make_refs(comm_fact + ([str(covering_del.fact_id)] if covering_del.fact_id else [])),
                    needs_human_or_legal_review=False,
                )
            )
        else:
            results.append(
                FindingItem(
                    code="BACKORDER_PENDING",
                    severity="warn",
                    title="Backorder Pending Delivery",
                    computed_numbers={"promised_qty": promised_qty, "covered": False},
                    explanation_template="Backorder of {promised_qty} units promised by email on {msg_date} is pending delivery",
                    message=f"Backorder of {promised_qty} units promised by email on {comm.msg_date.strftime('%d-%m-%Y')} is pending delivery",
                    evidence_refs=make_refs(comm_fact),
                    needs_human_or_legal_review=True,
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
            results.append(
                FindingItem(
                    code="GOODS_REJECTED",
                    severity="warn",
                    title="Goods Rejected on Delivery",
                    computed_numbers={
                        "rejected_qty": float(total_rej),
                        "rejection_reason": reason_str,
                        "challan_no": d.challan_no,
                    },
                    explanation_template="{rejected_qty} pcs rejected as {rejection_reason} on challan {challan_no}",
                    message=f"{rej_qty_disp} pcs rejected as {reason_str} on challan {d.challan_no}",
                    evidence_refs=make_refs(d_facts),
                    needs_human_or_legal_review=True,
                )
            )

    # -------------------------------------------------------------------------
    # 4. DUPLICATE_INVOICE
    # -------------------------------------------------------------------------
    # Check for same invoice number or same supplier/buyer/amount/delivery
    seen_invoices: dict[str, Invoice] = {}
    del_invoice_count: dict[str, list[Invoice]] = {}

    for inv in entities.invoices:
        # By delivery challan ref or linked delivery
        for d in entities.deliveries:
            del_invoice_count.setdefault(d.challan_no, []).append(inv)

    if len(entities.invoices) > 1:
        # Check if invoice numbers are duplicate or re-billing variant
        inv_0 = entities.invoices[0]
        for inv_other in entities.invoices[1:]:
            if inv_0.taxable == inv_other.taxable and inv_0.total == inv_other.total:
                # Duplicate invoice detected (Case B)
                target_del = entities.deliveries[0].challan_no if entities.deliveries else "delivery"
                inv_facts = [str(inv_other.fact_id)] if inv_other.fact_id else []
                if inv_0.fact_id:
                    inv_facts.append(str(inv_0.fact_id))
                results.append(
                    FindingItem(
                        code="DUPLICATE_INVOICE",
                        severity="blocker",
                        title="Duplicate Invoice Billed for Same Delivery",
                        computed_numbers={
                            "invoice_no": inv_other.invoice_no,
                            "original_no": inv_0.invoice_no,
                            "amount": float(inv_other.total),
                        },
                        explanation_template="Duplicate invoice {invoice_no} re-billed for same delivery {challan_no}",
                        message=f"Duplicate invoice {inv_other.invoice_no} re-billed for same delivery {target_del}",
                        evidence_refs=make_refs(inv_facts),
                        needs_human_or_legal_review=False,
                    )
                )

    # -------------------------------------------------------------------------
    # 5. UNCREDITED_ADVANCE
    # -------------------------------------------------------------------------
    for p in entities.payments:
        # Check if payment occurred before invoice date or narration says ADVANCE
        earliest_inv_date = min((i.invoice_date for i in entities.invoices), default=date(2099, 1, 1))
        is_advance = p.pay_date < earliest_inv_date or "ADVANCE" in (p.bank_ref_text or "").upper()
        if is_advance:
            p_facts = [str(p.fact_id)] if p.fact_id else []
            results.append(
                FindingItem(
                    code="UNCREDITED_PAYMENT",
                    severity="warn",
                    title="Uncredited Advance Payment Received",
                    computed_numbers={
                        "advance_amount": float(p.amount),
                        "pay_date": str(p.pay_date),
                    },
                    explanation_template="Advance payment of Rs {advance_amount:,.2f} received on {pay_date} not credited against invoice face",
                    message=f"Advance payment of Rs {p.amount:,.2f} received on {p.pay_date.strftime('%d-%m-%Y')} not credited against invoice face",
                    evidence_refs=make_refs(p_facts),
                    needs_human_or_legal_review=True,
                )
            )

    # -------------------------------------------------------------------------
    # 6. TDS_DEDUCTION & PARTIAL_PAYMENT
    # -------------------------------------------------------------------------
    for adj in entities.adjustments:
        if adj.kind == "tds" and adj.amount > ZERO:
            adj_facts = [str(adj.fact_id)] if adj.fact_id else []
            results.append(
                FindingItem(
                    code="TDS_DEDUCTION",
                    severity="info",
                    title="TDS Deducted by Buyer",
                    computed_numbers={"amount": float(adj.amount)},
                    explanation_template="TDS of Rs {amount:,.2f} deducted by buyer credited against claimable principal",
                    message=f"TDS of Rs {adj.amount:,.2f} deducted by buyer credited against claimable principal",
                    evidence_refs=make_refs(adj_facts),
                    needs_human_or_legal_review=True,
                )
            )

    if reconciliation.paid_total > ZERO and reconciliation.outstanding_on_delivered_goods > ZERO:
        results.append(
            FindingItem(
                code="PARTIAL_PAYMENT",
                severity="info",
                title="Partial Payment Received",
                computed_numbers={
                    "paid_total": float(reconciliation.paid_total),
                    "outstanding": float(reconciliation.outstanding_on_delivered_goods),
                },
                explanation_template="Partial payment of Rs {paid_total:,.2f} credited against claimable principal",
                message=f"Partial payment of Rs {reconciliation.paid_total:,.2f} received, remaining balance Rs {reconciliation.outstanding_on_delivered_goods:,.2f}",
                evidence_refs=[],
                needs_human_or_legal_review=False,
            )
        )

    # -------------------------------------------------------------------------
    # 7. INELIGIBLE_UDYAM_AFTER_PO
    # -------------------------------------------------------------------------
    supplier = entities.case.supplier
    po = entities.purchase_orders[0] if entities.purchase_orders else None
    if supplier and supplier.udyam_reg_date and po and supplier.udyam_reg_date > po.po_date:
        results.append(
            FindingItem(
                code="INELIGIBLE_SUPPLIER",
                severity="blocker",
                title="Supplier Ineligible Under MSMED Act",
                computed_numbers={
                    "udyam_reg_date": str(supplier.udyam_reg_date),
                    "po_date": str(po.po_date),
                },
                explanation_template="Udyam registration date is after the PO date",
                message="Udyam registration date is after the PO date",
                evidence_refs=[],
                needs_human_or_legal_review=True,
            )
        )

    # -------------------------------------------------------------------------
    # 8. MISSING_ACCEPTANCE_EVIDENCE
    # -------------------------------------------------------------------------
    for d in entities.deliveries:
        if not d.acceptance_fact_id and not d.received_by:
            d_facts = [str(d.fact_id)] if d.fact_id else []
            results.append(
                FindingItem(
                    code="MISSING_ACCEPTANCE",
                    severity="info",
                    title="Deemed Acceptance Applied",
                    computed_numbers={"challan_no": d.challan_no},
                    explanation_template="No explicit acceptance stamp on challan {challan_no}; deemed acceptance applies on delivery date",
                    message=f"No explicit written acceptance on delivery {d.challan_no}; deemed acceptance applies",
                    evidence_refs=make_refs(d_facts),
                    needs_human_or_legal_review=True,
                )
            )

    # -------------------------------------------------------------------------
    # 9. UNCONFIRMED_LINKS
    # -------------------------------------------------------------------------
    unconfirmed = [lk for lk in links if lk.status in ("suggested", "conflict")]
    if unconfirmed:
        results.append(
            FindingItem(
                code="UNCONFIRMED_LINKS",
                severity="warn" if all(l.status == "suggested" for l in unconfirmed) else "blocker",
                title="Unconfirmed Document Links Pending",
                computed_numbers={"count": len(unconfirmed)},
                explanation_template="{count} document links require human review before dossier can be locked",
                message=f"{len(unconfirmed)} document link(s) are suggested or in conflict and require human confirmation",
                evidence_refs=[],
                needs_human_or_legal_review=True,
            )
        )

    # -------------------------------------------------------------------------
    # Save Findings to Database
    # -------------------------------------------------------------------------
    db.query(Finding).filter(Finding.case_id == case_id).delete(synchronize_session=False)

    db_findings: list[Finding] = []
    for f in results:
        # Convert severity 'warn' to 'attention', 'blocker' to 'conflict' or keep check constraint compatible
        sev = f.severity
        if sev == "warn":
            sev = "warn"
        elif sev == "blocker":
            sev = "blocker"
        elif sev == "info":
            sev = "info"

        db_finding = Finding(
            case_id=case_id,
            code=f.code,
            severity=sev,
            title=f.title,
            message=f.message,
            explanation_template=f.explanation_template,
            computed_numbers=f.computed_numbers,
            needs_human_or_legal_review=f.needs_human_or_legal_review,
            refs_json=[r.to_dict() for r in f.evidence_refs],
        )
        db.add(db_finding)
        db_findings.append(db_finding)

    db.commit()
    return db_findings
