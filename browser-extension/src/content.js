chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "AIWANA_READ_PAGE") return false;
  const selection = String(window.getSelection?.() || "").trim();
  const text = selection || document.body?.innerText || "";
  sendResponse({
    title: document.title,
    url: location.href,
    text: text.slice(0, 250000),
    selection_used: Boolean(selection)
  });
  return true;
});
