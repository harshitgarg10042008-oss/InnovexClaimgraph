"use client";

/**
 * PART 5: Findings Tab
 *
 * GET /cases/{id}/findings → FindingsResponse
 * FindingResponseItem: id, code, severity, title, message,
 *   explanation_template, computed_numbers, needs_human_or_legal_review,
 *   blocks_ready, refs, refs_json, created_at
 *
 * Groups by severity: conflict → attention → info (icon plus word)
 * Filter chips: All | Conflict | Attention | Info | Needs legal review
 * UNCONFIRMED_LINKS card → "Go to Graph" button
 * Header count chips + summary line (e.g. "1 conflict, 1 attention, 2 info")
 */

import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  FileText,
  Info,
  Loader2,
  Scale,
  XCircle,
} from "lucide-react";
import { useMemo, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { fmtINR, fmtNum } from "./shared";
import type { FindingsResponse, FindingResponseItem } from "./shared";
import { BlockedPanel, NoDataPanel, StaleBanner } from "./LinkingPanel";

/* ------------------------------------------------------------------ */
/* Severity helpers                                                     */
/* ------------------------------------------------------------------ */
function severityIcon(sev: string) {
  switch (sev.toLowerCase()) {
    case "conflict":
      return <XCircle size={14} style={{ color: "var(--color-conflict)" }} />;
    case "attention":
      return <AlertCircle size={14} style={{ color: "var(--color-attention)" }} />;
    default:
      return <Info size={14} style={{ color: "var(--color-slate)" }} />;
  }
}

function severityLabel(sev: string): string {
  const s = sev.toLowerCase();
  if (s === "conflict") return "Conflict";
  if (s === "attention") return "Attention";
  return "Info";
}

function severityClass(sev: string): string {
  const s = sev.toLowerCase();
  if (s === "conflict") return "finding-card-conflict";
  if (s === "attention") return "finding-card-attention";
  return "finding-card-info";
}

/* ------------------------------------------------------------------ */
/* Computed numbers table with Indian grouping for money                */
/* ------------------------------------------------------------------ */
function ComputedNumbersTable({
  numbers,
}: {
  numbers: Record<string, unknown>;
}) {
  const entries = Object.entries(numbers).filter(
    ([, v]) => v !== null && v !== undefined
  );
  if (entries.length === 0) return null;

  return (
    <table className="computed-numbers-table">
      <tbody>
        {entries.map(([k, v]) => {
          const label = k.replace(/_/g, " ");
          const isMonetary =
            /amount|total|outstanding|paid|invoiced|delivered|accepted|balance|interest|principal|diff|deducted/i.test(
              k
            );
          let display: string;
          if (isMonetary && typeof v !== "boolean") {
            const raw = String(v).replace(/,/g, "");
            const n = parseFloat(raw);
            display = isFinite(n) ? fmtINR(n) : String(v);
          } else if (typeof v === "number") {
            display = fmtNum(v);
          } else {
            display = String(v);
          }
          return (
            <tr key={k}>
              <td className="cn-label">{label}</td>
              <td className="cn-value">{display}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/* ------------------------------------------------------------------ */
/* Single finding card                                                  */
/* ------------------------------------------------------------------ */
function FindingCard({
  finding,
  onGoToGraph,
  onOpenEvidence,
}: {
  finding: FindingResponseItem;
  onGoToGraph?: () => void;
  onOpenEvidence?: (docId: string, page: number, bbox?: number[] | null) => void;
}) {
  const computedNumbers =
    (finding.computed_numbers as Record<string, unknown> | null) ?? {};
  const hasNumbers = Object.keys(computedNumbers).length > 0;

  // Source refs from refs_json or refs
  const refs: Record<string, unknown>[] = Array.isArray(finding.refs_json)
    ? (finding.refs_json as Record<string, unknown>[])
    : Array.isArray(finding.refs)
      ? (finding.refs as Record<string, unknown>[])
      : [];

  const isUnconfirmedLinks = finding.code === "UNCONFIRMED_LINKS";

  return (
    <div
      className={`finding-card ${severityClass(finding.severity)}`}
      aria-label={`Finding: ${finding.title ?? finding.code}`}
    >
      <div className="finding-card-header">
        <div className="finding-severity-label">
          {severityIcon(finding.severity)}
          <span className="finding-severity-text">
            {severityLabel(finding.severity)}
          </span>
          <code className="mono-ref finding-code">{finding.code}</code>
        </div>
        <div className="finding-tags">
          {finding.needs_human_or_legal_review && (
            <span className="finding-tag finding-tag-legal">
              <Scale size={11} />
              Needs CA or lawyer review
            </span>
          )}
          {finding.blocks_ready && (
            <span className="finding-tag finding-tag-blocks">
              <AlertTriangle size={11} />
              Blocks ready
            </span>
          )}
        </div>
      </div>

      {finding.title && (
        <h4 className="finding-title">{finding.title}</h4>
      )}

      {/* Show explanation_template as returned; fallback to message */}
      <p className="finding-message">
        {finding.explanation_template ?? finding.message}
      </p>

      {hasNumbers && (
        <ComputedNumbersTable numbers={computedNumbers} />
      )}

      <div className="finding-footer">
        {/* Source ref buttons */}
        {refs.length > 0 && (
          <div className="finding-refs">
            {refs.map((ref, i) => {
              const docId = String(ref.doc_id ?? ref.document_id ?? "");
              const page = Number(ref.page ?? ref.page_no ?? 1);
              const bbox = (ref.bbox as number[] | null | undefined) ?? null;
              const hasBbox = Boolean(bbox);
              if (!docId) return null;
              return (
                <button
                  key={i}
                  type="button"
                  className="ref-button"
                  onClick={() => onOpenEvidence?.(docId, page, bbox)}
                  title={hasBbox ? "Open evidence" : "Exact location not available"}
                >
                  <FileText size={12} />
                  <span>
                    Doc …{docId.slice(-6)} p.{page}
                    {!hasBbox && " (location not available)"}
                  </span>
                </button>
              );
            })}
          </div>
        )}

        {/* Go to Graph for UNCONFIRMED_LINKS */}
        {isUnconfirmedLinks && onGoToGraph && (
          <button
            type="button"
            className="button"
            style={{ fontSize: "0.78rem" }}
            onClick={onGoToGraph}
          >
            Go to Graph
          </button>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Severity group                                                       */
/* ------------------------------------------------------------------ */
function SeverityGroup({
  severity,
  findings,
  onGoToGraph,
  onOpenEvidence,
}: {
  severity: string;
  findings: FindingResponseItem[];
  onGoToGraph?: () => void;
  onOpenEvidence?: (docId: string, page: number, bbox?: number[] | null) => void;
}) {
  if (findings.length === 0) return null;
  return (
    <div className="findings-group">
      <div className="findings-group-heading">
        {severityIcon(severity)}
        <span>
          {severityLabel(severity)} ({findings.length})
        </span>
      </div>
      <div className="findings-group-cards">
        {findings.map((f) => (
          <FindingCard
            key={f.id}
            finding={f}
            onGoToGraph={onGoToGraph}
            onOpenEvidence={onOpenEvidence}
          />
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Main FindingsTab export                                              */
/* ------------------------------------------------------------------ */
type FindingsFilter = "all" | "conflict" | "attention" | "info" | "legal";

export function FindingsTab({
  caseId,
  linkRunResult,
  isBlocked,
  isStale,
  onRunLinking,
  runLinkingLoading,
  onJumpToReview,
  onGoToGraph,
  onOpenEvidence,
}: {
  caseId: string;
  linkRunResult: { blockers?: import("./shared").BlockerItem[] } | null;
  isBlocked: boolean;
  isStale: boolean;
  onRunLinking: () => void;
  runLinkingLoading: boolean;
  onJumpToReview?: (docName: string) => void;
  onGoToGraph?: () => void;
  onOpenEvidence?: (docId: string, page: number, bbox?: number[] | null) => void;
}) {
  const [filter, setFilter] = useState<FindingsFilter>("all");

  const { data: findingsData, isLoading, error } = useQuery<FindingsResponse>({
    queryKey: ["findings", caseId],
    queryFn: () => apiClient<FindingsResponse>(`/cases/${caseId}/findings`),
    enabled: Boolean(caseId),
  });

  const allFindings = useMemo(
    () => findingsData?.findings ?? [],
    [findingsData]
  );

  const conflictCount = useMemo(
    () => allFindings.filter((f) => f.severity.toLowerCase() === "conflict").length,
    [allFindings]
  );
  const attentionCount = useMemo(
    () => allFindings.filter((f) => f.severity.toLowerCase() === "attention").length,
    [allFindings]
  );
  const infoCount = useMemo(
    () => allFindings.filter((f) => f.severity.toLowerCase() === "info").length,
    [allFindings]
  );
  const legalCount = useMemo(
    () => allFindings.filter((f) => f.needs_human_or_legal_review).length,
    [allFindings]
  );

  const filtered = useMemo(() => {
    switch (filter) {
      case "conflict":
        return allFindings.filter((f) => f.severity.toLowerCase() === "conflict");
      case "attention":
        return allFindings.filter((f) => f.severity.toLowerCase() === "attention");
      case "info":
        return allFindings.filter((f) => f.severity.toLowerCase() === "info");
      case "legal":
        return allFindings.filter((f) => f.needs_human_or_legal_review);
      default:
        return allFindings;
    }
  }, [allFindings, filter]);

  const byConflict = useMemo(
    () => filtered.filter((f) => f.severity.toLowerCase() === "conflict"),
    [filtered]
  );
  const byAttention = useMemo(
    () => filtered.filter((f) => f.severity.toLowerCase() === "attention"),
    [filtered]
  );
  const byInfo = useMemo(
    () => filtered.filter((f) => f.severity.toLowerCase() === "info"),
    [filtered]
  );

  const summaryLine = useMemo(() => {
    const parts: string[] = [];
    if (conflictCount > 0) parts.push(`${conflictCount} conflict${conflictCount > 1 ? "s" : ""}`);
    if (attentionCount > 0) parts.push(`${attentionCount} attention`);
    if (infoCount > 0) parts.push(`${infoCount} info`);
    return parts.join(", ");
  }, [conflictCount, attentionCount, infoCount]);

  const effectiveStale = isStale || (findingsData?.stale ?? false);

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
        <p>Loading findings…</p>
      </div>
    );
  }

  if (error || !findingsData) {
    return (
      <div className="tab-pane-scroll">
        <NoDataPanel label="Run linking to compute findings." />
      </div>
    );
  }

  return (
    <div
      className={`tab-pane-scroll ${effectiveStale ? "stale-dimmed" : ""}`}
    >
      {effectiveStale && (
        <StaleBanner onRun={onRunLinking} loading={runLinkingLoading} />
      )}

      {/* Header: count chips + summary line */}
      <div className="findings-header">
        <div className="findings-count-chips">
          {conflictCount > 0 && (
            <span className="count-chip chip-conflict">
              <XCircle size={12} />
              {conflictCount} conflict{conflictCount > 1 ? "s" : ""}
            </span>
          )}
          {attentionCount > 0 && (
            <span className="count-chip chip-attention">
              <AlertCircle size={12} />
              {attentionCount} attention
            </span>
          )}
          {infoCount > 0 && (
            <span className="count-chip chip-info">
              <Info size={12} />
              {infoCount} info
            </span>
          )}
        </div>
        {summaryLine && (
          <p className="findings-summary-line">{summaryLine}</p>
        )}
      </div>

      {/* Filter chips */}
      <div className="filter-chips" role="group" aria-label="Finding filter">
        {(
          [
            { key: "all", label: "All", count: allFindings.length },
            { key: "conflict", label: "Conflict", count: conflictCount },
            { key: "attention", label: "Attention", count: attentionCount },
            { key: "info", label: "Info", count: infoCount },
            { key: "legal", label: "Needs legal review", count: legalCount },
          ] as const
        ).map((chip) => (
          <button
            key={chip.key}
            type="button"
            className={`filter-chip ${filter === chip.key ? "active" : ""}`}
            onClick={() => setFilter(chip.key)}
          >
            <span>{chip.label}</span>
            <span className="chip-count">{chip.count}</span>
          </button>
        ))}
      </div>

      {/* Grouped findings */}
      {allFindings.length === 0 ? (
        <NoDataPanel label="No findings. Run linking to detect discrepancies." />
      ) : (
        <div className="findings-list">
          <SeverityGroup
            severity="conflict"
            findings={byConflict}
            onGoToGraph={onGoToGraph}
            onOpenEvidence={onOpenEvidence}
          />
          <SeverityGroup
            severity="attention"
            findings={byAttention}
            onGoToGraph={onGoToGraph}
            onOpenEvidence={onOpenEvidence}
          />
          <SeverityGroup
            severity="info"
            findings={byInfo}
            onGoToGraph={onGoToGraph}
            onOpenEvidence={onOpenEvidence}
          />
          {filtered.length === 0 && (
            <NoDataPanel label="No findings match the current filter." />
          )}
        </div>
      )}
    </div>
  );
}
