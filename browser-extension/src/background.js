chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "AIWANA_CAPTURE_PAGE") return false;
  chrome.storage.local.get(["aiwanaApiBase", "aiwanaToken", "aiwanaWorkspaceId"], async (settings) => {
    const apiBase = settings.aiwanaApiBase || "http://localhost:8000";
    const workspaceId = settings.aiwanaWorkspaceId || "default";
    try {
      const response = await fetch(`${apiBase}/browser/capture`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(settings.aiwanaToken ? { Authorization: `Bearer ${settings.aiwanaToken}` } : {}),
        },
        body: JSON.stringify({
          workspace_id: workspaceId,
          title: message.title || message.url || "Browser page",
          url: message.url || "",
          text: message.text || "",
          selection_used: Boolean(message.selection_used),
          extension_version: chrome.runtime.getManifest().version,
          metadata: {
            source_type: "browser_page",
            original_url: message.url,
            selection_used: Boolean(message.selection_used),
            captured_at: new Date().toISOString(),
          },
        }),
      });
      sendResponse({ ok: response.ok, status: response.status, body: await response.text() });
    } catch (error) {
      sendResponse({ ok: false, error: String(error) });
    }
  });
  return true;
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!["AIWANA_SUMMARIZE_PAGE", "AIWANA_PAGE_ENTITIES", "AIWANA_ASK_PAGE"].includes(message?.type)) return false;
  chrome.storage.local.get(["aiwanaApiBase", "aiwanaToken", "aiwanaWorkspaceId"], async (settings) => {
    const apiBase = settings.aiwanaApiBase || "http://localhost:8000";
    const workspaceId = settings.aiwanaWorkspaceId || "default";
    const path = message.type === "AIWANA_PAGE_ENTITIES" ? "/browser/entities" : message.type === "AIWANA_ASK_PAGE" ? "/browser/current-page/query" : "/browser/summarize";
    try {
      const response = await fetch(`${apiBase}${path}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(settings.aiwanaToken ? { Authorization: `Bearer ${settings.aiwanaToken}` } : {}),
        },
        body: JSON.stringify({
          workspace_id: workspaceId,
          title: message.title || message.url || "Browser page",
          url: message.url || "",
          text: message.text || "",
          selection_used: Boolean(message.selection_used),
          extension_version: chrome.runtime.getManifest().version,
          question: message.question || "What is this page about?"
        }),
      });
      sendResponse({ ok: response.ok, status: response.status, body: await response.json().catch(async () => ({ text: await response.text() })) });
    } catch (error) {
      sendResponse({ ok: false, error: String(error) });
    }
  });
  return true;
});
