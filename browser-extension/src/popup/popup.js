const apiBase = document.querySelector("#apiBase");
const workspaceId = document.querySelector("#workspaceId");
const token = document.querySelector("#token");
const status = document.querySelector("#status");
const result = document.querySelector("#result");
const question = document.querySelector("#question");

chrome.storage.local.get(["aiwanaApiBase", "aiwanaToken", "aiwanaWorkspaceId"], (settings) => {
  apiBase.value = settings.aiwanaApiBase || "http://localhost:8000";
  workspaceId.value = settings.aiwanaWorkspaceId || "default";
  token.value = settings.aiwanaToken || "";
});

document.querySelector("#saveSettings").addEventListener("click", () => {
  chrome.storage.local.set({
    aiwanaApiBase: apiBase.value.trim(),
    aiwanaWorkspaceId: workspaceId.value.trim(),
    aiwanaToken: token.value.trim(),
  });
  status.textContent = "Settings saved.";
});

document.querySelector("#capturePage").addEventListener("click", async () => {
  status.textContent = "Reading page...";
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const page = await chrome.tabs.sendMessage(tab.id, { type: "AIWANA_READ_PAGE" });
  chrome.runtime.sendMessage({ type: "AIWANA_CAPTURE_PAGE", ...page }, (result) => {
    status.textContent = result?.ok ? "Saved to Aiwana." : `Failed: ${result?.error || result?.body || result?.status}`;
  });
});

document.querySelector("#summarizePage").addEventListener("click", async () => {
  await runPageAction("AIWANA_SUMMARIZE_PAGE");
});

document.querySelector("#extractEntities").addEventListener("click", async () => {
  await runPageAction("AIWANA_PAGE_ENTITIES");
});

document.querySelector("#askPage").addEventListener("click", async () => {
  await runPageAction("AIWANA_ASK_PAGE", { question: question.value.trim() || "What is this page about?" });
});

async function runPageAction(type, extra = {}) {
  status.textContent = "Reading page...";
  result.textContent = "";
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const page = await chrome.tabs.sendMessage(tab.id, { type: "AIWANA_READ_PAGE" });
  chrome.runtime.sendMessage({ type, ...page, ...extra }, (payload) => {
    status.textContent = payload?.ok ? "Done." : `Failed: ${payload?.error || payload?.status || "unknown"}`;
    result.textContent = JSON.stringify(payload?.body || payload, null, 2);
  });
}
