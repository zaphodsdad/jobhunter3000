/**
 * JobHunter3000 — LinkedIn Extractor
 * Extracts job posting data from LinkedIn job pages.
 */
window.__jh3000_extract_linkedin = function () {
  // LinkedIn job detail pages: /jobs/view/XXXXX or /jobs/collections/...
  if (!location.pathname.includes("/jobs/")) return null;

  // Try multiple selector strategies — LinkedIn changes these frequently
  const selectors = {
    title: [
      ".job-details-jobs-unified-top-card__job-title",
      ".jobs-unified-top-card__job-title",
      ".t-24.t-bold.inline",
      "h1.topcard__title",
      "h1",
    ],
    company: [
      ".job-details-jobs-unified-top-card__company-name",
      ".jobs-unified-top-card__company-name",
      ".topcard__org-name-link",
      'a[data-tracking-control-name="public_jobs_topcard-org-name"]',
    ],
    location: [
      ".job-details-jobs-unified-top-card__bullet",
      ".jobs-unified-top-card__bullet",
      ".topcard__flavor--bullet",
    ],
    description: [
      ".jobs-description__content",
      ".jobs-box__html-content",
      ".description__text",
      "#job-details",
    ],
    salary: [
      ".job-details-jobs-unified-top-card__job-insight--highlight",
      ".salary-main-rail__data-body",
      ".compensation__salary",
    ],
  };

  function trySelectors(list) {
    for (const sel of list) {
      const el = document.querySelector(sel);
      if (el && el.textContent.trim()) return el.textContent.trim();
    }
    return "";
  }

  const title = trySelectors(selectors.title);
  if (!title) return null; // Not a job detail page

  const company = trySelectors(selectors.company);
  const location = trySelectors(selectors.location);
  const description = trySelectors(selectors.description);
  const salary = trySelectors(selectors.salary);

  return {
    title,
    company,
    location,
    salary_text: salary,
    description: description.substring(0, 5000),
  };
};
