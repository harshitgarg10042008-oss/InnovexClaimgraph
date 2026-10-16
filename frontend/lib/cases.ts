export type CaseListItem = {
  id: string;
  title: string;
  status: string;
  created_at: string;
  updated_at?: string;
  documents_count?: number;
  needs_review_count?: number;
  supplier?: { name: string } | null;
  buyer?: { name: string } | null;
};

/**
 * Returns 0 for Case A, 1 for Case B, 2 for Case C, 3 for Case D.
 * Returns null if not a demo case.
 */
export function getDemoCaseOrder(title: string): number | null {
  const match = title.match(/^Case\s+([A-D])\b/i);
  if (!match) return null;
  const letter = match[1].toUpperCase();
  const index = ["A", "B", "C", "D"].indexOf(letter);
  return index !== -1 ? index : null;
}

/**
 * Extracts a concise case code:
 * "CASE-A" for demo case A, or "CASE-XXXXXXXX" for other cases.
 */
export function getCaseCode(item: { id: string; title: string }): string {
  const match = item.title.match(/^Case\s+([A-D])\b/i);
  if (match) {
    return `CASE-${match[1].toUpperCase()}`;
  }
  return `CASE-${item.id.slice(0, 8).toUpperCase()}`;
}

export function partitionAndSortCases<
  T extends { title: string; updated_at?: string; created_at: string },
>(cases: T[]): { demoCases: T[]; yourCases: T[] } {
  const demoCases: T[] = [];
  const yourCases: T[] = [];

  for (const item of cases) {
    if (getDemoCaseOrder(item.title) !== null) {
      demoCases.push(item);
    } else {
      yourCases.push(item);
    }
  }

  demoCases.sort(
    (a, b) =>
      (getDemoCaseOrder(a.title) ?? 99) - (getDemoCaseOrder(b.title) ?? 99),
  );

  yourCases.sort((a, b) => {
    const timeA = new Date(a.updated_at || a.created_at).getTime();
    const timeB = new Date(b.updated_at || b.created_at).getTime();
    return timeB - timeA;
  });

  return { demoCases, yourCases };
}
