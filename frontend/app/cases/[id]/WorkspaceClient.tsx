"use client";

/**
 * M6 WorkspaceClient — full 4-tab workspace.
 * Replaces the M5 single-tab Review workspace.
 *
 * Tabs: Review (existing) | Graph | Ledger | Interest | Findings
 * Shared linking state managed here, passed down to each tab.
 * TanStack Query used for Graph/Ledger/Findings data.
 */

import {
  ChangeEvent,
  KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Check,
  CheckCircle2,
  FileUp,
  History,
  Image as ImageIcon,
  Pencil,
  RotateCcw,
  X,
} from "lucide-react";
import { useParams } from "next/navigation";
import Image from "next/image";
import Link from "next/link";
import { Header } from "../../components/Header";
import { apiClient } from "@/lib/api/client";
import { displayFactValue, formatDate } from "@/lib/format";
import { getCaseCode } from "@/lib/cases";
import type { components } from "@/lib/api/schema";
import {
  LinkingStatusBadge,
  RunLinkingButton,
  ErrorToast,
} from "@/app/components/m6/LinkingPanel";
import { GraphTab } from "@/app/components/m6/GraphTab";
import { LedgerTab } from "@/app/components/m6/LedgerTab";
import { InterestTab } from "@/app/components/m6/InterestTab";
import { FindingsTab } from "@/app/components/m6/FindingsTab";
import type { LinkRunResponse, LedgerResponse } from "@/app/components/m6/shared";

type Case = components["schemas"]["CaseRead"];
type Doc = components["schemas"]["DocumentResponse"];
type Fact = components["schemas"]["FactResponse"] & {
  validation_warnings?: string[] | null;
};
type Summary = components["schemas"]["ReviewSummary"];
type Value = Record<string, unknown>;
type Audit = {
  id: string;
  actor: string;
  action: string;
  target: string;
  at: string;
  before_json: Value;
  after_json: Value;
};
type FieldFilter = "needs_review" | "all" | "not_present";
type WorkspaceTab = "review" | "graph" | "ledger" | "interest" | "findings";

const terminalDocs = new Set([
  "ready",
  "needs_review",
  "complete",
  "completed",
  "failed",
  "error",
]);
const valueOf = (fact: Fact) =>
  fact.value_json as unknown as Value | null | undefined;
const factSort = (a: Fact, b: Fact) =>
  a.document_id.localeCompare(b.document_id) ||
  (a.group ?? "").localeCompare(b.group ?? "") ||
  a.page_no - b.page_no;

function statusLabel(status: string) {
  return status.replace("_", " ");
}

export default function CaseWorkspace() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();

  /* ---------------------------------------------------------------- */
  /* Workspace state                                                   */
  /* ---------------------------------------------------------------- */
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("review");
  const [caseData, setCaseData] = useState<Case | null>(null);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [facts, setFacts] = useState<Fact[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [audit, setAudit] = useState<Audit[]>([]);
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [selectedFact, setSelectedFact] = useState<Fact | null>(null);
  const [fieldFilter, setFieldFilter] = useState<FieldFilter>("needs_review");
  const [expandedNotPresent, setExpandedNotPresent] = useState<
    Record<string, boolean>
  >({});
  const [editing, setEditing] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [reviewer, setReviewer] = useState(() =>
    typeof window === "undefined"
      ? "Reviewer"
      : localStorage.getItem("claimgraph-reviewer") ?? "Reviewer",
  );
  const [showAudit, setShowAudit] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState<Record<string, string>>(
    {},
  );
  const [fitWidth, setFitWidth] = useState(true);

  /* Linking state */
  const [linkRunResult, setLinkRunResult] = useState<LinkRunResponse | null>(null);
  const [linkingLoading, setLinkingLoading] = useState(false);
  const [linkingError, setLinkingError] = useState<string | null>(null);

  /* Evidence drawer override for M6 tabs */
  const [m6EvidenceDoc, setM6EvidenceDoc] = useState<{
    docId: string;
    page: number;
    bbox?: number[] | null;
  } | null>(null);

  /* Query ledger data for case */
  const { data: ledgerData } = useQuery<LedgerResponse>({
    queryKey: ["ledger", id],
    queryFn: () => apiClient<LedgerResponse>(`/cases/${id}/ledger`),
    enabled: Boolean(id),
  });

  /* ---------------------------------------------------------------- */
  /* Derived linking state                                              */
  /* ---------------------------------------------------------------- */
  const displayLinkingStatus =
    linkRunResult?.linking_status ?? ledgerData?.ledger_status ?? null;
  const isBlocked =
    displayLinkingStatus === "blocked" ||
    (linkRunResult?.blockers ?? []).length > 0;
  const isStale = linkRunResult?.stale ?? ledgerData?.stale ?? false;
  const isProvisional = displayLinkingStatus === "provisional";
  const provisionalReason =
    (linkRunResult as unknown as Record<string, unknown>)?.provisional_reason as
      | string
      | undefined ?? ledgerData?.provisional_reason ?? undefined;

  /* ---------------------------------------------------------------- */
  /* Load case data                                                     */
  /* ---------------------------------------------------------------- */
  const load = useCallback(async () => {
    const [nextCase, nextDocs, nextFacts, nextSummary] = await Promise.all([
      apiClient<Case>(`/cases/${id}`),
      apiClient<Doc[]>(`/cases/${id}/documents`),
      apiClient<Fact[]>(`/cases/${id}/facts`),
      apiClient<Summary>(`/cases/${id}/review-summary`),
    ]);
    const sortedFacts = nextFacts.sort(factSort);
    setCaseData(nextCase);
    setDocs(nextDocs);
    setFacts(sortedFacts);
    setSummary(nextSummary);

    setSelectedFact((current) => {
      if (current) {
        const found = sortedFacts.find((f) => f.id === current.id);
        if (found) return found;
      }
      return (
        sortedFacts.find((f) => f.status === "needs_review") ??
        sortedFacts[0] ??
        null
      );
    });
  }, [id]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      load().catch(() => setError("This case could not be loaded."));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    if (!docs.some((doc) => !terminalDocs.has(doc.status))) return;
    const timer = window.setInterval(() => {
      load().catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [docs, load]);

  /* ---------------------------------------------------------------- */
  /* Run linking                                                        */
  /* ---------------------------------------------------------------- */
  const runLinking = useCallback(async () => {
    setLinkingLoading(true);
    setLinkingError(null);
    try {
      const result = await apiClient<LinkRunResponse>(
        `/cases/${id}/link/run`,
        {
          method: "POST",
          headers: { "X-Reviewer": reviewer },
        },
      );
      setLinkRunResult(result);
      // Invalidate TanStack Query caches for graph/ledger/findings
      await qc.invalidateQueries({ queryKey: ["graph", id] });
      await qc.invalidateQueries({ queryKey: ["ledger", id] });
      await qc.invalidateQueries({ queryKey: ["findings", id] });
    } catch (e) {
      setLinkingError(
        e instanceof Error ? e.message : "Linking failed. Please try again.",
      );
    } finally {
      setLinkingLoading(false);
    }
  }, [id, reviewer, qc]);

  // Initial link check on workspace load to determine blockers / provisional state
  useEffect(() => {
    let mounted = true;
    apiClient<LinkRunResponse>(`/cases/${id}/link/run`, {
      method: "POST",
      headers: { "X-Reviewer": reviewer },
    })
      .then((res) => {
        if (mounted) setLinkRunResult(res);
      })
      .catch(() => undefined);
    return () => {
      mounted = false;
    };
  }, [id, reviewer]);

  /* ---------------------------------------------------------------- */
  /* Review tab actions (unchanged from M5)                            */
  /* ---------------------------------------------------------------- */
  const advanceToNext = (
    currentFact: Fact,
    allFacts: Fact[],
    targetDocId: string | null,
  ) => {
    const candidateList = targetDocId
      ? allFacts.filter((f) => f.document_id === targetDocId)
      : allFacts;

    const currentIndex = candidateList.findIndex((f) => f.id === currentFact.id);
    const nextInDoc = candidateList
      .slice(currentIndex + 1)
      .find((f) => f.status === "needs_review");

    if (nextInDoc) return nextInDoc;

    const prevInDoc = candidateList
      .slice(0, currentIndex)
      .find((f) => f.status === "needs_review");

    if (prevInDoc) return prevInDoc;

    const anyNext = allFacts.find(
      (f) => f.status === "needs_review" && f.id !== currentFact.id,
    );
    return anyNext ?? currentFact;
  };

  const update = async (fact: Fact, action: string, value?: Value) => {
    setBusy(true);
    setError(null);
    try {
      const result = await apiClient<Fact>(`/facts/${fact.id}`, {
        method: "PATCH",
        headers: { "X-Reviewer": reviewer },
        body: JSON.stringify({ action, value }),
      });

      const nextFacts = facts
        .map((item) => (item.id === result.id ? result : item))
        .sort(factSort);

      setFacts(nextFacts);

      const nextFact = advanceToNext(fact, nextFacts, selectedDocId);
      setSelectedFact(nextFact);

      await load();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "The review action failed.",
      );
    } finally {
      setBusy(false);
    }
  };

  const saveEdit = (fact: Fact) => {
    const current = valueOf(fact) ?? {};
    const next: Value = { ...current, value: editValue };
    if (/amount|total|rate|price|qty|quantity/i.test(fact.field)) {
      const number = Number(editValue.replace(/,/g, ""));
      if (!Number.isNaN(number)) next.value = number;
    }
    void update(fact, "edit", next);
    setEditing(null);
  };

  const confirmReviewer = (event: ChangeEvent<HTMLInputElement>) => {
    setReviewer(event.target.value);
    localStorage.setItem("claimgraph-reviewer", event.target.value);
  };

  const process = async () => {
    if (docs.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      await apiClient(`/cases/${id}/process`, { method: "POST" });
      await load();
    } catch {
      setError("Documents could not be processed.");
    } finally {
      setBusy(false);
    }
  };

  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    if (!event.target.files?.length) return;
    const selected = Array.from(event.target.files);
    setUploadProgress(
      Object.fromEntries(selected.map((file) => [file.name, "Uploading"])),
    );
    const form = new FormData();
    selected.forEach((file) => form.append("files", file));
    setBusy(true);
    try {
      await apiClient(`/cases/${id}/documents`, {
        method: "POST",
        body: form,
      });
      await load();
    } catch {
      setError("Upload failed. Please try again.");
    } finally {
      setBusy(false);
      event.target.value = "";
    }
    setUploadProgress(
      Object.fromEntries(selected.map((file) => [file.name, "Stored"])),
    );
  };

  const uploadFiles = (files: FileList | File[]) => {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    const transfer = new DataTransfer();
    Array.from(files).forEach((file) => transfer.items.add(file));
    input.files = transfer.files;
    const event = { target: input } as ChangeEvent<HTMLInputElement>;
    void upload(event);
  };

  const bulk = async (doc: Doc) => {
    setBusy(true);
    try {
      await apiClient(`/documents/${doc.id}/facts/confirm-auto`, {
        method: "POST",
        headers: { "X-Reviewer": reviewer },
      });
      await load();
    } catch {
      setError("Bulk confirmation failed.");
    } finally {
      setBusy(false);
    }
  };

  const openAudit = async () => {
    setShowAudit(!showAudit);
    if (!showAudit) setAudit(await apiClient<Audit[]>(`/cases/${id}/audit-log`));
  };

  const handleSelectDocument = (docId: string | null) => {
    setSelectedDocId(docId);
    if (docId) {
      const docFacts = facts.filter((f) => f.document_id === docId);
      const firstNeedsReview = docFacts.find((f) => f.status === "needs_review");
      setSelectedFact(firstNeedsReview ?? docFacts[0] ?? null);
    } else {
      const firstNeedsReview = facts.find((f) => f.status === "needs_review");
      setSelectedFact(firstNeedsReview ?? facts[0] ?? null);
    }
  };

  const nextIssue = () => {
    const issue = facts.find((fact) => fact.status === "needs_review");
    if (issue) {
      setSelectedFact(issue);
      setSelectedDocId(issue.document_id);
    }
  };

  const toggleNotPresent = (docId: string) => {
    setExpandedNotPresent((prev) => ({
      ...prev,
      [docId]: !prev[docId],
    }));
  };

  const displayedDocs = useMemo(() => {
    if (selectedDocId) {
      return docs.filter((d) => d.id === selectedDocId);
    }
    return docs;
  }, [docs, selectedDocId]);

  const visibleFacts = useMemo(() => {
    const list: Fact[] = [];
    displayedDocs.forEach((doc) => {
      const docFacts = facts.filter((f) => f.document_id === doc.id);
      if (fieldFilter === "needs_review") {
        list.push(...docFacts.filter((f) => f.status === "needs_review"));
        if (expandedNotPresent[doc.id]) {
          list.push(...docFacts.filter((f) => f.status === "not_present"));
        }
      } else if (fieldFilter === "all") {
        list.push(...docFacts.filter((f) => f.status !== "not_present"));
        if (expandedNotPresent[doc.id]) {
          list.push(...docFacts.filter((f) => f.status === "not_present"));
        }
      } else if (fieldFilter === "not_present") {
        list.push(...docFacts.filter((f) => f.status === "not_present"));
      }
    });
    return list;
  }, [displayedDocs, facts, fieldFilter, expandedNotPresent]);

  const keyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    // Close dialogs on Escape
    if (event.key === "Escape") {
      if (m6EvidenceDoc) {
        setM6EvidenceDoc(null);
        return;
      }
      if (showAudit) {
        setShowAudit(false);
        return;
      }
    }

    if (activeTab !== "review") return;
    if (editing) return;
    if (
      event.target instanceof HTMLInputElement ||
      event.target instanceof HTMLTextAreaElement
    ) {
      return;
    }

    const index = selectedFact
      ? visibleFacts.findIndex((f) => f.id === selectedFact.id)
      : -1;

    if (event.key === "ArrowDown" || event.key.toLowerCase() === "j") {
      event.preventDefault();
      const next = visibleFacts[Math.min(index + 1, visibleFacts.length - 1)];
      if (next) setSelectedFact(next);
    } else if (event.key === "ArrowUp" || event.key.toLowerCase() === "k") {
      event.preventDefault();
      const prev = visibleFacts[Math.max(index - 1, 0)];
      if (prev) setSelectedFact(prev);
    } else if (event.key === "Enter" && selectedFact) {
      event.preventDefault();
      if (selectedFact.status === "needs_review") {
        void update(selectedFact, "confirm");
      }
    } else if (event.key.toLowerCase() === "e" && selectedFact) {
      event.preventDefault();
      setEditing(selectedFact.id);
      setEditValue(displayFactValue(valueOf(selectedFact), selectedFact.field));
    } else if (event.key.toLowerCase() === "n" && selectedFact) {
      event.preventDefault();
      if (selectedFact.status !== "not_present") {
        void update(selectedFact, "mark_not_present");
      }
    }
  };

  const activeDoc = useMemo(() => {
    if (selectedDocId) {
      return docs.find((d) => d.id === selectedDocId) ?? null;
    }
    if (selectedFact) {
      return docs.find((d) => d.id === selectedFact.document_id) ?? null;
    }
    return docs[0] ?? null;
  }, [docs, selectedDocId, selectedFact]);

  const activeDocAutoCount = useMemo(() => {
    if (!activeDoc) return 0;
    return facts.filter(
      (f) => f.document_id === activeDoc.id && f.status === "auto",
    ).length;
  }, [facts, activeDoc]);

  const caseCode = caseData ? getCaseCode(caseData) : "CASE";

  /* ---------------------------------------------------------------- */
  /* Jump to review tab (from blocker panel)                            */
  /* ---------------------------------------------------------------- */
  const handleJumpToReview = useCallback(
    (docName: string) => {
      setActiveTab("review");
      const doc = docs.find((d) => d.filename.includes(docName) || d.id === docName);
      if (doc) {
        setSelectedDocId(doc.id);
        const docFacts = facts.filter((f) => f.document_id === doc.id);
        const firstNeedsReview = docFacts.find((f) => f.status === "needs_review");
        setSelectedFact(firstNeedsReview ?? docFacts[0] ?? null);
      }
    },
    [docs, facts],
  );

  /* ---------------------------------------------------------------- */
  /* Open evidence from M6 tabs                                        */
  /* ---------------------------------------------------------------- */
  const handleOpenEvidence = useCallback(
    (docId: string, page: number, bbox?: number[] | null) => {
      setM6EvidenceDoc({ docId, page, bbox: bbox ?? null });
    },
    [],
  );

  /* Global Escape key listener to close evidence drawer and dialogs */
  useEffect(() => {
    const handleGlobalKeyDown = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") {
        if (m6EvidenceDoc) {
          setM6EvidenceDoc(null);
        } else if (showAudit) {
          setShowAudit(false);
        }
      }
    };
    window.addEventListener("keydown", handleGlobalKeyDown);
    return () => window.removeEventListener("keydown", handleGlobalKeyDown);
  }, [m6EvidenceDoc, showAudit]);

  const displayLedgerStatus =
    (linkRunResult as unknown as Record<string, unknown>)?.ledger_status as
      | string
      | null
      | undefined ?? displayLinkingStatus;

  return (
    <div
      className="workspace-container"
      tabIndex={0}
      onKeyDown={keyboard}
      aria-label="Case review workspace"
    >
      <Header />

      {/* Sticky Header */}
      <header className="workspace-pinned-header">
        <div className="workspace-header-bar">
          <div className="case-heading">
            <Link href="/" className="eyebrow" style={{ textDecoration: "none" }}>
              ← Cases
            </Link>
            <span className="case-code" style={{ fontSize: "0.85rem" }}>
              {caseCode}
            </span>
            <h1>{caseData?.title ?? "Loading case…"}</h1>
          </div>
          <div className="workspace-header-actions">
            <label className="reviewer-input-wrap">
              <span>Reviewer</span>
              <input
                value={reviewer}
                onChange={confirmReviewer}
                placeholder="Reviewer name"
              />
            </label>
            <RunLinkingButton
              loading={linkingLoading}
              onRun={() => void runLinking()}
              reviewSummaryReady={summary?.ready_for_linking}
            />
            <button
              type="button"
              className="button"
              onClick={() => void openAudit()}
              style={{ padding: "6px 10px", fontSize: "0.78rem" }}
            >
              <History size={14} />
              <span>Audit log</span>
            </button>
          </div>
        </div>

        {/* Linking error toast */}
        {linkingError && (
          <div style={{ margin: "4px 24px 0" }}>
            <ErrorToast
              message={linkingError}
              onDismiss={() => setLinkingError(null)}
            />
          </div>
        )}

        {/* Review error */}
        {error && (
          <div
            className="alert alert-error"
            role="alert"
            style={{ margin: "4px 24px 8px" }}
          >
            {error}
          </div>
        )}

        {/* 5 flat stat cells (4 review + 1 linking) */}
        <div className="workspace-stat-strip" style={{ gridTemplateColumns: "repeat(5, 1fr)" }}>
          <div className="stat-cell">
            <span className="stat-label">Needs review</span>
            <strong
              className="stat-value"
              style={{ color: "var(--color-attention)" }}
            >
              {summary?.status_counts.needs_review ?? 0}
            </strong>
          </div>
          <div className="stat-cell">
            <span className="stat-label">Confirmed</span>
            <strong
              className="stat-value"
              style={{ color: "var(--color-verified)" }}
            >
              {(summary?.status_counts.confirmed ?? 0) +
                (summary?.status_counts.edited ?? 0)}
            </strong>
          </div>
          <div className="stat-cell">
            <span className="stat-label">Auto</span>
            <strong className="stat-value">
              {summary?.status_counts.auto ?? 0}
            </strong>
          </div>
          <div className="stat-cell">
            <span className="stat-label">Review ready</span>
            <strong
              className="stat-value"
              style={{
                color: summary?.ready_for_linking
                  ? "var(--color-verified)"
                  : "var(--color-conflict)",
              }}
            >
              {summary?.ready_for_linking ? "Yes" : "No"}
            </strong>
          </div>
          <div className="stat-cell">
            <span className="stat-label">Linking</span>
            <strong className="stat-value">
              <LinkingStatusBadge
                linkingStatus={displayLinkingStatus}
                ledgerStatus={displayLedgerStatus}
                stale={isStale}
              />
            </strong>
          </div>
        </div>

        {/* Tab Bar */}
        <div className="workspace-tab-bar">
          <div style={{ display: "flex", gap: "6px" }}>
            {(
              [
                { key: "review", label: "Review" },
                { key: "graph", label: "Graph" },
                { key: "ledger", label: "Ledger" },
                { key: "interest", label: "Interest" },
                { key: "findings", label: "Findings" },
              ] as const
            ).map((tab) => (
              <button
                key={tab.key}
                type="button"
                className={`tab ${activeTab === tab.key ? "active" : ""}`}
                onClick={() => setActiveTab(tab.key)}
                tabIndex={0}
                data-active={activeTab === tab.key}
              >
                {tab.label}
              </button>
            ))}
          </div>
          {activeTab === "review" && (
            <div className="shortcut-hint" style={{ margin: 0 }}>
              Keyboard: Up/Down or j/k select · Enter confirm · E edit · N not
              present
            </div>
          )}
        </div>
      </header>

      {/* ============================================================ */}
      {/* Tab content                                                   */}
      {/* ============================================================ */}

      {/* REVIEW TAB — three-pane layout (unchanged from M5) */}
      {activeTab === "review" && (
        <div className="workspace-three-panes">
          {/* Left Rail: Documents */}
          <aside className="doc-rail-pane">
            <div className="doc-rail-top">
              <h2
                style={{
                  fontSize: "0.82rem",
                  textTransform: "uppercase",
                  color: "var(--color-slate)",
                  letterSpacing: "0.05em",
                }}
              >
                Documents ({docs.length})
              </h2>
              <label
                className="upload-label"
                style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}
              >
                <FileUp size={13} />
                <span>Upload</span>
                <input type="file" multiple onChange={upload} />
              </label>
            </div>

            <div
              className="drop-zone"
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                uploadFiles(e.dataTransfer.files);
              }}
            >
              <FileUp size={14} />
              <span>Drop files to add</span>
            </div>

            {Object.entries(uploadProgress).map(([name, status]) => (
              <p className="upload-progress" key={name}>
                {name}: {status}
              </p>
            ))}

            <div
              className={`doc-rail-row ${selectedDocId === null ? "active" : ""}`}
              onClick={() => handleSelectDocument(null)}
              title="Show all documents"
            >
              <div className="doc-rail-title-row">
                <span className="doc-kind-badge">ALL</span>
                <span className="doc-filename-text">
                  All documents ({docs.length})
                </span>
              </div>
              <div className="doc-rail-meta-row">
                <span className="text-slate text-xs">
                  {summary?.status_counts.needs_review ?? 0} needs review
                </span>
              </div>
            </div>

            {docs.map((doc) => {
              const docFacts = facts.filter((f) => f.document_id === doc.id);
              const needsReviewCount = docFacts.filter(
                (f) => f.status === "needs_review",
              ).length;
              const isSelected = selectedDocId === doc.id;
              return (
                <div
                  key={doc.id}
                  className={`doc-rail-row ${isSelected ? "active" : ""}`}
                  onClick={() => handleSelectDocument(doc.id)}
                  title={doc.filename}
                >
                  <div className="doc-rail-title-row">
                    <span className="doc-kind-badge">{doc.kind}</span>
                    <span className="doc-filename-text" title={doc.filename}>
                      {doc.filename}
                    </span>
                  </div>
                  <div className="doc-rail-meta-row">
                    <span
                      className={`status status-${doc.status === "ready" ? "verified" : doc.status === "needs_review" ? "attention" : "slate"}`}
                    >
                      {doc.status === "ready" ? (
                        <CheckCircle2 size={12} />
                      ) : (
                        <AlertCircle size={12} />
                      )}
                      <span>{doc.status.replace("_", " ")}</span>
                    </span>
                    {needsReviewCount > 0 ? (
                      <span className="needs-review-pill">
                        {needsReviewCount} review
                      </span>
                    ) : (
                      <span className="text-slate text-xs">0 review</span>
                    )}
                  </div>
                </div>
              );
            })}

            <button
              type="button"
              className="button button-dark full-width"
              onClick={process}
              disabled={busy || docs.length === 0}
              style={{ marginTop: "auto", fontSize: "0.78rem" }}
            >
              {docs.length > 0 &&
              docs.every((doc) => terminalDocs.has(doc.status))
                ? "Reprocess documents"
                : "Process documents"}
            </button>
          </aside>

          {/* Centre Pane: Fields */}
          <section className="centre-fields-pane">
            <div className="centre-pane-toolbar">
              <div
                className="segmented-control"
                role="group"
                aria-label="Field filter"
              >
                <button
                  type="button"
                  className={fieldFilter === "needs_review" ? "active" : ""}
                  onClick={() => setFieldFilter("needs_review")}
                >
                  Needs review
                </button>
                <button
                  type="button"
                  className={fieldFilter === "all" ? "active" : ""}
                  onClick={() => setFieldFilter("all")}
                >
                  All
                </button>
                <button
                  type="button"
                  className={fieldFilter === "not_present" ? "active" : ""}
                  onClick={() => setFieldFilter("not_present")}
                >
                  Not present
                </button>
              </div>

              <div style={{ fontSize: "0.76rem", color: "var(--color-slate)" }}>
                {selectedDocId
                  ? `${displayedDocs[0]?.kind ?? "Document"} · ${displayedDocs[0]?.filename ?? ""}`
                  : `Showing all ${docs.length} documents`}
              </div>
            </div>

            <div className="centre-pane-scroll">
              {displayedDocs.map((doc) => {
                const docFacts = facts.filter((f) => f.document_id === doc.id);
                const activeFacts = docFacts.filter((f) =>
                  fieldFilter === "needs_review"
                    ? f.status === "needs_review"
                    : fieldFilter === "all"
                      ? f.status !== "not_present"
                      : f.status === "not_present",
                );
                const notPresentFacts = docFacts.filter(
                  (f) => f.status === "not_present",
                );
                const isNotPresentExpanded = Boolean(expandedNotPresent[doc.id]);

                if (
                  activeFacts.length === 0 &&
                  (fieldFilter === "not_present" || notPresentFacts.length === 0)
                ) {
                  if (fieldFilter === "needs_review") {
                    return (
                      <div key={doc.id} className="fact-doc-section">
                        <div className="fact-doc-header">
                          <div className="doc-info">
                            <span className="doc-kind-badge">{doc.kind}</span>
                            <span className="filename-sub">{doc.filename}</span>
                          </div>
                        </div>
                        <div
                          style={{
                            padding: "8px 12px",
                            fontSize: "0.76rem",
                            color: "var(--color-verified)",
                            display: "flex",
                            alignItems: "center",
                            gap: "6px",
                          }}
                        >
                          <CheckCircle2 size={14} />
                          <span>All fields reviewed in this document.</span>
                        </div>
                        {notPresentFacts.length > 0 && (
                          <div className="not-present-bar">
                            <span>
                              {notPresentFacts.length} fields not present
                            </span>
                            <button
                              type="button"
                              className="text-button"
                              onClick={() => toggleNotPresent(doc.id)}
                            >
                              {isNotPresentExpanded ? "Hide" : "Show"}
                            </button>
                          </div>
                        )}
                        {isNotPresentExpanded &&
                          notPresentFacts.map((fact) => (
                            <FactCompactRow
                              key={fact.id}
                              fact={fact}
                              selected={selectedFact?.id === fact.id}
                              editing={editing === fact.id}
                              editValue={editValue}
                              onSelect={() => {
                                setSelectedFact(fact);
                                setEditValue(
                                  displayFactValue(valueOf(fact), fact.field),
                                );
                              }}
                              onEdit={setEditValue}
                              onSave={() => saveEdit(fact)}
                              onCancel={() => setEditing(null)}
                              onStartEdit={() => setEditing(fact.id)}
                              onAction={(action) => void update(fact, action)}
                            />
                          ))}
                      </div>
                    );
                  }
                  return null;
                }

                return (
                  <div key={doc.id} className="fact-doc-section">
                    <div className="fact-doc-header">
                      <div className="doc-info">
                        <span className="doc-kind-badge">{doc.kind}</span>
                        <span className="filename-sub">{doc.filename}</span>
                      </div>
                      <span
                        style={{
                          fontSize: "0.72rem",
                          color: "var(--color-slate)",
                        }}
                      >
                        {activeFacts.length} {fieldFilter.replace("_", " ")}{" "}
                        fields
                      </span>
                    </div>

                    {activeFacts.map((fact) => (
                      <FactCompactRow
                        key={fact.id}
                        fact={fact}
                        selected={selectedFact?.id === fact.id}
                        editing={editing === fact.id}
                        editValue={editValue}
                        onSelect={() => {
                          setSelectedFact(fact);
                          setEditValue(
                            displayFactValue(valueOf(fact), fact.field),
                          );
                        }}
                        onEdit={setEditValue}
                        onSave={() => saveEdit(fact)}
                        onCancel={() => setEditing(null)}
                        onStartEdit={() => setEditing(fact.id)}
                        onAction={(action) => void update(fact, action)}
                      />
                    ))}

                    {fieldFilter !== "not_present" && notPresentFacts.length > 0 && (
                      <div className="not-present-bar">
                        <span>{notPresentFacts.length} fields not present</span>
                        <button
                          type="button"
                          className="text-button"
                          onClick={() => toggleNotPresent(doc.id)}
                        >
                          {isNotPresentExpanded ? "Hide" : "Show"}
                        </button>
                      </div>
                    )}

                    {fieldFilter !== "not_present" &&
                      isNotPresentExpanded &&
                      notPresentFacts.map((fact) => (
                        <FactCompactRow
                          key={fact.id}
                          fact={fact}
                          selected={selectedFact?.id === fact.id}
                          editing={editing === fact.id}
                          editValue={editValue}
                          onSelect={() => {
                            setSelectedFact(fact);
                            setEditValue(
                              displayFactValue(valueOf(fact), fact.field),
                            );
                          }}
                          onEdit={setEditValue}
                          onSave={() => saveEdit(fact)}
                          onCancel={() => setEditing(null)}
                          onStartEdit={() => setEditing(fact.id)}
                          onAction={(action) => void update(fact, action)}
                        />
                      ))}
                  </div>
                );
              })}
            </div>

            <div className="centre-pane-action-bar">
              <div>
                {activeDoc && (
                  <button
                    type="button"
                    className="button button-dark"
                    onClick={() => void bulk(activeDoc)}
                    disabled={busy || activeDocAutoCount === 0}
                    title={`Confirm ${activeDocAutoCount} auto fields in ${activeDoc.filename}`}
                    style={{ fontSize: "0.78rem" }}
                  >
                    Confirm all auto ({activeDocAutoCount})
                  </button>
                )}
              </div>
              <div>
                <button
                  type="button"
                  className="button"
                  onClick={nextIssue}
                  disabled={
                    busy || (summary?.status_counts.needs_review ?? 0) === 0
                  }
                  style={{ fontSize: "0.78rem" }}
                >
                  Next issue
                </button>
              </div>
            </div>
          </section>

          {/* Right Pane: Evidence Drawer */}
          <EvidenceDrawer
            key={selectedFact?.id ?? "empty"}
            fact={selectedFact}
            maxPages={
              docs.find((doc) => doc.id === selectedFact?.document_id)
                ?.pages ?? 1
            }
            fitWidth={fitWidth}
            setFitWidth={setFitWidth}
          />
        </div>
      )}

      {/* GRAPH TAB */}
      {activeTab === "graph" && (
        <div className="workspace-m6-pane">
          <GraphTab
            caseId={id}
            linkRunResult={linkRunResult}
            isBlocked={isBlocked}
            isStale={isStale}
            isProvisional={isProvisional}
            provisionalReason={provisionalReason}
            onRunLinking={() => void runLinking()}
            runLinkingLoading={linkingLoading}
            onJumpToReview={handleJumpToReview}
            onOpenEvidence={handleOpenEvidence}
          />
        </div>
      )}

      {/* LEDGER TAB */}
      {activeTab === "ledger" && (
        <div className="workspace-m6-pane">
          <LedgerTab
            caseId={id}
            linkRunResult={linkRunResult}
            isBlocked={isBlocked}
            isStale={isStale}
            isProvisional={isProvisional}
            provisionalReason={provisionalReason}
            onRunLinking={() => void runLinking()}
            runLinkingLoading={linkingLoading}
            onJumpToReview={handleJumpToReview}
            onOpenEvidence={handleOpenEvidence}
            facts={facts}
          />
        </div>
      )}

      {/* INTEREST TAB */}
      {activeTab === "interest" && (
        <div className="workspace-m6-pane">
          <InterestTab
            caseId={id}
            linkRunResult={linkRunResult}
            isBlocked={isBlocked}
            isStale={isStale}
            isProvisional={isProvisional}
            provisionalReason={provisionalReason}
            onRunLinking={() => void runLinking()}
            runLinkingLoading={linkingLoading}
            onJumpToReview={handleJumpToReview}
            onGoToFindings={() => setActiveTab("findings")}
          />
        </div>
      )}

      {/* FINDINGS TAB */}
      {activeTab === "findings" && (
        <div className="workspace-m6-pane">
          <FindingsTab
            caseId={id}
            linkRunResult={linkRunResult}
            isBlocked={isBlocked}
            isStale={isStale}
            onRunLinking={() => void runLinking()}
            runLinkingLoading={linkingLoading}
            onJumpToReview={handleJumpToReview}
            onGoToGraph={() => setActiveTab("graph")}
            onOpenEvidence={handleOpenEvidence}
          />
        </div>
      )}

      {/* ============================================================ */}
      {/* M6 evidence overlay (opened from Graph/Ledger/Findings)      */}
      {/* ============================================================ */}
      {m6EvidenceDoc && (
        <div className="m6-evidence-overlay">
          <div className="m6-evidence-overlay-panel">
            <div className="section-heading" style={{ padding: "12px 16px" }}>
              <h2>Evidence</h2>
              <button
                type="button"
                className="icon-btn-compact"
                onClick={() => setM6EvidenceDoc(null)}
                aria-label="Close evidence"
              >
                <X size={15} />
              </button>
            </div>
            <M6EvidenceView
              docId={m6EvidenceDoc.docId}
              page={m6EvidenceDoc.page}
              bbox={m6EvidenceDoc.bbox}
              docs={docs}
            />
          </div>
        </div>
      )}

      {/* Audit panel */}
      {showAudit && (
        <aside className="audit-panel">
          <div className="section-heading">
            <h2>Audit log</h2>
            <button
              type="button"
              className="icon-button"
              onClick={() => setShowAudit(false)}
              aria-label="Close audit log"
            >
              <X size={17} />
            </button>
          </div>
          {audit.map((item) => (
            <div className="audit-row" key={item.id}>
              <strong>{item.action}</strong>
              <span>
                {item.actor} · {formatDate(item.at)}
              </span>
              <code>{item.target.slice(0, 8)}</code>
            </div>
          ))}
        </aside>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* FactCompactRow (unchanged from M5)                                  */
/* ------------------------------------------------------------------ */
function FactCompactRow({
  fact,
  selected,
  editing,
  editValue,
  onSelect,
  onEdit,
  onSave,
  onCancel,
  onStartEdit,
  onAction,
}: {
  fact: Fact;
  selected: boolean;
  editing: boolean;
  editValue: string;
  onSelect: () => void;
  onEdit: (value: string) => void;
  onSave: () => void;
  onCancel: () => void;
  onStartEdit: () => void;
  onAction: (action: string) => void;
}) {
  const valueOf = (fact: Fact) =>
    fact.value_json as unknown as Record<string, unknown> | null | undefined;

  const chipIcon =
    fact.status === "needs_review" ? (
      <AlertCircle size={11} />
    ) : fact.status === "not_present" ? (
      <X size={11} />
    ) : (
      <Check size={11} />
    );

  const displayVal = displayFactValue(valueOf(fact), fact.field);

  return (
    <div
      className={`fact-compact-row ${selected ? "selected" : ""}`}
      onClick={onSelect}
      title={`${fact.group ?? "Other"} · Page ${fact.page_no}`}
    >
      <div className="fact-label-cell">
        <span className="fact-label-name" title={fact.label ?? fact.field}>
          {fact.label ?? fact.field}
        </span>
        <span
          className="fact-page-badge"
          title={`${fact.group ?? "Other"} · Page ${fact.page_no}`}
        >
          p.{fact.page_no}
        </span>
      </div>

      <div className="fact-value-cell">
        {editing ? (
          <input
            autoFocus
            value={editValue}
            onChange={(e) => onEdit(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") onSave();
              if (e.key === "Escape") onCancel();
            }}
            onClick={(e) => e.stopPropagation()}
            className="compact-input"
          />
        ) : (
          <span className="fact-val-text" title={displayVal}>
            {displayVal}
          </span>
        )}
      </div>

      <div>
        <span className={`status-chip chip-${fact.status}`}>
          {chipIcon}
          <span>{statusLabel(fact.status)}</span>
        </span>
      </div>

      <div
        style={{ display: "flex", gap: "3px" }}
        onClick={(e) => e.stopPropagation()}
      >
        {fact.status === "needs_review" && (
          <button
            type="button"
            className="icon-btn-compact"
            title="Confirm (Enter)"
            onClick={() => onAction("confirm")}
            aria-label="Confirm"
          >
            <Check size={13} />
          </button>
        )}
        {fact.status === "needs_review" && (
          <button
            type="button"
            className="icon-btn-compact"
            title="Edit (E)"
            onClick={onStartEdit}
            aria-label="Edit"
          >
            <Pencil size={13} />
          </button>
        )}
        {fact.status !== "not_present" && (
          <button
            type="button"
            className="icon-btn-compact"
            title="Mark not present (N)"
            onClick={() => onAction("mark_not_present")}
            aria-label="Mark not present"
          >
            <X size={13} />
          </button>
        )}
        {["confirmed", "edited", "not_present"].includes(fact.status) && (
          <button
            type="button"
            className="icon-btn-compact"
            title="Reopen"
            onClick={() => onAction("reopen")}
            aria-label="Reopen"
          >
            <RotateCcw size={13} />
          </button>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* EvidenceDrawer (unchanged from M5)                                  */
/* ------------------------------------------------------------------ */
function EvidenceDrawer({
  fact,
  maxPages,
  fitWidth,
  setFitWidth,
}: {
  fact: Fact | null;
  maxPages: number;
  fitWidth: boolean;
  setFitWidth: (value: boolean) => void;
}) {
  const [page, setPage] = useState(fact?.page_no ?? 1);
  const [imageError, setImageError] = useState(false);
  const bboxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (fact?.bbox && bboxRef.current) {
      bboxRef.current.scrollIntoView({
        behavior: "smooth",
        block: "center",
        inline: "nearest",
      });
    }
  }, [fact?.bbox, page]);

  if (!fact) {
    return (
      <aside className="evidence-pane empty-drawer">
        <ImageIcon size={24} />
        <p>Select a fact to inspect its evidence.</p>
      </aside>
    );
  }

  const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const image = `${base}/documents/${fact.document_id}/pages/${page}/image`;
  const raw = fact.value_json as unknown as Record<string, unknown> | null;

  return (
    <aside className="evidence-pane">
      <div className="section-heading">
        <div>
          <h2>Evidence</h2>
          <span>
            Page {page} of {maxPages}
          </span>
        </div>
        {!imageError && (
          <a
            href={image}
            target="_blank"
            rel="noreferrer"
            className="text-button"
          >
            Open image
          </a>
        )}
      </div>

      <div className="evidence-controls">
        <button
          type="button"
          className="text-button"
          disabled={page <= 1}
          onClick={() => {
            setPage(page - 1);
            setImageError(false);
          }}
        >
          Previous
        </button>
        <button
          type="button"
          className="text-button"
          disabled={page >= maxPages}
          onClick={() => {
            setPage(page + 1);
            setImageError(false);
          }}
        >
          Next
        </button>
        <button
          type="button"
          className="text-button"
          onClick={() => setFitWidth(!fitWidth)}
        >
          {fitWidth ? "Fit width" : "Zoom"}
        </button>
      </div>

      <div className={`evidence-image ${fitWidth ? "fit-width" : "zoomed"}`}>
        {imageError ? (
          <div className="image-error">
            <ImageIcon size={22} />
            <p>Page image unavailable.</p>
            <small>Exact location not available. Check the page.</small>
          </div>
        ) : (
          <Image
            src={image}
            alt={`Page ${page}`}
            width={800}
            height={1100}
            unoptimized
            onError={() => setImageError(true)}
          />
        )}
        {!imageError && fact.bbox && page === fact.page_no && (
          <div
            ref={bboxRef}
            className="bbox"
            style={{
              left: `${fact.bbox[0] * 100}%`,
              top: `${fact.bbox[1] * 100}%`,
              width: `${(fact.bbox[2] - fact.bbox[0]) * 100}%`,
              height: `${(fact.bbox[3] - fact.bbox[1]) * 100}%`,
            }}
          />
        )}
      </div>

      {!fact.bbox && (
        <p className="muted" style={{ fontSize: "0.74rem" }}>
          Exact location not available. Check the page.
        </p>
      )}

      <dl className="evidence-details">
        <dt>Quoted source text</dt>
        <dd>{String(raw?.source_text ?? raw?.value ?? "No quoted text")}</dd>
        <dt>Extractor</dt>
        <dd>{fact.extractor_version ?? "Unknown"}</dd>
        <dt>Confidence</dt>
        <dd>
          {fact.confidence
            ? `${Number(fact.confidence) >= 0.85 ? "High" : Number(fact.confidence) >= 0.6 ? "Medium" : "Low"} (${fact.confidence})`
            : "Unknown"}
        </dd>
      </dl>
    </aside>
  );
}



/* ------------------------------------------------------------------ */
/* M6 Evidence view (simple viewer opened from tabs)                   */
/* ------------------------------------------------------------------ */
function M6EvidenceView({
  docId,
  page,
  bbox,
  docs,
}: {
  docId: string;
  page: number;
  bbox?: number[] | null;
  docs: Doc[];
}) {
  const [currentPage, setCurrentPage] = useState(page);
  const [imageError, setImageError] = useState(false);

  const doc = docs.find((d) => d.id === docId);
  const maxPages = doc?.pages ?? 1;
  const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const image = `${base}/documents/${docId}/pages/${currentPage}/image`;

  return (
    <div style={{ padding: "0 16px 16px" }}>
      {doc && (
        <p style={{ fontSize: "0.76rem", color: "var(--color-slate)", marginBottom: "8px" }}>
          {doc.filename} · Page {currentPage} of {maxPages}
        </p>
      )}
      <div className="evidence-controls">
        <button
          type="button"
          className="text-button"
          disabled={currentPage <= 1}
          onClick={() => { setCurrentPage(currentPage - 1); setImageError(false); }}
        >
          Previous
        </button>
        <button
          type="button"
          className="text-button"
          disabled={currentPage >= maxPages}
          onClick={() => { setCurrentPage(currentPage + 1); setImageError(false); }}
        >
          Next
        </button>
      </div>
      <div className="evidence-image fit-width" style={{ marginTop: "10px", position: "relative" }}>
        {imageError ? (
          <div className="image-error">
            <ImageIcon size={22} />
            <p>Page image unavailable.</p>
          </div>
        ) : (
          <Image
            src={image}
            alt={`Page ${currentPage}`}
            width={800}
            height={1100}
            unoptimized
            onError={() => setImageError(true)}
          />
        )}
        {!imageError && bbox && currentPage === page && (
          <div
            className="bbox"
            style={{
              left: `${bbox[0] * 100}%`,
              top: `${bbox[1] * 100}%`,
              width: `${(bbox[2] - bbox[0]) * 100}%`,
              height: `${(bbox[3] - bbox[1]) * 100}%`,
            }}
          />
        )}
      </div>
      {!bbox && (
        <p className="muted" style={{ fontSize: "0.74rem", margin: "8px 0 0" }}>
          Exact location not available. Check the page.
        </p>
      )}
    </div>
  );
}
