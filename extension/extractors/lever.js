/**
 * JobHunter3000 — Lever ATS Extractor
 * Lever-powered career pages (jobs.lever.co).
 */
window.__jh3000_extract_lever = function () {
  const selectors = {
    title: [".posting-headline h2", "h2", "h1"],
    company: [".posting-headline .sort-by-time.posting-category", ".main-header-logo img"],
    location: [
      '.posting-categories .sort-by-time.posting-category .posting-category:first-child',
      '.sort-by-time .location',
      '.posting-categories .location',
    ],
    description: [".posting-page .content", ".section-wrapper", ".posting-page"],
  };

  function trySelectors(list) {
    for (const sel of list) {
      const el = document.querySelector(sel);
      if (!el) continue;
      // For img elements, try alt text
      if (el.tagName === "IMG") return el.getAttribute("alt") || "";
      if (el.textContent.trim()) return el.textContent.trim();
    }
    return "";
  }

  const title = trySelectors(selectors.title);
  if (!title) return null;

  // Lever often puts company name in the header or page title
  let company = trySelectors(selectors.company);
  if (!company) {
    const pageTitle = document.title || "";
    const dashMatch = pageTitle.match(/^(.+?)\s*[-–]/);
    if (dashMatch) company = dashMatch[1].trim();
  }

  // Location is often in a .posting-categories div
  let location = trySelectors(selectors.location);
  if (!location) {
    const cats = document.querySelectorAll(".posting-categories .sort-by-time");
    if (cats.length > 0) location = cats[0].textContent.trim();
  }

  return {
    title,
    company,
    location,
    description: trySelectors(selectors.description).substring(0, 5000),
  };
};
