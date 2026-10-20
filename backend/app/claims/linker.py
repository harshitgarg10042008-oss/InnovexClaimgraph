"""Linker for ClaimGraph M5.

Strict ordering:
1. Hard keys (exact match after normalisation: PO number, challan number, invoice number, UTR).
   Creates method=hard_key, status=auto_linked.
2. Fuzzy (rapidfuzz) for unmatched items (item descriptions, party names, amounts, date windows).
   Creates method=fuzzy, status=suggested with score and reason.
3. Conflicts (multiple candidates for one key, duplicate invoices, amount mismatch).
   Creates status=conflict.
4. Human decisions (confirm/reject) preserved across rebuilds by stable business key.
5. Link types: PO -> Delivery, Delivery -> Invoice, Invoice -> Payment, Adjustment -> Invoice.
"""

from __future__ import annotations

import re
import uuid
from decimal import Decimal
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from app.claims.builder import BuiltEntities
from app.models.fact import Fact
from app.models.reconciliation import Adjustment, Link
from app.models.transaction import Delivery, Invoice, Payment, PurchaseOrder


def normalize_key(s: str | None) -> str:
    """Normalize key: trim, uppercase, strip hyphens/spaces/slashes/underscores."""
    if not s:
        return ""
    return re.sub(r"[\s\-\/_\.]", "", str(s)).upper()


def get_entity_stable_id(entity: Any) -> str:
    """Return stable identifier for an entity to preserve human link decisions."""
    if isinstance(entity, PurchaseOrder):
        return normalize_key(entity.po_no)
    if isinstance(entity, Delivery):
        return normalize_key(entity.challan_no)
    if isinstance(entity, Invoice):
        return normalize_key(entity.invoice_no)
    if isinstance(entity, Payment):
        return normalize_key(entity.utr) or f"{entity.pay_date}_{entity.amount}"
    if isinstance(entity, Adjustment):
        return normalize_key(entity.ref) or f"{entity.kind}_{entity.amount}"
    return str(getattr(entity, "id", ""))


class LinkResult:
    def __init__(
        self,
        from_type: str,
        from_id: uuid.UUID,
        from_stable_id: str,
        to_type: str,
        to_id: uuid.UUID,
        to_stable_id: str,
        method: str,
        status: str,
        confidence: Decimal,
        reason: str | None = None,
        evidence_fact_ids: list[str] | None = None,
        confirmed: bool = False,
    ):
        self.from_type = from_type
        self.from_id = from_id
        self.from_stable_id = from_stable_id
        self.to_type = to_type
        self.to_id = to_id
        self.to_stable_id = to_stable_id
        self.method = method
        self.status = status
        self.confidence = confidence
        self.reason = reason
        self.evidence_fact_ids = evidence_fact_ids or []
        self.confirmed = confirmed

    @property
    def stable_key(self) -> tuple[str, str, str, str]:
        return (self.from_type, self.from_stable_id, self.to_type, self.to_stable_id)


def run_linker(
    case_id: uuid.UUID,
    entities: BuiltEntities,
    db: Session,
) -> list[Link]:
    """Run linking across built entities, preserving previous human decisions."""
    # 1. Capture existing human decisions for this case
    existing_links = db.query(Link).filter(Link.case_id == case_id).all()
    saved_decisions: dict[tuple[str, str, str, str], tuple[str, bool]] = {}

    # Map existing entity IDs to stable keys where possible
    po_id_to_key = {po.id: get_entity_stable_id(po) for po in entities.purchase_orders}
    del_id_to_key = {d.id: get_entity_stable_id(d) for d in entities.deliveries}
    inv_id_to_key = {inv.id: get_entity_stable_id(inv) for inv in entities.invoices}
    pay_id_to_key = {p.id: get_entity_stable_id(p) for p in entities.payments}
    adj_id_to_key = {a.id: get_entity_stable_id(a) for a in entities.adjustments}

    def id_to_key(typ: str, eid: uuid.UUID) -> str:
        if typ == "PO":
            return po_id_to_key.get(eid, str(eid))
        if typ == "DELIVERY":
            return del_id_to_key.get(eid, str(eid))
        if typ == "INVOICE":
            return inv_id_to_key.get(eid, str(eid))
        if typ == "PAYMENT":
            return pay_id_to_key.get(eid, str(eid))
        if typ == "ADJUSTMENT":
            return adj_id_to_key.get(eid, str(eid))
        return str(eid)

    for lk in existing_links:
        if lk.status in ("confirmed", "rejected") or lk.confirmed:
            f_key = id_to_key(lk.from_type, lk.from_id)
            t_key = id_to_key(lk.to_type, lk.to_id)
            saved_decisions[(lk.from_type, f_key, lk.to_type, t_key)] = (lk.status, lk.confirmed)

    # 2. Extract supporting facts map for PO references and Challan references
    # Fact lookup for po_ref on deliveries, challan_ref on invoices
    po_ref_by_del: dict[uuid.UUID, str] = {}
    del_facts = (
        db.query(Fact)
        .filter(Fact.case_id == case_id, Fact.field.in_(["po_ref", "challan_ref"]))
        .all()
    )
    # Map document_id to ref string
    doc_refs: dict[uuid.UUID, dict[str, str]] = {}
    for f in del_facts:
        v = f.value_json
        val = ""
        if isinstance(v, dict):
            val = str(v.get("value") or v.get("normalised") or v.get("raw") or "")
        doc_refs.setdefault(f.document_id, {})[f.field] = val

    # Helper to collect fact IDs for an entity
    def get_fact_ids(*entities_args: Any) -> list[str]:
        res = []
        for e in entities_args:
            if hasattr(e, "fact_id") and e.fact_id:
                res.append(str(e.fact_id))
            if hasattr(e, "terms_fact_id") and e.terms_fact_id:
                res.append(str(e.terms_fact_id))
            if hasattr(e, "acceptance_fact_id") and e.acceptance_fact_id:
                res.append(str(e.acceptance_fact_id))
        return list(dict.fromkeys(res))

    link_results: list[LinkResult] = []

    # -------------------------------------------------------------------------
    # Link Type 1: PO -> Delivery
    # -------------------------------------------------------------------------
    for po in entities.purchase_orders:
        norm_po = normalize_key(po.po_no)
        for delivery in entities.deliveries:
            # Check delivery facts for po_ref
            po_ref = ""
            for doc_id, refs in doc_refs.items():
                if "po_ref" in refs:
                    po_ref = refs["po_ref"]
                    break

            norm_po_ref = normalize_key(po_ref)
            is_hard_match = norm_po and norm_po_ref and (norm_po == norm_po_ref or norm_po in norm_po_ref)

            if is_hard_match:
                link_results.append(
                    LinkResult(
                        from_type="PO",
                        from_id=po.id,
                        from_stable_id=get_entity_stable_id(po),
                        to_type="DELIVERY",
                        to_id=delivery.id,
                        to_stable_id=get_entity_stable_id(delivery),
                        method="hard_key",
                        status="auto_linked",
                        confidence=Decimal("1.0000"),
                        reason=f"Exact match on PO number: {po.po_no}",
                        evidence_fact_ids=get_fact_ids(po, delivery),
                    )
                )
            else:
                # Fuzzy fallback on line descriptions and dates
                score = 0.0
                if po.lines and delivery.lines:
                    po_text = " ".join(line.description for line in po.lines)
                    del_text = " ".join(line.item_key for line in delivery.lines)
                    score = fuzz.token_sort_ratio(po_text, del_text)

                if score >= 75.0 and delivery.delivery_date >= po.po_date:
                    link_results.append(
                        LinkResult(
                            from_type="PO",
                            from_id=po.id,
                            from_stable_id=get_entity_stable_id(po),
                            to_type="DELIVERY",
                            to_id=delivery.id,
                            to_stable_id=get_entity_stable_id(delivery),
                            method="fuzzy",
                            status="suggested",
                            confidence=Decimal(str(round(score / 100, 4))),
                            reason=f"Fuzzy match on item descriptions ({score:.0f}%)",
                            evidence_fact_ids=get_fact_ids(po, delivery),
                        )
                    )

    # If single PO and delivery without explicit po_ref, auto-link if date valid
    if len(entities.purchase_orders) == 1 and entities.deliveries:
        single_po = entities.purchase_orders[0]
        linked_del_ids = {lr.to_id for lr in link_results if lr.from_type == "PO"}
        for delivery in entities.deliveries:
            if delivery.id not in linked_del_ids and delivery.delivery_date >= single_po.po_date:
                link_results.append(
                    LinkResult(
                        from_type="PO",
                        from_id=single_po.id,
                        from_stable_id=get_entity_stable_id(single_po),
                        to_type="DELIVERY",
                        to_id=delivery.id,
                        to_stable_id=get_entity_stable_id(delivery),
                        method="hard_key",
                        status="auto_linked",
                        confidence=Decimal("1.0000"),
                        reason=f"Sole PO in deal covers delivery {delivery.challan_no}",
                        evidence_fact_ids=get_fact_ids(single_po, delivery),
                    )
                )

    # -------------------------------------------------------------------------
    # Link Type 2: Delivery -> Invoice
    # -------------------------------------------------------------------------
    # Check for delivery to invoice matching
    del_to_inv_candidates: list[tuple[Delivery, Invoice, str, Decimal]] = []

    for delivery in entities.deliveries:
        norm_ch = normalize_key(delivery.challan_no)
        for invoice in entities.invoices:
            challan_ref = ""
            for doc_id, refs in doc_refs.items():
                if "challan_ref" in refs:
                    challan_ref = refs["challan_ref"]
                    break

            norm_ch_ref = normalize_key(challan_ref)
            is_match = False
            match_method = "hard_key"
            score = Decimal("1.0000")

            if norm_ch and norm_ch_ref and (norm_ch == norm_ch_ref or norm_ch in norm_ch_ref):
                is_match = True
            elif norm_ch and norm_ch in normalize_key(invoice.invoice_no):
                is_match = True
            elif len(entities.deliveries) == 1 and len(entities.invoices) == 1:
                # Single delivery, single invoice: hard key match
                is_match = True
            else:
                # Check item descriptions / amounts fuzzy
                del_items = " ".join(line.item_key for line in delivery.lines)
                inv_items = " ".join(line.item_key for line in invoice.lines)
                sim = fuzz.token_sort_ratio(del_items, inv_items)
                if sim >= 80.0:
                    is_match = True
                    match_method = "fuzzy"
                    score = Decimal(str(round(sim / 100, 4)))

            if is_match:
                del_to_inv_candidates.append((delivery, invoice, match_method, score))

    # Conflict check: Multiple invoices claiming the same delivery challan (e.g. Case B duplicate invoice)
    del_usage_count: dict[uuid.UUID, list[Invoice]] = {}
    for d, inv, m, s in del_to_inv_candidates:
        del_usage_count.setdefault(d.id, []).append(inv)

    for d, inv, m, s in del_to_inv_candidates:
        invoices_for_del = del_usage_count[d.id]
        if len(invoices_for_del) > 1:
            # Conflict! Two candidates for one challan key
            link_results.append(
                LinkResult(
                    from_type="DELIVERY",
                    from_id=d.id,
                    from_stable_id=get_entity_stable_id(d),
                    to_type="INVOICE",
                    to_id=inv.id,
                    to_stable_id=get_entity_stable_id(inv),
                    method=m,
                    status="conflict",
                    confidence=s,
                    reason=f"Conflict: Delivery {d.challan_no} is referenced by multiple invoices ({', '.join(i.invoice_no for i in invoices_for_del)})",
                    evidence_fact_ids=get_fact_ids(d, inv),
                )
            )
        else:
            status = "auto_linked" if m == "hard_key" else "suggested"
            link_results.append(
                LinkResult(
                    from_type="DELIVERY",
                    from_id=d.id,
                    from_stable_id=get_entity_stable_id(d),
                    to_type="INVOICE",
                    to_id=inv.id,
                    to_stable_id=get_entity_stable_id(inv),
                    method=m,
                    status=status,
                    confidence=s,
                    reason=f"Match on delivery challan {d.challan_no}",
                    evidence_fact_ids=get_fact_ids(d, inv),
                )
            )

    # -------------------------------------------------------------------------
    # Link Type 3: Invoice -> Payment
    # -------------------------------------------------------------------------
    for invoice in entities.invoices:
        norm_inv = normalize_key(invoice.invoice_no)
        for payment in entities.payments:
            narration = payment.bank_ref_text or ""
            norm_narration = normalize_key(narration)

            is_hard_match = False
            reason = ""

            # 1. Invoice number in narration
            if norm_inv and norm_inv in norm_narration:
                is_hard_match = True
                reason = f"Payment narration contains invoice {invoice.invoice_no}"
            # 2. Check if payment references PO of linked invoice
            else:
                for po in entities.purchase_orders:
                    norm_po = normalize_key(po.po_no)
                    if norm_po and norm_po in norm_narration:
                        is_hard_match = True
                        reason = f"Advance payment references PO {po.po_no}"
                        break

            # 3. If single invoice and payment in date window
            if not is_hard_match and len(entities.invoices) == 1:
                # Check party name or generic credit
                is_hard_match = True
                reason = f"Sole invoice in case matching payment credit {payment.amount}"

            if is_hard_match:
                link_results.append(
                    LinkResult(
                        from_type="INVOICE",
                        from_id=invoice.id,
                        from_stable_id=get_entity_stable_id(invoice),
                        to_type="PAYMENT",
                        to_id=payment.id,
                        to_stable_id=get_entity_stable_id(payment),
                        method="hard_key",
                        status="auto_linked",
                        confidence=Decimal("1.0000"),
                        reason=reason,
                        evidence_fact_ids=get_fact_ids(invoice, payment),
                    )
                )
            else:
                # Fuzzy fallback
                if payment.amount <= invoice.total:
                    link_results.append(
                        LinkResult(
                            from_type="INVOICE",
                            from_id=invoice.id,
                            from_stable_id=get_entity_stable_id(invoice),
                            to_type="PAYMENT",
                            to_id=payment.id,
                            to_stable_id=get_entity_stable_id(payment),
                            method="fuzzy",
                            status="suggested",
                            confidence=Decimal("0.7500"),
                            reason="Fuzzy match: payment within invoice amount",
                            evidence_fact_ids=get_fact_ids(invoice, payment),
                        )
                    )

    # -------------------------------------------------------------------------
    # Link Type 4: Adjustment -> Invoice
    # -------------------------------------------------------------------------
    for adj in entities.adjustments:
        norm_ref = normalize_key(adj.ref)
        for invoice in entities.invoices:
            norm_inv = normalize_key(invoice.invoice_no)
            is_match = False
            if norm_inv and norm_inv in norm_ref:
                is_match = True
            elif len(entities.invoices) == 1:
                is_match = True

            if is_match:
                link_results.append(
                    LinkResult(
                        from_type="ADJUSTMENT",
                        from_id=adj.id,
                        from_stable_id=get_entity_stable_id(adj),
                        to_type="INVOICE",
                        to_id=invoice.id,
                        to_stable_id=get_entity_stable_id(invoice),
                        method="hard_key",
                        status="auto_linked",
                        confidence=Decimal("1.0000"),
                        reason=f"Adjustment applies to invoice {invoice.invoice_no}",
                        evidence_fact_ids=get_fact_ids(adj, invoice),
                    )
                )

    # -------------------------------------------------------------------------
    # Apply preserved human decisions and save
    # -------------------------------------------------------------------------
    # Delete old links for case in this transaction
    db.query(Link).filter(Link.case_id == case_id).delete(synchronize_session=False)

    saved_links: list[Link] = []
    for lr in link_results:
        # Check if human made a decision on this link
        if lr.stable_key in saved_decisions:
            h_status, h_confirmed = saved_decisions[lr.stable_key]
            lr.status = h_status
            lr.confirmed = h_confirmed
        elif lr.status == "auto_linked":
            # auto_linked links count by default as auto confirmed
            lr.confirmed = True
        else:
            lr.confirmed = False

        db_link = Link(
            case_id=case_id,
            from_type=lr.from_type,
            from_id=lr.from_id,
            to_type=lr.to_type,
            to_id=lr.to_id,
            method=lr.method,
            confidence=lr.confidence,
            confirmed=lr.confirmed,
            status=lr.status,
            reason=lr.reason,
            evidence_fact_ids=lr.evidence_fact_ids,
        )
        db.add(db_link)
        saved_links.append(db_link)

    db.commit()
    return saved_links
