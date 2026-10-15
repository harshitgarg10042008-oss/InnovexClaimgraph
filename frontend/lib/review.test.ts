import { describe, expect, it } from "vitest";
import { groupFacts, keyboardAction, sortFacts } from "./review";

const facts = [
  { id: "b", document_id: "doc-2", group: "Line 1", page_no: 1, status: "auto" },
  { id: "a", document_id: "doc-1", group: "Header", page_no: 2, status: "needs_review" },
  { id: "c", document_id: "doc-1", group: "Header", page_no: 1, status: "auto" },
];

describe("review utilities", () => {
  it("sorts facts by document, group, and page", () => {
    expect(sortFacts(facts).map((fact) => fact.id)).toEqual(["c", "a", "b"]);
  });

  it("groups facts by document and group", () => {
    expect(Object.keys(groupFacts(facts))).toEqual(["doc-1:Header", "doc-2:Line 1"]);
  });

  it("maps review keyboard shortcuts", () => {
    expect(keyboardAction("j")).toBe("next");
    expect(keyboardAction("ArrowUp")).toBe("previous");
    expect(keyboardAction("Enter")).toBe("confirm");
    expect(keyboardAction("E")).toBe("edit");
    expect(keyboardAction("n")).toBe("not_present");
    expect(keyboardAction("x")).toBeNull();
  });
});
