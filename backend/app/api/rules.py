"""
Rules API router.

GET  /rules/pack           — return the active rule pack configuration.
POST /rules/interest-preview — compute interest preview without DB access;
                               rate table rows are passed in the request body.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.rule import RateTable as DbRateTable
from app.rules.interest import compute_interest
from app.rules.pack_loader import get_active_pack
from app.rules.types import (
    ClaimItem,
    InterestResult,
    Payment,
    PaymentKind,
    RateRow,
    RateTable,
)

router = APIRouter(prefix="/rules", tags=["rules"])


# ---------------------------------------------------------------------------
# GET /rules/pack
# ---------------------------------------------------------------------------


@router.get("/pack")
def get_pack() -> dict:
    """Return the active rule pack configuration."""
    pack = get_active_pack()
    return pack.model_dump(mode="json")


# ---------------------------------------------------------------------------
# POST /rules/interest-preview
# ---------------------------------------------------------------------------


class PaymentIn(BaseModel):
    pay_date: date
    amount: Decimal
    kind: PaymentKind = PaymentKind.cash

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce(cls, v: object) -> Decimal:
        return Decimal(str(v))


class InterestPreviewRequest(BaseModel):
    """Input for the interest preview endpoint."""

    principal: Decimal = Field(gt=Decimal("0"), description="Claimable principal incl. GST")
    due_date: date
    payments: list[PaymentIn] = Field(default_factory=list)
    as_of: date
    # Rate table rows; if omitted the seed values are used
    rate_rows: list[RateRow] | None = None

    @field_validator("principal", mode="before")
    @classmethod
    def _coerce_principal(cls, v: object) -> Decimal:
        return Decimal(str(v))


# Seed rate table (used when rate_rows is not provided)
_SEED_RATE_ROWS = [
    RateRow(effective_from=date(2000, 1, 1), bank_rate_pct=Decimal("5.50")),
    RateRow(effective_from=date(2026, 10, 7), bank_rate_pct=Decimal("5.75")),
]


@router.post("/interest-preview", response_model=InterestResult)
def interest_preview(
    body: InterestPreviewRequest,
    db: Session = Depends(get_db),
) -> InterestResult:
    """Compute interest for a single principal/payments pair.

    The rate table can be supplied in the request; if omitted, rows are
    loaded from the database rate table (with seed fallback).

    Args:
        body: Principal, due date, payments, as_of, optional rate rows.
        db: Database session.

    Returns:
        :class:`InterestResult` with per-period rows and totals.
    """
    pack = get_active_pack()

    # Build rate table: supplied in body > DB > seed fallback
    if body.rate_rows:
        rows = body.rate_rows
    else:
        db_rows = list(
            db.scalars(select(DbRateTable).order_by(DbRateTable.effective_from.asc())).all()
        )
        if db_rows:
            rows = [
                RateRow(effective_from=r.effective_from, bank_rate_pct=r.bank_rate_pct)
                for r in db_rows
            ]
        else:
            rows = _SEED_RATE_ROWS

    rate_table = RateTable(rows=rows)

    # Build a synthetic ClaimItem
    payments = [
        Payment(pay_date=p.pay_date, amount=p.amount, kind=p.kind)
        for p in body.payments
    ]
    item = ClaimItem(
        id="preview",
        label="Interest preview",
        principal_amount=body.principal,
        delivery_date=body.due_date,  # not used by interest engine
        payments=payments,
    )

    # interest starts day after due_date
    interest_start = body.due_date + timedelta(days=1)

    return compute_interest(item, interest_start, pack, rate_table, body.as_of)
