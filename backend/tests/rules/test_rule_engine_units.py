"""
Unit and edge-case tests for the rule engine (M2).

Covers all requirements from the master plan and user instructions:
- due date with objection raised and removed
- objection unresolved -> blocked_by_objection
- written credit 60 days -> capped to 45 with a flag
- no written agreement -> 15 days default
- payment before the interest start date
- payment larger than principal
- limitation flag at 3 years plus 1 day
- month-end anniversary clamping (start 2026-01-31 gives period boundaries 2026-02-28 and 2026-03-31)
- engine refuses interest for an ineligible supplier
- determinism: same input twice gives identical output
- rule pack validation errors (unsupported options rejected)
- scoring engine: 100-point checklist, principal weighting, case gate blockers
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.rules.due_date import compute_due_date
from app.rules.engine import evaluate_claim
from app.rules.interest import compute_interest
from app.rules.limitation import check_limitation
from app.rules.pack_loader import RulePack, load_pack
from app.rules.score import compute_case_score, compute_invoice_score
from app.rules.types import (
    AcceptanceBasis,
    ClaimItem,
    EligibilityStatus,
    Objection,
    PartyFacts,
    Payment,
    PaymentKind,
    RateRow,
    RateTable,
    ScoreInput,
)

PACK = load_pack("msmed_v1")
RATE_TABLE = RateTable(
    rows=[
        RateRow(effective_from=date(2000, 1, 1), bank_rate_pct=Decimal("5.50")),
        RateRow(effective_from=date(2026, 10, 7), bank_rate_pct=Decimal("5.75")),
    ]
)


# ===========================================================================
# 1. Due date & Acceptance tests
# ===========================================================================


class TestDueDateRules:
    def test_objection_raised_and_removed(self):
        """When an objection is raised within 15 days and removed, acceptance is the removal date."""
        item = ClaimItem(
            id="item1",
            label="Item 1",
            principal_amount=Decimal("10000.00"),
            delivery_date=date(2026, 1, 10),
            objection=Objection(
                raised_on=date(2026, 1, 15),
                removed_on=date(2026, 1, 25),
            ),
            credit_days_written=30,
        )
        as_of = date(2026, 4, 1)
        res = compute_due_date(item, PACK, as_of)

        assert res.acceptance_date == date(2026, 1, 25)
        assert res.acceptance_basis == AcceptanceBasis.objection_removed
        # due_date = Jan 25 + 30 days = Feb 24 (Jan has 31: 31-25=6, 30-6=24)
        assert res.due_date == date(2026, 2, 24)
        assert res.interest_start_date == date(2026, 2, 25)
        assert res.credit_days == 30
        assert not res.credit_days_capped

    def test_objection_unresolved_blocked(self):
        """When an objection is unresolved, goods are blocked_by_objection and not claimable."""
        item = ClaimItem(
            id="item2",
            label="Item 2",
            principal_amount=Decimal("10000.00"),
            delivery_date=date(2026, 1, 10),
            objection=Objection(
                raised_on=date(2026, 1, 15),
                removed_on=None,
            ),
            credit_days_written=30,
        )
        as_of = date(2026, 4, 1)
        res = compute_due_date(item, PACK, as_of)

        assert res.acceptance_date is None
        assert res.acceptance_basis == AcceptanceBasis.blocked_by_objection
        assert res.due_date is None
        assert res.interest_start_date is None
        assert res.days_overdue is None

    def test_written_credit_60_days_capped_to_45(self):
        """Written credit terms > 45 days are capped to 45 and flagged."""
        item = ClaimItem(
            id="item3",
            label="Item 3",
            principal_amount=Decimal("10000.00"),
            delivery_date=date(2026, 1, 10),
            written_acceptance_date=date(2026, 1, 10),
            credit_days_written=60,
        )
        as_of = date(2026, 4, 1)
        res = compute_due_date(item, PACK, as_of)

        assert res.credit_days == 45
        assert res.credit_days_capped is True
        # Jan 10 + 45 days = Feb 24
        assert res.due_date == date(2026, 2, 24)

    def test_no_written_agreement_defaults_to_15_days(self):
        """When no credit terms are in writing, defaults to 15 days without capping flag."""
        item = ClaimItem(
            id="item4",
            label="Item 4",
            principal_amount=Decimal("10000.00"),
            delivery_date=date(2026, 1, 10),
            written_acceptance_date=date(2026, 1, 10),
            credit_days_written=None,
        )
        as_of = date(2026, 4, 1)
        res = compute_due_date(item, PACK, as_of)

        assert res.credit_days == 15
        assert res.credit_days_capped is False
        # Jan 10 + 15 days = Jan 25
        assert res.due_date == date(2026, 1, 25)

    def test_deemed_acceptance_delivery_day_not_shifted(self):
        """When no objection within 15 days, acceptance is actual delivery date."""
        item = ClaimItem(
            id="item5",
            label="Item 5",
            principal_amount=Decimal("10000.00"),
            delivery_date=date(2026, 1, 10),
            credit_days_written=30,
        )
        as_of = date(2026, 4, 1)
        res = compute_due_date(item, PACK, as_of)

        assert res.acceptance_date == date(2026, 1, 10)
        assert res.acceptance_basis == AcceptanceBasis.deemed
        assert res.due_date == date(2026, 2, 9)


# ===========================================================================
# 2. Interest calculation edge cases
# ===========================================================================


class TestInterestEdgeCases:
    def test_payment_before_interest_start(self):
        """Payments dated before interest starts reduce principal before accrual begins."""
        item = ClaimItem(
            id="test_pmt_pre",
            label="Pre-interest payment",
            principal_amount=Decimal("100000.00"),
            delivery_date=date(2026, 1, 1),
            payments=[
                Payment(pay_date=date(2026, 1, 15), amount=Decimal("30000.00"), kind=PaymentKind.cash),
            ],
        )
        # Interest starts Feb 1, 2026
        interest_start = date(2026, 2, 1)
        as_of = date(2026, 2, 28)
        rate_table = RateTable(
            rows=[RateRow(effective_from=date(2000, 1, 1), bank_rate_pct=Decimal("5.75"))]
        )
        res = compute_interest(item, interest_start, PACK, rate_table, as_of)

        assert res.outstanding_principal == Decimal("70000.00")
        # 1 full month on 70,000 at 3 * 5.75% = 17.25% -> 70000 * 0.1725 / 12 = 1006.25
        assert res.total_interest == Decimal("1006.25")
        assert res.total_claimable == Decimal("71006.25")

    def test_payment_larger_than_principal(self):
        """Payment larger than principal reduces principal to 0 and remainder reduces capitalised interest."""
        # Period 0: Jan 1 to Jan 31 accrues interest on 10,000.
        # At end of Period 0, interest is capitalised.
        # Period 1: Feb 15 payment of 10,100 arrives.
        item = ClaimItem(
            id="test_pmt_large",
            label="Large payment",
            principal_amount=Decimal("10000.00"),
            delivery_date=date(2025, 12, 1),
            payments=[
                Payment(pay_date=date(2026, 2, 15), amount=Decimal("10100.00"), kind=PaymentKind.cash),
            ],
        )
        interest_start = date(2026, 1, 1)
        as_of = date(2026, 2, 28)
        rate_table = RateTable(
            rows=[RateRow(effective_from=date(2000, 1, 1), bank_rate_pct=Decimal("5.75"))]
        )
        res = compute_interest(item, interest_start, PACK, rate_table, as_of)

        assert res.outstanding_principal == Decimal("0.00")
        assert res.total_claimable > Decimal("0.00")

    def test_month_end_anniversary_clamping(self):
        """Start on 2026-01-31 gives period boundaries 2026-02-28, 2026-03-31."""
        item = ClaimItem(
            id="test_clamping",
            label="Month end clamping",
            principal_amount=Decimal("50000.00"),
            delivery_date=date(2026, 1, 1),
        )
        interest_start = date(2026, 1, 31)
        as_of = date(2026, 4, 30)
        rate_table = RateTable(
            rows=[RateRow(effective_from=date(2000, 1, 1), bank_rate_pct=Decimal("5.75"))]
        )
        res = compute_interest(item, interest_start, PACK, rate_table, as_of)

        assert res.periods[0].start == date(2026, 1, 31)
        assert res.periods[0].end == date(2026, 2, 27)
        assert res.periods[1].start == date(2026, 2, 28)
        assert res.periods[1].end == date(2026, 3, 30)
        assert res.periods[2].start == date(2026, 3, 31)


# ===========================================================================
# 3. Limitation tests
# ===========================================================================


class TestLimitation:
    def test_within_limitation(self):
        due_date = date(2024, 1, 1)
        as_of = date(2026, 10, 14)  # ~2.8 years
        res = check_limitation(due_date, as_of, PACK)
        assert res.is_potentially_time_barred is False
        assert res.days_since_due == (as_of - due_date).days

    def test_time_barred_at_three_years_plus_one_day(self):
        due_date = date(2023, 1, 1)
        # 3 years is 2026-01-01; 2026-01-02 is 3 years + 1 day
        as_of = date(2026, 1, 2)
        res = check_limitation(due_date, as_of, PACK)
        assert res.is_potentially_time_barred is True


# ===========================================================================
# 4. Engine & Ineligible supplier checks
# ===========================================================================


class TestEngineIntegration:
    def test_refuses_interest_for_ineligible_supplier(self):
        """Engine refuses to compute interest when eligibility check fails."""
        party = PartyFacts(
            enterprise_type="medium",  # ineligible
            activity="manufacturer",
            udyam_reg_date=date(2020, 1, 1),
            contract_date=date(2026, 1, 1),
            udyam_certificate_present=True,
            written_contract_present=True,
        )
        item = ClaimItem(
            id="item_ineligible",
            label="Ineligible item",
            principal_amount=Decimal("100000.00"),
            delivery_date=date(2026, 1, 1),
            credit_days_written=30,
        )
        res = evaluate_claim(party, item, PACK, RATE_TABLE, date(2026, 10, 14))

        assert res.eligibility.status == EligibilityStatus.not_eligible
        assert res.interest is None
        assert res.interest_refused_reason is not None
        assert "not_eligible" in res.interest_refused_reason.lower()

    def test_determinism_identical_output(self):
        """Same input twice gives exact same output."""
        party = PartyFacts(
            enterprise_type="micro",
            activity="manufacturer",
            udyam_reg_date=date(2024, 1, 1),
            contract_date=date(2026, 1, 1),
            udyam_certificate_present=True,
            written_contract_present=True,
        )
        item = ClaimItem(
            id="item_det",
            label="Deterministic item",
            principal_amount=Decimal("50000.00"),
            delivery_date=date(2026, 3, 1),
            written_acceptance_date=date(2026, 3, 1),
            credit_days_written=30,
            payments=[
                Payment(pay_date=date(2026, 5, 1), amount=Decimal("10000.00"), kind=PaymentKind.cash)
            ],
        )
        as_of = date(2026, 10, 14)
        run1 = evaluate_claim(party, item, PACK, RATE_TABLE, as_of)
        run2 = evaluate_claim(party, item, PACK, RATE_TABLE, as_of)

        assert run1.model_dump() == run2.model_dump()


# ===========================================================================
# 5. Rule pack validation tests
# ===========================================================================


class TestRulePackValidation:
    def test_unsupported_compounding_rejected(self):
        raw = PACK.model_dump()
        raw["compounding"] = "quarterly_rests"
        with pytest.raises(ValidationError):
            RulePack.model_validate(raw)

    def test_unsupported_payment_application_rejected(self):
        raw = PACK.model_dump()
        raw["payment_application"] = "interest_first"
        with pytest.raises(ValidationError) as exc:
            RulePack.model_validate(raw)
        assert "principal_first" in str(exc.value)

    def test_unsupported_accrual_rejected(self):
        raw = PACK.model_dump()
        raw["within_period_accrual"] = "30_360"
        with pytest.raises(ValidationError):
            RulePack.model_validate(raw)

    def test_negative_values_rejected(self):
        raw = PACK.model_dump()
        raw["max_credit_days"] = -1
        with pytest.raises(ValidationError):
            RulePack.model_validate(raw)


# ===========================================================================
# 6. Scoring tests (Section 7.4)
# ===========================================================================


class TestScoreEngine:
    def test_perfect_invoice_score_100_points(self):
        inp = ScoreInput(
            item_id="inv1",
            principal_amount=Decimal("100000.00"),
            po_found_and_linked=True,
            written_credit_evidenced=True,
            delivery_proof_linked_qty_match=True,
            acceptance_evidence_or_deemed_basis=True,
            invoice_valid_not_duplicate=True,
            payments_reconciled=True,
            no_open_blocker_findings=True,
        )
        score = compute_invoice_score(inp)
        assert score.points == 100
        assert sum(score.breakdown.values()) == 100

    def test_partial_invoice_score(self):
        inp = ScoreInput(
            item_id="inv2",
            principal_amount=Decimal("50000.00"),
            po_found_and_linked=True,  # 15
            written_credit_evidenced=False,  # 0
            delivery_proof_linked_qty_match=True,  # 20
            acceptance_evidence_or_deemed_basis=True,  # 15
            invoice_valid_not_duplicate=True,  # 10
            payments_reconciled=False,  # 0
            no_open_blocker_findings=False,  # 0
        )
        score = compute_invoice_score(inp)
        assert score.points == 60

    def test_case_score_principal_weighting_and_blockers(self):
        inv1 = ScoreInput(
            item_id="inv1",
            principal_amount=Decimal("100000.00"),
            po_found_and_linked=True,
            written_credit_evidenced=True,
            delivery_proof_linked_qty_match=True,
            acceptance_evidence_or_deemed_basis=True,
            invoice_valid_not_duplicate=True,
            payments_reconciled=True,
            no_open_blocker_findings=True,
        )
        inv2 = ScoreInput(
            item_id="inv2",
            principal_amount=Decimal("100000.00"),
            po_found_and_linked=False,
            written_credit_evidenced=False,
            delivery_proof_linked_qty_match=False,
            acceptance_evidence_or_deemed_basis=False,
            invoice_valid_not_duplicate=False,
            payments_reconciled=False,
            no_open_blocker_findings=False,
        )
        # Equal weights 100 and 0 -> average 50.00
        res = compute_case_score(
            [inv1, inv2],
            eligibility_status=EligibilityStatus.eligible,
            udyam_certificate_present=True,
            all_low_confidence_facts_reviewed=True,
        )
        assert res.case_score == Decimal("50.00")
        assert len(res.blockers) == 0

        # With gate failures
        res_blocked = compute_case_score(
            [inv1, inv2],
            eligibility_status=EligibilityStatus.not_eligible,
            udyam_certificate_present=False,
            all_low_confidence_facts_reviewed=False,
        )
        assert len(res_blocked.blockers) == 3
