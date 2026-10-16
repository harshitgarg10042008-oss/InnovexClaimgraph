"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  FileText,
  Search,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Header } from "./components/Header";
import { apiClient } from "@/lib/api/client";
import { getCaseCode, partitionAndSortCases } from "@/lib/cases";
import { formatDate } from "@/lib/format";
import type { components } from "@/lib/api/schema";

type Case = components["schemas"]["CaseRead"];
type StatusFilter = "all" | "needs_review" | "ready" | "blocked";

function StatusBadge({
  status,
  needsReviewCount,
  docCount,
}: {
  status: string;
  needsReviewCount: number;
  docCount: number;
}) {
  if (status === "ready" || (docCount > 0 && needsReviewCount === 0)) {
    return (
      <span className="status status-verified">
        <CheckCircle2 size={14} />
        <span>Ready</span>
      </span>
    );
  }
  if (needsReviewCount > 0 || status === "needs_review") {
    return (
      <span className="status status-attention">
        <AlertCircle size={14} />
        <span>Needs review</span>
      </span>
    );
  }
  if (status === "blocked" || status === "error" || status === "failed") {
    return (
      <span className="status status-conflict">
        <AlertTriangle size={14} />
        <span>Blocked</span>
      </span>
    );
  }
  return (
    <span className="status status-slate">
      <FileText size={14} />
      <span>{status === "draft" ? "Draft" : status.replace("_", " ")}</span>
    </span>
  );
}

export default function CasesPage() {
  const router = useRouter();
  const [cases, setCases] = useState<Case[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  useEffect(() => {
    apiClient<Case[]>("/cases")
      .then(setCases)
      .catch(() =>
        setError("Cases could not be loaded. Check the API connection."),
      )
      .finally(() => setLoading(false));
  }, []);

  const totalCases = cases.length;
  const totalNeedsReview = useMemo(
    () =>
      cases.reduce((sum, item) => sum + (item.needs_review_count || 0), 0),
    [cases],
  );
  const readyCount = useMemo(
    () =>
      cases.filter(
        (c) =>
          c.status === "ready" ||
          ((c.documents_count ?? 0) > 0 && (c.needs_review_count ?? 0) === 0),
      ).length,
    [cases],
  );
  const blockedCount = useMemo(
    () =>
      cases.filter(
        (c) =>
          c.status === "blocked" ||
          c.status === "error" ||
          c.status === "failed",
      ).length,
    [cases],
  );

  const filteredCases = useMemo(() => {
    return cases.filter((item) => {
      // 1. Status Filter
      if (statusFilter === "needs_review") {
        const isNeedsReview =
          (item.needs_review_count ?? 0) > 0 || item.status === "needs_review";
        if (!isNeedsReview) return false;
      } else if (statusFilter === "ready") {
        const isReady =
          item.status === "ready" ||
          ((item.documents_count ?? 0) > 0 &&
            (item.needs_review_count ?? 0) === 0);
        if (!isReady) return false;
      } else if (statusFilter === "blocked") {
        const isBlocked =
          item.status === "blocked" ||
          item.status === "error" ||
          item.status === "failed";
        if (!isBlocked) return false;
      }

      // 2. Search Query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim();
        const code = getCaseCode(item).toLowerCase();
        const title = item.title.toLowerCase();
        const supplier = (item.supplier?.name ?? "").toLowerCase();
        const buyer = (item.buyer?.name ?? "").toLowerCase();
        return (
          code.includes(q) ||
          title.includes(q) ||
          supplier.includes(q) ||
          buyer.includes(q)
        );
      }

      return true;
    });
  }, [cases, statusFilter, searchQuery]);

  const { demoCases, yourCases } = useMemo(
    () => partitionAndSortCases(filteredCases),
    [filteredCases],
  );

  const renderRow = (item: Case) => {
    const code = getCaseCode(item);
    const supplierName = item.supplier?.name;
    const buyerName = item.buyer?.name;

    return (
      <tr
        key={item.id}
        className="register-row"
        tabIndex={0}
        onClick={() => router.push(`/cases/${item.id}`)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            router.push(`/cases/${item.id}`);
          }
        }}
        aria-label={`Open case ${code}`}
      >
        <td>
          <span className="case-code">{code}</span>
        </td>
        <td>
          <div className="supplier-buyer">
            <strong>{supplierName ?? "—"}</strong>
            <span className="to-label">to</span>
            <span>{buyerName ?? "—"}</span>
          </div>
        </td>
        <td>
          <StatusBadge
            status={item.status}
            needsReviewCount={item.needs_review_count ?? 0}
            docCount={item.documents_count ?? 0}
          />
        </td>
        <td className="num-col">{item.documents_count ?? 0}</td>
        <td className="num-col">{item.needs_review_count ?? 0}</td>
        <td className="num-col">—</td>
        <td>{formatDate(item.updated_at || item.created_at)}</td>
        <td className="action-col">
          <Link
            className="table-link"
            href={`/cases/${item.id}`}
            onClick={(e) => e.stopPropagation()}
          >
            Open
          </Link>
        </td>
      </tr>
    );
  };

  return (
    <>
      <Header />
      <main className="page-shell">
        <div className="page-heading">
          <div>
            <p className="eyebrow">Workspace</p>
            <h1>Cases register</h1>
            <p className="lede">
              Audit-workpaper register of supplier-buyer claims, extracted facts, and evidence.
            </p>
          </div>
          <Link href="/cases/new" className="button button-dark">
            New case
          </Link>
        </div>

        {/* Summary strip with 4 flat stat cells */}
        <div className="register-summary-strip">
          <div className="stat-cell">
            <span className="stat-label">Total cases</span>
            <strong className="stat-value">{totalCases}</strong>
          </div>
          <div className="stat-cell">
            <span className="stat-label">Needs review</span>
            <strong className="stat-value">{totalNeedsReview}</strong>
            <span className="stat-sub">fields across cases</span>
          </div>
          <div className="stat-cell">
            <span className="stat-label">Ready to link</span>
            <strong className="stat-value">{readyCount}</strong>
          </div>
          <div className="stat-cell">
            <span className="stat-label">Blocked</span>
            <strong className="stat-value">{blockedCount}</strong>
          </div>
        </div>

        {/* Toolbar: Search input and status filter chips */}
        <div className="register-toolbar">
          <div className="search-box">
            <Search size={15} />
            <input
              type="search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by supplier, buyer, or case code…"
              aria-label="Search cases"
            />
          </div>
          <div className="filter-chips" role="group" aria-label="Status filter">
            {(
              [
                { key: "all", label: "All", count: totalCases },
                {
                  key: "needs_review",
                  label: "Needs review",
                  count: cases.filter(
                    (c) =>
                      (c.needs_review_count ?? 0) > 0 ||
                      c.status === "needs_review",
                  ).length,
                },
                { key: "ready", label: "Ready", count: readyCount },
                { key: "blocked", label: "Blocked", count: blockedCount },
              ] as const
            ).map((chip) => (
              <button
                key={chip.key}
                type="button"
                className={`filter-chip ${statusFilter === chip.key ? "active" : ""}`}
                onClick={() => setStatusFilter(chip.key)}
              >
                <span>{chip.label}</span>
                <span className="chip-count">{chip.count}</span>
              </button>
            ))}
          </div>
        </div>

        {error && (
          <div className="alert alert-error" role="alert">
            {error}
          </div>
        )}

        {/* Loading skeleton */}
        {loading && (
          <div className="table-wrap">
            <table className="data-table register-table">
              <thead>
                <tr>
                  <th>Case code</th>
                  <th>Supplier to Buyer</th>
                  <th>Status</th>
                  <th className="num-col">Documents</th>
                  <th className="num-col">Needs review</th>
                  <th className="num-col">Outstanding</th>
                  <th>Last updated</th>
                  <th className="action-col">Action</th>
                </tr>
              </thead>
              <tbody>
                {Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="skeleton-row">
                    <td><div className="skeleton-bar w-16" /></td>
                    <td><div className="skeleton-bar w-48" /></td>
                    <td><div className="skeleton-bar w-20" /></td>
                    <td className="num-col"><div className="skeleton-bar w-12" style={{ marginLeft: "auto" }} /></td>
                    <td className="num-col"><div className="skeleton-bar w-12" style={{ marginLeft: "auto" }} /></td>
                    <td className="num-col"><div className="skeleton-bar w-16" style={{ marginLeft: "auto" }} /></td>
                    <td><div className="skeleton-bar w-24" /></td>
                    <td className="action-col"><div className="skeleton-bar w-12" style={{ marginLeft: "auto" }} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Empty state: No cases in database */}
        {!loading && !error && cases.length === 0 && (
          <div className="empty-state">
            <FileText size={28} />
            <h2>No cases yet</h2>
            <p>Create a case to start building a verifiable payment claim.</p>
            <Link href="/cases/new" className="button button-dark">
              Create your first case
            </Link>
          </div>
        )}

        {/* Empty state: No cases matching filter */}
        {!loading && !error && cases.length > 0 && filteredCases.length === 0 && (
          <div className="empty-state">
            <Search size={28} />
            <h2>No matching cases found</h2>
            <p>No cases match your current filter or search criteria.</p>
            <button
              type="button"
              className="button"
              onClick={() => {
                setSearchQuery("");
                setStatusFilter("all");
              }}
            >
              Clear filters
            </button>
          </div>
        )}

        {/* Table rows */}
        {!loading && !error && filteredCases.length > 0 && (
          <div className="table-wrap">
            <table className="data-table register-table">
              <thead>
                <tr>
                  <th>Case code</th>
                  <th>Supplier to Buyer</th>
                  <th>Status</th>
                  <th className="num-col">Documents</th>
                  <th className="num-col">Needs review</th>
                  <th className="num-col">Outstanding</th>
                  <th>Last updated</th>
                  <th className="action-col">Action</th>
                </tr>
              </thead>
              <tbody>
                {demoCases.length > 0 && (
                  <tr className="table-section-row">
                    <td colSpan={8}>Demo cases</td>
                  </tr>
                )}
                {demoCases.map(renderRow)}
                {yourCases.length > 0 && (
                  <tr className="table-section-row">
                    <td colSpan={8}>Your cases</td>
                  </tr>
                )}
                {yourCases.map(renderRow)}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </>
  );
}
