"use client";

import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Clock,
  ExternalLink,
  Info,
  Loader2,
  RefreshCw,
  XCircle,
} from "lucide-react";
import type { BlockerItem, LedgerStatus } from "./shared";
import { ledgerStatusLabel } from "./shared";

/* ------------------------------------------------------------------ */
/* Status badge shown in the sticky header stat strip                  */
/* ------------------------------------------------------------------ */
export function LinkingStatusBadge({
  linkingStatus,
  ledgerStatus,
  stale,
}: {
  linkingStatus?: string | null;
  ledgerStatus?: string | null;
  stale?: boolean;
}) {
  // Derive the effective status to display
  const effective: LedgerStatus = stale
    ? "stale"
    : ledgerStatus ?? linkingStatus ?? "";

  const label = ledgerStatusLabel(effective);

  if (effective === "final") {
    return (
      <span className="linking-badge linking-badge-final">
        <CheckCircle2 size={12} />
        <span>{label}</span>
      </span>
    );
  }
  if (effective === "blocked") {
    return (
      <span className="linking-badge linking-badge-blocked">
        <XCircle size={12} />
        <span>{label}</span>
      </span>
    );
  }
  if (effective === "stale") {
    return (
      <span className="linking-badge linking-badge-stale">
        <Clock size={12} />
        <span>{label}</span>
      </span>
    );
  }
  if (effective === "provisional") {
    return (
      <span className="linking-badge linking-badge-provisional">
        <AlertCircle size={12} />
        <span>{label}</span>
      </span>
    );
  }
  return (
    <span className="linking-badge linking-badge-default">
      <Info size={12} />
      <span>{label || "\u2013"}</span>
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Run Linking button                                                   */
/* ------------------------------------------------------------------ */
export function RunLinkingButton({
  loading,
  onRun,
  reviewSummaryReady,
}: {
  loading: boolean;
  onRun: () => void;
  reviewSummaryReady?: boolean;
}) {
  const notReady = reviewSummaryReady === false;
  const title = notReady
    ? "Some required fields are unconfirmed. Run anyway to see blockers."
    : "Run the linking and reconciliation pipeline";

  return (
    <button
      type="button"
      className="button button-run-linking"
      onClick={onRun}
      disabled={loading}
      title={title}
      aria-label="Run linking"
    >
      {loading ? (
        <Loader2 size={14} className="spin" />
      ) : (
        <RefreshCw size={14} />
      )}
      <span>Run linking</span>
      {notReady && !loading && (
        <span className="run-linking-badge">Unconfirmed fields</span>
      )}
    </button>
  );
}

/* ------------------------------------------------------------------ */
/* Stale banner                                                         */
/* ------------------------------------------------------------------ */
export function StaleBanner({ onRun, loading }: { onRun: () => void; loading: boolean }) {
  return (
    <div className="m6-banner m6-banner-attention" role="alert">
      <AlertTriangle size={15} />
      <span>
        Facts changed since the last run. Numbers below may be out of date. Run
        linking.
      </span>
      <button
        type="button"
        className="banner-run-btn"
        onClick={onRun}
        disabled={loading}
      >
        {loading ? <Loader2 size={13} className="spin" /> : <RefreshCw size={13} />}
        <span>Run linking</span>
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Provisional banner                                                   */
/* ------------------------------------------------------------------ */
export function ProvisionalBanner({ reason }: { reason: string }) {
  return (
    <div className="m6-banner m6-banner-attention" role="alert">
      <AlertCircle size={15} />
      <div>
        <strong>Provisional: </strong>
        <span>{reason}</span>
        <span className="banner-sub"> Confirm the link to finalise.</span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Blocked panel (replaces content area when status is blocked)        */
/* ------------------------------------------------------------------ */
export function BlockedPanel({
  blockers,
  onJumpToReview,
}: {
  blockers: BlockerItem[];
  onJumpToReview?: (docName: string) => void;
}) {
  return (
    <div className="m6-blocked-panel">
      <div className="m6-blocked-header">
        <XCircle size={18} />
        <div>
          <strong>Linking blocked</strong>
          <p>
            The following required fields need confirmation before linking can
            proceed. Click a row to jump to the Review tab.
          </p>
        </div>
      </div>
      {blockers.length === 0 ? (
        <p className="m6-blocked-none">No blockers reported.</p>
      ) : (
        <table className="data-table m6-blocker-table">
          <thead>
            <tr>
              <th>Document</th>
              <th>Field</th>
              <th>Reason</th>
              <th className="action-col">Jump</th>
            </tr>
          </thead>
          <tbody>
            {blockers.map((b, i) => (
              <tr
                key={i}
                className="register-row"
                tabIndex={0}
                onClick={() => onJumpToReview?.(b.document)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") onJumpToReview?.(b.document);
                }}
              >
                <td>
                  <code className="mono-ref">{b.document}</code>
                </td>
                <td>{b.field}</td>
                <td>{b.reason}</td>
                <td className="action-col">
                  <button
                    type="button"
                    className="text-button"
                    onClick={(e) => {
                      e.stopPropagation();
                      onJumpToReview?.(b.document);
                    }}
                  >
                    <ExternalLink size={13} />
                    <span>Review</span>
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Error toast (inline)                                                 */
/* ------------------------------------------------------------------ */
export function ErrorToast({
  message,
  onDismiss,
}: {
  message: string;
  onDismiss: () => void;
}) {
  return (
    <div className="m6-error-toast" role="alert">
      <AlertTriangle size={14} />
      <span>{message}</span>
      <button
        type="button"
        className="icon-btn-compact"
        onClick={onDismiss}
        aria-label="Dismiss error"
      >
        ×
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Empty state (no data yet — before first run)                        */
/* ------------------------------------------------------------------ */
export function NoDataPanel({ label }: { label: string }) {
  return (
    <div className="m6-no-data">
      <Info size={22} />
      <p>{label}</p>
    </div>
  );
}
