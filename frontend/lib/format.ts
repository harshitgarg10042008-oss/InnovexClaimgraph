/**
 * Formats a numeric amount into Indian Rupee currency format (e.g. ₹1,04,374.79).
 */
export function formatINR(amount: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(amount);
}

/**
 * Formats a date into "14 Oct 2026" format.
 */
export function formatDate(date: string | Date | number): string {
  const d =
    typeof date === "string" || typeof date === "number"
      ? new Date(date)
      : date;
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(d);
}

export function formatQuantity(value: number): string {
  return new Intl.NumberFormat("en-IN", { maximumFractionDigits: 3 }).format(
    value,
  );
}

export function displayFactValue(
  value: Record<string, unknown> | null | undefined,
  field: string,
): string {
  if (!value) return "Not present";
  const raw = (value as Record<string, unknown>).value;
  if (raw === null || raw === undefined || raw === "") return "Not present";
  if (typeof raw === "number") {
    return /amount|total|rate|price/i.test(field)
      ? formatINR(raw)
      : formatQuantity(raw);
  }
  if (/date/i.test(field) && typeof raw === "string") {
    const parsed = new Date(raw);
    if (!Number.isNaN(parsed.getTime())) return formatDate(parsed);
  }
  return String(raw);
}
