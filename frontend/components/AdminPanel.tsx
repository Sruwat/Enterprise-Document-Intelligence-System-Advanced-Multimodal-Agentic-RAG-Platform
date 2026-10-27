"use client";

import { KeyRound, MailPlus, Server, ShieldCheck, Users } from "lucide-react";
import { useState } from "react";
import { useWorkspace } from "../lib/workspace-state";
import { ReadinessPanel } from "./ReadinessPanel";

export function AdminPanel() {
  const [newApiKey, setNewApiKey] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("viewer");
  const [inviteToken, setInviteToken] = useState("");
  const { readiness, observability, refreshReadiness, refreshObservability, apiKeys, invitations, createApiKey, revokeApiKey, createInvitation, revokeInvitation, busy } = useWorkspace();

  async function createKey() {
    const created = await createApiKey();
    setNewApiKey(created);
  }

  async function inviteMember() {
    const created = await createInvitation(inviteEmail, inviteRole);
    setInviteEmail("");
    setInviteToken(created.invitation_token || "");
  }

  return (
    <div className="admin-screen">
      <ReadinessPanel readiness={readiness} onRefresh={refreshReadiness} />
      <section className="admin-card">
        <div className="panel-head row"><div><strong>Observability</strong><span>Worker, provider, graph, cache, and latency signals.</span></div><button className="ghost-button" onClick={() => void refreshObservability()}>Refresh</button></div>
        <div className="metric-row compact">
          <Metric label="Worker" value={String(observability?.components?.worker?.status || "unknown")} icon={<Server size={18} />} />
          <Metric label="HF" value={String(observability?.components?.huggingface?.enabled ? `${observability?.components?.huggingface?.ready_count || 0} ready` : "disabled")} icon={<ShieldCheck size={18} />} />
          <Metric label="Cache hit" value={`${Math.round((observability?.retrieval?.cache_hit_rate || 0) * 100)}%`} icon={<Server size={18} />} />
          <Metric label="Graph lift" value={String(observability?.components?.graph_eval?.lift ?? "n/a")} icon={<ShieldCheck size={18} />} />
          <Metric label="P95" value={observability?.latency?.p95_ms ? `${Math.round(observability.latency.p95_ms)}ms` : "n/a"} icon={<Server size={18} />} />
          <Metric label="Blocked" value={`${Math.round((observability?.retrieval?.blocked_answer_rate || 0) * 100)}%`} icon={<ShieldCheck size={18} />} />
        </div>
      </section>
      <section className="admin-card">
        <div className="panel-head row">
          <div><strong>API keys</strong><span>Workspace-scoped automation access.</span></div>
          <button className="ghost-button" onClick={() => void createKey()} disabled={busy}><KeyRound size={16} /> New key</button>
        </div>
        {newApiKey && <div className="secret-box"><strong>Copy this key now</strong><code>{newApiKey}</code></div>}
        <div className="source-list">
          {apiKeys.length ? apiKeys.map((key) => (
            <div className="key-row" key={key.key_id}>
              <KeyRound size={16} />
              <div><strong>{key.name}</strong><span>{key.masked_key} / {key.role}{key.revoked_at ? " / revoked" : ""}</span></div>
              {!key.revoked_at && <button className="danger-button" onClick={() => void revokeApiKey(key.key_id)} disabled={busy}>Revoke</button>}
            </div>
          )) : <div className="empty-state">No API keys yet.</div>}
        </div>
      </section>
      <section className="admin-card">
        <div className="panel-head">
          <strong>Members</strong>
          <span>Invitation-only onboarding for enterprise workspaces.</span>
        </div>
        <div className="auth-grid compact-form">
          <input value={inviteEmail} onChange={(event) => setInviteEmail(event.target.value)} placeholder="employee@company.com" aria-label="Invite email" />
          <select value={inviteRole} onChange={(event) => setInviteRole(event.target.value)} aria-label="Invite role">
            <option value="viewer">Viewer</option>
            <option value="analyst">Analyst</option>
            <option value="admin">Admin</option>
          </select>
          <button className="ghost-button" onClick={() => void inviteMember()} disabled={busy || !inviteEmail.trim()}><MailPlus size={16} /> Invite</button>
        </div>
        {inviteToken && <div className="secret-box"><strong>One-time invite token</strong><code>{inviteToken}</code></div>}
        <div className="source-list">
          {invitations.length ? invitations.map((invitation) => (
            <div className="key-row" key={invitation.invitation_id}>
              <Users size={16} />
              <div><strong>{invitation.email}</strong><span>{invitation.role} / {invitation.status} / expires {new Date(invitation.expires_at).toLocaleDateString()}</span></div>
              {invitation.status === "pending" && <button className="danger-button" onClick={() => void revokeInvitation(invitation.invitation_id)} disabled={busy}>Revoke</button>}
            </div>
          )) : <div className="empty-state">No invitations yet.</div>}
        </div>
      </section>
    </div>
  );
}

function Metric({ label, value, icon }: { label: string; value: string; icon: React.ReactNode }) {
  return <div className="metric-card">{icon}<span>{label}</span><strong>{value}</strong></div>;
}
