/**
 * JobHunter3000 — Greenhouse ATS Extractor
 * Many company career pages use Greenhouse (boards.greenhouse.io).
 */
window.__jh3000_extract_greenhouse = function () {
  const selectors = {
    title: [".app-title", "h1.heading", "h1"],
    company: [".company-name", 'meta[property="og:site_name"]'],
    location: [".location", ".body--metadata"],
    description: ["#content", ".content", "#app_body"],
  };

  function trySelectors(list) {
    for (const sel of list) {
      const el = document.querySelector(sel);
      if (!el) continue;
      if (sel.startsWith("meta")) return el.getAttribute("content") || "";
      if (el.textContent.trim()) return el.textContent.trim();
    }
    return "";
  }

  const title = trySelectors(selectors.title);
  if (!title) return null;

  // Greenhouse often has company name in the page title: "Job Title at Company"
  let company = trySelectors(selectors.company);
  if (!company) {
    const pageTitle = document.title || "";
    const atMatch = pageTitle.match(/at\s+(.+?)(?:\s*[-|]|$)/i);
    if (atMatch) company = atMatch[1].trim();
  }

  return {
    title,
    company,
    location: trySelectors(selectors.location),
    description: trySelectors(selectors.description).substring(0, 5000),
  };
};
