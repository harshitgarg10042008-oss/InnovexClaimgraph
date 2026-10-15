export type ReviewFact = {
  id: string;
  document_id: string;
  group?: string | null;
  page_no: number;
  status: string;
};

export function sortFacts<T extends ReviewFact>(facts: T[]): T[] {
  return [...facts].sort(
    (a, b) =>
      a.document_id.localeCompare(b.document_id) ||
      (a.group ?? "").localeCompare(b.group ?? "") ||
      a.page_no - b.page_no,
  );
}

export function groupFacts<T extends ReviewFact>(facts: T[]) {
  return sortFacts(facts).reduce<Record<string, T[]>>((groups, fact) => {
    const key = `${fact.document_id}:${fact.group ?? "Other"}`;
    (groups[key] ??= []).push(fact);
    return groups;
  }, {});
}

export function keyboardAction(key: string): "next" | "previous" | "confirm" | "edit" | "not_present" | null {
  if (key === "ArrowDown" || key.toLowerCase() === "j") return "next";
  if (key === "ArrowUp" || key.toLowerCase() === "k") return "previous";
  if (key === "Enter") return "confirm";
  if (key.toLowerCase() === "e") return "edit";
  if (key.toLowerCase() === "n") return "not_present";
  return null;
}
