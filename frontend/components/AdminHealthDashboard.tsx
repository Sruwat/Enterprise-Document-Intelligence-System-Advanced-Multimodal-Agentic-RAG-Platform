"use client";

type ReadinessReport = {
  status: "ready" | "warning" | "blocked";
};

type ObservabilitySnapshot = {
  components?: Record<string, any>;
  retrieval?: { cache_hit_rate?: number; blocked_answer_rate?: number };
};

type AdminHealthDashboardProps = {
  readiness: ReadinessReport | null;
  observability: ObservabilitySnapshot | null;
  busy: boolean;
  onRefresh: () => void;
};

export function AdminHealthDashboard({ readiness, observability, busy, onRefresh }: AdminHealthDashboardProps) {
  return (
    <section className="documents-card admin-card">
      <div className="card-head">
        <div>
          <strong>Production health</strong>
          <span>Readiness, cache, graph, worker, and provider signals</span>
        </div>
        <button onClick={onRefresh} disabled={busy}>Refresh</button>
      </div>
      <div className="health-grid">
        <HealthMetric label="Readiness" value={readiness?.status || "unknown"} />
        <HealthMetric label="Worker" value={String(observability?.components?.worker?.status || "unknown")} />
        <HealthMetric label="Cache hit" value={`${Math.round((observability?.retrieval?.cache_hit_rate || 0) * 100)}%`} />
        <HealthMetric label="Blocked" value={`${Math.round((observability?.retrieval?.blocked_answer_rate || 0) * 100)}%`} />
        <HealthMetric label="Graph lift" value={String(observability?.components?.graph_eval?.lift ?? "n/a")} />
        <HealthMetric label="HF" value={String(observability?.components?.huggingface?.enabled ? `${observability?.components?.huggingface?.ready_count || 0} ready` : "disabled")} />
      </div>
    </section>
  );
}

function HealthMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="health-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
