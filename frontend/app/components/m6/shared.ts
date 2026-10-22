"use client";

/**
 * M6 shared utilities: formatting, status helpers, shared types for the
 * Graph / Ledger / Interest / Findings tabs.
 */

import type { components } from "@/lib/api/schema";

// Re-export generated types used across M6 tabs
export type GraphResponse = components["schemas"]["GraphResponse"];
export type GraphNode = components["schemas"]["GraphNode"];
export type GraphEdge = components["schemas"]["GraphEdge"];
export type LedgerResponse = components["schemas"]["LedgerResponse"];
export type FindingsResponse = components["schemas"]["FindingsResponse"];
export type FindingResponseItem = components["schemas"]["FindingResponseItem"];
export type LinkRunResponse = components["schemas"]["LinkRunResponse"];
export type LinkResponse = components["schemas"]["LinkResponse"];
export type BlockerItem = components["schemas"]["BlockerItem"];

/**
 * Indian rupee grouping: ₹1,04,374.79
 * Uses the en-IN locale which already produces Indian grouping.
 */
export function fmtINR(val: number | string | null | undefined): string {
  if (val === null || val === undefined || val === "") return "\u2013";
  const n = typeof val === "string" ? parseFloat(val) : val;
  if (!isFinite(n)) return "\u2013";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(n);
}

export function fmtNum(val: number | string | null | undefined): string {
  if (val === null || val === undefined || val === "") return "\u2013";
  const n = typeof val === "string" ? parseFloat(val) : val;
  if (!isFinite(n)) return "\u2013";
  return new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(n);
}

/**
 * Date formatted as "14 Oct 2026"
 */
export function fmtDate(val: string | null | undefined): string {
  if (!val) return "\u2013";
  const d = new Date(val);
  if (isNaN(d.getTime())) return val;
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(d);
}

/**
 * Today formatted as "14 Oct 2026" — used for the interest label.
 */
export function todayLabel(): string {
  return fmtDate(new Date().toISOString().slice(0, 10));
}

// Ledger status values from the API
export type LedgerStatus = "blocked" | "provisional" | "final" | "stale" | string;

export function ledgerStatusLabel(s: string | null | undefined): string {
  if (!s) return "\u2013";
  switch (s) {
    case "blocked": return "Blocked";
    case "provisional": return "Provisional";
    case "final": return "Final";
    case "stale": return "Stale";
    default: return s.replace(/_/g, " ");
  }
}
