"use client";

import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, LoaderCircle } from "lucide-react";
import { Header } from "../components/Header";

type Health = {
  status: string;
  service: string;
  version: string;
  time: string;
  db: string;
};

export default function StatusPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    fetch(`${base}/health`)
      .then(async (response) => {
        if (!response.ok) throw new Error(`Health check returned ${response.status}`);
        return response.json() as Promise<Health>;
      })
      .then(setHealth)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Health check failed."))
      .finally(() => setLoading(false));
  }, []);

  const healthy = health?.status === "ok" && health.db === "ok";

  return (
    <>
      <Header />
      <main className="page-shell">
        <div className="page-heading">
          <div>
            <p className="eyebrow">Operations</p>
            <h1>System status</h1>
            <p className="lede">Live availability for the ClaimGraph API and database.</p>
          </div>
        </div>
        {loading && <div className="empty-state"><LoaderCircle className="spin" /> Checking services</div>}
        {error && <div className="alert alert-error" role="alert"><AlertCircle size={18} /> {error}</div>}
        {health && (
          <section className="status-card" aria-live="polite">
            <div className={`status ${healthy ? "status-verified" : "status-attention"}`}>
              {healthy ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
              {healthy ? "All systems operational" : "Attention required"}
            </div>
            <dl className="status-details">
              <div><dt>API service</dt><dd>{health.service}</dd></div>
              <div><dt>Database</dt><dd>{health.db}</dd></div>
              <div><dt>Version</dt><dd>{health.version}</dd></div>
              <div><dt>Checked</dt><dd>{new Date(health.time).toLocaleString()}</dd></div>
            </dl>
          </section>
        )}
      </main>
    </>
  );
}
