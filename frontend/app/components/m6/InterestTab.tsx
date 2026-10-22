"use client";

/**
 * PART 4: Interest Tab
 *
 * The API /cases/{id}/ledger returns summary as Record<string,never>.
 * The interest data (if present) lives inside summary.interest.
 *
 * The /rules/interest-preview endpoint returns InterestResult with periods[],
 * but that is a *preview* endpoint requiring a POST with principal/payments.
 * There is NO dedicated GET /cases/{id}/interest endpoint in the API.
 *
 * Therefore:
 * - We read interest data from summary.interest (inside LedgerResponse.summary).
 * - If the API provides total-only data (no per-period slices), we show totals
 *   and report that per-period breakdown needs a backend endpoint.
 * - If the API provides periods[] we render them.
 * - Refused state (interest.status === "refused"): show reason, NO amount anywhere.
 */

import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Info,
  Loader2,
  XCircle,
} from "lucide-react";
import { apiClient } from "@/lib/api/client";
import { fmtDate, fmtINR, fmtNum, todayLabel } from "./shared";
import type { LedgerResponse } from "./shared";
import {
  BlockedPanel,
  NoDataPanel,
  ProvisionalBanner,
  StaleBanner,
} from "./LinkingPanel";

/* ------------------------------------------------------------------ */
/* Helpers                                                              */
/* ------------------------------------------------------------------ */
function s(obj: Record<string, unknown> | null | undefined, key: string): unknown {
  return obj?.[key] ?? undefined;
}

function dash(val: unknown): string {
  if (val === null || val === undefined || val === "") return "\u2013";
  const n = typeof val === "string" ? parseFloat(val) : (val as number);
  if (!isFinite(n as number)) return "\u2013";
  return fmtINR(n as number);
}

function statusIcon(status: string | undefined) {
  const st = (status ?? "").toLowerCase();
  if (st === "computed" || st === "final")
    return <CheckCircle2 size={13} style={{ color: "var(--color-verified)" }} />;
  if (st === "provisional")
    return <AlertCircle size={13} style={{ color: "var(--color-attention)" }} />;
  if (st === "refused")
    return <XCircle size={13} style={{ color: "var(--color-conflict)" }} />;
  return <Info size={13} />;
}

/* ------------------------------------------------------------------ */
/* Refused state panel                                                  */
/* ------------------------------------------------------------------ */
function RefusedPanel({
  reason,
  findingId,
}: {
  reason: string;
  findingId?: string;
}) {
  return (
    <div className="interest-refused-panel">
      <div className="interest-refused-header">
        <XCircle size={18} style={{ color: "var(--color-conflict)" }} />
        <strong>Interest not applicable</strong>
      </div>
      <p className="interest-refused-reason">{reason}</p>
      {findingId && (
        <p className="interest-refused-finding">
          See finding:{" "}
          <code className="mono-ref">{findingId}</code>
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
  const interest = (s(summary, "interest") as Record<string, unknown> | null) ?? null;
  const effectiveStale = isStale || ledger.stale;

  // Interest status
  const interestStatus = String(s(interest, "status") ?? "");
  const isRefused = interestStatus.toLowerCase() === "refused";
  const refusalReason = String(s(interest, "refusal_reason") ?? s(interest, "reason") ?? "");
  const refusalFindingId = String(s(interest, "finding_id") ?? "");

  // Periods (if available)
  const periods = (s(interest, "periods") as unknown[] | undefined) ?? [];
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

      {/* Rule pack label — ALWAYS shown, exact wording from HARD RULES */}
      <div className="interest-label-header">
        <Info size={14} />
        <span>
          Interest as computed under our configurable rule pack, as of{" "}
          {todayLabel()}
        </span>
      </div>

      {/* Refused state: show reason, NO amount anywhere */}
      {isRefused ? (
        <RefusedPanel
          reason={refusalReason || "Interest was refused for this claim."}
          findingId={refusalFindingId || undefined}
        />
      ) : !interest ? (
        <NoDataPanel label="Run linking to compute interest." />
      ) : (
        <>
          {/* Summary stats */}
          <div className="interest-stats-grid">
            <div className="interest-stat-cell">
              <span className="interest-stat-label">Principal</span>
              <strong className="interest-stat-value">
                {dash(s(interest, "principal") ?? s(interest, "outstanding_principal"))}
              </strong>
            </div>
            <div className="interest-stat-cell">
              <span className="interest-stat-label">Due date</span>
              <strong className="interest-stat-value">
                {fmtDate(s(interest, "due_date") as string | undefined)}
              </strong>
            </div>
            <div className="interest-stat-cell">
              <span className="interest-stat-label">Interest start</span>
              <strong className="interest-stat-value">
                {fmtDate(
                  s(interest, "interest_start_date") as string | undefined ??
                  s(interest, "start_date") as string | undefined
                )}
              </strong>
            </div>
            <div className="interest-stat-cell">
              <span className="interest-stat-label">Days overdue</span>
              <strong className="interest-stat-value">
                {s(interest, "days_overdue") != null
                  ? fmtNum(Number(s(interest, "days_overdue")))
                  : "\u2013"}
              </strong>
            </div>
            <div className="interest-stat-cell">
              <span className="interest-stat-label">Rate</span>
              <strong className="interest-stat-value">
                {s(interest, "rate") != null
                  ? `${s(interest, "rate")}%`
                  : "\u2013"}
              </strong>
            </div>
            <div className="interest-stat-cell">
              <span className="interest-stat-label">Interest total</span>
              <strong
                className="interest-stat-value"
                style={{ color: "var(--color-ink)" }}
              >
                {dash(
                  s(interest, "total_interest") ??
                  s(interest, "interest_amount") ??
                  s(interest, "interest")
                )}
              </strong>
            </div>
            <div className="interest-stat-cell">
              <span className="interest-stat-label">Status</span>
              <strong className="interest-stat-value interest-status-cell">
                {statusIcon(interestStatus)}
                <span>{interestStatus || "\u2013"}</span>
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
                only aggregate interest totals inside{" "}
                <code>summary.interest</code>. A read-only{" "}
                <code>GET /cases/&#123;id&#125;/interest</code> endpoint with
                per-period slices and monthly rests is needed from the backend.
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
