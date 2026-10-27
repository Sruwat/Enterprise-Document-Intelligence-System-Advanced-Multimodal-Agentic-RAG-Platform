"use client";

import { ReactNode, useState } from "react";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { StatusToast } from "./StatusToast";
import { AuthGate } from "./AuthGate";
import { useAuth } from "../lib/auth";
import { useTheme } from "../lib/theme-state";
import { useWorkspace } from "../lib/workspace-state";

export function AppShell({ children }: { children: ReactNode }) {
  const [navOpen, setNavOpen] = useState(false);
  const { theme } = useTheme();
  const { status, error } = useWorkspace();
  const { token } = useAuth();

  return (
    <main className="app-shell" data-theme={theme}>
      <Sidebar open={navOpen} onClose={() => setNavOpen(false)} />
      <section className="app-main">
        <TopBar onOpenNav={() => setNavOpen(true)} />
        <StatusToast status={status} error={error} />
        {token ? children : <AuthGate />}
      </section>
    </main>
  );
}
