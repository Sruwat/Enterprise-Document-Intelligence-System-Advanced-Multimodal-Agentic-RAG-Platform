"use client";

import Link from "next/link";
import { ArrowRight, CheckCircle2, FileText, MessageSquareText, ShieldCheck, UploadCloud, Zap, LockKeyhole, ScanSearch } from "lucide-react";
import { useEffect, useState } from "react";
import { apiRequest } from "../lib/api";
import { useAuth } from "../lib/auth";
import { IndustryPack } from "../lib/types";
import { useWorkspace } from "../lib/workspace-state";
import { ReadinessPanel } from "./ReadinessPanel";

export function DashboardPanel() {
  const { documents, jobs, readiness, observability, refreshReadiness } = useWorkspace();
  const { token } = useAuth();
  const [industryPacks, setIndustryPacks] = useState<IndustryPack[]>([]);
  const indexedDocs = documents.filter((document) => ["indexed", "ready", "completed"].includes(document.status)).length;

  useEffect(() => {
    if (!token) return;
    apiRequest<IndustryPack[]>("/industry-packs", token)
      .then(setIndustryPacks)
      .catch(() => setIndustryPacks([]));
  }, [token]);

  return (
    <div className="screen-grid dashboard-grid">
      <section className="page-heading dashboard-heading">
        <div className="heading-copy"><span>Private document intelligence</span><h1>Grounded answers across contracts, research, policies, charts, and scanned pages.</h1><p>One workspace to ask, inspect, and govern the knowledge your business cannot afford to lose.</p></div>
        <div className="heading-rail"><div><LockKeyhole size={17} /><strong>Captive Data</strong><span>Lifecycle visibility from upload to deletion.</span></div><div><ScanSearch size={17} /><strong>Evidence first</strong><span>Answers stay close to their sources.</span></div></div>
      </section>
      <div className="metric-row">
        <Metric label="Sources" value={documents.length} icon={<FileText size={18} />} />
        <Metric label="Indexed" value={indexedDocs} icon={<CheckCircle2 size={18} />} />
        <Metric label="Jobs" value={jobs.length} icon={<Zap size={18} />} />
        <Metric label="P95 latency" value={observability?.latency?.p95_ms ? `${Math.round(observability.latency.p95_ms)}ms` : "n/a"} icon={<ShieldCheck size={18} />} />
      </div>
      <section className="quick-actions">
        <Link href="/sources"><UploadCloud size={18} /> Upload sources</Link>
        <Link href="/chat"><MessageSquareText size={18} /> Ask a question</Link>
        <Link href="/evidence"><ShieldCheck size={18} /> Inspect evidence</Link>
        <Link href="/data-vault"><ShieldCheck size={18} /> Check data vault</Link>
      </section>
      <section className="dashboard-callout"><div><span className="section-kicker">Why Aiwana</span><h2>Your documents. Your vectors. Your retention. Your control.</h2><p>Explore the platform story and the workflows it is designed to support.</p></div><div className="callout-actions"><Link href="/features">Explore features <ArrowRight size={15} /></Link><Link href="/usage">See use cases <ArrowRight size={15} /></Link></div></section>
      <section className="admin-card">
        <div className="panel-head"><strong>Industry packs</strong><span>Starting profiles for common document-heavy teams.</span></div>
        <div className="industry-grid">
          {industryPacks.length ? industryPacks.map((pack) => (
            <div className="industry-card" key={pack.pack_id}>
              <strong>{pack.label}</strong>
              <span>{pack.query_mode} mode / {pack.data_boundary.replaceAll("_", " ")}</span>
              <small>{pack.extraction_focus.slice(0, 5).join(", ")}</small>
            </div>
          )) : <div className="empty-state">Industry packs load after authentication.</div>}
        </div>
      </section>
      <ReadinessPanel readiness={readiness} onRefresh={refreshReadiness} />
    </div>
  );
}

function Metric({ label, value, icon }: { label: string; value: string | number; icon: React.ReactNode }) {
  return (
    <div className="metric-card">
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
