"use client";

import {
  ChangeEvent,
  KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
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

    // Initial fact selection if none selected yet
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

  // Find next needs-review fact for auto-advance
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

    // Look across entire case if no more needs_review in current scope
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

      // Auto-advance to next needs_review field
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
      const firstNeedsReview = docFacts.find(
        (f) => f.status === "needs_review",
      );
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

  // Grouped documents for the centre pane
  const displayedDocs = useMemo(() => {
    if (selectedDocId) {
      return docs.filter((d) => d.id === selectedDocId);
    }
    return docs;
  }, [docs, selectedDocId]);

  // List of currently visible facts in centre pane (for keyboard navigation)
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

  // Determine active document for bulk auto confirm button
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

  return (
    <div
      className="workspace-container"
      tabIndex={0}
      onKeyDown={keyboard}
      aria-label="Case review workspace"
    >
      <Header />

      {/* Sticky Header: Header bar, 4 stat cells, and tab bar */}
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

        {error && (
          <div
            className="alert alert-error"
            role="alert"
            style={{ margin: "4px 24px 8px" }}
          >
            {error}
          </div>
        )}

        {/* 4 flat stat cells pinned */}
        <div className="workspace-stat-strip">
          <div className="stat-cell">
            <span className="stat-label">Needs review</span>
            <strong className="stat-value" style={{ color: "var(--color-attention)" }}>
              {summary?.status_counts.needs_review ?? 0}
            </strong>
          </div>
          <div className="stat-cell">
            <span className="stat-label">Confirmed</span>
            <strong className="stat-value" style={{ color: "var(--color-verified)" }}>
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
            <span className="stat-label">Linking</span>
            <strong
              className="stat-value"
              style={{
                color: summary?.ready_for_linking
                  ? "var(--color-verified)"
                  : "var(--color-conflict)",
              }}
            >
              {summary?.ready_for_linking ? "Ready" : "Blocked"}
            </strong>
          </div>
        </div>

        {/* Tabs Bar */}
        <div className="workspace-tab-bar">
          <div style={{ display: "flex", gap: "6px" }}>
            <button type="button" className="tab active">
              Review
            </button>
            {["Graph", "Ledger", "Interest", "Findings", "Dossier"].map((tab) => (
              <button
                key={tab}
                type="button"
                className="tab disabled"
                title="Coming in a later milestone"
                disabled
              >
                {tab}
              </button>
            ))}
          </div>
          <div className="shortcut-hint" style={{ margin: 0 }}>
            Keyboard: Up/Down or j/k select · Enter confirm · E edit · N not present
          </div>
        </div>
      </header>

      {/* Three independent scrollable panes under sticky header */}
      <div className="workspace-three-panes">
        {/* Left Rail: Documents */}
        <aside className="doc-rail-pane">
          <div className="doc-rail-top">
            <h2 style={{ fontSize: "0.82rem", textTransform: "uppercase", color: "var(--color-slate)", letterSpacing: "0.05em" }}>
              Documents ({docs.length})
            </h2>
            <label className="upload-label" style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
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

          {/* All documents selector */}
          <div
            className={`doc-rail-row ${selectedDocId === null ? "active" : ""}`}
            onClick={() => handleSelectDocument(null)}
            title="Show all documents"
          >
            <div className="doc-rail-title-row">
              <span className="doc-kind-badge">ALL</span>
              <span className="doc-filename-text">All documents ({docs.length})</span>
            </div>
            <div className="doc-rail-meta-row">
              <span className="text-slate text-xs">
                {summary?.status_counts.needs_review ?? 0} needs review
              </span>
            </div>
          </div>

          {/* Document list */}
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
            {docs.length > 0 && docs.every((doc) => terminalDocs.has(doc.status))
              ? "Reprocess documents"
              : "Process documents"}
          </button>
        </aside>

        {/* Centre Pane: Fields & Sticky Action Bar */}
        <section className="centre-fields-pane">
          {/* Centre pane toolbar: segmented filter and doc filter note */}
          <div className="centre-pane-toolbar">
            <div className="segmented-control" role="group" aria-label="Field filter">
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

          {/* Scrollable fields area */}
          <div className="centre-pane-scroll">
            {displayedDocs.map((doc) => {
              const docFacts = facts.filter((f) => f.document_id === doc.id);
              const activeFacts = docFacts.filter(
                (f) =>
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
                    <span style={{ fontSize: "0.72rem", color: "var(--color-slate)" }}>
                      {activeFacts.length} {fieldFilter.replace("_", " ")} fields
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

                  {/* Collapsed not-present row per document */}
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

          {/* Sticky action bar at the bottom of the centre pane */}
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
                disabled={busy || (summary?.status_counts.needs_review ?? 0) === 0}
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
            docs.find((doc) => doc.id === selectedFact?.document_id)?.pages ?? 1
          }
          fitWidth={fitWidth}
          setFitWidth={setFitWidth}
        />
      </div>

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

  // Scroll bbox into view when selection or page changes
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
  const raw = valueOf(fact);

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
            <small>Exact location not found. Check the page.</small>
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
          Exact location not found. Check the page.
        </p>
      )}

      <dl className="evidence-details">
        <dt>Quoted source text</dt>
        <dd>
          {String(raw?.source_text ?? raw?.value ?? "No quoted text")}
        </dd>
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
