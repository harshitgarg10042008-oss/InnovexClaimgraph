"""Reconciliation and Ledger Engine for ClaimGraph M5.

- Creates claim items per invoice.
- Claimable principal = delivered AND accepted goods value (including GST).
- Configurable payment allocation strategy (default: oldest_due_date_first).
- TDS and other adjustments tracked as separate ledger lines.
- Due date, eligibility, interest, limitation, and readiness score computed exclusively via app.rules.
- All money math uses Decimal with 2 decimal places. No floats in money paths.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.claims.builder import BuiltEntities
from app.models.reconciliation import Link
from app.models.rule import RateTable as DbRateTable
from app.models.transaction import Delivery, Invoice, Payment, PurchaseOrder
from app.rules.engine import evaluate_claim
from app.rules.pack_loader import get_active_pack
from app.rules.score import compute_case_score
from app.rules.types import (
    ClaimItem as RuleClaimItem,
    ClaimResult,
    EligibilityStatus,
    PartyFacts,
    Payment as RulePayment,
    PaymentKind,
    RateRow,
    RateTable,
    ScoreInput,
    ScoreResult,
)

TWO_DP = Decimal("0.01")
ZERO = Decimal("0.00")


def quantize_money(d: Decimal | None) -> Decimal:
    if d is None:
        return ZERO
    return d.quantize(TWO_DP, rounding=ROUND_HALF_UP)


@dataclass
class LedgerRow:
    date: str
    type: str  # invoice | payment | tds | debit_note | credit_note
    reference: str
    debit: Decimal
    credit: Decimal
    running_balance: Decimal
    source_fact_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "type": self.type,
            "reference": self.reference,
            "debit": str(self.debit),
            "credit": str(self.credit),
            "running_balance": str(self.running_balance),
            "source_fact_ids": self.source_fact_ids,
        }


@dataclass
class PaymentAllocation:
    payment_id: str
    utr: str | None
    claim_item_id: str
    amount: Decimal
    strategy: str
    assumption: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "payment_id": self.payment_id,
            "utr": self.utr,
            "claim_item_id": self.claim_item_id,
            "amount": str(self.amount),
            "strategy": self.strategy,
            "assumption": self.assumption,
        }


@dataclass
class ReconciledClaimItem:
    id: str
    invoice_id: str
    invoice_no: str
    invoice_date: str
    invoiced_total: Decimal
    delivered_value: Decimal
    accepted_value: Decimal
    claim_basis: str  # delivered_and_accepted | full_invoice
    claimable_principal: Decimal
    full_invoice_principal: Decimal
    paid_amount: Decimal
    adjustment_amount: Decimal
    outstanding_on_delivered_goods: Decimal
    outstanding_on_full_invoice: Decimal
    due_date: str | None
    interest_start_date: str | None
    days_overdue: int | None
    interest_amount: Decimal | None
    interest_refused_reason: str | None
    total_claimable: Decimal | None
    rule_result: ClaimResult | None
    ledger_rows: list[LedgerRow] = field(default_factory=list)
    source_fact_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "invoice_id": self.invoice_id,
            "invoice_no": self.invoice_no,
            "invoice_date": self.invoice_date,
            "invoiced_total": str(self.invoiced_total),
            "delivered_value": str(self.delivered_value),
            "accepted_value": str(self.accepted_value),
            "claim_basis": self.claim_basis,
            "claimable_principal": str(self.claimable_principal),
            "full_invoice_principal": str(self.full_invoice_principal),
            "paid_amount": str(self.paid_amount),
            "adjustment_amount": str(self.adjustment_amount),
            "outstanding_on_delivered_goods": str(self.outstanding_on_delivered_goods),
            "outstanding_on_full_invoice": str(self.outstanding_on_full_invoice),
            "due_date": self.due_date,
            "interest_start_date": self.interest_start_date,
            "days_overdue": self.days_overdue,
            "interest_amount": str(self.interest_amount) if self.interest_amount is not None else None,
            "interest_refused_reason": self.interest_refused_reason,
            "total_claimable": str(self.total_claimable) if self.total_claimable is not None else None,
            "ledger_rows": [r.to_dict() for r in self.ledger_rows],
            "source_fact_ids": self.source_fact_ids,
        }


@dataclass
class ReconciliationSummary:
    invoiced_total: Decimal
    delivered_value: Decimal
    accepted_value: Decimal
    paid_total: Decimal
    adjustments_total: Decimal
    outstanding_on_delivered_goods: Decimal
    outstanding_on_full_invoice: Decimal
    interest_total: Decimal | None
    interest_status: str  # computed | refused: <reason>
    total_claimable: Decimal | None
    due_date: str | None
    assumptions: list[str] = field(default_factory=list)
    score_result: ScoreResult | None = None
    claim_items: list[ReconciledClaimItem] = field(default_factory=list)
    allocations: list[PaymentAllocation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "invoiced_total": str(self.invoiced_total),
            "delivered_value": str(self.delivered_value),
            "accepted_value": str(self.accepted_value),
            "paid_total": str(self.paid_total),
            "adjustments_total": str(self.adjustments_total),
            "outstanding_on_delivered_goods": str(self.outstanding_on_delivered_goods),
            "outstanding_on_full_invoice": str(self.outstanding_on_full_invoice),
            "interest_total": str(self.interest_total) if self.interest_total is not None else None,
            "interest_status": self.interest_status,
            "total_claimable": str(self.total_claimable) if self.total_claimable is not None else None,
            "due_date": self.due_date,
            "assumptions": self.assumptions,
            "case_score": str(self.score_result.case_score) if self.score_result else "0.00",
            "score_blockers": self.score_result.blockers if self.score_result else [],
            "claim_items": [ci.to_dict() for ci in self.claim_items],
            "allocations": [a.to_dict() for a in self.allocations],
        }


def get_rate_table(db: Session) -> RateTable:
    """Load RateTable from database or fallback to seed rates."""
    db_rows = db.query(DbRateTable).order_by(DbRateTable.effective_from.asc()).all()
    if db_rows:
        return RateTable(
            rows=[
                RateRow(
                    effective_from=r.effective_from,
                    bank_rate_pct=quantize_money(r.bank_rate_pct),
                )
                for r in db_rows
            ]
        )
    # Master plan seed rate table
    return RateTable(
        rows=[
            RateRow(effective_from=date(2025, 12, 6), bank_rate_pct=Decimal("5.50")),
            RateRow(effective_from=date(2026, 10, 7), bank_rate_pct=Decimal("5.75")),
        ]
    )


def run_reconciliation(
    entities: BuiltEntities,
    links: list[Link],
    db: Session,
    as_of: date = date(2026, 10, 14),
    allocation_strategy: str = "oldest_due_date_first",
    tds_as_payment: bool = True,
    claim_basis: str = "delivered_and_accepted",
) -> ReconciliationSummary:
    """Run full reconciliation pipeline according to Part 3 specs."""
    pack = get_active_pack()
    rate_table = get_rate_table(db)

    # 1. Filter links: ONLY auto_linked and confirmed links count in reconciliation!
    # Suggested (fuzzy) and conflict links NEVER count until a human confirms them.
    active_links = [
        lk for lk in links
        if (lk.confirmed or lk.status in ("auto_linked", "confirmed"))
        and lk.status not in ("suggested", "conflict", "rejected")
    ]

    # Map deliveries to invoices
    del_to_inv: dict[uuid.UUID, list[uuid.UUID]] = {}
    inv_to_del: dict[uuid.UUID, list[uuid.UUID]] = {}
    for lk in active_links:
        if lk.from_type == "DELIVERY" and lk.to_type == "INVOICE":
            del_to_inv.setdefault(lk.from_id, []).append(lk.to_id)
            inv_to_del.setdefault(lk.to_id, []).append(lk.from_id)

    # Map PO to Delivery / Invoice
    po_by_del: dict[uuid.UUID, PurchaseOrder] = {}
    del_map = {d.id: d for d in entities.deliveries}
    po_map = {po.id: po for po in entities.purchase_orders}
    for lk in active_links:
        if lk.from_type == "PO" and lk.to_type == "DELIVERY":
            if lk.to_id in del_map and lk.from_id in po_map:
                po_by_del[lk.to_id] = po_map[lk.from_id]

    # Map payments linked to invoices
    pay_to_inv: dict[uuid.UUID, list[uuid.UUID]] = {}
    for lk in active_links:
        if lk.from_type == "INVOICE" and lk.to_type == "PAYMENT":
            pay_to_inv.setdefault(lk.to_id, []).append(lk.from_id)

    # Map adjustments linked to invoices
    adj_to_inv: dict[uuid.UUID, list[uuid.UUID]] = {}
    for lk in active_links:
        if lk.from_type == "ADJUSTMENT" and lk.to_type == "INVOICE":
            adj_to_inv.setdefault(lk.from_id, []).append(lk.to_id)

    # Fallback: if only 1 PO and deliveries exist, link PO
    if len(entities.purchase_orders) == 1:
        default_po = entities.purchase_orders[0]
        for d in entities.deliveries:
            if d.id not in po_by_del:
                po_by_del[d.id] = default_po

    assumptions: list[str] = [
        f"Payment appropriation order: {allocation_strategy} (open legal item)",
    ]
    if tds_as_payment:
        assumptions.append("Treatment of TDS: credited as payment against claimable principal (open legal item)")

    # -------------------------------------------------------------------------
    # 2. Compute delivery and accepted values per invoice
    # -------------------------------------------------------------------------
    invoice_del_map: dict[uuid.UUID, list[Delivery]] = {}
    for inv in entities.invoices:
        linked_del_ids = inv_to_del.get(inv.id, [])
        # If no explicit links, and case has single invoice and deliveries:
        if not linked_del_ids and len(entities.invoices) == 1 and entities.deliveries:
            invoice_del_map[inv.id] = entities.deliveries
        else:
            invoice_del_map[inv.id] = [del_map[did] for did in linked_del_ids if did in del_map]

    # Total invoiced
    case_invoiced_total = sum((inv.total for inv in entities.invoices), ZERO)
    case_delivered_val = ZERO
    case_accepted_val = ZERO

    # Interim struct per invoice
    inv_calc: dict[uuid.UUID, dict[str, Any]] = {}

    for inv in entities.invoices:
        linked_dels = invoice_del_map.get(inv.id, [])

        inv_qty = sum((l.qty for l in inv.lines), ZERO)
        total_disp_qty = ZERO
        total_acc_qty = ZERO
        total_rej_qty = ZERO

        for d in linked_dels:
            for dl in d.lines:
                disp = dl.dispatched_qty or dl.qty
                acc = dl.accepted_qty if dl.accepted_qty is not None else disp
                rej = dl.rejected_qty or ZERO
                total_disp_qty += disp
                total_acc_qty += acc
                total_rej_qty += rej

        # Calculate delivered and accepted values
        if linked_dels and inv_qty > ZERO:
            # Check if line rates available
            if len(inv.lines) == 1:
                ratio_del = min(Decimal("1.0"), total_acc_qty / inv_qty) if total_acc_qty > ZERO else (total_disp_qty / inv_qty)
                del_val = quantize_money(inv.total * ratio_del)
                
                # Check for explicit accepted value
                if total_acc_qty > ZERO and total_rej_qty > ZERO:
                    rate = inv.lines[0].rate
                    gst_pct = (inv.gst / inv.taxable) if inv.taxable > ZERO else Decimal("0.18")
                    taxable_acc = total_acc_qty * rate
                    acc_val = quantize_money(taxable_acc * (Decimal("1.0") + gst_pct))
                else:
                    acc_val = del_val
            else:
                del_val = inv.total
                acc_val = inv.total
        elif not linked_dels:
            del_val = ZERO
            acc_val = ZERO
        else:
            del_val = inv.total
            acc_val = inv.total

        case_delivered_val += del_val
        case_accepted_val += acc_val

        # Primary PO and Delivery dates for due date clock
        primary_del = linked_dels[0] if linked_dels else None
        primary_po = po_by_del.get(primary_del.id) if primary_del else None
        if not primary_po and entities.purchase_orders:
            primary_po = entities.purchase_orders[0]

        del_date = primary_del.delivery_date if primary_del else inv.invoice_date
        written_acc_date = primary_del.delivery_date if (primary_del and primary_del.acceptance_fact_id) else None
        credit_days_written = primary_po.credit_days_written if primary_po else None

        # Claimable principal based on chosen basis
        claimable_p = acc_val if claim_basis == "delivered_and_accepted" else inv.total
        if claimable_p == ZERO and (acc_val > ZERO or del_val > ZERO):
            claimable_p = acc_val or del_val

        # Source fact IDs
        fact_ids = []
        if inv.fact_id:
            fact_ids.append(str(inv.fact_id))
        if primary_del and primary_del.fact_id:
            fact_ids.append(str(primary_del.fact_id))
        if primary_po and primary_po.fact_id:
            fact_ids.append(str(primary_po.fact_id))

        inv_calc[inv.id] = {
            "invoice": inv,
            "deliveries": linked_dels,
            "po": primary_po,
            "del_val": del_val,
            "acc_val": acc_val,
            "claimable_p": claimable_p,
            "del_date": del_date,
            "written_acc_date": written_acc_date,
            "credit_days": credit_days_written,
            "fact_ids": fact_ids,
        }

    # -------------------------------------------------------------------------
    # 3. Adjustments (TDS, etc.)
    # -------------------------------------------------------------------------
    inv_adjustments: dict[uuid.UUID, list[Adjustment]] = {inv.id: [] for inv in entities.invoices}
    for adj in entities.adjustments:
        target_inv_ids = adj_to_inv.get(adj.id, [])
        if not target_inv_ids and len(entities.invoices) == 1:
            target_inv_ids = [entities.invoices[0].id]
        for inv_id in target_inv_ids:
            if inv_id in inv_adjustments:
                inv_adjustments[inv_id].append(adj)

    # -------------------------------------------------------------------------
    # 4. Payment Allocations (Strategy: oldest_due_date_first)
    # -------------------------------------------------------------------------
    # Sort invoices by delivery/invoice date for oldest-first allocation
    sorted_inv_ids = sorted(
        entities.invoices,
        key=lambda i: inv_calc[i.id]["del_date"],
    )

    allocations: list[PaymentAllocation] = []
    inv_payments: dict[uuid.UUID, list[tuple[Payment, Decimal]]] = {inv.id: [] for inv in entities.invoices}

    # Track remaining unallocated payment balances
    pay_remaining: dict[uuid.UUID, Decimal] = {p.id: p.amount for p in entities.payments}

    # First pass: Allocate explicitly linked payments
    for p in entities.payments:
        linked_inv_ids = pay_to_inv.get(p.id, [])
        if len(linked_inv_ids) == 1 and linked_inv_ids[0] in inv_calc:
            inv_id = linked_inv_ids[0]
            amt_to_alloc = pay_remaining[p.id]
            if amt_to_alloc > ZERO:
                inv_payments[inv_id].append((p, amt_to_alloc))
                allocations.append(
                    PaymentAllocation(
                        payment_id=str(p.id),
                        utr=p.utr,
                        claim_item_id=str(inv_id),
                        amount=amt_to_alloc,
                        strategy=allocation_strategy,
                        assumption="Payment matched by invoice key or remittance reference",
                    )
                )
                pay_remaining[p.id] = ZERO

    # Second pass: Allocate unallocated payments to remaining invoices by oldest date
    for inv in sorted_inv_ids:
        # Calculate current net balance on invoice
        base_p = inv_calc[inv.id]["claimable_p"]
        tot_adj = sum((a.amount for a in inv_adjustments[inv.id]), ZERO)
        tot_paid = sum((amt for _, amt in inv_payments[inv.id]), ZERO)
        rem_balance = max(ZERO, base_p - tot_adj - tot_paid)

        if rem_balance <= ZERO:
            continue

        for p in entities.payments:
            avail = pay_remaining[p.id]
            if avail <= ZERO:
                continue

            alloc_amt = min(rem_balance, avail)
            inv_payments[inv.id].append((p, alloc_amt))
            pay_remaining[p.id] -= alloc_amt
            rem_balance -= alloc_amt

            allocations.append(
                PaymentAllocation(
                    payment_id=str(p.id),
                    utr=p.utr,
                    claim_item_id=str(inv.id),
                    amount=alloc_amt,
                    strategy=allocation_strategy,
                    assumption="Open legal item: payment appropriation applied oldest-due-date first",
                )
            )
            if rem_balance <= ZERO:
                break

    # -------------------------------------------------------------------------
    # 5. Evaluate Claim Items with app.rules
    # -------------------------------------------------------------------------
    claim_items: list[ReconciledClaimItem] = []
    score_inputs: list[ScoreInput] = []

    case_paid_total = ZERO
    case_adj_total = ZERO
    case_out_delivered = ZERO
    case_out_full = ZERO
    case_interest_total: Decimal | None = ZERO
    case_interest_status = "computed"
    case_total_claimable: Decimal | None = ZERO
    case_earliest_due_date: str | None = None

    # Supplier eligibility facts for rule engine
    supplier = entities.case.supplier
    po_date_contract = entities.purchase_orders[0].po_date if entities.purchase_orders else date(2026, 1, 1)

    party_facts = PartyFacts(
        enterprise_type=supplier.enterprise_type or "micro",
        activity=supplier.activity or "manufacturer",
        udyam_reg_date=supplier.udyam_reg_date,
        contract_date=po_date_contract,
        udyam_certificate_present=bool(supplier.udyam_no and supplier.udyam_reg_date),
        written_contract_present=bool(entities.purchase_orders),
    )

    for inv in entities.invoices:
        c = inv_calc[inv.id]
        linked_adjs = inv_adjustments[inv.id]
        allocated_pays = inv_payments[inv.id]

        adj_total = sum((a.amount for a in linked_adjs), ZERO)
        paid_total = sum((amt for _, amt in allocated_pays), ZERO)

        case_adj_total += adj_total
        case_paid_total += paid_total

        # Build ledger rows
        ledger_rows: list[LedgerRow] = []
        running_bal = c["claimable_p"]

        # Row 1: Invoice debit
        ledger_rows.append(
            LedgerRow(
                date=str(inv.invoice_date),
                type="invoice",
                reference=inv.invoice_no,
                debit=c["claimable_p"],
                credit=ZERO,
                running_balance=running_bal,
                source_fact_ids=c["fact_ids"],
            )
        )

        # Row 2: Adjustments (TDS, etc.)
        for adj in linked_adjs:
            running_bal = quantize_money(running_bal - adj.amount)
            adj_facts = [str(adj.fact_id)] if adj.fact_id else []
            ledger_rows.append(
                LedgerRow(
                    date=str(inv.invoice_date),
                    type=adj.kind,
                    reference=adj.ref or f"{adj.kind.upper()} adjustment",
                    debit=ZERO,
                    credit=adj.amount,
                    running_balance=running_bal,
                    source_fact_ids=adj_facts,
                )
            )

        # Row 3: Payments
        for p, amt in allocated_pays:
            running_bal = quantize_money(running_bal - amt)
            p_facts = [str(p.fact_id)] if p.fact_id else []
            ledger_rows.append(
                LedgerRow(
                    date=str(p.pay_date),
                    type="payment",
                    reference=p.utr or p.bank_ref_text or "Bank payment",
                    debit=ZERO,
                    credit=amt,
                    running_balance=running_bal,
                    source_fact_ids=p_facts,
                )
            )

        out_delivered = quantize_money(c["del_val"] - (paid_total + (adj_total if tds_as_payment else ZERO)))
        out_full = quantize_money(inv.total - (paid_total + (adj_total if tds_as_payment else ZERO)))

        case_out_delivered += out_delivered
        case_out_full += out_full

        # Prepare rule engine claim item
        rule_payments: list[RulePayment] = []

        # If TDS counts as payment, pass it to rule engine as TDS payment
        if tds_as_payment and adj_total > ZERO:
            rule_payments.append(
                RulePayment(
                    pay_date=inv.invoice_date,
                    amount=adj_total,
                    kind=PaymentKind.tds,
                )
            )

        for p, amt in allocated_pays:
            if amt > ZERO:
                rule_payments.append(
                    RulePayment(
                        pay_date=p.pay_date,
                        amount=amt,
                        kind=PaymentKind.cash,
                    )
                )

        # Sort payments chronologically for rule engine
        rule_payments.sort(key=lambda rp: rp.pay_date)

        rule_item = RuleClaimItem(
            id=str(inv.id),
            label=inv.invoice_no,
            principal_amount=c["claimable_p"],
            delivery_date=c["del_date"],
            written_acceptance_date=c["written_acc_date"],
            credit_days_written=c["credit_days"],
            payments=rule_payments,
        )

        # Evaluate rules
        claim_result: ClaimResult = evaluate_claim(
            party_facts=party_facts,
            item=rule_item,
            pack=pack,
            rate_table=rate_table,
            as_of=as_of,
        )

        item_due_date = str(claim_result.due_date.due_date) if claim_result.due_date and claim_result.due_date.due_date else None
        item_interest_start = str(claim_result.due_date.interest_start_date) if claim_result.due_date and claim_result.due_date.interest_start_date else None
        item_days_overdue = claim_result.due_date.days_overdue if claim_result.due_date else None

        if item_due_date and (case_earliest_due_date is None or item_due_date < case_earliest_due_date):
            case_earliest_due_date = item_due_date

        item_interest: Decimal | None = None
        item_refused: str | None = None
        item_total_claimable: Decimal | None = None

        if claim_result.eligibility.status == EligibilityStatus.not_eligible:
            item_refused = claim_result.interest_refused_reason
            case_interest_total = None
            case_interest_status = f"refused: {'; '.join(claim_result.eligibility.reasons)}"
            case_total_claimable = None
        elif claim_result.interest:
            item_interest = quantize_money(claim_result.interest.total_interest)
            item_total_claimable = quantize_money(claim_result.interest.total_claimable)
            if case_interest_total is not None:
                case_interest_total += item_interest
            if case_total_claimable is not None:
                case_total_claimable += item_total_claimable
        else:
            item_refused = claim_result.interest_refused_reason

        claim_item_obj = ReconciledClaimItem(
            id=str(inv.id),
            invoice_id=str(inv.id),
            invoice_no=inv.invoice_no,
            invoice_date=str(inv.invoice_date),
            invoiced_total=inv.total,
            delivered_value=c["del_val"],
            accepted_value=c["acc_val"],
            claim_basis=claim_basis,
            claimable_principal=c["claimable_p"],
            full_invoice_principal=inv.total,
            paid_amount=paid_total,
            adjustment_amount=adj_total,
            outstanding_on_delivered_goods=out_delivered,
            outstanding_on_full_invoice=out_full,
            due_date=item_due_date,
            interest_start_date=item_interest_start,
            days_overdue=item_days_overdue,
            interest_amount=item_interest,
            interest_refused_reason=item_refused,
            total_claimable=item_total_claimable,
            rule_result=claim_result,
            ledger_rows=ledger_rows,
            source_fact_ids=c["fact_ids"],
        )
        claim_items.append(claim_item_obj)

        # Score input per invoice
        score_inputs.append(
            ScoreInput(
                item_id=str(inv.id),
                principal_amount=c["claimable_p"],
                po_found_and_linked=bool(c["po"]),
                written_credit_evidenced=bool(c["credit_days"]),
                delivery_proof_linked_qty_match=bool(c["deliveries"] and c["del_val"] == inv.total),
                acceptance_evidence_or_deemed_basis=bool(c["deliveries"]),
                invoice_valid_not_duplicate=True,  # Discrepancy detector updates if duplicate
                payments_reconciled=bool(paid_total > ZERO or out_delivered == ZERO),
                no_open_blocker_findings=True,
            )
        )

    # Readiness score
    score_res = compute_case_score(
        invoice_inputs=score_inputs,
        eligibility_not_failed=(party_facts.udyam_reg_date is None or party_facts.udyam_reg_date <= party_facts.contract_date),
        udyam_certificate_present=party_facts.udyam_certificate_present,
        all_low_confidence_facts_reviewed=True,
    )

    return ReconciliationSummary(
        invoiced_total=case_invoiced_total,
        delivered_value=case_delivered_val,
        accepted_value=case_accepted_val,
        paid_total=case_paid_total,
        adjustments_total=case_adj_total,
        outstanding_on_delivered_goods=case_out_delivered,
        outstanding_on_full_invoice=case_out_full,
        interest_total=case_interest_total,
        interest_status=case_interest_status,
        total_claimable=case_total_claimable,
        due_date=case_earliest_due_date,
        assumptions=assumptions,
        score_result=score_res,
        claim_items=claim_items,
        allocations=allocations,
    )
