import { describe, expect, it } from "vitest";
import { displayFactValue, formatDate, formatINR } from "./format";

describe("formatters", () => {
  it("formats rupees with Indian grouping", () => {
    expect(formatINR(123456)).toBe("₹1,23,456.00");
  });

  it("formats dates in the project display format", () => {
    expect(formatDate("2026-10-14")).toBe("14 Oct 2026");
  });

  it("formats values according to their field type", () => {
    expect(displayFactValue({ value: 460 } as Record<string, unknown>, "accepted_qty")).toBe("460");
    expect(displayFactValue({ value: 123456 } as Record<string, unknown>, "amount")).toBe("₹1,23,456.00");
  });
});
