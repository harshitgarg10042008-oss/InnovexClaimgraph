"use client";

import { ChangeEvent, KeyboardEvent, useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, Check, FileUp, History, Image as ImageIcon, Pencil, RotateCcw, X } from "lucide-react";
import { useParams } from "next/navigation";
import Image from "next/image";
import { Header } from "../../components/Header";
import { apiClient } from "@/lib/api/client";
import { displayFactValue, formatDate } from "@/lib/format";
import type { components } from "@/lib/api/schema";

type Case = components["schemas"]["CaseRead"];
type Doc = components["schemas"]["DocumentResponse"];
type Fact = components["schemas"]["FactResponse"] & { validation_warnings?: string[] | null };
type Summary = components["schemas"]["ReviewSummary"];
type Value = Record<string, unknown>;
type Audit = { id: string; actor: string; action: string; target: string; at: string; before_json: Value; after_json: Value };

const terminalDocs = new Set(["ready", "needs_review", "complete", "completed", "failed", "error"]);
const valueOf = (fact: Fact) => fact.value_json as unknown as Value | null | undefined;
const factSort = (a: Fact, b: Fact) => a.document_id.localeCompare(b.document_id) || (a.group ?? "").localeCompare(b.group ?? "") || a.page_no - b.page_no;

function statusLabel(status: string) { return status.replace("_", " "); }

export default function CaseWorkspace() {
  const { id } = useParams<{ id: string }>();
  const [caseData, setCaseData] = useState<Case | null>(null);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [facts, setFacts] = useState<Fact[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [audit, setAudit] = useState<Audit[]>([]);
  const [selectedFact, setSelectedFact] = useState<Fact | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [reviewer, setReviewer] = useState(() => typeof window === "undefined" ? "Reviewer" : localStorage.getItem("claimgraph-reviewer") ?? "Reviewer");
  const [showAudit, setShowAudit] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState<Record<string, string>>({});
  const [fitWidth, setFitWidth] = useState(true);

  const load = useCallback(async () => {
    const [nextCase, nextDocs, nextFacts, nextSummary] = await Promise.all([
      apiClient<Case>(`/cases/${id}`), apiClient<Doc[]>(`/cases/${id}/documents`), apiClient<Fact[]>(`/cases/${id}/facts`), apiClient<Summary>(`/cases/${id}/review-summary`),
    ]);
    setCaseData(nextCase); setDocs(nextDocs); setFacts(nextFacts.sort(factSort)); setSummary(nextSummary);
  }, [id]);
  useEffect(() => {
    const timer = window.setTimeout(() => { load().catch(() => setError("This case could not be loaded.")); }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);
  useEffect(() => {
    if (!docs.some((doc) => !terminalDocs.has(doc.status))) return;
    const timer = window.setInterval(() => { load().catch(() => undefined); }, 2000);
    return () => window.clearInterval(timer);
  }, [docs, load]);

  const update = async (fact: Fact, action: string, value?: Value) => {
    setBusy(true); setError(null);
    try {
      const result = await apiClient<Fact>(`/facts/${fact.id}`, { method: "PATCH", headers: { "X-Reviewer": reviewer }, body: JSON.stringify({ action, value }) });
      setFacts((current) => current.map((item) => item.id === result.id ? result : item).sort(factSort)); setSelectedFact(result); await load();
    } catch (err) { setError(err instanceof Error ? err.message : "The review action failed."); } finally { setBusy(false); }
  };
  const saveEdit = (fact: Fact) => {
    const current = valueOf(fact) ?? {};
    const next: Value = { ...current, value: editValue };
    if (/amount|total|rate|price|qty|quantity/i.test(fact.field)) {
      const number = Number(editValue.replace(/,/g, ""));
      if (!Number.isNaN(number)) next.value = number;
    }
    void update(fact, "edit", next); setEditing(null);
  };
  const confirmReviewer = (event: ChangeEvent<HTMLInputElement>) => { setReviewer(event.target.value); localStorage.setItem("claimgraph-reviewer", event.target.value); };
  const process = async () => { setBusy(true); try { await apiClient(`/cases/${id}/process`, { method: "POST" }); await load(); } catch { setError("Documents could not be processed."); } finally { setBusy(false); } };
  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    if (!event.target.files?.length) return;
    const selected = Array.from(event.target.files);
    setUploadProgress(Object.fromEntries(selected.map((file) => [file.name, "Uploading"])));
    const form = new FormData(); selected.forEach((file) => form.append("files", file));
    setBusy(true); try { await apiClient(`/cases/${id}/documents`, { method: "POST", body: form }); await load(); } catch { setError("Upload failed. Please try again."); } finally { setBusy(false); event.target.value = ""; }
    setUploadProgress(Object.fromEntries(selected.map((file) => [file.name, "Stored"])));
  };
  const uploadFiles = (files: FileList | File[]) => {
    const input = document.createElement("input");
    input.type = "file"; input.multiple = true;
    const transfer = new DataTransfer(); Array.from(files).forEach((file) => transfer.items.add(file));
    input.files = transfer.files;
    const event = { target: input } as ChangeEvent<HTMLInputElement>;
    void upload(event);
  };
  const bulk = async (doc: Doc) => { setBusy(true); try { await apiClient(`/documents/${doc.id}/facts/confirm-auto`, { method: "POST", headers: { "X-Reviewer": reviewer } }); await load(); } catch { setError("Bulk confirmation failed."); } finally { setBusy(false); } };
  const openAudit = async () => { setShowAudit(!showAudit); if (!showAudit) setAudit(await apiClient<Audit[]>(`/cases/${id}/audit-log`)); };

  const grouped = useMemo(() => docs.map((doc) => ({ doc, facts: facts.filter((fact) => fact.document_id === doc.id) })).filter((item) => item.facts.length), [docs, facts]);
  const nextIssue = () => {
    const issue = facts.find((fact) => fact.status === "needs_review");
    if (issue) setSelectedFact(issue);
  };
  const keyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return;
    const index = selectedFact ? facts.findIndex((fact) => fact.id === selectedFact.id) : -1;
    if (event.key === "ArrowDown" || event.key.toLowerCase() === "j") setSelectedFact(facts[Math.min(index + 1, facts.length - 1)] ?? null);
    if (event.key === "ArrowUp" || event.key.toLowerCase() === "k") setSelectedFact(facts[Math.max(index - 1, 0)] ?? null);
    if (event.key === "Enter" && selectedFact) void update(selectedFact, "confirm");
    if (event.key.toLowerCase() === "e" && selectedFact) { setEditing(selectedFact.id); setEditValue(displayFactValue(valueOf(selectedFact), selectedFact.field)); }
    if (event.key.toLowerCase() === "n" && selectedFact) void update(selectedFact, "mark_not_present");
  };

  return <><Header /><main className="workspace-shell">
    <div className="workspace-title"><div><p className="eyebrow">Case workspace</p><h1>{caseData?.title ?? "Loading case…"}</h1></div><label className="reviewer-field">Reviewer<input value={reviewer} onChange={confirmReviewer} /></label></div>
    {error && <div className="alert alert-error" role="alert">{error}</div>}
    <div className="workspace-grid">
      <aside className="document-sidebar"><div className="section-heading"><h2>Documents</h2><label className="upload-label"><FileUp size={15} /> Upload<input type="file" multiple onChange={upload} /></label></div><div className="drop-zone" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); uploadFiles(event.dataTransfer.files); }}><FileUp size={16} /><span>Drop files here</span></div>{Object.entries(uploadProgress).map(([name, status]) => <p className="upload-progress" key={name}>{name}: {status}</p>)}{docs.length === 0 && <p className="muted">No documents uploaded.</p>}{docs.map((doc) => { const docFacts = facts.filter((fact) => fact.document_id === doc.id); const auto = docFacts.filter((fact) => fact.status === "auto").length; return <div className="document-row" key={doc.id}><div><strong>{doc.kind}</strong><span>{doc.filename}</span></div><span className="document-meta">{doc.status} · {docFacts.filter((fact) => fact.status === "needs_review").length} review</span>{auto > 0 && <button className="text-button" onClick={() => void bulk(doc)} disabled={busy}>Confirm {auto} auto</button>}</div>; })}<button className="button button-dark full-width" onClick={process} disabled={busy || docs.length === 0}>Process documents</button></aside>
      <section className="review-panel" tabIndex={0} onKeyDown={keyboard}><div className="summary-strip"><SummaryItem label="Needs review" value={summary?.status_counts.needs_review ?? 0} /><SummaryItem label="Confirmed" value={summary?.status_counts.confirmed ?? 0} /><SummaryItem label="Auto" value={summary?.status_counts.auto ?? 0} /><SummaryItem label="Required remaining" value={summary?.required_fields_needing_review ?? 0} /><SummaryItem label="Linking" value={summary?.ready_for_linking ? "Ready" : "Blocked"} /></div><div className="tabs"><button className="tab active">Review</button>{["Graph", "Ledger", "Interest", "Findings", "Dossier"].map((tab) => <button key={tab} className="tab disabled" title="Coming in a later milestone" disabled>{tab}</button>)}<button className="audit-toggle" onClick={() => void openAudit()}><History size={15} /> Audit log</button></div><div className="review-tools"><p className="shortcut-hint">Keyboard: Up/Down or j/k select · Enter confirm · E edit · N not present</p><button className="text-button" onClick={nextIssue}>Next issue</button></div>{grouped.map(({ doc, facts: docFacts }) => <section className="fact-document" key={doc.id}><div className="fact-document-heading"><div><h2>{doc.kind}</h2><span>{doc.filename}</span></div><button className="text-button" onClick={() => void bulk(doc)}>Confirm all auto ({docFacts.filter((fact) => fact.status === "auto").length})</button></div>{docFacts.map((fact) => <FactRow key={fact.id} fact={fact} selected={selectedFact?.id === fact.id} editing={editing === fact.id} editValue={editValue} onSelect={() => { setSelectedFact(fact); setEditValue(displayFactValue(valueOf(fact), fact.field)); }} onEdit={setEditValue} onSave={() => saveEdit(fact)} onCancel={() => setEditing(null)} onStartEdit={() => setEditing(fact.id)} onAction={(action) => void update(fact, action)} />)}</section>)}</section>
      <EvidenceDrawer key={selectedFact?.id ?? "empty"} fact={selectedFact} maxPages={docs.find((doc) => doc.id === selectedFact?.document_id)?.pages ?? 1} fitWidth={fitWidth} setFitWidth={setFitWidth} />
    </div>
    {showAudit && <aside className="audit-panel"><div className="section-heading"><h2>Audit log</h2><button className="icon-button" onClick={() => setShowAudit(false)} aria-label="Close audit log"><X size={17} /></button></div>{audit.map((item) => <div className="audit-row" key={item.id}><strong>{item.action}</strong><span>{item.actor} · {formatDate(item.at)}</span><code>{item.target.slice(0, 8)}</code></div>)}</aside>}
  </main></>;
}

function SummaryItem({ label, value }: { label: string; value: number | string }) { return <div><span>{label}</span><strong>{value}</strong></div>; }

function FactRow({ fact, selected, editing, editValue, onSelect, onEdit, onSave, onCancel, onStartEdit, onAction }: { fact: Fact; selected: boolean; editing: boolean; editValue: string; onSelect: () => void; onEdit: (value: string) => void; onSave: () => void; onCancel: () => void; onStartEdit: () => void; onAction: (action: string) => void }) {
  const chipIcon = fact.status === "needs_review" ? <AlertCircle size={12} /> : fact.status === "not_present" ? <X size={12} /> : <Check size={12} />;
  return <div className={`fact-row ${selected ? "selected" : ""}`} onClick={onSelect}><div className="fact-label"><strong>{fact.label ?? fact.field}</strong><span>{fact.group ?? "Other"} · page {fact.page_no}</span></div><div className="fact-value">{editing ? <input autoFocus value={editValue} onChange={(e) => onEdit(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") onSave(); if (e.key === "Escape") onCancel(); }} /> : <><span title={JSON.stringify(valueOf(fact))}>{displayFactValue(valueOf(fact), fact.field)}</span>{fact.reason && <small>{fact.reason}</small>}{fact.status === "edited" && fact.original_value_json && <small>was: {displayFactValue(fact.original_value_json as unknown as Value, fact.field)}</small>}{fact.validation_warnings?.map((warning) => <small key={warning}>{warning}</small>)}</>}</div><span className={`status-chip chip-${fact.status}`}>{chipIcon}{statusLabel(fact.status)}</span><div className="fact-actions">{fact.status === "needs_review" && <button className="icon-button" title="Confirm" onClick={(e) => { e.stopPropagation(); onAction("confirm"); }}><Check size={15} /></button>}{fact.status === "needs_review" && <button className="icon-button" title="Edit" onClick={(e) => { e.stopPropagation(); onStartEdit(); }}><Pencil size={15} /></button>}{fact.status !== "not_present" && <button className="icon-button" title="Mark not present" onClick={(e) => { e.stopPropagation(); onAction("mark_not_present"); }}><X size={15} /></button>}{["confirmed", "edited", "not_present"].includes(fact.status) && <button className="icon-button" title="Reopen" onClick={(e) => { e.stopPropagation(); onAction("reopen"); }}><RotateCcw size={15} /></button>}</div></div>;
}

function EvidenceDrawer({ fact, maxPages, fitWidth, setFitWidth }: { fact: Fact | null; maxPages: number; fitWidth: boolean; setFitWidth: (value: boolean) => void }) {
  const [page, setPage] = useState(fact?.page_no ?? 1);
  if (!fact) return <aside className="evidence-drawer empty-drawer"><ImageIcon size={24} /><p>Select a fact to inspect its evidence.</p></aside>;
  const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const image = `${base}/documents/${fact.document_id}/pages/${page}/image`;
  const raw = valueOf(fact);
  return <aside className="evidence-drawer"><div className="section-heading"><div><h2>Evidence</h2><span>Page {page} of {maxPages}</span></div><a href={image} target="_blank" rel="noreferrer" className="text-button">Open image</a></div><div className="evidence-controls"><button className="text-button" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button><button className="text-button" disabled={page >= maxPages} onClick={() => setPage(page + 1)}>Next</button><button className="text-button" onClick={() => setFitWidth(!fitWidth)}>{fitWidth ? "Fit width" : "Zoom"}</button></div><div className={`evidence-image ${fitWidth ? "fit-width" : "zoomed"}`}><Image src={image} alt={`Page ${page}`} width={800} height={1100} unoptimized />{fact.bbox && page === fact.page_no && <div className="bbox" style={{ left: `${fact.bbox[0] * 100}%`, top: `${fact.bbox[1] * 100}%`, width: `${(fact.bbox[2] - fact.bbox[0]) * 100}%`, height: `${(fact.bbox[3] - fact.bbox[1]) * 100}%` }} />}</div>{!fact.bbox && <p className="muted">Exact location not found. Check the page.</p>}<dl className="evidence-details"><dt>Quoted source text</dt><dd>{String(raw?.source_text ?? raw?.value ?? "No quoted text")}</dd><dt>Extractor</dt><dd>{fact.extractor_version ?? "Unknown"}</dd><dt>Confidence</dt><dd>{fact.confidence ? `${Number(fact.confidence) >= .85 ? "High" : Number(fact.confidence) >= .6 ? "Medium" : "Low"} (${fact.confidence})` : "Unknown"}</dd></dl></aside>;
}
