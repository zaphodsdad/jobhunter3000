/**
 * JobHunter3000 — Indeed Extractor
 * Extracts job posting data from Indeed job pages.
 */
window.__jh3000_extract_indeed = function () {
  const selectors = {
    title: [
      ".jobsearch-JobInfoHeader-title",
      'h1[data-testid="jobsearch-JobInfoHeader-title"]',
      ".icl-u-xs-mb--xs.icl-u-xs-mt--none h1",
      "h1",
    ],
    company: [
      '[data-testid="inlineHeader-companyName"]',
      '[data-company-name="true"]',
      ".icl-u-lg-mr--sm.icl-u-xs-mr--xs a",
      ".jobsearch-InlineCompanyRating a",
    ],
    location: [
      '[data-testid="inlineHeader-companyLocation"]',
      '[data-testid="job-location"]',
      ".icl-u-xs-mt--xs .icl-u-textColor--secondary",
      ".jobsearch-JobInfoHeader-subtitle .icl-u-textColor--secondary",
    ],
    description: [
      "#jobDescriptionText",
      ".jobsearch-jobDescriptionText",
      "#jobsearch-ViewJobLayout-jobDisplay",
    ],
    salary: [
      "#salaryInfoAndJobType",
      '[data-testid="attribute_snippet_testid"]',
      ".jobsearch-JobMetadataHeader-item",
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
  if (!title) return null;

  return {
    title,
    company: trySelectors(selectors.company),
    location: trySelectors(selectors.location),
    salary_text: trySelectors(selectors.salary),
    description: trySelectors(selectors.description).substring(0, 5000),
  };
};
