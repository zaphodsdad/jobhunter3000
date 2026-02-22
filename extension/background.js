/**
 * JobHunter3000 — Service Worker (background.js)
 * Handles API communication with the local JH3000 instance.
 */

const DEFAULT_BASE_URL = "http://localhost:8001";

async function getBaseUrl() {
  const { jh3000_url } = await chrome.storage.local.get("jh3000_url");
  return (jh3000_url || DEFAULT_BASE_URL).replace(/\/+$/, "");
}

/**
 * Send extracted job data to JH3000 for scoring.
 */
async function captureJob(data) {
  const baseUrl = await getBaseUrl();
  const resp = await fetch(`${baseUrl}/api/jobs/capture`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });

  if (!resp.ok) {
    const errBody = await resp.json().catch(() => ({}));
    throw new Error(errBody.error || `HTTP ${resp.status}`);
  }

  return resp.json();
}

/**
 * Delete a job from JH3000.
 */
async function deleteJob(jobId) {
  const baseUrl = await getBaseUrl();
  const resp = await fetch(`${baseUrl}/api/jobs/${jobId}`, {
    method: "DELETE",
  });

  if (!resp.ok) {
    const errBody = await resp.json().catch(() => ({}));
    throw new Error(errBody.error || `HTTP ${resp.status}`);
  }

  return resp.json();
}

/**
 * Test connection to JH3000.
 */
async function testConnection() {
  const baseUrl = await getBaseUrl();
  const resp = await fetch(`${baseUrl}/api/stats`, { method: "GET" });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

/**
 * Set the badge on the browser action icon.
 */
function setBadge(tabId, score) {
  if (score === null || score === undefined) {
    chrome.action.setBadgeText({ text: "", tabId });
    return;
  }
  const text = String(score);
  let color;
  if (score >= 70) color = "#4ade80";      // green — strong match
  else if (score >= 50) color = "#22d3ee";  // cyan — decent
  else if (score >= 30) color = "#fbbf24";  // amber — weak
  else color = "#6b7280";                   // gray — poor

  chrome.action.setBadgeText({ text, tabId });
  chrome.action.setBadgeBackgroundColor({ color, tabId });
}

// Listen for messages from popup and content scripts
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === "capture") {
    captureJob(msg.data)
      .then((result) => {
        // Set badge on the tab
        if (msg.tabId && result.score !== undefined) {
          setBadge(msg.tabId, result.score);
        }
        // Persist result for popup state recovery
        chrome.storage.local.set({
          jh3000_last_result: result,
          jh3000_last_tab: msg.tabId || null,
        });
        sendResponse({ ok: true, result });
      })
      .catch((err) => {
        sendResponse({ ok: false, error: err.message });
      });
    return true; // keep message channel open for async response
  }

  if (msg.action === "removeJob") {
    deleteJob(msg.jobId)
      .then(() => {
        // Clear persisted result if it was the same job
        chrome.storage.local.get("jh3000_last_result", (data) => {
          if (data.jh3000_last_result && data.jh3000_last_result.id === msg.jobId) {
            chrome.storage.local.remove(["jh3000_last_result", "jh3000_last_tab"]);
          }
        });
        // Clear badge on tab
        if (msg.tabId) {
          setBadge(msg.tabId, null);
        }
        sendResponse({ ok: true });
      })
      .catch((err) => {
        sendResponse({ ok: false, error: err.message });
      });
    return true;
  }

  if (msg.action === "clearResult") {
    chrome.storage.local.remove(["jh3000_last_result", "jh3000_last_tab"]);
    sendResponse({ ok: true });
    return false;
  }

  if (msg.action === "testConnection") {
    testConnection()
      .then((stats) => sendResponse({ ok: true, stats }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (msg.action === "getBaseUrl") {
    getBaseUrl().then((url) => sendResponse({ url }));
    return true;
  }
});

// Handle keyboard shortcut
chrome.commands.onCommand.addListener((command) => {
  if (command === "capture-job") {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0]) {
        chrome.tabs.sendMessage(tabs[0].id, { action: "extract" }, (response) => {
          if (chrome.runtime.lastError || !response) return;
          captureJob(response).then((result) => {
            setBadge(tabs[0].id, result.score);
            chrome.storage.local.set({
              jh3000_last_result: result,
              jh3000_last_tab: tabs[0].id,
            });
          });
        });
      }
    });
  }
});
