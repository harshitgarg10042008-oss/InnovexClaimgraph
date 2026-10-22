"use client";

/**
 * PART 4: Interest Tab
 *
 * Reads GET /cases/{id}/ledger → LedgerResponse
 * Interest totals live on summary (interest_total, interest_status, outstanding_on_delivered_goods)
 * and summary.claim_items (interest_start_date, days_overdue, interest_refused_reason).
 *
 * - Per-period breakdown check: The API currently returns only aggregate totals.
 *   If periods[] is absent, we display totals and state that per-period breakdown
 *   requires a dedicated read-only backend endpoint. We do NOT calculate periods in the frontend.
 * - Refused state (Case C): show the refusal reason from the API prominently with
 *   a link/reference to the finding; show NO interest amount anywhere on the page, not even as zero.
 * - Exact rule-pack label from HARD RULES: "Interest as computed under our configurable rule pack, as of 14 Oct 2026"
 * - Always show "Not legal advice".
 * - Never show "verdict", "legal amount", or "you will receive".
 */

import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  Info,
  Loader2,
  XCircle,
} from "lucide-react";
import { apiClient } from "@/lib/api/client";
import { fmtDate, fmtINR, fmtNum } from "./shared";
import type { LedgerResponse, FindingsResponse } from "./shared";
import {
  BlockedPanel,
  NoDataPanel,
  ProvisionalBanner,
  StaleBanner,
} from "./LinkingPanel";

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */
function s(obj: Record<string, unknown> | null | undefined, key: string): unknown {
  return obj?.[key] ?? undefined;
}

function dash(val: unknown): string {
  if (val === null || val === undefined || val === "") return "\u2013";
  const n = typeof val === "string" ? parseFloat(String(val).replace(/,/g, "")) : (val as number);
  if (!isFinite(n as number)) return "\u2013";
  return fmtINR(n as number);
}

function numOrDash(val: unknown): string {
  if (val === null || val === undefined || val === "") return "\u2013";
  const n = typeof val === "string" ? parseFloat(String(val).replace(/,/g, "")) : (val as number);
  if (!isFinite(n as number)) return "\u2013";
  return fmtNum(n as number);
}

function statusIcon(status: string | undefined) {
  const st = (status ?? "").toLowerCase();
  if (st === "computed" || st === "final")
    return <CheckCircle2 size={13} style={{ color: "var(--color-verified)" }} />;
  if (st === "provisional")
    return <AlertCircle size={13} style={{ color: "var(--color-attention)" }} />;
  if (st.includes("refused"))
    return <XCircle size={13} style={{ color: "var(--color-conflict)" }} />;
  return <Info size={13} />;
}

/* ------------------------------------------------------------------ */
/* Refused state panel                                                  */
/* ------------------------------------------------------------------ */
function RefusedPanel({
  reason,
  findingCode,
  onGoToFindings,
}: {
  reason: string;
  findingCode?: string;
  onGoToFindings?: () => void;
}) {
  return (
    <div className="interest-refused-panel">
      <div className="interest-refused-header">
        <XCircle size={18} style={{ color: "var(--color-conflict)" }} />
        <strong>Interest refused under applicable rules</strong>
      </div>
      <p className="interest-refused-reason">{reason}</p>
      {findingCode && (
        <p className="interest-refused-finding">
          Related finding:{" "}
          <button
            type="button"
            className="text-button"
            onClick={onGoToFindings}
            style={{ display: "inline-flex", gap: "4px", fontSize: "0.8rem", marginLeft: "4px" }}
          >
            <code className="mono-ref">{findingCode}</code>
            <ExternalLink size={12} />
          </button>
        </p>
      )}
      <div className="interest-legal-notice">
        <AlertTriangle size={13} />
        <span>Not legal advice.</span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Period breakdown table (if API provides periods)                     */
/* ------------------------------------------------------------------ */
function PeriodsTable({ periods }: { periods: unknown[] }) {
  return (
    <div className="table-wrap">
      <table className="data-table interest-periods-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Period start</th>
            <th>Period end</th>
            <th>Days</th>
            <th className="num-col">Opening principal</th>
            <th>Rate(s)</th>
            <th className="num-col">Interest</th>
            <th>Capitalised</th>
          </tr>
        </thead>
        <tbody>
          {periods.map((p, i) => {
            const row = p as Record<string, unknown>;
            const slices = (row.rate_slices as [string, number][] | undefined) ?? [];
            return (
              <tr key={i}>
                <td>{Number(row.period_index ?? i) + 1}</td>
                <td>{fmtDate(row.start as string | undefined)}</td>
                <td>{fmtDate(row.end as string | undefined)}</td>
                <td>{String(row.days_in_period ?? "\u2013")}</td>
                <td className="num-col">
                  {row.opening_base != null
                    ? fmtINR(parseFloat(String(row.opening_base)))
                    : "\u2013"}
                </td>
                <td>
                  {slices.length > 0
                    ? slices
                        .map(([name, rate]) => `${name} ${rate}%`)
                        .join(", ")
                    : "\u2013"}
                </td>
                <td className="num-col">
                  {row.interest != null
                    ? fmtINR(parseFloat(String(row.interest)))
                    : "\u2013"}
                </td>
                <td>{row.capitalised ? "Yes" : "No"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Main InterestTab export                                              */
/* ------------------------------------------------------------------ */
export function InterestTab({
  caseId,
  linkRunResult,
  isBlocked,
  isStale,
  isProvisional,
  provisionalReason,
  onRunLinking,
  runLinkingLoading,
  onJumpToReview,
  onGoToFindings,
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
  onGoToFindings?: () => void;
}) {
  const { data: ledger, isLoading, error } = useQuery<LedgerResponse>({
    queryKey: ["ledger", caseId],
    queryFn: () => apiClient<LedgerResponse>(`/cases/${caseId}/ledger`),
    enabled: Boolean(caseId),
  });

  const { data: findingsData } = useQuery<FindingsResponse>({
    queryKey: ["findings", caseId],
    queryFn: () => apiClient<FindingsResponse>(`/cases/${caseId}/findings`),
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
        <p>Loading interest data…</p>
      </div>
    );
  }

  if (error || !ledger) {
    return (
      <div className="tab-pane-scroll">
        <NoDataPanel label="Run linking to compute interest." />
      </div>
    );
  }

  const summary = (ledger.summary as Record<string, unknown> | null) ?? {};
  const claimItems = (s(summary, "claim_items") as Record<string, unknown>[] | undefined) ?? [];
  const firstItem = claimItems[0];
  const effectiveStale = isStale || ledger.stale;

  // Refusal check: check summary.interest_status or firstItem.interest_refused_reason
  const interestStatus = String(s(summary, "interest_status") ?? "");
  const isRefused =
    interestStatus.toLowerCase().startsWith("refused") ||
    Boolean(firstItem?.interest_refused_reason);

  const refusalReason =
    String(firstItem?.interest_refused_reason ?? "") ||
    (interestStatus.toLowerCase().startsWith("refused")
      ? interestStatus.replace(/^refused:\s*/i, "")
      : "Interest was refused under applicable eligibility rules.");

  // Identify ineligible / refusal finding if available
  const ineligibleFinding = (findingsData?.findings ?? []).find(
    (f) =>
      f.code.includes("INELIGIBLE") ||
      f.code.includes("REFUSED") ||
      f.severity.toLowerCase() === "conflict"
  );

  // Interest data fields from summary and claim items
  const principal = s(summary, "outstanding_on_delivered_goods") ?? firstItem?.claimable_principal;
  const dueDate = (s(summary, "due_date") ?? firstItem?.due_date) as string | undefined;
  const interestStartDate = firstItem?.interest_start_date as string | undefined;
  const daysOverdue = firstItem?.days_overdue as number | undefined;
  const interestTotal = s(summary, "interest_total") ?? firstItem?.interest_amount;
  const statusDisplay = isRefused ? "Refused" : interestStatus || "Computed";

  // Per-period breakdown check
  const periods = (s(summary, "periods") as unknown[] | undefined) ?? [];
  const hasPeriods = periods.length > 0;

  return (
    <div
      className={`tab-pane-scroll ${effectiveStale ? "stale-dimmed" : ""}`}
    >
      {effectiveStale && (
        <StaleBanner onRun={onRunLinking} loading={runLinkingLoading} />
      )}
      {isProvisional && provisionalReason && (
        <ProvisionalBanner reason={provisionalReason} />
      )}

      {/* Mandatory exact rule pack label */}
      <div className="interest-label-header">
        <Info size={14} />
        <span>Interest as computed under our configurable rule pack, as of 14 Oct 2026</span>
      </div>

      {/* Refused state: prominently display refusal reason, NO amount anywhere */}
      {isRefused ? (
        <RefusedPanel
          reason={refusalReason}
          findingCode={ineligibleFinding?.code}
          onGoToFindings={onGoToFindings}
        />
      ) : Object.keys(summary).length === 0 ? (
        <NoDataPanel label="Run linking to compute interest." />
      ) : (
        <>
          {/* Summary stats */}
          <div className="interest-stats-grid">
            <div className="interest-stat-cell">
              <span className="interest-stat-label">Principal</span>
              <strong className="interest-stat-value">
                {dash(principal)}
              </strong>
            </div>
            <div className="interest-stat-cell">
              <span className="interest-stat-label">Due date</span>
              <strong className="interest-stat-value">
                {fmtDate(dueDate)}
              </strong>
            </div>
            <div className="interest-stat-cell">
              <span className="interest-stat-label">Interest start date</span>
              <strong className="interest-stat-value">
                {fmtDate(interestStartDate)}
              </strong>
            </div>
            <div className="interest-stat-cell">
              <span className="interest-stat-label">Days overdue</span>
              <strong className="interest-stat-value">
                {daysOverdue != null ? numOrDash(daysOverdue) : "\u2013"}
              </strong>
            </div>
            <div className="interest-stat-cell">
              <span className="interest-stat-label">Rate</span>
              <strong className="interest-stat-value">
                MSMEDA 3× RBI
              </strong>
            </div>
            <div className="interest-stat-cell">
              <span className="interest-stat-label">Interest total</span>
              <strong
                className="interest-stat-value"
                style={{ color: "var(--color-ink)" }}
              >
                {dash(interestTotal)}
              </strong>
            </div>
            <div className="interest-stat-cell">
              <span className="interest-stat-label">Status</span>
              <strong className="interest-stat-value interest-status-cell">
                {statusIcon(statusDisplay)}
                <span>{statusDisplay}</span>
              </strong>
            </div>
          </div>

          {/* Period breakdown */}
          {hasPeriods ? (
            <div className="interest-periods">
              <h3 className="ledger-section-title">Period breakdown</h3>
              <PeriodsTable periods={periods} />
            </div>
          ) : (
            <div className="interest-no-breakdown">
              <AlertCircle size={14} />
              <p>
                Per-period breakdown is not available. The API currently returns
                only aggregate interest totals inside <code>summary</code>.
                A read-only <code>GET /cases/&#123;id&#125;/interest</code> endpoint
                with per-period slices and monthly rests is needed from the backend.
              </p>
            </div>
          )}
        </>
      )}

      {/* Legal notice — always shown */}
      <div className="interest-legal-notice">
        <AlertTriangle size={13} />
        <span>Not legal advice.</span>
      </div>
    </div>
  );
}
