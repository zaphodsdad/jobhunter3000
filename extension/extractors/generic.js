/**
 * JobHunter3000 — Generic Extractor (Fallback)
 *
 * Three-tier strategy:
 * 1. JSON-LD schema.org/JobPosting (best — structured data)
 * 2. Open Graph + heading heuristics
 * 3. Raw page text (LLM will parse on the backend)
 */
window.__jh3000_extract_generic = function () {
  // === Tier 1: JSON-LD schema.org/JobPosting ===
  const jsonLdScripts = document.querySelectorAll('script[type="application/ld+json"]');
  for (const script of jsonLdScripts) {
    try {
      let data = JSON.parse(script.textContent);
      // Handle arrays (some sites wrap in an array)
      if (Array.isArray(data)) data = data[0];
      // Handle @graph arrays
      if (data["@graph"]) {
        const job = data["@graph"].find(
          (item) => item["@type"] === "JobPosting"
        );
        if (job) data = job;
      }

      if (data["@type"] === "JobPosting") {
        const loc = data.jobLocation;
        let locationStr = "";
        if (loc) {
          if (typeof loc === "string") {
            locationStr = loc;
          } else if (loc.address) {
            const addr = loc.address;
            locationStr = [
              addr.addressLocality,
              addr.addressRegion,
              addr.addressCountry,
            ]
              .filter(Boolean)
              .join(", ");
          }
        }

        let salary = "";
        const bp = data.baseSalary;
        if (bp && bp.value) {
          const val = bp.value;
          if (val.minValue && val.maxValue) {
            salary = `$${val.minValue.toLocaleString()} - $${val.maxValue.toLocaleString()}`;
          } else if (val.value) {
            salary = `$${val.value.toLocaleString()}`;
          }
        }

        // Description might be HTML
        let desc = data.description || "";
        if (desc.includes("<")) {
          const tmp = document.createElement("div");
          tmp.innerHTML = desc;
          desc = tmp.textContent || tmp.innerText;
        }

        return {
          title: data.title || "",
          company:
            (data.hiringOrganization && data.hiringOrganization.name) || "",
          location: locationStr,
          salary_text: salary,
          description: desc.substring(0, 5000),
        };
      }
    } catch (e) {
      // Invalid JSON-LD, skip
    }
  }

  // === Tier 2: Open Graph + heuristics ===
  const ogTitle =
    document.querySelector('meta[property="og:title"]')?.content || "";
  const ogDesc =
    document.querySelector('meta[property="og:description"]')?.content || "";
  const h1 = document.querySelector("h1")?.textContent?.trim() || "";

  // If we have OG title that looks like a job title, use it
  if (ogTitle && ogTitle.length > 5 && ogTitle.length < 200) {
    // Try to get description from the page
    const mainContent =
      document.querySelector("main")?.textContent ||
      document.querySelector('[role="main"]')?.textContent ||
      document.querySelector("article")?.textContent ||
      "";

    if (mainContent.length > 100) {
      // Extract company from OG or page title patterns
      let company = "";
      const pageTitle = document.title || "";
      // Common patterns: "Job at Company", "Job - Company", "Job | Company"
      const patterns = [
        /at\s+(.+?)(?:\s*[-|]|$)/i,
        /[-–|]\s*(.+?)(?:\s*[-|]|$)/,
      ];
      for (const pat of patterns) {
        const m = pageTitle.match(pat);
        if (m) {
          company = m[1].trim();
          break;
        }
      }

      return {
        title: ogTitle,
        company,
        location: "",
        description: mainContent.substring(0, 5000),
        title_hint: ogTitle,
        company_hint: company,
      };
    }
  }

  // === Tier 3: Raw text fallback ===
  const bodyText = document.body?.innerText || "";
  if (bodyText.length < 100) return null; // Not enough content

  return {
    raw_text: bodyText.substring(0, 15000),
    title_hint: h1 || ogTitle,
    company_hint: "",
  };
};
