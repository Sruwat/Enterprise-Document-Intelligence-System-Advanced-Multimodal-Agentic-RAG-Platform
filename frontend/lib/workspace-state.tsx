"use client";

import { createContext, ReactNode, useContext, useEffect, useMemo, useState } from "react";
import { apiRequest, toMessage } from "./api";
import { streamChatQuery } from "./sse";
import {
  AgentRun,
  ApiKeyRecord,
  ChatMessageRecord,
  ChatSession,
  DocumentRecord,
  EvidenceCanvas,
  IngestionJob,
  Message,
  Objective,
  ObservabilitySnapshot,
  QueryPayload,
  QueryMode,
  ReadinessReport,
  WorkspaceInvitation,
  Workspace,
} from "./types";
import { useAuth } from "./auth";

type WorkspaceContextValue = {
  workspaceId: string;
  setWorkspaceId: (workspaceId: string) => void;
  workspaces: Workspace[];
  documents: DocumentRecord[];
  jobs: IngestionJob[];
  chatSessions: ChatSession[];
  apiKeys: ApiKeyRecord[];
  invitations: WorkspaceInvitation[];
  readiness: ReadinessReport | null;
  observability: ObservabilitySnapshot | null;
  messages: Message[];
  latestCanvas: EvidenceCanvas | null;
  latestAgentRun: AgentRun | null;
  objective: Objective;
  setObjective: (objective: Objective) => void;
  language: string;
  setLanguage: (language: string) => void;
  analysisMode: string;
  setAnalysisMode: (mode: string) => void;
  queryMode: QueryMode;
  setQueryMode: (mode: QueryMode) => void;
  busy: boolean;
  status: string;
  error: string;
  refreshWorkspace: () => Promise<void>;
  refreshReadiness: () => Promise<void>;
  refreshObservability: () => Promise<void>;
  uploadSources: (files: FileList) => Promise<void>;
  refreshJobs: () => Promise<void>;
  sendMessage: (text: string) => Promise<void>;
  startNewChat: () => void;
  openChatSession: (session: ChatSession) => Promise<void>;
  createApiKey: () => Promise<string>;
  revokeApiKey: (keyId: string) => Promise<void>;
  createInvitation: (email: string, role: string) => Promise<WorkspaceInvitation>;
  revokeInvitation: (invitationId: string) => Promise<void>;
};

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { token } = useAuth();
  const [workspaceId, setWorkspaceId] = useState("default");
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [jobs, setJobs] = useState<IngestionJob[]>([]);
  const [chatSessions, setChatSessions] = useState<ChatSession[]>([]);
  const [apiKeys, setApiKeys] = useState<ApiKeyRecord[]>([]);
  const [invitations, setInvitations] = useState<WorkspaceInvitation[]>([]);
  const [readiness, setReadiness] = useState<ReadinessReport | null>(null);
  const [observability, setObservability] = useState<ObservabilitySnapshot | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [objective, setObjective] = useState<Objective>("enterprise");
  const [language, setLanguage] = useState("auto");
  const [analysisMode, setAnalysisMode] = useState("agentic");
  const [queryMode, setQueryMode] = useState<QueryMode>(() => (typeof window === "undefined" ? "balanced" : ((localStorage.getItem("aiwana_query_mode") as QueryMode | null) || "balanced")));
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [messages, setMessages] = useState<Message[]>([
    { role: "assistant", text: "Upload your sources, choose a mode, and ask a grounded question. I will answer with citations, visual evidence, and an agent trace." },
  ]);

  const latestCanvas = [...messages].reverse().find((message) => message.evidenceCanvas)?.evidenceCanvas || null;
  const latestAgentRun = [...messages].reverse().find((message) => message.agentRun)?.agentRun || null;

  useEffect(() => {
    if (typeof window !== "undefined") localStorage.setItem("aiwana_query_mode", queryMode);
  }, [queryMode]);

  useEffect(() => {
    if (!token) {
      setError("");
      setStatus("");
      setWorkspaces([]);
      setDocuments([]);
      setJobs([]);
      setChatSessions([]);
      setApiKeys([]);
      setInvitations([]);
      setReadiness(null);
      setObservability(null);
      return;
    }
    void refreshWorkspace();
  }, [workspaceId, token]);

  async function api<T>(path: string, init?: RequestInit) {
    return apiRequest<T>(path, token, init);
  }

  async function refreshWorkspace() {
    if (!token) return;
    try {
      setError("");
      const workspaceData = await api<Workspace[]>("/workspaces");
      const nextWorkspaceId = workspaceData.length && !workspaceData.some((workspace) => workspace.workspace_id === workspaceId) ? workspaceData[0].workspace_id : workspaceId;
      setWorkspaces(workspaceData);
      if (nextWorkspaceId !== workspaceId) setWorkspaceId(nextWorkspaceId);
      const documentData = await api<DocumentRecord[]>(`/documents?workspace_id=${encodeURIComponent(nextWorkspaceId)}`);
      setDocuments(documentData);
      await Promise.all([refreshChatSessions(nextWorkspaceId), refreshReadiness(), refreshObservability(nextWorkspaceId), refreshApiKeys(nextWorkspaceId), refreshInvitations(nextWorkspaceId)]);
    } catch (cause) {
      setError(toMessage(cause));
      setWorkspaces([]);
      setDocuments([]);
    }
  }

  async function refreshReadiness() {
    if (!token) return;
    try {
      setReadiness(await api<ReadinessReport>("/readiness/launch"));
    } catch {
      setReadiness(null);
    }
  }

  async function refreshObservability(targetWorkspaceId = workspaceId) {
    if (!token) return;
    try {
      setObservability(await api<ObservabilitySnapshot>(`/observability/workspaces/${targetWorkspaceId}/snapshot`));
    } catch {
      setObservability(null);
    }
  }

  async function refreshChatSessions(targetWorkspaceId = workspaceId) {
    if (!token) return;
    try {
      setChatSessions(await api<ChatSession[]>(`/workspaces/${targetWorkspaceId}/chat/sessions`));
    } catch {
      setChatSessions([]);
    }
  }

  async function refreshApiKeys(targetWorkspaceId = workspaceId) {
    if (!token) return;
    try {
      setApiKeys(await api<ApiKeyRecord[]>(`/workspaces/${targetWorkspaceId}/api-keys`));
    } catch {
      setApiKeys([]);
    }
  }

  async function refreshInvitations(targetWorkspaceId = workspaceId) {
    if (!token) return;
    try {
      setInvitations(await api<WorkspaceInvitation[]>(`/workspaces/${targetWorkspaceId}/invitations?include_inactive=true`));
    } catch {
      setInvitations([]);
    }
  }

  async function uploadSources(files: FileList) {
    if (!token) {
      setError("Log in before uploading sources.");
      return;
    }
    setBusy(true);
    setError("");
    setStatus("Uploading and indexing sources...");
    const form = new FormData();
    Array.from(files).forEach((file) => form.append("files", file));
    form.append("objective_profile", objective);
    try {
      const submitted = await api<IngestionJob[]>(`/workspaces/${workspaceId}/sources`, { method: "POST", body: form });
      setJobs((current) => [...submitted, ...current]);
      setStatus("Ingestion started. Refresh jobs until documents show completed.");
      await refreshWorkspace();
    } catch (cause) {
      setError(toMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function refreshJobs() {
    if (!jobs.length) return;
    setBusy(true);
    try {
      setJobs(await Promise.all(jobs.map((job) => api<IngestionJob>(`/ingestions/${job.job_id}`))));
      await refreshWorkspace();
    } catch (cause) {
      setError(toMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function ensureSession() {
    if (sessionId) return sessionId;
    const session = await api<{ session_id: string }>("/chat/sessions", {
      method: "POST",
      body: JSON.stringify({
        workspace_id: workspaceId,
        language,
        response_language: language === "auto" ? undefined : language,
        explanation_level: "normal",
        objective_profile: objective,
        analysis_mode: analysisMode,
      }),
    });
    setSessionId(session.session_id);
    return session.session_id;
  }

  async function sendMessage(text: string) {
    if (!token) {
      setError("Log in before asking grounded questions.");
      return;
    }
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setError("");
    const assistantIndex = messages.length + 1;
    setMessages((current) => [...current, { role: "user", text: trimmed }, { role: "assistant", text: "" }]);
    try {
      const chatSessionId = await ensureSession();
      const payload: QueryPayload = {
        question: trimmed,
        workspace_id: workspaceId,
        language,
        response_language: language === "auto" ? undefined : language,
        explanation_level: "normal",
        answer_mode: "answer",
        objective_profile: objective,
        analysis_mode: analysisMode,
        query_mode: queryMode,
        include_visual_evidence: true,
        return_evidence_canvas: true,
        mode: analysisMode === "agentic" ? "multistep" : "single",
        session_id: chatSessionId,
      };
      const response = await streamChatQuery(
        payload,
        token,
        (streamToken) => setMessages((current) => current.map((message, index) => (index === assistantIndex ? { ...message, text: `${message.text}${streamToken}` } : message))),
        (stage) =>
          setMessages((current) =>
            current.map((message, index) =>
              index === assistantIndex ? { ...message, stages: [...(message.stages || []).filter((item) => item.stage !== stage.stage), stage] } : message,
            ),
          ),
      );
      setMessages((current) =>
        current.map((message, index) =>
          index === assistantIndex
            ? { ...message, text: response.answer, evidenceCanvas: response.evidence_canvas, agentRun: response.agent_run, groundingStatus: response.grounding_status }
            : message,
        ),
      );
      await refreshChatSessions();
    } catch (cause) {
      setError(toMessage(cause));
      setMessages((current) => [...current, { role: "assistant", text: "I could not complete that request. Check backend health and source readiness." }]);
    } finally {
      setBusy(false);
    }
  }

  function startNewChat() {
    setSessionId(null);
    setMessages([{ role: "assistant", text: "New chat started. Ask anything grounded in your uploaded sources." }]);
    setStatus("New chat ready.");
  }

  async function openChatSession(session: ChatSession) {
    setBusy(true);
    setError("");
    try {
      const records = await api<ChatMessageRecord[]>(`/chat/sessions/${session.session_id}/messages`);
      setSessionId(session.session_id);
      if (session.objective_profile && session.objective_profile !== "general") setObjective(session.objective_profile);
      if (session.analysis_mode) setAnalysisMode(session.analysis_mode);
      const loaded = records.filter((record) => record.role === "user" || record.role === "assistant").map((record) => ({ role: record.role as "user" | "assistant", text: record.content }));
      setMessages(loaded.length ? loaded : [{ role: "assistant", text: "Chat opened. Ask a follow-up to continue with saved context." }]);
    } catch (cause) {
      setError(toMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function createApiKey() {
    setBusy(true);
    setError("");
    try {
      const created = await api<{ api_key: string } & ApiKeyRecord>(`/workspaces/${workspaceId}/api-keys`, {
        method: "POST",
        body: JSON.stringify({ name: "Workspace automation", role: "viewer", permissions: ["workspace.read", "document.query"] }),
      });
      await refreshApiKeys();
      return created.api_key;
    } catch (cause) {
      setError(toMessage(cause));
      throw cause;
    } finally {
      setBusy(false);
    }
  }

  async function revokeApiKey(keyId: string) {
    setBusy(true);
    try {
      await api<void>(`/workspaces/${workspaceId}/api-keys/${keyId}`, { method: "DELETE" });
      await refreshApiKeys();
    } catch (cause) {
      setError(toMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function createInvitation(email: string, role: string) {
    setBusy(true);
    setError("");
    try {
      const created = await api<WorkspaceInvitation>(`/workspaces/${workspaceId}/invitations`, {
        method: "POST",
        body: JSON.stringify({ email, role }),
      });
      await refreshInvitations();
      return created;
    } catch (cause) {
      setError(toMessage(cause));
      throw cause;
    } finally {
      setBusy(false);
    }
  }

  async function revokeInvitation(invitationId: string) {
    setBusy(true);
    setError("");
    try {
      await api<void>(`/workspaces/${workspaceId}/invitations/${invitationId}`, { method: "DELETE" });
      await refreshInvitations();
    } catch (cause) {
      setError(toMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  const value = useMemo(
    () => ({
      workspaceId,
      setWorkspaceId,
      workspaces,
      documents,
      jobs,
      chatSessions,
      apiKeys,
      invitations,
      readiness,
      observability,
      messages,
      latestCanvas,
      latestAgentRun,
      objective,
      setObjective,
      language,
      setLanguage,
      analysisMode,
      setAnalysisMode,
      queryMode,
      setQueryMode,
      busy,
      status,
      error,
      refreshWorkspace,
      refreshReadiness,
      refreshObservability,
      uploadSources,
      refreshJobs,
      sendMessage,
      startNewChat,
      openChatSession,
      createApiKey,
      revokeApiKey,
      createInvitation,
      revokeInvitation,
    }),
    [workspaceId, workspaces, documents, jobs, chatSessions, apiKeys, invitations, readiness, observability, messages, latestCanvas, latestAgentRun, objective, language, analysisMode, queryMode, busy, status, error],
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace() {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("useWorkspace must be used inside WorkspaceProvider");
  return value;
}
