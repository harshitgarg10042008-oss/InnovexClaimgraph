"use client";

import Link from "next/link";
import { AlertCircle, CheckCircle2, FileText, LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { Header } from "./components/Header";
import { apiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type Case = components["schemas"]["CaseRead"];

function CaseStatus({ value }: { value: string }) {
  const ready = value === "ready" || value === "processed";
  return (
    <span className={`status status-${ready ? "verified" : "attention"}`}>
      {ready ? <CheckCircle2 size={15} /> : <AlertCircle size={15} />}
      {value.replace("_", " ")}
    </span>
  );
}

export default function CasesPage() {
  const [cases, setCases] = useState<Case[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiClient<Case[]>("/cases")
      .then(setCases)
      .catch(() => setError("Cases could not be loaded. Check the API connection."))
      .finally(() => setLoading(false));
  }, []);

  return (
    <><Header /><main className="page-shell">
      <div className="page-heading">
        <div><p className="eyebrow">Workspace</p><h1>Cases</h1><p className="lede">Each case gathers one supplier-buyer transaction and its evidence.</p></div>
        <Link href="/cases/new" className="button button-dark">New case</Link>
      </div>
      {loading && <div className="empty-state"><LoaderCircle className="spin" /> Loading cases</div>}
      {error && <div className="alert alert-error" role="alert">{error}</div>}
      {!loading && !error && cases.length === 0 && <div className="empty-state"><FileText size={28} /><h2>No cases yet</h2><p>Create a case to start building a verifiable payment claim.</p><Link href="/cases/new" className="button button-dark">Create your first case</Link></div>}
      {!loading && cases.length > 0 && <div className="table-wrap"><table className="data-table"><thead><tr><th>Case</th><th>Supplier</th><th>Buyer</th><th>Documents</th><th>Needs review</th><th>Status</th><th>Next step</th></tr></thead><tbody>{cases.map((item) => { const draft = item.documents_count === 0; return <tr key={item.id}><td><Link className="table-link" href={`/cases/${item.id}`}>{item.title}</Link></td><td>{item.supplier?.name ?? "—"}</td><td>{item.buyer?.name ?? "—"}</td><td>{item.documents_count}</td><td>{item.needs_review_count}</td><td><CaseStatus value={item.status} /></td><td><Link className="text-button" href={`/cases/${item.id}`}>{draft ? "Upload documents" : "Open review"}</Link></td></tr>; })}</tbody></table></div>}
    </main></>
  );
}
