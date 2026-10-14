import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")

DATE_FORMATS = [
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%Y-%m-%d",
    "%d-%b-%Y",  # 12-May-2026
    "%d %b %Y",  # 12 May 2026
    "%d-%B-%Y",  # 12-May-2026
    "%d %B %Y",  # 12 May 2026
    "%d.%m.%Y",
]


ACTIVITY_VOCABULARY = {
    "manufacturer": ["manufacturer", "manufacturing", "production", "mfg"],
    "service": ["service", "services", "servicing"],
    "trader": ["trader", "trading", "retail", "wholesale"],
}


def normalize_activity(activity_raw: Any) -> tuple[str | None, list[str]]:
    """Maps activity text (e.g. 'Manufacturing', 'Manufacturer') to fixed vocabulary: manufacturer, service, trader."""
    if activity_raw is None:
        return None, []
    s = str(activity_raw).strip().lower()
    if not s:
        return None, []
    for canonical, variants in ACTIVITY_VOCABULARY.items():
        if any(v in s for v in variants):
            return canonical, []
    return s, ["UNKNOWN_ACTIVITY_VOCABULARY"]


def normalize_date(date_raw: Any, as_of_date_str: str = "2026-10-14") -> tuple[str | None, list[str]]:
    """Normalizes various Indian and commercial date strings to ISO YYYY-MM-DD.

    Flags any date outside 2000 to 2035, or after as-of date by more than a year.
    Handles PDF-wrapped dates where a table cell wraps mid-year (e.g. '05-06-202\n6').
    """
    if date_raw is None:
        return None, []

    s = str(date_raw).strip()
    if not s:
        return None, []

    # De-wrap dates split across PDF table lines: "05-06-202\n6" -> "05-06-2026"
    # Matches 8-digit date that got linebroken: "DD-MM-202\n6" or "DD/MM/202\n6"
    s = re.sub(r"(\d{2}[-/]\d{2}[-/]\d{3})\s*\n\s*(\d)", r"\1\2", s)
    s = s.replace("\n", " ").strip()

    # Clean ordinals like 1st, 2nd, 3rd, 4th
    s_clean = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", s, flags=re.IGNORECASE)

    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(s_clean, fmt)
            flags: list[str] = []
            if dt.year < 2000 or dt.year > 2035:
                flags.append("DATE_OUT_OF_RANGE")
            try:
                as_of = datetime.strptime(as_of_date_str, "%Y-%m-%d")
                if (dt - as_of).days > 365:
                    flags.append("DATE_AFTER_AS_OF_PLUS_1YR")
            except Exception:
                pass
            return dt.strftime("%Y-%m-%d"), flags
        except ValueError:
            continue

    return s, ["INVALID_DATE_FORMAT"]



def normalize_indian_number(num_raw: Any) -> tuple[Decimal | None, list[str]]:
    """Normalizes Indian and commercial numbers (e.g. ₹ 1,00,000.00, 460 pcs, 18%) to Decimal.

    A standalone '-' means absent/null (e.g. bank statement empty cell), not an invalid number.
    """
    if num_raw is None:
        return None, []

    if isinstance(num_raw, int | float | Decimal):
        try:
            return Decimal(str(num_raw)), []
        except (InvalidOperation, ValueError):
            return None, ["INVALID_NUMBER_FORMAT"]

    s = str(num_raw).strip()
    if not s:
        return None, []

    # A standalone dash means "absent / not applicable" — return null silently
    if s in ("-", "—", "–", "N/A", "n/a", "nil", "NIL"):
        return None, []

    # Remove currency symbols, commas, percent, units like pcs, metres, etc.
    cleaned = re.sub(r"[₹\$,%]", "", s)
    cleaned = re.sub(r"\b(rs\.?|inr|pcs|nos|kg|mtr|metres|units)\b", "", cleaned, flags=re.IGNORECASE).strip()

    # Match numeric float / integer string
    m = re.search(r"[-+]?\d*\.?\d+", cleaned)
    if not m:
        return None, ["INVALID_NUMBER_FORMAT"]

    try:
        val = Decimal(m.group(0))
        return val, []
    except (InvalidOperation, ValueError):
        return None, ["INVALID_NUMBER_FORMAT"]



def validate_gstin(gstin_raw: Any) -> tuple[str | None, list[str]]:
    """Validates 15-character Indian GSTIN format."""
    if not gstin_raw:
        return None, []
    gstin = str(gstin_raw).strip().upper()
    if not GSTIN_REGEX.match(gstin):
        return gstin, ["INVALID_GSTIN_FORMAT"]
    return gstin, []


def validate_line_math(
    qty: Decimal | None,
    rate: Decimal | None,
    amount: Decimal | None,
    tolerance: Decimal = Decimal("0.05"),
) -> list[str]:
    """Validates line item: qty * rate == amount."""
    if qty is None or rate is None or amount is None:
        return []
    expected = qty * rate
    if abs(expected - amount) > tolerance:
        return ["LINE_MATH_MISMATCH"]
    return []


def validate_lines_sum(
    line_amounts: list[Decimal],
    taxable_total: Decimal | None,
    tolerance: Decimal = Decimal("0.05"),
) -> list[str]:
    """Validates sum of line amounts == taxable_total."""
    if taxable_total is None or not line_amounts:
        return []
    total_lines = sum(line_amounts)
    if abs(total_lines - taxable_total) > tolerance:
        return ["TAXABLE_TOTAL_MISMATCH"]
    return []


def validate_grand_total(
    taxable: Decimal | None,
    gst: Decimal | None,
    grand: Decimal | None,
    tolerance: Decimal = Decimal("0.05"),
) -> list[str]:
    """Validates taxable + gst == grand_total."""
    if taxable is None or gst is None or grand is None:
        return []
    if abs((taxable + gst) - grand) > tolerance:
        return ["GRAND_TOTAL_MISMATCH"]
    return []


def validate_date_order(
    earlier_date: str | None,
    later_date: str | None,
) -> list[str]:
    """Ensures earlier_date <= later_date (in ISO YYYY-MM-DD format)."""
    if not earlier_date or not later_date:
        return []
    if earlier_date > later_date:
        return ["DATE_ORDER_VIOLATION"]
    return []
