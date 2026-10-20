"""Claims pipeline orchestration service for ClaimGraph M5."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.claims.builder import (
    build_entities_from_facts,
    check_linking_blockers,
)
from app.claims.findings import run_findings_detectors
from app.claims.linker import run_linker
from app.claims.reconcile import run_reconciliation
from app.models.audit import AuditLog
from app.models.case import Case
from app.models.fact import Fact
from app.models.reconciliation import Finding, Link
from app.models.rule import RulePack as DbRulePack
from app.models.rule import RuleRun
from app.models.transaction import Delivery, Invoice, Payment, PurchaseOrder
from app.rules.pack_loader import get_active_pack


def is_case_stale(
    case_id: uuid.UUID,
    db: Session,
    last_run_at: datetime | None = None,
) -> bool:
    """Check if any fact or audit action was modified after the last pipeline run."""
    if last_run_at is None:
        last_run = (
            db.query(RuleRun)
            .filter(RuleRun.case_id == case_id)
            .order_by(RuleRun.run_at.desc())
            .first()
        )
        if not last_run:
            return True
        last_run_at = last_run.run_at

    # Ensure timezone-aware or naive comparison compatibility
    if last_run_at.tzinfo is not None:
        last_run_at = last_run_at.replace(tzinfo=None)

    # Check for facts confirmed or created after last run
    newer_facts = (
        db.query(Fact)
        .filter(
            Fact.case_id == case_id,
            (Fact.confirmed_at > last_run_at) | (Fact.created_at > last_run_at),
        )
        .count()
    )
    if newer_facts > 0:
        return True

    # Check audit log entries after last run
    newer_audits = (
        db.query(AuditLog)
        .filter(AuditLog.case_id == case_id, AuditLog.at > last_run_at)
        .count()
    )
    if newer_audits > 0:
        return True

    return False


def get_or_create_db_rule_pack(db: Session) -> DbRulePack:
    """Ensure active RulePack exists in the rule_packs table."""
    pack = get_active_pack()
    db_pack = db.query(DbRulePack).filter(DbRulePack.name == pack.pack_name, DbRulePack.version == pack.version).first()
    if not db_pack:
        db_pack = DbRulePack(
            name=pack.pack_name,
            version=pack.version,
            effective_from=pack.effective_from,
            config_json=pack.model_dump(mode="json"),
        )
        db.add(db_pack)
        db.commit()
        db.refresh(db_pack)
    return db_pack


def run_claims_pipeline(
    case_id: uuid.UUID,
    db: Session,
    as_of: date = date(2026, 10, 14),
    actor: str = "system",
) -> dict[str, Any]:
    """Execute M5 pipeline: Build entities -> Link -> Reconcile -> Findings -> Save run."""
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise ValueError(f"Case {case_id} not found")

    # 1. Check blockers first
    blockers = check_linking_blockers(case_id, db)
    if blockers:
        case.status = "linking_blocked"
        db.commit()
        return {
            "case_id": str(case_id),
            "status": "blocked",
            "linking_status": "blocked",
            "stale": False,
            "blockers": [
                {"field": b.field, "document": b.document, "reason": b.reason}
                for b in blockers
            ],
            "summary": None,
        }

    # 2. Build entities from confirmed facts
    entities, build_blockers = build_entities_from_facts(case_id, db)
    if build_blockers or entities is None:
        case.status = "linking_blocked"
        db.commit()
        return {
            "case_id": str(case_id),
            "status": "blocked",
            "linking_status": "blocked",
            "stale": False,
            "blockers": [
                {"field": b.field, "document": b.document, "reason": b.reason}
                for b in build_blockers
            ],
            "summary": None,
        }

    # 3. Linker
    links = run_linker(case_id, entities, db)

    # 4. Reconciliation
    reconciliation = run_reconciliation(
        entities=entities,
        links=links,
        db=db,
        as_of=as_of,
    )

    # 5. Deterministic Findings Detectors
    db_findings = run_findings_detectors(
        case_id=case_id,
        entities=entities,
        reconciliation=reconciliation,
        links=links,
        db=db,
    )

    # 6. Store RuleRun
    db_pack = get_or_create_db_rule_pack(db)
    now_utc = datetime.utcnow()

    reconciliation_dict = reconciliation.to_dict()
    rule_run = RuleRun(
        case_id=case_id,
        rule_pack_id=db_pack.id,
        result_json={
            "summary": reconciliation_dict,
            "findings_count": len(db_findings),
            "as_of": str(as_of),
            "links_count": len(links),
        },
        run_at=now_utc,
    )
    db.add(rule_run)

    # Update case status
    has_blocker_findings = any(f.severity in ("blocker", "conflict") for f in db_findings)
    case.status = "attention" if has_blocker_findings else "ready"
    db.commit()

    return {
        "case_id": str(case_id),
        "status": case.status,
        "linking_status": "ready" if not blockers else "blocked",
        "stale": False,
        "blockers": [],
        "run_at": now_utc.isoformat(),
        "summary": reconciliation_dict,
        "findings": [
            {
                "id": str(f.id),
                "code": f.code,
                "severity": f.severity,
                "title": f.title,
                "message": f.message,
                "explanation_template": f.explanation_template,
                "computed_numbers": f.computed_numbers,
                "needs_human_or_legal_review": f.needs_human_or_legal_review,
                "blocks_ready": f.blocks_ready,
                "refs": f.refs_json or [],
                "refs_json": f.refs_json,
            }
            for f in db_findings
        ],
    }


def get_case_graph(case_id: uuid.UUID, db: Session) -> dict[str, Any]:
    """Generate nodes and edges for @xyflow/react graph visualization."""
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise ValueError(f"Case {case_id} not found")

    pos = db.query(PurchaseOrder).filter(PurchaseOrder.case_id == case_id).all()
    deliveries = db.query(Delivery).filter(Delivery.case_id == case_id).all()
    invoices = db.query(Invoice).filter(Invoice.case_id == case_id).all()
    payments = db.query(Payment).filter(Payment.case_id == case_id).all()
    links = db.query(Link).filter(Link.case_id == case_id).all()

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    # Map facts for source refs
    all_facts = db.query(Fact).filter(Fact.case_id == case_id).all()
    fact_map = {str(f.id): f for f in all_facts}

    def make_refs(fact_ids: list[str]) -> list[dict[str, Any]]:
        refs = []
        for fid in fact_ids:
            if fid in fact_map:
                f = fact_map[fid]
                refs.append({
                    "fact_id": fid,
                    "doc_id": str(f.document_id),
                    "page": f.page_no,
                    "bbox": f.bbox if isinstance(f.bbox, list) else None,
                })
        return refs

    # Fixed left-to-right columns
    # PO: x=50, Delivery: x=300, Invoice: x=550, Payment: x=800
    y_gap = 120

    for idx, po in enumerate(pos):
        nodes.append({
            "id": f"po_{po.id}",
            "type": "po",
            "position": {"x": 50, "y": 80 + idx * y_gap},
            "data": {
                "label": f"PO {po.po_no}",
                "number": po.po_no,
                "date": str(po.po_date),
                "credit_days": po.credit_days_written,
                "status": "verified",
                "source_refs": make_refs([str(po.fact_id)] if po.fact_id else []),
            },
        })

    for idx, d in enumerate(deliveries):
        disp_qty = sum((dl.dispatched_qty or dl.qty for dl in d.lines), Decimal("0"))
        acc_qty = sum((dl.accepted_qty if dl.accepted_qty is not None else dl.qty for dl in d.lines), Decimal("0"))
        rej_qty = sum((dl.rejected_qty or Decimal("0") for dl in d.lines), Decimal("0"))
        node_status = "conflict" if rej_qty > Decimal("0") else "verified"

        nodes.append({
            "id": f"delivery_{d.id}",
            "type": "delivery",
            "position": {"x": 300, "y": 80 + idx * y_gap},
            "data": {
                "label": f"Challan {d.challan_no}",
                "number": d.challan_no,
                "date": str(d.delivery_date),
                "quantity": f"{acc_qty:.0f} / {disp_qty:.0f}" if disp_qty > Decimal("0") else None,
                "status": node_status,
                "source_refs": make_refs([str(d.fact_id)] if d.fact_id else []),
            },
        })

    for idx, inv in enumerate(invoices):
        nodes.append({
            "id": f"invoice_{inv.id}",
            "type": "invoice",
            "position": {"x": 550, "y": 80 + idx * y_gap},
            "data": {
                "label": f"Invoice {inv.invoice_no}",
                "number": inv.invoice_no,
                "date": str(inv.invoice_date),
                "amount": f"{inv.total:,.2f}",
                "status": "verified",
                "source_refs": make_refs([str(inv.fact_id)] if inv.fact_id else []),
            },
        })

    for idx, p in enumerate(payments):
        nodes.append({
            "id": f"payment_{p.id}",
            "type": "payment",
            "position": {"x": 800, "y": 80 + idx * y_gap},
            "data": {
                "label": f"Payment {p.utr or 'UTR'}",
                "number": p.utr or "Bank Credit",
                "date": str(p.pay_date),
                "amount": f"{p.amount:,.2f}",
                "status": "verified",
                "source_refs": make_refs([str(p.fact_id)] if p.fact_id else []),
            },
        })

    # Edges
    for lk in links:
        src = f"{lk.from_type.lower()}_{lk.from_id}"
        tgt = f"{lk.to_type.lower()}_{lk.to_id}"
        edges.append({
            "id": f"e_{lk.id}",
            "source": src,
            "target": tgt,
            "animated": lk.status == "suggested",
            "data": {
                "method": lk.method,
                "status": lk.status,
                "confidence": float(lk.confidence) if lk.confidence else 1.0,
                "reason": lk.reason,
                "confirmed": lk.confirmed,
                "source_fact_ids": lk.evidence_fact_ids or [],
            },
        })

    return {
        "case_id": str(case_id),
        "nodes": nodes,
        "edges": edges,
        "stale": is_case_stale(case_id, db),
    }


def get_case_ledger(case_id: uuid.UUID, db: Session) -> dict[str, Any]:
    """Retrieve the latest reconciled ledger rows and claim totals."""
    last_run = (
        db.query(RuleRun)
        .filter(RuleRun.case_id == case_id)
        .order_by(RuleRun.run_at.desc())
        .first()
    )
    stale = is_case_stale(case_id, db, last_run.run_at if last_run else None)

    if not last_run or not last_run.result_json:
        return {
            "case_id": str(case_id),
            "stale": stale,
            "summary": None,
        }

    res_json = last_run.result_json
    summary = res_json.get("summary") if isinstance(res_json, dict) else None
    return {
        "case_id": str(case_id),
        "stale": stale,
        "run_at": last_run.run_at.isoformat(),
        "summary": summary,
        "ledger_status": summary.get("ledger_status", "final") if isinstance(summary, dict) else "final",
        "provisional_reason": summary.get("provisional_reason") if isinstance(summary, dict) else None,
    }


def get_case_findings(case_id: uuid.UUID, db: Session) -> dict[str, Any]:
    """Retrieve current findings for case with stale flag."""
    findings = db.query(Finding).filter(Finding.case_id == case_id).all()
    stale = is_case_stale(case_id, db)

    return {
        "case_id": str(case_id),
        "stale": stale,
        "findings": [
            {
                "id": str(f.id),
                "code": f.code,
                "severity": f.severity,
                "title": f.title,
                "message": f.message,
                "explanation_template": f.explanation_template,
                "computed_numbers": f.computed_numbers,
                "needs_human_or_legal_review": f.needs_human_or_legal_review,
                "blocks_ready": f.blocks_ready,
                "refs": f.refs_json or [],
                "refs_json": f.refs_json,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in findings
        ],
    }


def update_link_status(
    case_id: uuid.UUID,
    link_id: uuid.UUID,
    new_status: str,  # confirmed | rejected
    actor: str,
    db: Session,
) -> Link:
    """Confirm or reject a link and record audit log."""
    link = db.query(Link).filter(Link.id == link_id, Link.case_id == case_id).first()
    if not link:
        raise ValueError(f"Link {link_id} for case {case_id} not found")

    before_state = {
        "status": link.status,
        "confirmed": link.confirmed,
    }

    if new_status == "confirmed":
        link.status = "confirmed"
        link.confirmed = True
    elif new_status == "rejected":
        link.status = "rejected"
        link.confirmed = False
    else:
        raise ValueError(f"Invalid link status update: {new_status}")

    after_state = {
        "status": link.status,
        "confirmed": link.confirmed,
    }

    audit = AuditLog(
        case_id=case_id,
        actor=actor,
        action=f"{new_status}_link",
        target=str(link_id),
        before_json=before_state,
        after_json=after_state,
    )
    db.add(audit)
    db.commit()
    db.refresh(link)
    return link
