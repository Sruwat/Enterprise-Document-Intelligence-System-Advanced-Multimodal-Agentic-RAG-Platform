"use client";

import { useEffect, useMemo, useState } from "react";
import { Database, FileText, LockKeyhole, RefreshCw, ShieldCheck, Trash2, GitBranch } from "lucide-react";
import { apiRequest, toMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { DataFootprintSummary, DataLineage, DataVaultOverview, PurgeJobRecord } from "../lib/types";
import { useWorkspace } from "../lib/workspace-state";

type ChunkPreview = {
  chunk_id: string;
  page_number?: number;
  content_type?: string;
  text_preview?: string;
  metadata?: Record<string, unknown>;
};

function formatBytes(value?: number | null) {
  if (value === null || value === undefined) return "Unavailable";
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let next = value / 1024;
  let unit = units[0];
  for (let index = 1; index < units.length && next >= 1024; index += 1) {
    next /= 1024;
    unit = units[index];
  }
  return `${next.toFixed(next >= 10 ? 0 : 1)} ${unit}`;
}

function display(value?: string | number | null) {
  if (value === null || value === undefined || value === "") return "Unavailable";
  return String(value);
}

export function DataVaultPanel() {
  const { token } = useAuth();
  const { workspaceId, documents } = useWorkspace();
  const [overview, setOverview] = useState<DataVaultOverview | null>(null);
  const [purgeJobs, setPurgeJobs] = useState<PurgeJobRecord[]>([]);
  const [chunks, setChunks] = useState<ChunkPreview[]>([]);
  const [lineage, setLineage] = useState<DataLineage | null>(null);
  const [selectedDocumentId, setSelectedDocumentId] = useState<string>("");
  const [externalAllowed, setExternalAllowed] = useState(true);
  const [documentMode, setDocumentMode] = useState("knowledge_base");
  const [classification, setClassification] = useState("internal");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  const selectedFootprint = useMemo(
    () => overview?.documents_footprint.find((item) => item.document_id === selectedDocumentId) || overview?.documents_footprint[0],
    [overview, selectedDocumentId],
  );

  useEffect(() => {
    if (!selectedFootprint) return;
    setSelectedDocumentId(selectedFootprint.document_id);
    setExternalAllowed(Boolean(selectedFootprint.privacy_boundary?.external_processing_allowed ?? true));
    setDocumentMode(selectedFootprint.document_mode || "knowledge_base");
    setClassification(selectedFootprint.classification || "internal");
  }, [selectedFootprint?.document_id]);

  useEffect(() => {
    void refresh();
  }, [workspaceId, token]);

  useEffect(() => {
    void loadChunks();
    void loadLineage();
  }, [selectedDocumentId, token]);

  async function api<T>(path: string, init?: RequestInit) {
    return apiRequest<T>(path, token, init);
  }

  async function refresh() {
    if (!token) return;
    setBusy(true);
    setError("");
    try {
      const [vault, jobs] = await Promise.all([
        api<DataVaultOverview>(`/workspaces/${workspaceId}/data-vault`),
        api<PurgeJobRecord[]>(`/workspaces/${workspaceId}/data-vault/purge-jobs`),
      ]);
      setOverview(vault);
      setPurgeJobs(jobs);
      if (!selectedDocumentId && vault.documents_footprint[0]) setSelectedDocumentId(vault.documents_footprint[0].document_id);
    } catch (cause) {
      setError(toMessage(cause));
      setOverview(null);
    } finally {
      setBusy(false);
    }
  }

  async function loadChunks() {
    if (!token || !selectedDocumentId) {
      setChunks([]);
      return;
    }
    try {
      const payload = await api<{ chunks: ChunkPreview[] }>(`/workspaces/${workspaceId}/data-vault/documents/${selectedDocumentId}/chunks`);
      setChunks(payload.chunks || []);
    } catch {
      setChunks([]);
    }
  }

  async function loadLineage() {
    if (!token || !selectedDocumentId) { setLineage(null); return; }
    try {
      setLineage(await api<DataLineage>(`/workspaces/${workspaceId}/data-vault/documents/${selectedDocumentId}/lineage`));
    } catch { setLineage(null); }
  }

  async function savePolicy() {
    if (!selectedFootprint) return;
    setBusy(true);
    setError("");
    setStatus("");
    try {
      await api<DataFootprintSummary>(`/workspaces/${workspaceId}/data-vault/documents/${selectedFootprint.document_id}/policy`, {
        method: "PATCH",
        body: JSON.stringify({
          document_mode: documentMode,
          classification,
          external_processing_allowed: externalAllowed,
        }),
      });
      setStatus("Document policy updated.");
      await refresh();
    } catch (cause) {
      setError(toMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function purgeDocument() {
    if (!selectedFootprint) return;
    if (!window.confirm(`Purge ${selectedFootprint.filename} from metadata, chunks, vectors, graph links, previews, and managed storage?`)) return;
    setBusy(true);
    setError("");
    setStatus("");
    try {
      const receipt = await api<PurgeJobRecord>(`/workspaces/${workspaceId}/data-vault/documents/${selectedFootprint.document_id}/purge`, {
        method: "POST",
        body: JSON.stringify({ reason: "user_requested_privacy_purge" }),
      });
      setStatus(`Purge ${receipt.status}. Receipt ${receipt.purge_job_id}`);
      setChunks([]);
      await refresh();
    } catch (cause) {
      setError(toMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="data-vault-screen">
      <section className="page-heading compact data-vault-hero">
        <span>Captive data controls</span>
        <h1>Private workspace knowledge, deletion receipts, and processing boundaries.</h1>
        <p>Inspect what Aiwana stores for this workspace before answering industry data-security questions.</p>
      </section>

      {error && <div className="inline-empty error">{error}</div>}
      {status && <div className="status-toast"><ShieldCheck size={16} /> {status}</div>}

      <section className="admin-card vault-overview">
        <div className="panel-head row">
          <div><strong>Workspace data vault</strong><span>{overview ? `${overview.documents} document(s), ${overview.indexed_chunks} chunk(s)` : "Load live storage inventory."}</span></div>
          <button className="ghost-button" onClick={() => void refresh()} disabled={busy}><RefreshCw size={16} /> Refresh</button>
        </div>
        <div className="metric-row compact">
          <Metric label="Original files" value={formatBytes(overview?.original_storage_bytes)} />
          <Metric label="Extracted text" value={formatBytes(overview?.extracted_content_bytes || 0)} />
          <Metric label="Vectors" value={display(overview?.vector_embeddings)} />
          <Metric label="OCR pages" value={display(overview?.ocr_pages || 0)} />
          <Metric label="Graph entities" value={display(overview?.graph_entities)} />
          <Metric label="Pending purges" value={display(overview?.pending_purges || 0)} />
          <Metric label="Expirations" value={display(overview?.retention_expirations || 0)} />
          <Metric label="Privacy mode" value={display(overview?.privacy_mode)} />
        </div>
      </section>

      <section className="admin-card">
        <div className="panel-head">
          <strong><GitBranch size={16} /> Data lineage</strong>
          <span>{lineage ? "Derived from live document, chunk, index, and graph records." : "Select an indexed document to inspect lineage."}</span>
        </div>
        <div className="source-list">
          {lineage?.stages.length ? lineage.stages.map((stage) => (
            <div className="vault-chunk" key={stage.stage}>
              <Database size={16} />
              <div><strong>{stage.stage} / {stage.status}</strong><span>{stage.count !== null && stage.count !== undefined ? `${stage.count} records` : "Count unavailable"}{stage.provider ? ` / ${stage.provider}` : ""}{stage.boundary ? ` / ${stage.boundary}` : ""}</span></div>
            </div>
          )) : <div className="empty-state">No lineage returned for this document.</div>}
        </div>
      </section>

      <section className="documents-panel">
        <div className="panel-head">
          <strong>Protected documents</strong>
          <span>{documents.length ? "Select a document to inspect its footprint." : "No indexed documents returned."}</span>
        </div>
        <div className="source-list">
          {overview?.documents_footprint.length ? overview.documents_footprint.map((item) => (
            <button key={item.document_id} className={`source-card ${item.document_id === selectedFootprint?.document_id ? "active" : ""}`} onClick={() => setSelectedDocumentId(item.document_id)}>
              <FileText size={17} />
              <strong>{item.filename}</strong>
              <span>{item.page_count} page(s) / {item.chunk_count} chunk(s) / {item.classification}</span>
            </button>
          )) : <div className="empty-state">Upload a source before using Data Vault controls.</div>}
        </div>
      </section>

      <section className="admin-card">
        <div className="panel-head">
          <strong>Document footprint</strong>
          <span>{selectedFootprint ? selectedFootprint.filename : "No document selected."}</span>
        </div>
        {selectedFootprint ? (
          <div className="vault-detail-grid">
            <Metric label="Mode" value={selectedFootprint.document_mode} />
            <Metric label="Classification" value={selectedFootprint.classification} />
            <Metric label="Original" value={formatBytes(selectedFootprint.original_bytes)} />
            <Metric label="Extracted" value={formatBytes(selectedFootprint.extracted_text_bytes)} />
            <Metric label="Chunks" value={String(selectedFootprint.chunk_count)} />
            <Metric label="Vectors" value={display(selectedFootprint.vector_count)} />
            <Metric label="Graph facts" value={`${display(selectedFootprint.graph_entity_count)} / ${display(selectedFootprint.graph_relation_count)}`} />
            <Metric label="External AI" value={externalAllowed ? "Allowed" : "Blocked"} />
          </div>
        ) : <div className="empty-state">No footprint available.</div>}
      </section>

      <section className="admin-card">
        <div className="panel-head">
          <strong>Processing policy</strong>
          <span>Controls are persisted on the document metadata record and enforced during indexing.</span>
        </div>
        <div className="auth-grid compact-form">
          <select value={documentMode} onChange={(event) => setDocumentMode(event.target.value)} aria-label="Document mode">
            <option value="knowledge_base">Knowledge base</option>
            <option value="temporary_analysis">Temporary analysis</option>
          </select>
          <select value={classification} onChange={(event) => setClassification(event.target.value)} aria-label="Classification">
            <option value="public">Public</option>
            <option value="internal">Internal</option>
            <option value="confidential">Confidential</option>
            <option value="highly_confidential">Highly confidential</option>
            <option value="regulated">Regulated</option>
          </select>
          <label className="toggle-row"><input type="checkbox" checked={!externalAllowed} onChange={(event) => setExternalAllowed(!event.target.checked)} /> Block external processing</label>
          <button className="ghost-button" onClick={() => void savePolicy()} disabled={busy || !selectedFootprint}><LockKeyhole size={16} /> Save policy</button>
          <button className="danger-button" onClick={() => void purgeDocument()} disabled={busy || !selectedFootprint}><Trash2 size={16} /> Purge document</button>
        </div>
      </section>

      <section className="admin-card">
        <div className="panel-head">
          <strong>Chunk inspection</strong>
          <span>Text previews only. Raw vector values are intentionally not exposed.</span>
        </div>
        <div className="source-list">
          {chunks.length ? chunks.slice(0, 12).map((chunk) => (
            <div className="vault-chunk" key={chunk.chunk_id}>
              <Database size={16} />
              <div><strong>{chunk.content_type || "text"} / page {chunk.page_number || "n/a"}</strong><span>{chunk.text_preview || "No preview text."}</span></div>
            </div>
          )) : <div className="empty-state">No chunk previews available.</div>}
        </div>
      </section>

      <section className="admin-card">
        <div className="panel-head">
          <strong>Purge receipts</strong>
          <span>Audit-safe deletion records for vectors, sparse index, graph links, previews, and metadata.</span>
        </div>
        <div className="source-list">
          {purgeJobs.length ? purgeJobs.map((job) => (
            <div className="key-row" key={job.purge_job_id}>
              <Trash2 size={16} />
              <div><strong>{job.status} / {job.document_id}</strong><span>{job.reason} / {new Date(job.created_at).toLocaleString()}</span></div>
            </div>
          )) : <div className="empty-state">No purge receipts yet.</div>}
        </div>
      </section>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="metric-card"><span>{label}</span><strong>{value}</strong></div>;
}
