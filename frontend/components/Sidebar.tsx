"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, BarChart3, Database, FileSearch, Home, KeyRound, Menu, MessageSquareText, Settings, Sparkles, X, Layers3, Waypoints } from "lucide-react";
import { useWorkspace } from "../lib/workspace-state";

const navItems = [
  { href: "/", label: "Dashboard", icon: Home },
  { href: "/chat", label: "Chat", icon: MessageSquareText },
  { href: "/sources", label: "Sources", icon: FileSearch },
  { href: "/data-vault", label: "Data Vault", icon: Database },
  { href: "/evidence", label: "Evidence", icon: Activity },
  { href: "/admin", label: "Admin", icon: BarChart3 },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const pathname = usePathname();
  const { chatSessions, openChatSession, startNewChat } = useWorkspace();

  return (
    <aside className={`sidebar ${open ? "open" : ""}`}>
      <div className="brand-row">
        <div className="brand-mark"><Sparkles size={18} /></div>
        <div>
          <strong>Aiwana</strong>
          <span>Document intelligence</span>
        </div>
        <button className="icon-button sidebar-close" onClick={onClose} aria-label="Close navigation"><X size={18} /></button>
      </div>

      <nav className="nav-list" aria-label="Primary">
        {navItems.map((item) => {
          const Icon = item.icon;
          const active = pathname === item.href;
          return (
            <Link key={item.href} className={`nav-link ${active ? "active" : ""}`} href={item.href} onClick={onClose}>
              <Icon size={18} />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="nav-divider" />
      <div className="section-label">Product</div>
      <nav className="nav-list secondary-nav" aria-label="Product pages">
        <Link className="nav-link" href="/features" onClick={onClose}><Layers3 size={18} /><span>Platform features</span></Link>
        <Link className="nav-link" href="/usage" onClick={onClose}><Waypoints size={18} /><span>Use cases</span></Link>
      </nav>

      <section className="sidebar-section">
        <div className="section-label">Recent chats</div>
        <button className="nav-action" onClick={() => { startNewChat(); onClose(); }}>
          <Menu size={16} />
          New chat
        </button>
        {chatSessions.slice(0, 5).map((session) => (
          <button className="chat-link" key={session.session_id} onClick={() => { void openChatSession(session); onClose(); }}>
            <strong>{session.title || "Untitled chat"}</strong>
            <span>{session.objective_profile || "general"} / {session.analysis_mode || "quick"}</span>
          </button>
        ))}
      </section>

      <section className="sidebar-section extension-card">
        <KeyRound size={17} />
        <div>
          <strong>Browser extension</strong>
          <span>Connect from Chrome to save pages into this workspace.</span>
        </div>
      </section>
    </aside>
  );
}
