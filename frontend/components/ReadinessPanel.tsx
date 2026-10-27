"use client";

import { Activity } from "lucide-react";
import { ReadinessReport } from "../lib/types";

export function ReadinessPanel({ readiness, onRefresh }: { readiness: ReadinessReport | null; onRefresh: () => void }) {
  const visibleChecks = readiness?.checks.filter((check) => check.status !== "ok").slice(0, 6) || [];
  return (
    <section className={`readiness-panel ${readiness?.status || "warning"}`}>
      <div className="panel-head row">
        <div><strong>Launch readiness</strong><span>{readiness?.summary || "Backend readiness has not loaded yet."}</span></div>
        <button className="ghost-button" onClick={onRefresh}><Activity size={16} /> Check</button>
      </div>
      <div className="metric-row compact">
        <div className="mini-metric"><span>Status</span><strong>{readiness?.status || "unknown"}</strong></div>
        <div className="mini-metric"><span>Blockers</span><strong>{readiness?.blocker_count ?? "n/a"}</strong></div>
        <div className="mini-metric"><span>Warnings</span><strong>{readiness?.warning_count ?? "n/a"}</strong></div>
      </div>
      {visibleChecks.map((check) => <div className={`readiness-check ${check.status}`} key={check.name}><strong>{check.name}</strong><span>{check.message}</span></div>)}
    </section>
  );
}
