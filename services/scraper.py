"""
Job board scraper — Playwright-based headless browser scraping.
Currently supports Indeed. SimplyHired planned.
"""

import logging
import random
import time
import urllib.parse
from datetime import datetime
from playwright.sync_api import sync_playwright

logger = logging.getLogger("jobhunter3000.scraper")

# Rotating user agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]


def _random_delay(min_s=3, max_s=8):
    """Human-like random delay between actions."""
    time.sleep(random.uniform(min_s, max_s))


def _build_indeed_url(query: str, location: str, radius_miles: int = 30,
                      salary_min: int = 0, start: int = 0) -> str:
    """Build an Indeed search URL from search parameters."""
    params = {
        "q": query,
        "l": location,
        "radius": str(radius_miles),
        "sort": "date",  # Most recent first
        "fromage": "14",  # Last 14 days
    }
    if salary_min > 0:
        params["q"] += f" ${salary_min}"
    if start > 0:
        params["start"] = str(start)

    return "https://www.indeed.com/jobs?" + urllib.parse.urlencode(params)


def scrape_indeed(profile: dict, max_pages: int = 3) -> list[dict]:
    """Scrape Indeed for jobs matching a search profile.

    profile: dict with keys: query, location, radius_miles, salary_min
    Returns: list of job dicts ready for upsert_job()
    """
    query = profile.get("query", "")
    location = profile.get("location", "")
    radius = profile.get("radius_miles", 30)
    salary_min = profile.get("salary_min", 0)

    if not query or not location:
        return []

    jobs = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )

        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )

        # Stealth: hide webdriver signals
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        """)

        page = context.new_page()

        for page_num in range(max_pages):
            start = page_num * 10
            url = _build_indeed_url(query, location, radius, salary_min, start)

            logger.info(f"Indeed: page {page_num + 1}, query='{query}', location='{location}'")

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                _random_delay(2, 5)

                # Wait for job cards to appear
                page.wait_for_selector("div.job_seen_beacon, div.jobsearch-ResultsList", timeout=15000)

            except Exception as e:
                logger.warning(f"Indeed page load failed: {e}")
                break

            # Extract job cards
            cards = page.query_selector_all("div.job_seen_beacon")
            if not cards:
                # Try alternate selector
                cards = page.query_selector_all("div.cardOutline")

            if not cards:
                logger.info(f"No job cards found on page {page_num + 1}")
                break

            logger.info(f"Found {len(cards)} job cards on page {page_num + 1}")

            for card in cards:
                try:
                    job = _extract_indeed_card(card, page)
                    if job and job.get("url"):
                        job["source"] = "indeed"
                        job["scraped_at"] = datetime.now().isoformat()
                        jobs.append(job)
                except Exception as e:
                    logger.warning(f"Failed to extract card: {e}")
                    continue

            # Check if there's a next page
            next_btn = page.query_selector('a[data-testid="pagination-page-next"]')
            if not next_btn and page_num < max_pages - 1:
                logger.info("No next page button found, stopping")
                break

            if page_num < max_pages - 1:
                _random_delay(3, 7)

        browser.close()

    logger.info(f"Indeed scrape complete: {len(jobs)} jobs found for '{query}' in '{location}'")
    return jobs


def _extract_indeed_card(card, page) -> dict | None:
    """Extract job data from a single Indeed job card element."""
    job = {}

    # Title
    title_el = card.query_selector("h2.jobTitle a, h2 a, a[data-jk]")
    if title_el:
        job["title"] = (title_el.inner_text() or "").strip()
        href = title_el.get_attribute("href") or ""
        if href.startswith("/"):
            href = "https://www.indeed.com" + href
        # Clean URL — remove tracking params, keep the job key
        if "jk=" in href or "/viewjob" in href:
            job["url"] = href.split("&")[0] if "&" in href else href
        else:
            job["url"] = href
    else:
        return None

    # Company
    company_el = card.query_selector('[data-testid="company-name"], .companyName, .company_location .companyName')
    if company_el:
        job["company"] = (company_el.inner_text() or "").strip()

    # Location
    location_el = card.query_selector('[data-testid="text-location"], .companyLocation, .company_location .companyLocation')
    if location_el:
        job["location"] = (location_el.inner_text() or "").strip()

    # Salary (if listed)
    salary_el = card.query_selector('[data-testid="attribute_snippet_testid"], .salary-snippet-container, .metadata .attribute_snippet')
    if salary_el:
        salary_text = (salary_el.inner_text() or "").strip()
        if "$" in salary_text or "year" in salary_text.lower() or "hour" in salary_text.lower():
            job["salary_text"] = salary_text

    # Description snippet
    snippet_el = card.query_selector('.job-snippet, [data-testid="job-snippet"], .underShelfFooter')
    if snippet_el:
        job["description"] = (snippet_el.inner_text() or "").strip()

    # Try to get the full description by clicking through
    if job.get("url") and title_el:
        try:
            full_desc = _get_full_description(job["url"], page)
            if full_desc:
                job["description"] = full_desc
        except Exception:
            pass  # Keep the snippet

    return job


def _get_full_description(url: str, page) -> str | None:
    """Try to get full job description from the right-side panel or detail page."""
    # Indeed shows job details in a side panel when you click a card.
    # Look for the description in the existing page first (side panel)
    desc_el = page.query_selector("#jobDescriptionText, .jobsearch-JobComponent-description")
    if desc_el:
        text = (desc_el.inner_text() or "").strip()
        if len(text) > 100:
            return text

    # If no side panel, we could navigate to the full page, but that's slower
    # and risks detection. Skip for now — snippet is better than nothing.
    return None


def run_scrape_for_profile(profile: dict) -> list[dict]:
    """Run a scrape for a single search profile. Entry point for the pipeline."""
    source = profile.get("boards", ["indeed"])[0] if profile.get("boards") else "indeed"

    if source == "indeed":
        return scrape_indeed(profile, max_pages=2)
    # Future: elif source == "simplyhired": return scrape_simplyhired(profile)

    return []


def run_full_scrape(settings: dict) -> dict:
    """Run scrapes for all enabled search profiles. Returns summary."""
    from services.db import get_db, upsert_job

    profiles = settings.get("search_profiles", [])
    enabled = [p for p in profiles if p.get("enabled", True)]

    results = {
        "profiles_run": 0,
        "jobs_found": 0,
        "jobs_new": 0,
        "errors": [],
        "started_at": datetime.now().isoformat(),
    }

    conn = get_db()

    for profile in enabled:
        try:
            logger.info(f"Scraping profile: {profile.get('name', 'unnamed')}")
            jobs = run_scrape_for_profile(profile)
            results["profiles_run"] += 1
            results["jobs_found"] += len(jobs)

            for job in jobs:
                new_id = upsert_job(conn, job)
                if new_id > 0:  # upsert_job returns -1 if URL already exists
                    results["jobs_new"] += 1

        except Exception as e:
            error_msg = f"Profile '{profile.get('name', '?')}': {str(e)}"
            logger.error(error_msg)
            results["errors"].append(error_msg)

        # Delay between profiles
        if profile != enabled[-1]:
            _random_delay(5, 12)

    conn.close()
    results["completed_at"] = datetime.now().isoformat()

    return results
