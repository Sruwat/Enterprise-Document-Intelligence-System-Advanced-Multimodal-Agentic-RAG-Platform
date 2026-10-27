"use client";

import { ChangeEvent, useState } from "react";
import { FileText, RefreshCw, UploadCloud } from "lucide-react";
import { previewUrl } from "../lib/api";
import { useWorkspace } from "../lib/workspace-state";

export function SourcesPanel() {
  const [files, setFiles] = useState<FileList | null>(null);
  const [selectedDocument, setSelectedDocument] = useState<string | null>(null);
  const { workspaceId, documents, jobs, busy, uploadSources, refreshJobs } = useWorkspace();
  const activeDocument = documents.find((document) => document.document_id === selectedDocument) || documents[0];

  function selectFiles(event: ChangeEvent<HTMLInputElement>) {
    setFiles(event.target.files);
  }

  return (
    <div className="sources-screen">
      <section className="upload-panel">
        <div className="panel-head">
          <strong>Upload center</strong>
          <span>PDF, Word, spreadsheet, slides, image, text, and markdown sources.</span>
        </div>
        <label className="dropzone">
          <UploadCloud size={24} />
          <strong>{files?.length ? `${files.length} source file(s)` : "Choose source files"}</strong>
          <span>Documents are sent to the existing ingestion API.</span>
          <input type="file" multiple accept=".pdf,.docx,.csv,.xlsx,.pptx,.png,.jpg,.jpeg,.webp,.bmp,.tiff,.txt,.md" onChange={selectFiles} />
        </label>
        <button className="primary-action" onClick={() => files && void uploadSources(files)} disabled={busy || !files?.length}>
          <UploadCloud size={18} /> Index sources
        </button>
      </section>

      <section className="documents-panel">
        <div className="panel-head row">
          <div>
            <strong>Document explorer</strong>
            <span>{documents.length ? `${documents.length} workspace source(s)` : "No sources loaded yet."}</span>
          </div>
          <button className="ghost-button" onClick={() => void refreshJobs()} disabled={busy || !jobs.length}><RefreshCw size={16} /> Refresh jobs</button>
        </div>
        {!!jobs.length && <IngestionTimeline />}
        <div className="source-list">
          {documents.length ? documents.map((document) => (
            <button key={document.document_id} className={`source-card ${activeDocument?.document_id === document.document_id ? "active" : ""}`} onClick={() => setSelectedDocument(document.document_id)}>
              <FileText size={17} />
              <strong>{document.filename}</strong>
              <span>{document.page_count} page(s) / {document.status}</span>
            </button>
          )) : <div className="empty-state">Upload source files to build a grounded workspace.</div>}
        </div>
      </section>

      <section className="preview-panel">
        <div className="panel-head">
          <strong>Document preview</strong>
          <span>First-page preview when the backend has rendered pages.</span>
        </div>
        {activeDocument ? (
          <>
            <img className="document-preview" src={previewUrl(workspaceId, activeDocument.document_id, 1)} alt={`${activeDocument.filename} page 1 preview`} />
            <OcrStatusCard status={activeDocument.status} />
          </>
        ) : (
          <div className="empty-state">Select a document to preview extracted pages and status.</div>
        )}
      </section>
    </div>
  );
}

export function IngestionTimeline() {
  const { jobs } = useWorkspace();
  return (
    <div className="timeline">
      {jobs.slice(0, 6).map((job) => (
        <div className="timeline-row" key={job.job_id}>
          <div>
            <strong>{job.filename}</strong>
            <span>{job.status}{job.message ? ` / ${job.message}` : ""}</span>
          </div>
          <progress value={job.progress || 0} max={100} />
        </div>
      ))}
    </div>
  );
}

function OcrStatusCard({ status }: { status: string }) {
  return (
    <div className="ocr-card">
      <strong>OCR and parser status</strong>
      <span>{status}</span>
      <button disabled>Retry failed pages</button>
    </div>
  );
}
