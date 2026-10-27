"use client";

import { AlertCircle, BrainCircuit, Network, PanelRight, ShieldCheck } from "lucide-react";
import { previewUrl } from "../lib/api";
import { EvidenceCanvas } from "../lib/types";
import { useWorkspace } from "../lib/workspace-state";

export function EvidencePanel() {
  const { latestCanvas, latestAgentRun, workspaceId } = useWorkspace();
  return (
    <div className="evidence-screen">
      <section className="page-heading compact">
        <span>Evidence canvas</span>
        <h1>Inspect citations, artifacts, graph evidence, and verification status.</h1>
      </section>
      {latestCanvas ? <EvidenceCanvasView canvas={latestCanvas} workspaceId={workspaceId} agentSteps={latestAgentRun?.steps || []} /> : <EmptyEvidence />}
    </div>
  );
}

export function EvidenceCanvasView({ canvas, workspaceId, agentSteps = [] }: { canvas: EvidenceCanvas; workspaceId: string; agentSteps?: { agent_name: string; action: string; output_summary?: string }[] }) {
  const steps = canvas.agent_steps?.length ? canvas.agent_steps : agentSteps;
  const confidence = Math.round((canvas.confidence || 0) * 100);
  return (
    <div className="evidence-grid">
      <section className="confidence-card">
        <strong>{confidence}%</strong>
        <span>confidence</span>
        {canvas.why_this_answer && <p>{canvas.why_this_answer}</p>}
      </section>

      <section className="evidence-column">
        <SectionTitle icon={<PanelRight size={17} />} title="Citations" />
        {canvas.citations?.length ? canvas.citations.map((citation) => (
          <a className="citation-card" key={citation.chunk_id} href={citation.document_id ? previewUrl(workspaceId, citation.document_id, citation.page_number) : "#"} target="_blank" rel="noreferrer">
            {citation.document_id && <img src={previewUrl(workspaceId, citation.document_id, citation.page_number)} alt={`${citation.filename} page ${citation.page_number}`} />}
            <strong>{citation.filename}</strong>
            <span>Page {citation.page_number} / {citation.content_type || "text"}</span>
            <p>{citation.snippet}</p>
          </a>
        )) : <div className="empty-state">No citations returned.</div>}
      </section>

      <section className="evidence-column">
        <SectionTitle icon={<Network size={17} />} title="Graph evidence" />
        {canvas.graph_contribution ? <pre className="json-card">{JSON.stringify(canvas.graph_contribution, null, 2)}</pre> : <div className="empty-state">No graph evidence returned for this answer.</div>}
        {!!canvas.missing_evidence?.length && (
          <div className="warning-note"><AlertCircle size={16} /><span>{canvas.missing_evidence.join(" ")}</span></div>
        )}
      </section>

      <section className="evidence-column">
        <SectionTitle icon={<ShieldCheck size={17} />} title="Artifacts" />
        {canvas.artifact_cards?.length ? canvas.artifact_cards.map((card) => (
          <div className="artifact-card" key={card.artifact_id}>
            <strong>{card.title}</strong>
            <span>{card.artifact_type} / p.{card.page_number}{card.severity ? ` / ${card.severity}` : ""}</span>
            {card.text && <p>{Array.isArray(card.text) ? card.text.join(" | ") : card.text}</p>}
          </div>
        )) : <div className="empty-state">No extracted artifacts for the latest answer.</div>}
      </section>

      <section className="evidence-column">
        <SectionTitle icon={<BrainCircuit size={17} />} title="Agent trace" />
        {steps.length ? steps.slice(0, 8).map((step, index) => (
          <div className="agent-step" key={`${step.agent_name}-${index}`}>
            <BrainCircuit size={15} />
            <div><strong>{step.agent_name}</strong><span>{step.output_summary || step.action}</span></div>
          </div>
        )) : <div className="empty-state">No agent trace has been returned yet.</div>}
      </section>
    </div>
  );
}

function SectionTitle({ icon, title }: { icon: React.ReactNode; title: string }) {
  return <h2 className="section-title">{icon}{title}</h2>;
}

function EmptyEvidence() {
  return (
    <div className="full-empty">
      <ShieldCheck size={28} />
      <strong>No answer selected yet</strong>
      <span>Ask a question in chat to see citations, graph evidence, confidence, and verifier notes here.</span>
    </div>
  );
}
