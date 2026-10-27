"use client";

import { createContext, ReactNode, useContext, useEffect, useMemo, useState } from "react";
import { apiRequest, toMessage } from "./api";
import { User } from "./types";

type AuthContextValue = {
  token: string | null;
  user: User | null;
  authError: string;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string) => Promise<void>;
  googleLogin: (workspaceId: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [authError, setAuthError] = useState("");

  useEffect(() => {
    const stored = window.localStorage.getItem("aiwana_session_token");
    if (stored) {
      setToken(stored);
      void loadCurrentUser(stored);
    }
  }, []);

  async function loadCurrentUser(sessionToken: string) {
    try {
      setUser(await apiRequest<User>("/auth/me", sessionToken));
    } catch {
      window.localStorage.removeItem("aiwana_session_token");
      setToken(null);
      setUser(null);
    }
  }

  async function authenticate(mode: "login" | "signup", email: string, password: string) {
    setAuthError("");
    try {
      const data = await apiRequest<{ user: User; session_token: string }>(`/auth/${mode}`, null, {
        method: "POST",
        body: JSON.stringify({ email, password, display_name: "Aiwana Founder" }),
      });
      window.localStorage.setItem("aiwana_session_token", data.session_token);
      setToken(data.session_token);
      setUser(data.user);
    } catch (cause) {
      setAuthError(toMessage(cause));
      throw cause;
    }
  }

  async function logout() {
    if (token) await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"}/auth/logout`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }).catch(() => undefined);
    window.localStorage.removeItem("aiwana_session_token");
    setToken(null);
    setUser(null);
  }

  async function googleLogin(workspaceId: string) {
    setAuthError("");
    try {
      const data = await apiRequest<{ authorization_url: string }>(`/auth/google/login?workspace_id=${encodeURIComponent(workspaceId)}`, null);
      window.location.href = data.authorization_url;
    } catch (cause) {
      setAuthError(toMessage(cause));
      throw cause;
    }
  }

  const value = useMemo(
    () => ({ token, user, authError, login: (email: string, password: string) => authenticate("login", email, password), signup: (email: string, password: string) => authenticate("signup", email, password), googleLogin, logout }),
    [token, user, authError],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
