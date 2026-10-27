import { apiRequest } from "./api";
import { QueryPayload, QueryResponse, StreamStage } from "./types";

export async function streamChatQuery(
  payload: QueryPayload,
  token: string | null,
  onToken: (token: string) => void,
  onStage: (stage: StreamStage) => void,
): Promise<QueryResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"}/chat/query/stream`, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });
  if (!response.ok || !response.body) return apiRequest<QueryResponse>("/chat/query", token, { method: "POST", body: JSON.stringify(payload) });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResponse: QueryResponse | null = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() || "";
    for (const eventText of events) {
      const event = parseSseEvent(eventText);
      if (!event) continue;
      if (event.event === "token") onToken(String(event.data.text || ""));
      if (event.event === "stage" || event.event === "agent_stage") onStage(event.data as StreamStage);
      if (event.event === "final" || event.event === "completed") finalResponse = event.data as QueryResponse;
    }
  }
  if (!finalResponse) throw new Error("Streaming response ended before final payload.");
  return finalResponse;
}

function parseSseEvent(eventText: string): { event: string; data: Record<string, unknown> } | null {
  const lines = eventText.split("\n");
  const eventLine = lines.find((line) => line.startsWith("event:"));
  const dataLine = lines.find((line) => line.startsWith("data:"));
  if (!eventLine || !dataLine) return null;
  try {
    return { event: eventLine.replace("event:", "").trim(), data: JSON.parse(dataLine.replace("data:", "").trim()) as Record<string, unknown> };
  } catch {
    return null;
  }
}
