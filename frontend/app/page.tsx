"use client";

import { useEffect, useState } from "react";
import {
  CheckCircle2,
  AlertTriangle,
  AlertCircle,
  RefreshCw,
} from "lucide-react";
import { apiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type HealthData = components["schemas"]["HealthResponse"];

type ServiceStatus = "verified" | "attention" | "conflict";

export default function SystemStatusPage() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const handleRefresh = async () => {
    setLoading(true);
    try {
      const data = await apiClient<HealthData>("/health");
      setHealth(data);
      setError(null);
    } catch {
      setError(
        "Can't reach the API. Check that the backend container is running.",
      );
      setHealth(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let ignore = false;
    async function load() {
      try {
        const data = await apiClient<HealthData>("/health");
        if (!ignore) {
          setHealth(data);
          setError(null);
        }
      } catch {
        if (!ignore) {
          setError(
            "Can't reach the API. Check that the backend container is running.",
          );
          setHealth(null);
        }
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    }
    load();
    return () => {
      ignore = true;
    };
  }, []);

  // Determine status and style for each component
  const getBackendStatus = (): { label: string; type: ServiceStatus } => {
    if (error || !health) return { label: "unreachable", type: "conflict" };
    if (health.status === "degraded")
      return { label: "degraded", type: "attention" };
    if (health.status === "ok") return { label: "ok", type: "verified" };
    return { label: health.status, type: "attention" };
  };

  const getDbStatus = (): { label: string; type: ServiceStatus } => {
    if (error || !health) return { label: "unreachable", type: "conflict" };
    if (health.db === "ok") return { label: "ok", type: "verified" };
    return { label: "error", type: "conflict" };
  };

  const renderStatusBadge = (label: string, type: ServiceStatus) => {
    if (type === "verified") {
      return (
        <span className="inline-flex items-center gap-1.5 text-verified font-medium">
          <CheckCircle2 className="w-4 h-4" aria-hidden="true" />
          <span>{label}</span>
        </span>
      );
    }
    if (type === "attention") {
      return (
        <span className="inline-flex items-center gap-1.5 text-attention font-medium">
          <AlertTriangle className="w-4 h-4" aria-hidden="true" />
          <span>{label}</span>
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1.5 text-conflict font-medium">
        <AlertCircle className="w-4 h-4" aria-hidden="true" />
        <span>{label}</span>
      </span>
    );
  };

  const backendState = getBackendStatus();
  const dbState = getDbStatus();

  return (
    <main className="min-h-screen bg-paper text-ink px-4 py-8 sm:px-8 sm:py-12">
      <div className="max-w-xl mx-auto">
        <header className="mb-8">
          <h1 className="font-serif text-3xl sm:text-4xl font-semibold tracking-tight text-ink mb-2">
            ClaimGraph
          </h1>
          <p className="text-slate text-base">
            Evidence compiler for MSME payment claims
          </p>
        </header>

        <section
          aria-labelledby="status-heading"
          className="bg-surface border border-rule rounded-[8px] p-4 sm:p-6 mb-6"
        >
          <div className="flex items-center justify-between pb-4 border-b border-rule mb-4">
            <h2 id="status-heading" className="text-lg font-medium text-ink">
              System status
            </h2>
            <button
              onClick={handleRefresh}
              disabled={loading}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs sm:text-sm font-medium text-ink bg-surface border border-rule rounded-[4px] hover:bg-paper transition-colors disabled:opacity-50"
            >
              <RefreshCw
                className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`}
                aria-hidden="true"
              />
              <span>Refresh</span>
            </button>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm border-collapse">
              <thead>
                <tr className="border-b border-rule">
                  <th scope="col" className="py-2.5 font-medium text-slate">
                    Component
                  </th>
                  <th scope="col" className="py-2.5 font-medium text-slate">
                    Details
                  </th>
                  <th
                    scope="col"
                    className="py-2.5 text-right font-medium text-slate"
                  >
                    Status
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-rule">
                <tr>
                  <td className="py-3 font-medium text-ink">Frontend</td>
                  <td className="py-3 text-slate">Next.js App Router</td>
                  <td className="py-3 text-right">
                    {renderStatusBadge("ok", "verified")}
                  </td>
                </tr>
                <tr>
                  <td className="py-3 font-medium text-ink">Backend API</td>
                  <td className="py-3 text-slate font-mono text-xs">
                    {health ? `v${health.version}` : "—"}
                  </td>
                  <td className="py-3 text-right">
                    {renderStatusBadge(backendState.label, backendState.type)}
                  </td>
                </tr>
                <tr>
                  <td className="py-3 font-medium text-ink">Database</td>
                  <td className="py-3 text-slate">PostgreSQL 16</td>
                  <td className="py-3 text-right">
                    {renderStatusBadge(dbState.label, dbState.type)}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          {error && (
            <div
              className="mt-4 pt-3 border-t border-rule text-conflict text-sm font-medium"
              role="alert"
            >
              {error}
            </div>
          )}
        </section>

        {health && (
          <footer className="text-xs text-slate space-y-1">
            <p>
              API Service: {health.service} (v{health.version})
            </p>
            <p className="font-mono">Server Time: {health.time}</p>
          </footer>
        )}
      </div>
    </main>
  );
}
