export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export function toMessage(cause: unknown) {
  if (cause instanceof Error) {
    if (/Failed to fetch|NetworkError|fetch failed/i.test(cause.message)) {
      return "Backend is unavailable. Start the Aiwana API, then refresh this screen.";
    }
    return cause.message;
  }
  return "Something went wrong.";
}

export async function apiRequest<T>(path: string, token?: string | null, init?: RequestInit): Promise<T> {
  const bodyIsForm = init?.body instanceof FormData;
  const headers = {
    ...(bodyIsForm ? {} : { "Content-Type": "application/json" }),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(init?.headers || {}),
  };
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!response.ok) throw new Error((await response.text()) || `${response.status} ${response.statusText}`);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function previewUrl(workspaceId: string, documentId: string, pageNumber: number) {
  return `${API_BASE}/workspaces/${encodeURIComponent(workspaceId)}/documents/${encodeURIComponent(documentId)}/pages/${pageNumber}/preview`;
}
