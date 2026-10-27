"use client";

import { Building2 } from "lucide-react";
import { useWorkspace } from "../lib/workspace-state";

export function WorkspaceSwitcher() {
  const { workspaces, workspaceId, setWorkspaceId } = useWorkspace();
  return (
    <label className="workspace-switcher">
      <Building2 size={18} />
      <select value={workspaceId} onChange={(event) => setWorkspaceId(event.target.value)} aria-label="Workspace">
        {workspaces.length ? workspaces.map((workspace) => <option key={workspace.workspace_id} value={workspace.workspace_id}>{workspace.name}</option>) : <option value="default">Default workspace</option>}
      </select>
    </label>
  );
}
