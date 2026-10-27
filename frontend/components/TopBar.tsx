"use client";

import { Menu, RefreshCw } from "lucide-react";
import { ThemeToggle } from "./ThemeToggle";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher";
import { useAuth } from "../lib/auth";
import { useWorkspace } from "../lib/workspace-state";

export function TopBar({ onOpenNav }: { onOpenNav: () => void }) {
  const { token, user } = useAuth();
  const { refreshWorkspace, busy } = useWorkspace();

  return (
    <header className="topbar">
      <button className="icon-button mobile-nav-button" onClick={onOpenNav} aria-label="Open navigation"><Menu size={19} /></button>
      <WorkspaceSwitcher />
      <div className="topbar-actions">
        <span className="user-chip">{user?.email || (token ? "Signed in" : "Login required")}</span>
        <ThemeToggle />
        <button className="icon-button" onClick={() => void refreshWorkspace()} disabled={busy} aria-label="Refresh workspace">
          <RefreshCw size={18} />
        </button>
      </div>
    </header>
  );
}
