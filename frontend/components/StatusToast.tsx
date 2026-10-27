"use client";

import { AlertCircle, CheckCircle2 } from "lucide-react";

export function StatusToast({ status, error }: { status: string; error: string }) {
  if (!status && !error) return null;
  return (
    <div className={`status-toast ${error ? "error" : ""}`}>
      {error ? <AlertCircle size={18} /> : <CheckCircle2 size={18} />}
      <span>{error || status}</span>
    </div>
  );
}
