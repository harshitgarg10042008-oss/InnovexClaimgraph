"""
Rule-pack loader with Pydantic v2 validation.

All legal numbers and conventions live here (in the JSON file), not in Python
code.  The loader validates the pack structure and rejects anything that
deviates from the allowed values.
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

PACKS_DIR = Path(__file__).parent / "packs"

_ALLOWED_COMPOUNDING = {"monthly_rests"}
_ALLOWED_ACCRUAL = {"daily_weighted"}
_ALLOWED_ROUNDING = {"per_period_half_up_2dp"}
_ALLOWED_PAYMENT_APPLICATION = {"principal_first"}


class RulePack(BaseModel):
    """Validated representation of a rule-pack JSON file."""

    pack_name: str
    version: str
    effective_from: date
    status: str
    max_credit_days: int
    default_credit_days_without_written_agreement: int
    objection_window_days: int
    acceptance_rule: str
    due_date_rule: str
    interest_starts: Literal["day_after_due_date"]
    interest_multiplier: int
    compounding: str
    rest_anchor: str
    within_period_accrual: str
    rounding: str
    payment_application: str
    interest_on_gst_component: bool
    tds_counts_as_payment: bool
    arbitration_limitation_years: int
    eligible_enterprise_types: list[str]
    excluded_activities: list[str]

    @field_validator("compounding")
    @classmethod
    def _check_compounding(cls, v: str) -> str:
        if v not in _ALLOWED_COMPOUNDING:
            raise ValueError(f"compounding must be one of {_ALLOWED_COMPOUNDING}, got {v!r}")
        return v

    @field_validator("within_period_accrual")
    @classmethod
    def _check_accrual(cls, v: str) -> str:
        if v not in _ALLOWED_ACCRUAL:
            raise ValueError(f"within_period_accrual must be one of {_ALLOWED_ACCRUAL}, got {v!r}")
        return v

    @field_validator("rounding")
    @classmethod
    def _check_rounding(cls, v: str) -> str:
        if v not in _ALLOWED_ROUNDING:
            raise ValueError(f"rounding must be one of {_ALLOWED_ROUNDING}, got {v!r}")
        return v

    @field_validator("payment_application")
    @classmethod
    def _check_payment_application(cls, v: str) -> str:
        if v not in _ALLOWED_PAYMENT_APPLICATION:
            raise ValueError(
                f"payment_application must be one of {_ALLOWED_PAYMENT_APPLICATION}, got {v!r}. "
                "Only 'principal_first' is supported."
            )
        return v

    @model_validator(mode="after")
    def _check_credit_days(self) -> RulePack:
        if self.default_credit_days_without_written_agreement > self.max_credit_days:
            raise ValueError(
                "default_credit_days_without_written_agreement must not exceed max_credit_days"
            )
        if self.max_credit_days <= 0:
            raise ValueError("max_credit_days must be positive")
        if self.interest_multiplier <= 0:
            raise ValueError("interest_multiplier must be positive")
        if self.arbitration_limitation_years <= 0:
            raise ValueError("arbitration_limitation_years must be positive")
        return self


def load_pack(name: str = "msmed_v1") -> RulePack:
    """Load a rule pack JSON by name and validate it.

    Args:
        name: The pack file stem (e.g. ``"msmed_v1"``).

    Returns:
        A validated :class:`RulePack`.

    Raises:
        FileNotFoundError: If the pack JSON does not exist.
        pydantic.ValidationError: If the pack fails validation.
    """
    path = PACKS_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Rule pack not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return RulePack.model_validate(raw)


@lru_cache(maxsize=8)
def get_active_pack() -> RulePack:
    """Return the cached active rule pack (msmed_v1)."""
    return load_pack("msmed_v1")
