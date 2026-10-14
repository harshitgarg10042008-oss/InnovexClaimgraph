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
