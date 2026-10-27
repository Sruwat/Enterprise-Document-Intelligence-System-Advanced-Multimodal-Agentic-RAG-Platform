"use client";

import { LogOut, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useAuth } from "../lib/auth";
import { useWorkspace } from "../lib/workspace-state";
import { ThemeToggle } from "./ThemeToggle";

export function SettingsPanel() {
  const { user, login, signup, googleLogin, logout, authError } = useAuth();
  const { workspaceId, workspaces } = useWorkspace();
  const [email, setEmail] = useState("founder@aiwana.local");
  const [password, setPassword] = useState("aiwana-demo-password");

  return (
    <div className="settings-screen">
      <section className="admin-card">
        <div className="panel-head"><strong>Account</strong><span>Production auth remains backend-enforced.</span></div>
        {user ? (
          <div className="identity-card">
            <ShieldCheck size={18} />
            <div><strong>{user.display_name || user.email}</strong><span>{user.email}</span></div>
            <button className="ghost-button" onClick={() => void logout()}><LogOut size={16} /> Log out</button>
          </div>
        ) : (
          <div className="auth-grid">
            <input value={email} onChange={(event) => setEmail(event.target.value)} aria-label="Email" />
            <input value={password} onChange={(event) => setPassword(event.target.value)} aria-label="Password" type="password" />
            <button className="primary-action" onClick={() => void login(email, password)}>Log in</button>
            <button className="ghost-button" onClick={() => void googleLogin(workspaceId)}>Continue with Google</button>
            <button className="ghost-button" onClick={() => void signup(email, password)}>Sign up</button>
            {authError && <div className="inline-empty error">{authError}</div>}
          </div>
        )}
      </section>
      <section className="admin-card">
        <div className="panel-head"><strong>AI privacy</strong><span>Workspace policy is enforced by the backend provider configuration.</span></div>
        <div className="identity-card">
          <ShieldCheck size={18} />
          <div>
            <strong>{workspaces.find((workspace) => workspace.workspace_id === workspaceId)?.external_ai_allowed === false ? "Private-only workspace" : "External AI allowed"}</strong>
            <span>Secrets are never shown in the browser. Private-only mode blocks public LLM fallback server-side.</span>
          </div>
        </div>
      </section>
      <section className="admin-card">
        <div className="panel-head"><strong>Theme</strong><span>Persisted locally for this browser.</span></div>
        <ThemeToggle />
      </section>
      <section className="admin-card">
        <div className="panel-head"><strong>Browser extension</strong><span>Use API keys or authenticated session flow from the extension.</span></div>
        <div className="disabled-state">Extension connection status will appear when the Chrome extension sends workspace metadata.</div>
      </section>
    </div>
  );
}
