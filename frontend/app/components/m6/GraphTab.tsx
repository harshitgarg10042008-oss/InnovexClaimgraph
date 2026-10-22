"use client";

/**
 * PART 2: Graph Tab — @xyflow/react visualisation of document links.
 *
 * - Nodes sourced from GET /cases/{id}/graph
 * - Deterministic column layout: PO | Delivery | Invoice | Payment | Adjustment
 * - Edge style by status: solid (auto_linked/confirmed), dashed (suggested), conflict colour
 * - Side panel on node/edge click with Confirm/Reject for suggested/conflict
 * - TanStack Query for data fetching; invalidates after confirm/reject and recalculates
 */

import { useCallback, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ReactFlow,
  Background,
  Controls,
  Panel,
  useNodesState,
  useEdgesState,
  useReactFlow,
  ReactFlowProvider,
  type Node,
  type Edge,
  type NodeTypes,
  type EdgeTypes,
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  FileText,
  Info,
  Loader2,
  X,
  XCircle,
} from "lucide-react";
import { apiClient } from "@/lib/api/client";
import { fmtDate, fmtINR, fmtNum } from "./shared";
import type { GraphResponse, GraphNode, LinkResponse } from "./shared";
import {
  BlockedPanel,
  NoDataPanel,
  ProvisionalBanner,
  StaleBanner,
} from "./LinkingPanel";

/* ------------------------------------------------------------------ */
/* Column order for deterministic layout                               */
/* ------------------------------------------------------------------ */
const COLUMN_ORDER = ["po", "delivery", "invoice", "payment", "adjustment"];
const COL_WIDTH = 220;
const COL_GAP = 70;
const ROW_HEIGHT = 135;
const NODE_H = 115;

function typeToCol(type: string): number {
  const t = type.toLowerCase();
  if (t.includes("po") || t.includes("order")) return 0;
  if (t.includes("deliver") || t.includes("challan") || t.includes("receipt") || t.includes("grn")) return 1;
  if (t.includes("invoice") || t.includes("bill")) return 2;
  if (t.includes("payment") || t.includes("pay")) return 3;
  if (t.includes("tds") || t.includes("adjust") || t.includes("advance") || t.includes("note") || t.includes("credit") || t.includes("debit")) return 4;
  return COLUMN_ORDER.indexOf(t) >= 0 ? COLUMN_ORDER.indexOf(t) : 5;
}

function computePositions(nodes: GraphNode[]): Map<string, { x: number; y: number }> {
  const colCount: Record<number, number> = {};
  const result = new Map<string, { x: number; y: number }>();

  for (const n of nodes) {
    const col = typeToCol(n.type ?? "");
    const row = colCount[col] ?? 0;
    colCount[col] = row + 1;
    result.set(n.id, {
      x: col * (COL_WIDTH + COL_GAP) + 30,
      y: row * ROW_HEIGHT + 30,
    });
  }
  return result;
}

/* ------------------------------------------------------------------ */
/* Node card                                                            */
/* ------------------------------------------------------------------ */
function statusIcon(status: string | undefined) {
  if (!status) return <Info size={11} />;
  const s = status.toLowerCase();
  if (s.includes("confirm") || s.includes("verified") || s.includes("ok") || s === "auto_linked")
    return <CheckCircle2 size={11} />;
  if (s.includes("conflict")) return <XCircle size={11} />;
  if (s.includes("suggest") || s.includes("pending")) return <AlertCircle size={11} />;
  return <Info size={11} />;
}

function nodeStatusClass(status: string | undefined): string {
  if (!status) return "";
  const s = status.toLowerCase();
  if (s.includes("conflict")) return "node-status-conflict";
  if (s.includes("suggest") || s.includes("pending")) return "node-status-attention";
  if (s.includes("confirm") || s === "auto_linked" || s === "verified") return "node-status-verified";
  return "";
}

function GraphNodeCard({
  data,
  selected,
}: {
  data: Record<string, unknown>;
  selected: boolean;
}) {
  const rawType = String(data.type ?? data.doc_type ?? "").toLowerCase();
  let typeLabel = "Document";
  if (rawType === "po" || rawType.includes("order")) typeLabel = "Purchase Order";
  else if (rawType === "delivery" || rawType.includes("challan")) typeLabel = "Delivery Challan";
  else if (rawType === "invoice") typeLabel = "Tax Invoice";
  else if (rawType === "payment") typeLabel = "Payment";
  else if (rawType === "adjustment" || rawType === "tds") typeLabel = "Adjustment";
  else if (data.label && typeof data.label === "string") {
    typeLabel = String(data.label).split(" ")[0];
  }

  const ref = String(data.number ?? data.reference_number ?? data.reference ?? data.ref ?? "");

  let displayAmount: string | null = null;
  if (data.amount != null) {
    const raw = String(data.amount).replace(/,/g, "");
    const n = parseFloat(raw);
    displayAmount = isFinite(n) ? fmtINR(n) : String(data.amount);
  }

  const qty = data.quantity != null ? `${String(data.quantity)} units` : null;
  const date = fmtDate(data.date as string | undefined ?? data.doc_date as string | undefined);
  const status = String(data.status ?? "");

  return (
    <div className={`graph-node-card ${selected ? "selected" : ""} ${nodeStatusClass(status)}`}>
      <div className="graph-node-type">{typeLabel}</div>
      {ref && <code className="graph-node-ref">{ref}</code>}
      <div className="graph-node-amount">
        {displayAmount ?? qty ?? "\u2013"}
      </div>
      <div className="graph-node-date">{date}</div>
      <div className={`graph-node-status ${nodeStatusClass(status)}`}>
        {statusIcon(status)}
        <span>{status.replace(/_/g, " ") || "\u2013"}</span>
      </div>
    </div>
  );
}

const nodeTypes: NodeTypes = {
  default: ({ data, selected }: { data: Record<string, unknown>; selected: boolean }) => (
    <GraphNodeCard data={data} selected={selected} />
  ),
};

/* ------------------------------------------------------------------ */
/* Custom edge with label                                              */
/* ------------------------------------------------------------------ */
function edgeStyle(data: Record<string, unknown>) {
  const status = String(data.status ?? data.link_status ?? "").toLowerCase();
  if (status.includes("conflict")) {
    return { stroke: "var(--color-conflict)", strokeWidth: 2.5 };
  }
  if (status.includes("suggest")) {
    return { stroke: "var(--color-attention)", strokeWidth: 1.5, strokeDasharray: "5,4" };
  }
  if (status.includes("confirm") || status === "auto_linked") {
    return { stroke: "var(--color-slate)", strokeWidth: 1.5 };
  }
  return { stroke: "var(--color-slate)", strokeWidth: 1.5 };
}

function ClaimEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  selected,
}: {
  id: string;
  sourceX: number;
  sourceY: number;
  targetX: number;
  targetY: number;
  sourcePosition: import("@xyflow/react").Position;
  targetPosition: import("@xyflow/react").Position;
  data?: Record<string, unknown>;
  selected?: boolean;
}) {
  const d = data ?? {};
  const [path, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  });
  const style = edgeStyle(d);
  const method = String(d.method ?? "");
  const confidence = d.confidence != null ? Number(d.confidence) : null;
  const score = confidence != null && confidence < 1.0 ? `(${confidence.toFixed(2)})` : "";

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        style={{ ...style, opacity: selected ? 1 : 0.8 }}
      />
      {(method || score) && (
        <EdgeLabelRenderer>
          <div
            className="graph-edge-label"
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              pointerEvents: "all",
            }}
          >
            <span>{method}</span>
            {score && <span className="edge-score">{score}</span>}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

const edgeTypes: EdgeTypes = {
  default: ClaimEdge as unknown as EdgeTypes["default"],
};

/* ------------------------------------------------------------------ */
/* Side panel for selected node or edge                                */
/* ------------------------------------------------------------------ */
function SidePanel({
  item,
  type,
  caseId,
  onClose,
  onOpenEvidence,
}: {
  item: Node | Edge;
  type: "node" | "edge";
  caseId: string;
  onClose: () => void;
  onOpenEvidence?: (docId: string, page: number, bbox?: number[] | null) => void;
}) {
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [confirmNote, setConfirmNote] = useState("");
  const [showConfirmDialog, setShowConfirmDialog] = useState(false);
  const [showRejectDialog, setShowRejectDialog] = useState(false);
  const [mutErr, setMutErr] = useState<string | null>(null);

  // Link ID: strips the 'e_' prefix from edge IDs so it matches the backend UUID
  const linkId = type === "edge" ? String(item.id).replace(/^e_/, "") : null;
  const data = (item.data as Record<string, unknown>) ?? {};
  const status = String(data.status ?? data.link_status ?? "");
  const isSuggested = status.toLowerCase().includes("suggest");
  const isConflict = status.toLowerCase().includes("conflict");
  const canAction = (isSuggested || isConflict) && linkId;

  const doConfirm = async () => {
    if (!linkId) return;
    setConfirming(true);
    setMutErr(null);
    try {
      await apiClient<LinkResponse>(`/cases/${caseId}/links/${linkId}/confirm`, {
        method: "POST",
        headers: { "X-Reviewer": "reviewer" },
      });
      // Recalculate ledger so ledger_status becomes final with numbers preserved
      await apiClient(`/cases/${caseId}/link/run`, {
        method: "POST",
        headers: { "X-Reviewer": "reviewer" },
      });
      await qc.invalidateQueries({ queryKey: ["graph", caseId] });
      await qc.invalidateQueries({ queryKey: ["ledger", caseId] });
      await qc.invalidateQueries({ queryKey: ["findings", caseId] });
      setShowConfirmDialog(false);
      onClose();
    } catch (e) {
      setMutErr(e instanceof Error ? e.message : "Confirm failed.");
    } finally {
      setConfirming(false);
    }
  };

  const doReject = async () => {
    if (!linkId) return;
    setRejecting(true);
    setMutErr(null);
    try {
      await apiClient<LinkResponse>(`/cases/${caseId}/links/${linkId}/reject`, {
        method: "POST",
        headers: { "X-Reviewer": "reviewer" },
      });
      // Recalculate ledger
      await apiClient(`/cases/${caseId}/link/run`, {
        method: "POST",
        headers: { "X-Reviewer": "reviewer" },
      });
      await qc.invalidateQueries({ queryKey: ["graph", caseId] });
      await qc.invalidateQueries({ queryKey: ["ledger", caseId] });
      await qc.invalidateQueries({ queryKey: ["findings", caseId] });
      setShowRejectDialog(false);
      onClose();
    } catch (e) {
      setMutErr(e instanceof Error ? e.message : "Reject failed.");
    } finally {
      setRejecting(false);
    }
  };

  const refs: Record<string, unknown>[] = Array.isArray(data.source_refs)
    ? (data.source_refs as Record<string, unknown>[])
    : Array.isArray(data.refs)
      ? (data.refs as Record<string, unknown>[])
      : [];

  return (
    <aside className="graph-side-panel">
      <div className="graph-side-panel-header">
        <h2 className="graph-side-panel-title">
          {type === "node" ? "Document details" : "Link details"}
        </h2>
        <button
          type="button"
          className="icon-btn-compact"
          onClick={onClose}
          aria-label="Close panel"
        >
          <X size={15} />
        </button>
      </div>

      {mutErr && (
        <div className="m6-error-toast" role="alert">
          <AlertTriangle size={13} />
          <span>{mutErr}</span>
        </div>
      )}

      <dl className="side-panel-dl">
        {Object.entries(data).map(([k, v]) => {
          if (k === "refs" || k === "source_refs" || k === "source_fact_ids" || v === null || v === undefined || typeof v === "object") return null;
          return (
            <div key={k}>
              <dt>{k.replace(/_/g, " ")}</dt>
              <dd className={k === "id" || k.endsWith("_id") || k === "number" ? "mono-ref" : ""}>
                {String(v)}
              </dd>
            </div>
          );
        })}
      </dl>

      {/* Confirmed metadata if returned */}
      {Boolean(data.confirmed_by) && (
        <div className="side-panel-meta" style={{ fontSize: "0.76rem", color: "var(--color-slate)", padding: "8px 0" }}>
          Confirmed by {String(data.confirmed_by)}
          {data.confirmed_at ? ` on ${fmtDate(String(data.confirmed_at))}` : ""}
        </div>
      )}

      {refs.length > 0 && (
        <div className="side-panel-refs">
          <h3>Source references</h3>
          {refs.map((ref, i) => {
            const docId = String(ref.doc_id ?? ref.document_id ?? "");
            const page = Number(ref.page ?? ref.page_no ?? 1);
            const bbox = (ref.bbox as number[] | null | undefined) ?? null;
            const hasBbox = Boolean(bbox);
            return (
              <button
                key={i}
                type="button"
                className="ref-button"
                onClick={() => onOpenEvidence?.(docId, page, bbox)}
              >
                <FileText size={13} />
                <span>
                  Doc …{docId.slice(-6)} p.{page}
                </span>
                {!hasBbox && (
                  <span className="ref-no-bbox">(location not available)</span>
                )}
                <ChevronRight size={12} />
              </button>
            );
          })}
        </div>
      )}

      {canAction && (
        <div className="side-panel-actions">
          {/* Confirm dialog */}
          {showConfirmDialog ? (
            <div className="confirm-dialog">
              <label className="confirm-dialog-label">
                Note (optional)
                <input
                  type="text"
                  value={confirmNote}
                  onChange={(e) => setConfirmNote(e.target.value)}
                  placeholder="Add a one-line note…"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") doConfirm();
                    if (e.key === "Escape") setShowConfirmDialog(false);
                  }}
                  autoFocus
                />
              </label>
              <div className="confirm-dialog-btns">
                <button
                  type="button"
                  className="button button-dark"
                  onClick={doConfirm}
                  disabled={confirming}
                >
                  {confirming ? <Loader2 size={13} className="spin" /> : <CheckCircle2 size={13} />}
                  <span>Confirm link</span>
                </button>
                <button
                  type="button"
                  className="button"
                  onClick={() => setShowConfirmDialog(false)}
                  disabled={confirming}
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : showRejectDialog ? (
            <div className="confirm-dialog">
              <p style={{ fontSize: "0.8rem", margin: "0 0 8px", color: "var(--color-conflict)" }}>
                Reject this proposed link?
              </p>
              <div className="confirm-dialog-btns">
                <button
                  type="button"
                  className="button"
                  style={{ borderColor: "var(--color-conflict)", color: "var(--color-conflict)" }}
                  onClick={doReject}
                  disabled={rejecting}
                >
                  {rejecting ? <Loader2 size={13} className="spin" /> : <XCircle size={13} />}
                  <span>Reject link</span>
                </button>
                <button
                  type="button"
                  className="button"
                  onClick={() => setShowRejectDialog(false)}
                  disabled={rejecting}
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <div className="side-panel-action-btns">
              <button
                type="button"
                className="button button-dark"
                onClick={() => setShowConfirmDialog(true)}
              >
                <CheckCircle2 size={13} />
                <span>Confirm link</span>
              </button>
              <button
                type="button"
                className="button"
                style={{ borderColor: "var(--color-conflict)", color: "var(--color-conflict)" }}
                onClick={() => setShowRejectDialog(true)}
              >
                <XCircle size={13} />
                <span>Reject link</span>
              </button>
            </div>
          )}
        </div>
      )}
    </aside>
  );
}

/* ------------------------------------------------------------------ */
/* Legend                                                              */
/* ------------------------------------------------------------------ */
function GraphLegend() {
  return (
    <div className="graph-legend">
      <div className="legend-item">
        <span className="legend-line legend-solid" />
        <span>Auto-linked / Confirmed</span>
      </div>
      <div className="legend-item">
        <span className="legend-line legend-dashed" />
        <span>Suggested</span>
      </div>
      <div className="legend-item">
        <span className="legend-line legend-conflict" />
        <span>Conflict</span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Graph flow inner (needs ReactFlowProvider wrapper)                  */
/* ------------------------------------------------------------------ */
function GraphFlow({
  graphData,
  caseId,
  filterMode,
  onOpenEvidence,
}: {
  graphData: GraphResponse;
  caseId: string;
  filterMode: "all" | "attention";
  onOpenEvidence?: (docId: string, page: number, bbox?: number[] | null) => void;
}) {
  const { fitView } = useReactFlow();
  const [selectedItem, setSelectedItem] = useState<{
    item: Node | Edge;
    type: "node" | "edge";
  } | null>(null);

  // Deterministic positions computed by type and index
  const positions = useMemo(
    () => computePositions(graphData.nodes),
    [graphData.nodes]
  );

  // Map API nodes → React Flow nodes
  const rfNodes = useMemo<Node[]>(() => {
    const raw = graphData.nodes.map((n) => {
      const pos = positions.get(n.id) ?? { x: 0, y: 0 };
      const data: Record<string, unknown> = {
        ...(n.data as Record<string, unknown>),
        type: n.type,
      };
      const status = String(data.status ?? data.link_status ?? "");
      if (filterMode === "attention") {
        const s = status.toLowerCase();
        if (!s.includes("suggest") && !s.includes("conflict")) return null;
      }
      return {
        id: n.id,
        type: "default",
        position: pos,
        data,
        style: { width: COL_WIDTH, height: NODE_H },
      };
    });
    return raw.filter(Boolean) as Node[];
  }, [graphData.nodes, positions, filterMode]);

  // Map API edges → React Flow edges
  const rfEdges = useMemo<Edge[]>(() => {
    const visibleNodeIds = new Set(rfNodes.map((n) => n.id));
    return graphData.edges
      .filter((e) => visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target))
      .map((e) => {
        const data = e.data as Record<string, unknown>;
        const status = String(data.status ?? data.link_status ?? "");
        if (filterMode === "attention") {
          const s = status.toLowerCase();
          if (!s.includes("suggest") && !s.includes("conflict")) return null;
        }
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          type: "default",
          animated: e.animated,
          data,
        };
      })
      .filter(Boolean) as Edge[];
  }, [graphData.edges, rfNodes, filterMode]);

  const [nodes, , onNodesChange] = useNodesState(rfNodes);
  const [edges, , onEdgesChange] = useEdgesState(rfEdges);

  // Fit view once nodes load
  const fitted = useRef(false);
  const onInit = useCallback(() => {
    if (!fitted.current) {
      fitted.current = true;
      setTimeout(() => fitView({ padding: 0.1 }), 50);
    }
  }, [fitView]);

  return (
    <div className="graph-flow-container">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={(_, node) => setSelectedItem({ item: node, type: "node" })}
        onEdgeClick={(_, edge) => setSelectedItem({ item: edge, type: "edge" })}
        onInit={onInit}
        fitView
        minZoom={0.2}
        maxZoom={2.5}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="var(--color-rule)" gap={24} />
        <Controls showInteractive={false} />
        <Panel position="bottom-left">
          <GraphLegend />
        </Panel>
      </ReactFlow>

      {selectedItem && (
        <SidePanel
          item={selectedItem.item}
          type={selectedItem.type}
          caseId={caseId}
          onClose={() => setSelectedItem(null)}
          onOpenEvidence={onOpenEvidence}
        />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Main GraphTab export                                                 */
/* ------------------------------------------------------------------ */
export function GraphTab({
  caseId,
  linkRunResult,
  isBlocked,
  isStale,
  isProvisional,
  provisionalReason,
  onRunLinking,
  runLinkingLoading,
  onJumpToReview,
  onOpenEvidence,
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
  onOpenEvidence?: (docId: string, page: number, bbox?: number[] | null) => void;
}) {
  const [filterMode, setFilterMode] = useState<"all" | "attention">("all");

  const { data: graphData, isLoading, error } = useQuery<GraphResponse>({
    queryKey: ["graph", caseId],
    queryFn: () => apiClient<GraphResponse>(`/cases/${caseId}/graph`),
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
        <p>Loading graph…</p>
      </div>
    );
  }

  if (error || !graphData) {
    return (
      <div className="tab-pane-scroll">
        <NoDataPanel label="Run linking to build the document graph." />
      </div>
    );
  }

  const hasNodes = graphData.nodes.length > 0;
  const effectiveStale = isStale || graphData.stale;

  return (
    <div className="tab-pane-full">
      {/* Banners */}
      {effectiveStale && (
        <StaleBanner onRun={onRunLinking} loading={runLinkingLoading} />
      )}
      {isProvisional && provisionalReason && (
        <ProvisionalBanner reason={provisionalReason} />
      )}

      {/* Filter toggle */}
      <div className="graph-toolbar">
        <div className="segmented-control" role="group" aria-label="Graph filter">
          <button
            type="button"
            className={filterMode === "all" ? "active" : ""}
            onClick={() => setFilterMode("all")}
          >
            All
          </button>
          <button
            type="button"
            className={filterMode === "attention" ? "active" : ""}
            onClick={() => setFilterMode("attention")}
          >
            Needs attention
          </button>
        </div>
        <span className="graph-node-count">
          {graphData.nodes.length} nodes · {graphData.edges.length} links
        </span>
      </div>

      {!hasNodes ? (
        <NoDataPanel label="No graph data. Run linking to build the graph." />
      ) : (
        <div className="graph-flow-wrapper">
          <ReactFlowProvider>
            <GraphFlow
              graphData={graphData}
              caseId={caseId}
              filterMode={filterMode}
              onOpenEvidence={onOpenEvidence}
            />
          </ReactFlowProvider>
        </div>
      )}
    </div>
  );
}
