import { describe, expect, it } from "vitest";
import {
  getCaseCode,
  getDemoCaseOrder,
  partitionAndSortCases,
} from "./cases";

describe("cases utilities", () => {
  it("identifies demo case order A to D", () => {
    expect(
      getDemoCaseOrder(
        "Case A: Sharma Auto Components vs Meridian Motors Pvt Ltd",
      ),
    ).toBe(0);
    expect(
      getDemoCaseOrder(
        "Case B: Kaveri Packaging Works vs Northline Foods Ltd",
      ),
    ).toBe(1);
    expect(
      getDemoCaseOrder("Case C: Tara Textiles vs Ashoka Retail Pvt Ltd"),
    ).toBe(2);
    expect(
      getDemoCaseOrder("Case D: Raman Fasteners vs Orbit Machines Pvt Ltd"),
    ).toBe(3);
    expect(getDemoCaseOrder("Test Case")).toBeNull();
    expect(getDemoCaseOrder("Case E: Unknown")).toBeNull();
  });

  it("extracts clean case codes", () => {
    expect(
      getCaseCode({
        id: "12345678-abcd",
        title: "Case A: Sharma Auto Components",
      }),
    ).toBe("CASE-A");
    expect(
      getCaseCode({
        id: "abcdef12-3456-7890",
        title: "Regular Supplier vs Buyer",
      }),
    ).toBe("CASE-ABCDEF12");
  });

  it("partitions and sorts demo cases A-D first, then other cases by last updated desc", () => {
    const raw = [
      {
        id: "user-old",
        title: "Old Case",
        created_at: "2026-10-14T08:00:00Z",
        updated_at: "2026-10-14T08:00:00Z",
      },
      {
        id: "case-c",
        title: "Case C: Tara Textiles",
        created_at: "2026-10-14T06:00:00Z",
      },
      {
        id: "case-a",
        title: "Case A: Sharma Auto",
        created_at: "2026-10-14T06:00:00Z",
      },
      {
        id: "user-new",
        title: "Recent Case",
        created_at: "2026-10-15T10:00:00Z",
        updated_at: "2026-10-15T12:00:00Z",
      },
      {
        id: "case-d",
        title: "Case D: Raman Fasteners",
        created_at: "2026-10-14T06:00:00Z",
      },
      {
        id: "case-b",
        title: "Case B: Kaveri Packaging",
        created_at: "2026-10-14T06:00:00Z",
      },
    ];

    const { demoCases, yourCases } = partitionAndSortCases(raw);

    expect(demoCases.map((c) => c.id)).toEqual([
      "case-a",
      "case-b",
      "case-c",
      "case-d",
    ]);
    expect(yourCases.map((c) => c.id)).toEqual(["user-new", "user-old"]);
  });
});
