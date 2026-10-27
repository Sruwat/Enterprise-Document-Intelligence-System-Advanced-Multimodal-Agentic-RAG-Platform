"use client";

import { ReactNode } from "react";
import { AuthProvider } from "../lib/auth";
import { ThemeProvider } from "../lib/theme-state";
import { WorkspaceProvider } from "../lib/workspace-state";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider>
      <AuthProvider>
        <WorkspaceProvider>{children}</WorkspaceProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}
