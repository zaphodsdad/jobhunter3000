/**
 * JobHunter3000 — Content Script Orchestrator
 * Detects which site we're on and runs the appropriate extractor.
 */

(() => {
  // Skip non-HTTP pages
  if (!location.protocol.startsWith("http")) return;

  /**
   * Detect which extractor to use based on hostname.
   */
  function detectSite() {
    const host = location.hostname.toLowerCase();
    if (host.includes("linkedin.com")) return { name: "linkedin", extract: window.__jh3000_extract_linkedin };
    if (host.includes("indeed.com")) return { name: "indeed", extract: window.__jh3000_extract_indeed };
    if (host.includes("greenhouse.io") || host.includes("boards.greenhouse")) return { name: "greenhouse", extract: window.__jh3000_extract_greenhouse };
    if (host.includes("lever.co") || host.includes("jobs.lever")) return { name: "lever", extract: window.__jh3000_extract_lever };
    return { name: "generic", extract: window.__jh3000_extract_generic };
  }

  /**
   * Run extraction and return job data payload.
   */
  function extractJobData() {
    const site = detectSite();
    let data = null;

    // Try site-specific extractor
    if (site.extract) {
      try {
        data = site.extract();
      } catch (e) {
        console.warn(`[JH3000] ${site.name} extractor failed:`, e);
      }
    }

    // If site-specific failed or returned nothing, try generic
    if (!data && site.name !== "generic" && window.__jh3000_extract_generic) {
      try {
        data = window.__jh3000_extract_generic();
      } catch (e) {
        console.warn("[JH3000] Generic extractor also failed:", e);
      }
    }

    if (!data) return null;

    // Attach metadata
    data.url = data.url || location.href;
    data.source = `extension-${site.name}`;

    return data;
  }

  // Listen for extraction requests from popup or background
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.action === "extract") {
      const data = extractJobData();
      sendResponse(data || { error: "Could not extract job data from this page" });
    }

    if (msg.action === "detectSite") {
      const site = detectSite();
      sendResponse({
        site: site.name,
        hostname: location.hostname,
        hasJobData: !!site.extract,
      });
    }
  });
})();
