"use client";

import { BookOpenCheck, BrainCircuit, Building2, Gavel, Loader2, Send, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Objective } from "../lib/types";
import { useWorkspace } from "../lib/workspace-state";

const objectiveOptions = {
  legal: { label: "Legal", icon: Gavel, line: "Clauses, parties, dates, risks" },
  research: { label: "Research", icon: BookOpenCheck, line: "Findings, charts, recommendations" },
  enterprise: { label: "Enterprise", icon: Building2, line: "Policies, controls, audit trail" },
} satisfies Record<Objective, { label: string; icon: typeof Gavel; line: string }>;

const starterPrompts = [
  "What are the highest risk clauses and exact pages?",
  "Explain the chart and table evidence in simple language.",
  "Give me a research-grade recommendation with assumptions.",
  "Answer in Hinglish and cite the source page.",
];

export function ChatPanel() {
  const [prompt, setPrompt] = useState("");
  const { messages, sendMessage, busy, documents, objective, setObjective, language, setLanguage, analysisMode, setAnalysisMode, queryMode, setQueryMode } = useWorkspace();
  const indexedDocs = documents.filter((document) => ["indexed", "ready", "completed"].includes(document.status)).length;

  async function submit(text = prompt) {
    if (!text.trim()) return;
    setPrompt("");
    await sendMessage(text);
  }

  return (
    <div className="chat-screen">
      <aside className="chat-config">
        <div className="panel-head">
          <strong>Answer mode</strong>
          <span>Visible, grounded agent stages only.</span>
        </div>
        <div className="objective-stack">
          {(Object.keys(objectiveOptions) as Objective[]).map((key) => {
            const item = objectiveOptions[key];
            const Icon = item.icon;
            return (
              <button key={key} className={`objective-option ${objective === key ? "selected" : ""}`} onClick={() => setObjective(key)}>
                <Icon size={18} />
                <strong>{item.label}</strong>
                <span>{item.line}</span>
              </button>
            );
          })}
        </div>
        <label className="field-label">Language
          <select value={language} onChange={(event) => setLanguage(event.target.value)}>
            <option value="auto">Auto</option>
            <option value="english">English</option>
            <option value="hindi">Hindi</option>
            <option value="hinglish">Hinglish</option>
            <option value="spanish">Spanish</option>
          </select>
        </label>
        <label className="field-label">Reasoning
          <select value={analysisMode} onChange={(event) => setAnalysisMode(event.target.value)}>
            <option value="quick">Quick</option>
            <option value="deep">Deep</option>
            <option value="agentic">Agentic</option>
          </select>
        </label>
        <div className="mode-grid" aria-label="Query mode">
          {[
            ["fast", "Fast", "Quick answers from relevant sources."],
            ["balanced", "Balanced", "Best default mix of speed and accuracy."],
            ["deep", "Deep", "More evidence, reranking and multistep reasoning."],
            ["auto", "Auto", "Aiwana selects based on query complexity."],
          ].map(([value, label, description]) => (
            <button key={value} className={`mode-card ${queryMode === value ? "selected" : ""}`} onClick={() => setQueryMode(value as any)}>
              <strong>{label}</strong>
              <span>{description}</span>
            </button>
          ))}
        </div>
      </aside>

      <section className="chat-panel">
        <div className="chat-toolbar">
          <div>
            <strong>Agentic chat</strong>
            <span>{indexedDocs ? `${indexedDocs} indexed source(s) ready` : "Upload sources for grounded answers"}</span>
          </div>
          {busy && <Loader2 className="spin" size={18} />}
        </div>
        {!indexedDocs && <div className="inline-empty"><ShieldCheck size={18} /> No indexed sources yet. You can still ask, but grounded evidence needs uploaded documents.</div>}
        <div className="messages">
          {messages.map((message, index) => (
            <article key={`${message.role}-${index}`} className={`message ${message.role}`}>
              <span>{message.text || (message.role === "assistant" ? "Thinking..." : "")}</span>
              {!!message.stages?.length && (
                <div className="stage-strip">
                  {message.stages.slice(-5).map((stage) => <small key={stage.stage}>{stage.label || stage.stage}{typeof stage.latency_ms === "number" ? ` ${Math.round(stage.latency_ms)}ms` : ""}</small>)}
                </div>
              )}
              {message.groundingStatus && <small className={`grounding ${message.groundingStatus}`}>{message.groundingStatus}</small>}
            </article>
          ))}
        </div>
        <div className="prompt-library">
          {starterPrompts.map((sample) => <button key={sample} onClick={() => void submit(sample)} disabled={busy}>{sample}</button>)}
        </div>
        <div className="composer">
          <BrainCircuit size={18} />
          <input value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void submit(); }} placeholder="Ask about clauses, tables, images, OCR, or previous context" />
          <button onClick={() => void submit()} disabled={busy || !prompt.trim()} aria-label="Send message"><Send size={18} /></button>
        </div>
      </section>
    </div>
  );
}
