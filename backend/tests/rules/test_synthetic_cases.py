"""
Synthetic case tests for the rule engine (Cases A, B, C, D).

as_of = 2026-10-14 for all cases.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from app.rules.engine import evaluate_claim
from app.rules.pack_loader import load_pack
from app.rules.types import (
    ClaimItem,
    EligibilityStatus,
    PartyFacts,
    Payment,
    PaymentKind,
    RateRow,
    RateTable,
)

PACK = load_pack("msmed_v1")
AS_OF = date(2026, 10, 14)

# Seed rate table matching the master plan
SEED_RATE_TABLE = RateTable(
    rows=[
        RateRow(effective_from=date(2000, 1, 1), bank_rate_pct=Decimal("5.50")),
        RateRow(effective_from=date(2026, 10, 7), bank_rate_pct=Decimal("5.75")),
    ]
)


def get_synthetic_dir() -> Path:
    docker_path = Path("/data/synthetic")
    if docker_path.exists():
        return docker_path
    local_path = (
        Path(__file__).resolve().parent.parent.parent.parent / "data" / "synthetic"
    ).resolve()
    if local_path.exists():
        return local_path
    raise FileNotFoundError("Synthetic directory not found")


# ---------------------------------------------------------------------------
# Case A – base stage
# principal 445096.00, delivery+written_acceptance 2026-04-20,
# written credit 45 days -> due date 2026-06-04, interest starts 2026-06-05
# payments: 198000.00 cash + 2000.00 tds on 2026-06-30
# Expected: outstanding principal 245096.00, total interest 17349.26
# Period interests: 5661.74, 3447.92, 3495.33, 3543.39, partial 1200.88
# ---------------------------------------------------------------------------


class TestCaseA:
    party_facts = PartyFacts(
        enterprise_type="micro",
        activity="manufacturer",
        udyam_reg_date=date(2024, 3, 12),
        contract_date=date(2026, 4, 2),
        udyam_certificate_present=True,
        written_contract_present=True,
    )
    item = ClaimItem(
        id="case_a_inv7731",
        label="INV-7731 (460 units delivered)",
        principal_amount=Decimal("445096.00"),
        delivery_date=date(2026, 4, 20),
        written_acceptance_date=date(2026, 4, 20),
        credit_days_written=45,
        payments=[
            Payment(
                pay_date=date(2026, 6, 30),
                amount=Decimal("198000.00"),
                kind=PaymentKind.cash,
            ),
            Payment(
                pay_date=date(2026, 6, 30),
                amount=Decimal("2000.00"),
                kind=PaymentKind.tds,
            ),
        ],
    )

    EXPECTED_DUE_DATE = date(2026, 6, 4)
    EXPECTED_INTEREST_START = date(2026, 6, 5)
    EXPECTED_OUTSTANDING_PRINCIPAL = Decimal("245096.00")
    EXPECTED_TOTAL_INTEREST = Decimal("17349.26")
    EXPECTED_PERIOD_INTERESTS = [
        Decimal("5661.74"),
        Decimal("3447.92"),
        Decimal("3495.33"),
        Decimal("3543.39"),
        Decimal("1200.88"),
    ]

    def _run(self):
        return evaluate_claim(self.party_facts, self.item, PACK, SEED_RATE_TABLE, AS_OF)

    def test_eligibility(self):
        result = self._run()
        assert result.eligibility.status == EligibilityStatus.eligible

    def test_due_date(self):
        result = self._run()
        assert result.due_date is not None
        assert result.due_date.due_date == self.EXPECTED_DUE_DATE, (
            f"Case A due date: expected {self.EXPECTED_DUE_DATE}, "
            f"got {result.due_date.due_date}.\n"
            + "\n".join(result.due_date.working)
        )
        assert result.due_date.interest_start_date == self.EXPECTED_INTEREST_START

    def test_outstanding_principal(self):
        result = self._run()
        assert result.interest is not None
        assert result.interest.outstanding_principal == self.EXPECTED_OUTSTANDING_PRINCIPAL, (
            f"Case A outstanding principal: expected {self.EXPECTED_OUTSTANDING_PRINCIPAL}, "
            f"got {result.interest.outstanding_principal}.\n"
            + "\n".join(result.interest.working)
        )

    def test_total_interest(self):
        result = self._run()
        assert result.interest is not None
        assert result.interest.total_interest == self.EXPECTED_TOTAL_INTEREST, (
            f"Case A total interest: expected {self.EXPECTED_TOTAL_INTEREST}, "
            f"got {result.interest.total_interest}.\n"
            f"Period rows:\n"
            + "\n".join(
                f"  period {p.period_index}: {p.interest}"
                for p in result.interest.periods
            )
            + "\nWorking:\n"
            + "\n".join(result.interest.working)
        )

    def test_period_interests(self):
        result = self._run()
        assert result.interest is not None
        for i, (expected, period) in enumerate(
            zip(self.EXPECTED_PERIOD_INTERESTS, result.interest.periods, strict=False)
        ):
            assert period.interest == expected, (
                f"Case A period {i}: expected {expected}, got {period.interest}.\n"
                + "\n".join(result.interest.working)
            )


# ---------------------------------------------------------------------------
# Case B – non-duplicate invoice 86140.00, delivery 2026-03-18,
# written credit 30 days -> due date 2026-04-17
# payments: 20000.00 on 2026-03-01, 50000.00 on 2026-05-02
# Expected: outstanding principal 16140.00, total interest 1700.39
# ---------------------------------------------------------------------------


class TestCaseB:
    party_facts = PartyFacts(
        enterprise_type="small",
        activity="manufacturer",
        udyam_reg_date=date(2023, 8, 1),
        contract_date=date(2026, 3, 5),
        udyam_certificate_present=True,
        written_contract_present=True,
    )
    item = ClaimItem(
        id="case_b_inv0412",
        label="KP/INV/0412",
        principal_amount=Decimal("86140.00"),
        delivery_date=date(2026, 3, 18),
        written_acceptance_date=date(2026, 3, 18),
        credit_days_written=30,
        payments=[
            Payment(
                pay_date=date(2026, 3, 1),
                amount=Decimal("20000.00"),
                kind=PaymentKind.cash,
            ),
            Payment(
                pay_date=date(2026, 5, 2),
                amount=Decimal("50000.00"),
                kind=PaymentKind.cash,
            ),
        ],
    )

    EXPECTED_DUE_DATE = date(2026, 4, 17)
    EXPECTED_OUTSTANDING_PRINCIPAL = Decimal("16140.00")
    EXPECTED_TOTAL_INTEREST = Decimal("1700.39")

    def _run(self):
        return evaluate_claim(self.party_facts, self.item, PACK, SEED_RATE_TABLE, AS_OF)

    def test_eligibility(self):
        result = self._run()
        assert result.eligibility.status == EligibilityStatus.eligible

    def test_due_date(self):
        result = self._run()
        assert result.due_date is not None
        assert result.due_date.due_date == self.EXPECTED_DUE_DATE, (
            f"Case B due date: expected {self.EXPECTED_DUE_DATE}, "
            f"got {result.due_date.due_date}.\n" + "\n".join(result.due_date.working)
        )

    def test_outstanding_principal(self):
        result = self._run()
        assert result.interest is not None
        assert result.interest.outstanding_principal == self.EXPECTED_OUTSTANDING_PRINCIPAL, (
            f"Case B outstanding principal: expected {self.EXPECTED_OUTSTANDING_PRINCIPAL}, "
            f"got {result.interest.outstanding_principal}.\n"
            + "\n".join(result.interest.working)
        )

    def test_total_interest(self):
        result = self._run()
        assert result.interest is not None
        assert result.interest.total_interest == self.EXPECTED_TOTAL_INTEREST, (
            f"Case B total interest: expected {self.EXPECTED_TOTAL_INTEREST}, "
            f"got {result.interest.total_interest}.\n"
            f"Period rows:\n"
            + "\n".join(
                f"  period {p.period_index}: {p.interest}"
                for p in result.interest.periods
            )
            + "\nWorking:\n"
            + "\n".join(result.interest.working)
        )


# ---------------------------------------------------------------------------
# Case C – ineligible (Udyam reg after PO date)
# ---------------------------------------------------------------------------


class TestCaseC:
    party_facts = PartyFacts(
        enterprise_type="micro",
        activity="manufacturer",
        udyam_reg_date=date(2026, 5, 20),  # AFTER PO date 2026-03-10
        contract_date=date(2026, 3, 10),
        udyam_certificate_present=True,
        written_contract_present=True,
    )
    item = ClaimItem(
        id="case_c_inv901",
        label="INV-901",
        principal_amount=Decimal("264600.00"),
        delivery_date=date(2026, 3, 25),
        written_acceptance_date=date(2026, 3, 25),
        credit_days_written=30,
    )

    def _run(self):
        return evaluate_claim(self.party_facts, self.item, PACK, SEED_RATE_TABLE, AS_OF)

    def test_not_eligible(self):
        result = self._run()
        assert result.eligibility.status == EligibilityStatus.not_eligible, (
            f"Case C should be not_eligible: {result.eligibility}"
        )

    def test_eligibility_reason(self):
        result = self._run()
        reasons_text = " ".join(result.eligibility.reasons)
        assert "Udyam registration date is after the PO date" in reasons_text, (
            f"Case C eligibility reason should mention Udyam date: {result.eligibility.reasons}"
        )

    def test_interest_is_null(self):
        result = self._run()
        assert result.interest is None, (
            f"Case C interest must be null for ineligible supplier; got {result.interest}"
        )

    def test_interest_refused_reason(self):
        result = self._run()
        assert result.interest_refused_reason is not None
        assert len(result.interest_refused_reason) > 0


# ---------------------------------------------------------------------------
# Case D – accepted value 16189.60 (980 accepted pcs)
# Challan date from expected.json (scan shows 12-05-2026): 2026-05-12
# written credit 30 days -> due date 2026-06-11
# payment 10000.00 on 2026-07-15
# Expected: outstanding principal 6189.60, total interest 514.43
# ---------------------------------------------------------------------------


class TestCaseD:
    # Challan date per expected.json (confirmed: 2026-05-12)
    DELIVERY_DATE = date(2026, 5, 12)
    EXPECTED_DUE_DATE = date(2026, 6, 11)  # May 12 + 30 days = June 11
    EXPECTED_OUTSTANDING_PRINCIPAL = Decimal("6189.60")
    EXPECTED_TOTAL_INTEREST = Decimal("514.43")

    party_facts = PartyFacts(
        enterprise_type="micro",
        activity="manufacturer",
        udyam_reg_date=date(2022, 11, 4),
        contract_date=date(2026, 5, 6),
        udyam_certificate_present=True,
        written_contract_present=True,
    )
    item = ClaimItem(
        id="case_d_inv1042",
        label="INV-1042 (980 accepted pcs)",
        principal_amount=Decimal("16189.60"),
        delivery_date=date(2026, 5, 12),
        written_acceptance_date=date(2026, 5, 12),
        credit_days_written=30,
        payments=[
            Payment(
                pay_date=date(2026, 7, 15),
                amount=Decimal("10000.00"),
                kind=PaymentKind.cash,
            )
        ],
    )

    def _run(self):
        return evaluate_claim(self.party_facts, self.item, PACK, SEED_RATE_TABLE, AS_OF)

    def test_due_date(self):
        result = self._run()
        assert result.due_date is not None
        assert result.due_date.due_date == self.EXPECTED_DUE_DATE, (
            f"Case D due date: expected {self.EXPECTED_DUE_DATE}, "
            f"got {result.due_date.due_date}.\n"
            + "\n".join(result.due_date.working)
        )

    def test_outstanding_principal(self):
        result = self._run()
        assert result.interest is not None
        assert result.interest.outstanding_principal == self.EXPECTED_OUTSTANDING_PRINCIPAL, (
            f"Case D outstanding principal: expected {self.EXPECTED_OUTSTANDING_PRINCIPAL}, "
            f"got {result.interest.outstanding_principal}.\n"
            + "\n".join(result.interest.working)
        )

    def test_total_interest(self):
        result = self._run()
        assert result.interest is not None
        assert result.interest.total_interest == self.EXPECTED_TOTAL_INTEREST, (
            f"Case D total interest: expected {self.EXPECTED_TOTAL_INTEREST}, "
            f"got {result.interest.total_interest}.\n"
            f"Period rows:\n"
            + "\n".join(
                f"  period {p.period_index}: {p.interest}"
                for p in result.interest.periods
            )
            + "\nWorking:\n"
            + "\n".join(result.interest.working)
        )
