# Aiwana Capture Chrome Extension

This is a minimal Manifest V3 extension for saving the current browser page into an Aiwana workspace.

## Load Unpacked

1. Open Chrome and go to `chrome://extensions`.
2. Enable Developer mode.
3. Click Load unpacked.
4. Select the `browser-extension` folder.
5. Open the extension popup and set:
   - API base: `http://localhost:8000`
   - Workspace ID: your Aiwana workspace id
   - Token: your Aiwana session token or workspace API key

## Capture Behavior

- If text is selected on the page, Aiwana saves the selection.
- If nothing is selected, Aiwana saves the page text.
- The backend receives title, URL, text, source type, and capture timestamp through `/browser/capture`.
- The popup also supports summarize, entity extraction, and ask-current-page flows through `/browser/summarize`, `/browser/entities`, and `/browser/current-page/query`.
