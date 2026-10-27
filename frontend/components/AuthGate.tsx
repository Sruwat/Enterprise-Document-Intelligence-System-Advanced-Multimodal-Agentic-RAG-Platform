"use client";

import { ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useAuth } from "../lib/auth";

export function AuthGate() {
  const { login, signup, authError } = useAuth();
  const [email, setEmail] = useState("smoke@aiwana.local");
  const [password, setPassword] = useState("aiwana-smoke-password");
  const [busy, setBusy] = useState(false);

  async function authenticate(mode: "login" | "signup") {
    setBusy(true);
    try {
      if (mode === "login") await login(email, password);
      else await signup(email, password);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="auth-gate">
      <div className="auth-gate-card">
        <ShieldCheck size={28} />
        <div>
          <span>Production auth enabled</span>
          <h1>Log in to open your Aiwana workspace.</h1>
          <p>Backend auth is required, so workspace data, uploads, queries, admin health, and API keys load only after a valid session.</p>
        </div>
        <div className="auth-grid">
          <input value={email} onChange={(event) => setEmail(event.target.value)} aria-label="Email" />
          <input value={password} onChange={(event) => setPassword(event.target.value)} aria-label="Password" type="password" />
          <button className="primary-action" onClick={() => void authenticate("login")} disabled={busy}>Log in</button>
          <button className="ghost-button" onClick={() => void authenticate("signup")} disabled={busy}>Sign up</button>
          {authError && <div className="inline-empty error">{authError}</div>}
        </div>
      </div>
    </section>
  );
}
