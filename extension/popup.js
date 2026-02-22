/**
 * JobHunter3000 — Popup Script
 * Manages the popup UI states: idle, loading, result, error.
 * Persists last result so it survives popup close/reopen.
 */

const $ = (sel) => document.querySelector(sel);

// State elements
const stateIdle = $("#state-idle");
const stateLoading = $("#state-loading");
const stateResult = $("#state-result");
const stateError = $("#state-error");

// Track current result for remove button
let currentResult = null;

function showState(state) {
  stateIdle.classList.add("hidden");
  stateLoading.classList.add("hidden");
  stateResult.classList.add("hidden");
  stateError.classList.add("hidden");
  state.classList.remove("hidden");
}

function setLoadingText(text) {
  $("#loading-text").textContent = text;
}

/**
 * Display the score result in the popup.
 */
function showResult(result) {
  currentResult = result;
  showState(stateResult);

  const score = result.score;
  const badge = $("#score-badge");
  badge.textContent = score !== null && score !== undefined ? score : "--";
  badge.className = "score-badge";
  if (score === null || score === undefined) {
    badge.classList.add("score-low");
    $("#score-label").textContent = "Not Scored";
  } else if (score >= 70) {
    badge.classList.add("score-high");
    $("#score-label").textContent = "Strong Match";
  } else if (score >= 50) {
    badge.classList.add("score-good");
    $("#score-label").textContent = "Decent Match";
  } else if (score >= 30) {
    badge.classList.add("score-mid");
    $("#score-label").textContent = "Weak Match";
  } else {
    badge.classList.add("score-low");
    $("#score-label").textContent = "Poor Match";
  }

  // Duplicate badge
  const dupBadge = $("#duplicate-badge");
  if (result.duplicate) {
    dupBadge.classList.remove("hidden");
  } else {
    dupBadge.classList.add("hidden");
  }

  // Fit summary
  $("#fit-summary").textContent = result.fit_summary || "";

  // Pros
  const prosEl = $("#pros-list");
  prosEl.innerHTML = "";
  const pros = result.pros || [];
  if (pros.length > 0) {
    const ul = document.createElement("ul");
    pros.slice(0, 3).forEach((p) => {
      const li = document.createElement("li");
      li.textContent = p;
      ul.appendChild(li);
    });
    prosEl.appendChild(ul);
  }

  // Cons
  const consEl = $("#cons-list");
  consEl.innerHTML = "";
  const cons = result.cons || [];
  if (cons.length > 0) {
    const ul = document.createElement("ul");
    cons.slice(0, 3).forEach((c) => {
      const li = document.createElement("li");
      li.textContent = c;
      ul.appendChild(li);
    });
    consEl.appendChild(ul);
  }

  // Detail link
  if (result.detail_url) {
    chrome.runtime.sendMessage({ action: "getBaseUrl" }, (resp) => {
      const base = resp?.url || "http://localhost:8001";
      $("#link-detail").href = `${base}${result.detail_url}`;
    });
  }

  // Show/hide remove button (hide for duplicates — they were already there)
  const removeBtn = $("#btn-remove");
  if (result.id && !result.duplicate) {
    removeBtn.classList.remove("hidden");
  } else {
    removeBtn.classList.add("hidden");
  }
}

function showError(message) {
  showState(stateError);
  $("#error-message").textContent = message;
}

/**
 * Main capture flow.
 */
async function doCapture() {
  showState(stateLoading);
  setLoadingText("Extracting job data...");

  try {
    // Get the active tab
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) {
      showError("No active tab found");
      return;
    }

    // Ask content script to extract
    const extracted = await new Promise((resolve, reject) => {
      chrome.tabs.sendMessage(tab.id, { action: "extract" }, (response) => {
        if (chrome.runtime.lastError) {
          reject(new Error("Cannot access this page. Try refreshing."));
          return;
        }
        resolve(response);
      });
    });

    if (!extracted || extracted.error) {
      showError(extracted?.error || "Could not extract job data from this page");
      return;
    }

    // Send to background for API call
    setLoadingText("Scoring against your profile...");

    const response = await new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(
        { action: "capture", data: extracted, tabId: tab.id },
        (resp) => {
          if (chrome.runtime.lastError) {
            reject(new Error("Extension error"));
            return;
          }
          resolve(resp);
        }
      );
    });

    if (!response || !response.ok) {
      showError(response?.error || "Failed to capture job");
      return;
    }

    showResult(response.result);
  } catch (err) {
    showError(err.message || "Cannot reach JH3000");
  }
}

/**
 * Remove the current job from JH3000.
 */
async function doRemove() {
  if (!currentResult || !currentResult.id) return;

  const removeBtn = $("#btn-remove");
  removeBtn.textContent = "Removing...";
  removeBtn.disabled = true;

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    const response = await new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(
        { action: "removeJob", jobId: currentResult.id, tabId: tab?.id },
        (resp) => {
          if (chrome.runtime.lastError) {
            reject(new Error("Extension error"));
            return;
          }
          resolve(resp);
        }
      );
    });

    if (response?.ok) {
      // Go back to idle
      currentResult = null;
      showState(stateIdle);
    } else {
      removeBtn.textContent = "Failed — try again";
      removeBtn.disabled = false;
    }
  } catch (err) {
    removeBtn.textContent = "Failed — try again";
    removeBtn.disabled = false;
  }
}

/**
 * Initialize popup — check for persisted result, detect site, check connection.
 */
async function init() {
  // Check for a persisted result first
  const stored = await chrome.storage.local.get(["jh3000_last_result", "jh3000_last_tab"]);
  if (stored.jh3000_last_result) {
    showResult(stored.jh3000_last_result);

    // Still check connection in the background
    chrome.runtime.sendMessage({ action: "testConnection" }, () => {});
    return;
  }

  // No persisted result — show idle state
  showState(stateIdle);

  // Check connection to JH3000
  const statusDot = $("#connection-status");
  chrome.runtime.sendMessage({ action: "testConnection" }, (resp) => {
    if (resp?.ok) {
      statusDot.classList.add("connected");
      statusDot.title = "Connected to JH3000";
    } else {
      statusDot.classList.add("disconnected");
      statusDot.title = "Cannot reach JH3000";
    }
  });

  // Detect current site
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab) {
      const hostname = new URL(tab.url || "").hostname;
      const siteNames = {
        "linkedin.com": "LinkedIn",
        "indeed.com": "Indeed",
        "greenhouse.io": "Greenhouse",
        "lever.co": "Lever",
      };
      let siteName = "";
      for (const [domain, name] of Object.entries(siteNames)) {
        if (hostname.includes(domain)) {
          siteName = name;
          break;
        }
      }
      if (siteName) {
        $("#site-info").textContent = `${siteName} job page detected`;
      } else {
        $("#site-info").textContent = `Ready to capture from ${hostname}`;
      }
    }
  } catch {
    $("#site-info").textContent = "Ready to capture";
  }

  // Set up dashboard link
  chrome.runtime.sendMessage({ action: "getBaseUrl" }, (resp) => {
    const base = resp?.url || "http://localhost:8001";
    $("#link-dashboard").href = base;
    $("#link-dashboard").target = "_blank";
  });
}

// Event listeners
$("#btn-capture").addEventListener("click", doCapture);
$("#btn-retry").addEventListener("click", doCapture);
$("#btn-remove").addEventListener("click", doRemove);

$("#btn-another").addEventListener("click", () => {
  currentResult = null;
  chrome.runtime.sendMessage({ action: "clearResult" });
  showState(stateIdle);
});

// Settings links
["#link-settings", "#link-settings-err"].forEach((sel) => {
  $(sel)?.addEventListener("click", (e) => {
    e.preventDefault();
    chrome.runtime.openOptionsPage();
  });
});

// Initialize
init();
