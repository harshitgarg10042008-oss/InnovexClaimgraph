"""
Pydantic v2 input and output models for the rule engine.

Hard rules enforced here:
- No float for money or rates: use Decimal.
- All money fields use Annotated[Decimal, ...] with 2 dp semantics.
- RateTable lookup raises ValueError if the date precedes all rows.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Shared primitives
# ---------------------------------------------------------------------------


class PaymentKind(str, Enum):
    cash = "cash"
    tds = "tds"
    other = "other"


class EligibilityStatus(str, Enum):
    eligible = "eligible"
    not_eligible = "not_eligible"
    unknown = "unknown"


class AcceptanceBasis(str, Enum):
    actual = "actual"
    deemed = "deemed"
    objection_removed = "objection_removed"
    blocked_by_objection = "blocked_by_objection"


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


class PartyFacts(BaseModel):
    """Supplier facts needed for eligibility gating."""

    enterprise_type: str  # micro | small | medium | large
    activity: str  # manufacturer | service | trader
    udyam_reg_date: date | None = None
    contract_date: date  # the PO date
    udyam_certificate_present: bool
    written_contract_present: bool


class Objection(BaseModel):
    """Written buyer objection on a delivery."""

    raised_on: date
    removed_on: date | None = None  # None = still unresolved


class Payment(BaseModel):
    """One payment or TDS entry against a claim item."""

    pay_date: date
    amount: Decimal = Field(gt=Decimal("0"))
    kind: PaymentKind = PaymentKind.cash

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce_amount(cls, v: object) -> Decimal:
        return Decimal(str(v))


class ClaimItem(BaseModel):
    """One invoice / delivery pair submitted to the rule engine."""

    id: str
    label: str
    principal_amount: Decimal  # total claimable incl. GST
    delivery_date: date
    # Optional: explicit written acceptance by buyer
    written_acceptance_date: date | None = None
    # Optional: written buyer objection (triggers the objection-removed rule)
    objection: Objection | None = None
    # Credit days from a written agreement (PO / contract)
    credit_days_written: int | None = None
    payments: list[Payment] = Field(default_factory=list)

    @field_validator("principal_amount", mode="before")
    @classmethod
    def _coerce_principal(cls, v: object) -> Decimal:
        return Decimal(str(v))

    @model_validator(mode="after")
    def _no_duplicate_payment_dates(self) -> ClaimItem:
        # Payments on the same date are allowed (different UTRs), so no
        # uniqueness constraint here — just a guard against nonsense amounts.
        return self


class RateRow(BaseModel):
    """One row of the bank-rate table."""

    effective_from: date
    bank_rate_pct: Decimal

    @field_validator("bank_rate_pct", mode="before")
    @classmethod
    def _coerce_rate(cls, v: object) -> Decimal:
        return Decimal(str(v))


class RateTable(BaseModel):
    """Ordered list of rate rows.  Lookup returns the rate in force on a date."""

    rows: list[RateRow]

    @model_validator(mode="after")
    def _sorted_asc(self) -> RateTable:
        self.rows = sorted(self.rows, key=lambda r: r.effective_from)
        return self

    def rate_on(self, d: date) -> Decimal:
        """Return the bank_rate_pct in force on date *d*.

        Raises:
            ValueError: If *d* is before the first row's effective_from.
        """
        if not self.rows:
            raise ValueError("RateTable is empty")
        if d < self.rows[0].effective_from:
            raise ValueError(
                f"Date {d} is before the first rate-table row "
                f"({self.rows[0].effective_from}). "
                "Add a rate row covering this date."
            )
        result = self.rows[0].bank_rate_pct
        for row in self.rows:
            if row.effective_from <= d:
                result = row.bank_rate_pct
            else:
                break
        return result


# ---------------------------------------------------------------------------
# Score input
# ---------------------------------------------------------------------------


class ScoreInput(BaseModel):
    """Simple boolean/count checklist for one invoice, feeding the score."""

    item_id: str
    principal_amount: Decimal
    po_found_and_linked: bool
    written_credit_evidenced: bool
    delivery_proof_linked_qty_match: bool
    acceptance_evidence_or_deemed_basis: bool
    invoice_valid_not_duplicate: bool
    payments_reconciled: bool
    no_open_blocker_findings: bool

    @field_validator("principal_amount", mode="before")
    @classmethod
    def _coerce(cls, v: object) -> Decimal:
        return Decimal(str(v))


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------


class EligibilityResult(BaseModel):
    status: EligibilityStatus
    reasons: list[str]
    working: list[str]


class DueDateResult(BaseModel):
    acceptance_date: date | None
    acceptance_basis: AcceptanceBasis
    credit_days: int
    credit_days_capped: bool  # True when written value > max_credit_days
    due_date: date | None
    interest_start_date: date | None
    days_overdue: int | None
    working: list[str]


class PeriodRow(BaseModel):
    """Per-period accrual row returned by the interest engine."""

    period_index: int  # 0-based
    start: date
    end: date
    days_in_period: int
    opening_base: Decimal  # principal + capitalised interest at period start
    # List of (annual_rate_pct, days) slices within this period
    rate_slices: list[tuple[Decimal, int]]
    interest: Decimal
    capitalised: bool  # True for full periods, False for the final partial


class InterestResult(BaseModel):
    interest_start_date: date
    as_of: date
    total_interest: Decimal
    outstanding_principal: Decimal
    capitalised_interest: Decimal
    total_claimable: Decimal
    periods: list[PeriodRow]
    working: list[str]


class LimitationResult(BaseModel):
    due_date: date
    as_of: date
    limitation_years: int
    days_since_due: int
    is_potentially_time_barred: bool
    working: list[str]


class InvoiceScore(BaseModel):
    item_id: str
    points: int  # 0–100
    breakdown: dict[str, int]  # check_name -> points awarded


class ScoreResult(BaseModel):
    invoice_scores: list[InvoiceScore]
    case_score: Decimal  # principal-weighted average 0–100
    blockers: list[str]  # gate failures — not points
    working: list[str]


class ClaimResult(BaseModel):
    """Unified result from evaluate_claim."""

    eligibility: EligibilityResult
    due_date: DueDateResult | None = None
    interest: InterestResult | None = None
    limitation: LimitationResult | None = None
    interest_refused_reason: str | None = None
    working: list[str]
