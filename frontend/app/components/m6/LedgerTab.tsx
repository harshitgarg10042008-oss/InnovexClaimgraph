"use client";

/**
 * PART 3: Ledger Tab
 *
 * Reads GET /cases/{id}/ledger → LedgerResponse
 * summary is Record<string,never> in the schema (untyped); we access it safely.
 *
 * Layout:
 * - Stale/provisional banners
 * - Totals block: BOTH bases side by side
 * - One section per claim_item (from summary.claim_items)
 * - Ledger rows table per claim item
 * - Allocation table
 * - Assumptions list
 */

import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  FileText,
  Info,
  Loader2,
  Minus,
} from "lucide-react";
import { apiClient } from "@/lib/api/client";
import { fmtDate, fmtINR, fmtNum } from "./shared";
import type { LedgerResponse } from "./shared";
import {
  BlockedPanel,
  NoDataPanel,
  ProvisionalBanner,
  StaleBanner,
} from "./LinkingPanel";

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

// Safe accessor into the untyped summary object
function s(obj: Record<string, unknown> | null | undefined, key: string): unknown {
  return obj?.[key] ?? undefined;
}

function dash(val: unknown): string {
  if (val === null || val === undefined || val === "") return "\u2013";
  const n = typeof val === "string" ? parseFloat(val) : val as number;
  if (typeof n === "number" && !isFinite(n)) return "\u2013";
  return fmtINR(n as number);
}

function numOrDash(val: unknown): string {
  if (val === null || val === undefined || val === "") return "\u2013";
  const n = typeof val === "string" ? parseFloat(val) : val as number;
  if (typeof n !== "number" || !isFinite(n)) return "\u2013";
  return fmtNum(n);
}

function rowTypeIcon(type: string | undefined) {
  const t = (type ?? "").toLowerCase();
  if (t.includes("invoice") || t.includes("bill")) return <FileText size={12} />;
  if (t.includes("payment") || t.includes("paid")) return <CheckCircle2 size={12} />;
  if (t.includes("tds") || t.includes("adjust")) return <Minus size={12} />;
  if (t.includes("note") || t.includes("credit") || t.includes("debit")) return <AlertCircle size={12} />;
  return <Info size={12} />;
}

/* ------------------------------------------------------------------ */
/* Totals block                                                         */
/* ------------------------------------------------------------------ */
function TotalsBlock({ summary }: { summary: Record<string, unknown> }) {
  const delivered = s(summary, "delivered_basis") as Record<string, unknown> | undefined;
  const invoice = s(summary, "invoice_basis") as Record<string, unknown> | undefined;
  const dueDate = s(summary, "due_date") as string | undefined;
  const daysOverdue = s(summary, "days_overdue") as number | undefined;

  return (
    <div className="ledger-totals-block">
      <div className="ledger-totals-grid">
        {/* Column 1: Delivered and accepted goods */}
        <div className="ledger-totals-col">
          <div className="ledger-totals-col-heading">Delivered and accepted goods</div>
          <table className="ledger-totals-table">
            <tbody>
              <tr>
                <td>Delivered</td>
                <td className="num-col">{dash(s(delivered, "delivered"))}</td>
              </tr>
              <tr>
                <td>Accepted</td>
                <td className="num-col">{dash(s(delivered, "accepted"))}</td>
              </tr>
              <tr>
                <td>Paid</td>
                <td className="num-col">{dash(s(delivered, "paid"))}</td>
              </tr>
              <tr>
                <td>Adjustments</td>
                <td className="num-col">{dash(s(delivered, "adjustments"))}</td>
              </tr>
              <tr className="totals-row-highlight">
                <td>
                  <strong>Outstanding</strong>
                </td>
                <td className="num-col">
                  <strong>{dash(s(delivered, "outstanding"))}</strong>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Column 2: Full invoice value */}
        <div className="ledger-totals-col">
          <div className="ledger-totals-col-heading">Full invoice value</div>
          <table className="ledger-totals-table">
            <tbody>
              <tr>
                <td>Invoiced</td>
                <td className="num-col">{dash(s(invoice, "invoiced"))}</td>
              </tr>
              <tr>
                <td>Delivered</td>
                <td className="num-col">{dash(s(invoice, "delivered"))}</td>
              </tr>
              <tr>
                <td>Paid</td>
                <td className="num-col">{dash(s(invoice, "paid"))}</td>
              </tr>
              <tr>
                <td>Adjustments</td>
                <td className="num-col">{dash(s(invoice, "adjustments"))}</td>
              </tr>
              <tr className="totals-row-highlight">
                <td>
                  <strong>Outstanding</strong>
                </td>
                <td className="num-col">
                  <strong>{dash(s(invoice, "outstanding"))}</strong>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Column 3: Due date and overdue */}
        <div className="ledger-totals-col">
          <div className="ledger-totals-col-heading">Timing</div>
          <table className="ledger-totals-table">
            <tbody>
              <tr>
                <td>Due date</td>
                <td className="num-col">{fmtDate(dueDate)}</td>
              </tr>
              <tr>
                <td>Days overdue</td>
                <td className="num-col">
                  {daysOverdue != null ? numOrDash(daysOverdue) : "\u2013"}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Assumptions                                                          */
/* ------------------------------------------------------------------ */
function AssumptionsList({ assumptions }: { assumptions: unknown[] }) {
  if (!assumptions || assumptions.length === 0) return null;
  return (
    <div className="ledger-assumptions">
      <h3 className="ledger-section-title">Assumptions</h3>
      <ul className="assumptions-list">
        {assumptions.map((a, i) => {
          const obj = a as Record<string, unknown>;
          const text = String(obj.text ?? obj.assumption ?? obj.description ?? a);
          const legal = Boolean(obj.legal_item ?? obj.needs_legal ?? false);
          return (
            <li key={i} className="assumption-item">
              <span>{text}</span>
              {legal && (
                <span className="assumption-legal-tag">Open legal item</span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Allocation table                                                     */
/* ------------------------------------------------------------------ */
function AllocationTable({ allocations }: { allocations: unknown[] }) {
  if (!allocations || allocations.length === 0) return null;
  return (
    <div className="ledger-allocation">
      <h3 className="ledger-section-title">Payment allocation</h3>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Payment</th>
              <th>Claim item</th>
              <th className="num-col">Amount</th>
              <th>Strategy</th>
            </tr>
          </thead>
          <tbody>
            {allocations.map((a, i) => {
              const obj = a as Record<string, unknown>;
              return (
                <tr key={i}>
                  <td>
                    <code className="mono-ref">
                      {String(obj.payment ?? obj.payment_ref ?? "\u2013")}
                    </code>
                  </td>
                  <td>{String(obj.claim_item ?? obj.item ?? "\u2013")}</td>
                  <td className="num-col">{dash(obj.amount)}</td>
                  <td>{String(obj.strategy ?? "\u2013")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Claim item section with ledger rows                                  */
/* ------------------------------------------------------------------ */
function ClaimItemSection({
  item,
  index,
  onOpenEvidence,
}: {
  item: Record<string, unknown>;
  index: number;
  onOpenEvidence?: (docId: string, page: number) => void;
}) {
  const rows = (item.rows as unknown[] | undefined) ?? [];
  const label = String(item.label ?? item.description ?? `Claim item ${index + 1}`);

  return (
    <div className="ledger-claim-section">
      <div className="ledger-claim-header">
        <h3 className="ledger-claim-title">{label}</h3>
      </div>
      <div className="table-wrap">
        <table className="data-table ledger-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Type</th>
              <th>Reference</th>
              <th className="num-col">Debit</th>
              <th className="num-col">Credit</th>
              <th className="num-col">Balance</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={7} className="ledger-empty-row">
                  No rows for this claim item.
                </td>
              </tr>
            ) : (
              rows.map((r, ri) => {
                const row = r as Record<string, unknown>;
                const docId = String(row.source_document_id ?? row.doc_id ?? "");
                const page = Number(row.page_no ?? 1);
                const isFirst = ri === 0;
                return (
                  <tr key={ri}>
                    <td>{fmtDate(row.date as string | undefined)}</td>
                    <td>
                      <span className="row-type-cell">
                        {rowTypeIcon(row.type as string | undefined)}
                        <span>
                          {isFirst
                            ? label
                            : String(row.type ?? "\u2013").replace(/_/g, " ")}
                        </span>
                      </span>
                    </td>
                    <td>
                      <code className="mono-ref">
                        {String(row.reference ?? row.ref ?? row.doc_ref ?? "\u2013")}
                      </code>
                    </td>
                    <td className="num-col">
                      {row.debit != null ? dash(row.debit) : "\u2013"}
                    </td>
                    <td className="num-col">
                      {row.credit != null ? dash(row.credit) : "\u2013"}
                    </td>
                    <td className="num-col">
                      {row.running_balance != null ? dash(row.running_balance) : "\u2013"}
                    </td>
                    <td>
                      {docId ? (
                        <button
                          type="button"
                          className="source-icon-btn"
                          onClick={() => onOpenEvidence?.(docId, page)}
                          title="Open source evidence"
                          aria-label="Open source evidence"
                        >
                          <FileText size={13} />
                        </button>
                      ) : (
                        <span className="text-slate" style={{ fontSize: "0.7rem" }}>
                          \u2013
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Main LedgerTab export                                                */
/* ------------------------------------------------------------------ */
export function LedgerTab({
  caseId,
  linkRunResult,
  isBlocked,
  isStale,
  isProvisional,
  provisionalReason,
  onRunLinking,
  runLinkingLoading,
  onJumpToReview,
  onOpenEvidence,
}: {
  caseId: string;
  linkRunResult: { blockers?: import("./shared").BlockerItem[] } | null;
  isBlocked: boolean;
  isStale: boolean;
  isProvisional: boolean;
  provisionalReason?: string;
  onRunLinking: () => void;
  runLinkingLoading: boolean;
  onJumpToReview?: (docName: string) => void;
  onOpenEvidence?: (docId: string, page: number) => void;
}) {
  const { data: ledger, isLoading, error } = useQuery<LedgerResponse>({
    queryKey: ["ledger", caseId],
    queryFn: () => apiClient<LedgerResponse>(`/cases/${caseId}/ledger`),
    enabled: Boolean(caseId),
  });

  if (isBlocked) {
    return (
      <div className="tab-pane-scroll">
        <BlockedPanel
          blockers={linkRunResult?.blockers ?? []}
          onJumpToReview={onJumpToReview}
        />
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="tab-pane-scroll m6-loading">
        <Loader2 size={24} className="spin" />
        <p>Loading ledger…</p>
      </div>
    );
  }

  if (error || !ledger) {
    return (
      <div className="tab-pane-scroll">
        <NoDataPanel label="Run linking to compute the ledger." />
      </div>
    );
  }

  const summary = (ledger.summary as Record<string, unknown> | null) ?? {};
  const effectiveStale = isStale || ledger.stale;
  const effectiveProvisional =
    isProvisional ||
    ledger.ledger_status === "provisional" ||
    Boolean(ledger.provisional_reason);
  const effectiveReason =
    provisionalReason ?? ledger.provisional_reason ?? "";

  const claimItems = (s(summary, "claim_items") as unknown[] | undefined) ?? [];
  const allocations = (s(summary, "allocations") as unknown[] | undefined) ?? [];
  const assumptions = (s(summary, "assumptions") as unknown[] | undefined) ?? [];

  const hasData = claimItems.length > 0 || Object.keys(summary).length > 0;

  return (
    <div
      className={`tab-pane-scroll ${effectiveStale ? "stale-dimmed" : ""}`}
    >
      {effectiveStale && (
        <StaleBanner onRun={onRunLinking} loading={runLinkingLoading} />
      )}
      {effectiveProvisional && effectiveReason && (
        <ProvisionalBanner reason={effectiveReason} />
      )}

      {!hasData ? (
        <NoDataPanel label="Run linking to compute the ledger." />
      ) : (
        <>
          {/* Totals block */}
          <TotalsBlock summary={summary} />

          {/* One section per claim item */}
          {claimItems.map((item, i) => (
            <ClaimItemSection
              key={i}
              item={item as Record<string, unknown>}
              index={i}
              onOpenEvidence={onOpenEvidence}
            />
          ))}

          {/* Fallback: show raw summary keys if claim_items not present */}
          {claimItems.length === 0 && (
            <div className="ledger-raw-summary">
              <h3 className="ledger-section-title">Summary</h3>
              <dl className="summary-dl">
                {Object.entries(summary).map(([k, v]) => {
                  if (typeof v === "object") return null;
                  return (
                    <div key={k} className="summary-dl-row">
                      <dt>{k.replace(/_/g, " ")}</dt>
                      <dd className="num-col">
                        {v !== null && v !== undefined
                          ? /amount|total|outstanding|paid|invoiced|delivered|accepted|balance/i.test(k)
                            ? dash(v)
                            : String(v)
                          : "\u2013"}
                      </dd>
                    </div>
                  );
                })}
              </dl>
            </div>
          )}

          {/* Allocation table */}
          <AllocationTable allocations={allocations} />

          {/* Assumptions */}
          <AssumptionsList assumptions={assumptions} />

          {/* Run date */}
          {ledger.run_at && (
            <p className="ledger-run-at">
              Last computed: {fmtDate(ledger.run_at)}
            </p>
          )}
        </>
      )}
    </div>
  );
}
