/**
 * JobHunter3000 — Options Page
 */

const urlInput = document.getElementById("url-input");
const statusEl = document.getElementById("status");

// Load saved URL
chrome.storage.local.get("jh3000_url", (data) => {
  urlInput.value = data.jh3000_url || "http://localhost:8001";
});

// Save
document.getElementById("btn-save").addEventListener("click", () => {
  const url = urlInput.value.trim().replace(/\/+$/, "");
  if (!url) {
    statusEl.textContent = "URL cannot be empty";
    statusEl.className = "status-err";
    return;
  }
  chrome.storage.local.set({ jh3000_url: url }, () => {
    statusEl.textContent = "Saved";
    statusEl.className = "status-ok";
    setTimeout(() => { statusEl.textContent = ""; }, 2000);
  });
});

// Test connection
document.getElementById("btn-test").addEventListener("click", async () => {
  const url = urlInput.value.trim().replace(/\/+$/, "");
  statusEl.textContent = "Testing...";
  statusEl.className = "";

  try {
    const resp = await fetch(`${url}/api/stats`, { method: "GET" });
    if (resp.ok) {
      const data = await resp.json();
      statusEl.textContent = `Connected! ${data.total || 0} jobs in database.`;
      statusEl.className = "status-ok";
    } else {
      statusEl.textContent = `Error: HTTP ${resp.status}`;
      statusEl.className = "status-err";
    }
  } catch (err) {
    statusEl.textContent = `Cannot reach ${url} — is JH3000 running?`;
    statusEl.className = "status-err";
  }
});
