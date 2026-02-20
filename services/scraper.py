"""
Job board scraper — Playwright-based headless browser scraping.
Supports: Indeed, SimplyHired, Rigzone.
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

# Board scraper registry — maps board name to scrape function
BOARD_SCRAPERS = {}


def _random_delay(min_s=3, max_s=8):
    """Human-like random delay between actions."""
    time.sleep(random.uniform(min_s, max_s))


def _launch_browser(playwright):
    """Launch a stealth headless browser. Returns (browser, context)."""
    browser = playwright.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        viewport={"width": 1920, "height": 1080},
        locale="en-US",
    )
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    """)
    return browser, context


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

    if not query:
        return []

    jobs = []

    with sync_playwright() as p:
        browser, context = _launch_browser(p)
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


# ═══════════════════════════════════════════════════════════════
# SimplyHired Scraper
# ═══════════════════════════════════════════════════════════════

def _build_simplyhired_url(query: str, location: str, radius_miles: int = 25,
                           salary_min: int = 0) -> str:
    """Build a SimplyHired search URL."""
    params = {
        "q": query,
        "l": location,
        "sr": str(radius_miles),
        "t": "14",  # Last 14 days
        "sb": "dd",  # Sort by date
    }
    if salary_min >= 45000:
        # SimplyHired uses fixed salary brackets
        brackets = [115000, 90000, 70000, 55000, 45000]
        for b in brackets:
            if salary_min >= b:
                params["mip"] = str(b)
                break
    return "https://www.simplyhired.com/search?" + urllib.parse.urlencode(params)


def scrape_simplyhired(profile: dict, max_pages: int = 2) -> list[dict]:
    """Scrape SimplyHired for jobs matching a search profile."""
    query = profile.get("query", "")
    location = profile.get("location", "")
    radius = profile.get("radius_miles", 25)
    salary_min = profile.get("salary_min", 0)

    if not query:
        return []

    jobs = []

    with sync_playwright() as p:
        browser, context = _launch_browser(p)
        page = context.new_page()

        url = _build_simplyhired_url(query, location, radius, salary_min)

        for page_num in range(max_pages):
            logger.info(f"SimplyHired: page {page_num + 1}, query='{query}', location='{location}'")

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                _random_delay(2, 5)
                page.wait_for_selector('[data-testid="searchSerpJob"]', timeout=15000)
            except Exception as e:
                logger.warning(f"SimplyHired page load failed: {e}")
                break

            cards = page.query_selector_all('[data-testid="searchSerpJob"]')
            if not cards:
                logger.info(f"No job cards found on page {page_num + 1}")
                break

            logger.info(f"Found {len(cards)} job cards on page {page_num + 1}")

            for card in cards:
                try:
                    job = _extract_simplyhired_card(card)
                    if job and job.get("url"):
                        job["source"] = "simplyhired"
                        job["scraped_at"] = datetime.now().isoformat()
                        jobs.append(job)
                except Exception as e:
                    logger.warning(f"Failed to extract SimplyHired card: {e}")
                    continue

            # Try to get full descriptions by clicking cards
            for i, card in enumerate(cards):
                if i >= 10:  # Limit to first 10 to avoid being too slow
                    break
                try:
                    title_link = card.query_selector('[data-testid="searchSerpJobTitle"] a')
                    if title_link:
                        title_link.click()
                        _random_delay(1, 2)
                        desc_el = page.query_selector('[data-testid="viewJobBodyJobFullDescriptionContent"]')
                        if desc_el:
                            full_desc = (desc_el.inner_text() or "").strip()
                            if full_desc and i < len(jobs):
                                # Match by index since we processed in order
                                job_key = card.get_attribute("data-jobkey") or ""
                                for j in jobs:
                                    if j.get("external_id") == job_key:
                                        j["description"] = full_desc
                                        break
                except Exception:
                    pass

            # Pagination — cursor-based
            next_link = page.query_selector('[data-testid="pageNumberBlockNext"]')
            if next_link and page_num < max_pages - 1:
                next_href = next_link.get_attribute("href")
                if next_href:
                    url = "https://www.simplyhired.com" + next_href if next_href.startswith("/") else next_href
                    _random_delay(3, 6)
                else:
                    break
            else:
                break

        browser.close()

    logger.info(f"SimplyHired scrape complete: {len(jobs)} jobs for '{query}' in '{location}'")
    return jobs


def _extract_simplyhired_card(card) -> dict | None:
    """Extract job data from a SimplyHired job card."""
    job = {}

    # Job key (external ID)
    job_key = card.get_attribute("data-jobkey") or ""
    if job_key:
        job["external_id"] = job_key

    # Title + URL
    title_el = card.query_selector('[data-testid="searchSerpJobTitle"] a')
    if title_el:
        job["title"] = (title_el.inner_text() or "").strip()
        href = title_el.get_attribute("href") or ""
        if href.startswith("/"):
            href = "https://www.simplyhired.com" + href
        job["url"] = href
    else:
        return None

    # Company
    company_el = card.query_selector('[data-testid="companyName"]')
    if company_el:
        job["company"] = (company_el.inner_text() or "").strip()

    # Location
    loc_el = card.query_selector('[data-testid="searchSerpJobLocation"]')
    if loc_el:
        job["location"] = (loc_el.inner_text() or "").strip()

    # Salary
    salary_el = card.query_selector('[data-testid="salaryChip-0"]')
    if salary_el:
        job["salary_text"] = (salary_el.inner_text() or "").strip()

    return job


# ═══════════════════════════════════════════════════════════════
# Rigzone Scraper
# ═══════════════════════════════════════════════════════════════

def _build_rigzone_url(query: str, location: str = "", page: int = 1) -> str:
    """Build a Rigzone search URL.

    Rigzone uses 'fl' for country/region filter (not free-text location).
    We map common locations to their filter values.
    """
    params = {"keyword": query}
    # Rigzone uses fl= for location filtering (country/region level)
    if location:
        loc_lower = location.lower()
        if any(s in loc_lower for s in ["oklahoma", "texas", "united states", "us", "usa"]):
            params["fl"] = "United States"
        elif "canada" in loc_lower:
            params["fl"] = "Canada"
        elif "uk" in loc_lower or "united kingdom" in loc_lower:
            params["fl"] = "United Kingdom"
        else:
            # Default to US for any US city/state
            params["fl"] = "United States"
    if page > 1:
        params["page"] = str(page)
    return "https://www.rigzone.com/oil/jobs/search/?" + urllib.parse.urlencode(params)


def scrape_rigzone(profile: dict, max_pages: int = 2) -> list[dict]:
    """Scrape Rigzone for oil & gas jobs matching a search profile."""
    query = profile.get("query", "")
    location = profile.get("location", "")

    if not query:
        return []

    jobs = []

    with sync_playwright() as p:
        browser, context = _launch_browser(p)
        page = context.new_page()

        for page_num in range(1, max_pages + 1):
            url = _build_rigzone_url(query, location, page_num)
            logger.info(f"Rigzone: page {page_num}, query='{query}', location='{location}'")

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                _random_delay(2, 5)
                page.wait_for_selector("article.update-block", timeout=15000)
            except Exception as e:
                logger.warning(f"Rigzone page load failed: {e}")
                break

            cards = page.query_selector_all("article.update-block")
            if not cards:
                logger.info(f"No job cards found on page {page_num}")
                break

            logger.info(f"Found {len(cards)} job cards on page {page_num}")

            for card in cards:
                try:
                    job = _extract_rigzone_card(card)
                    if job and job.get("url"):
                        job["source"] = "rigzone"
                        job["scraped_at"] = datetime.now().isoformat()
                        jobs.append(job)
                except Exception as e:
                    logger.warning(f"Failed to extract Rigzone card: {e}")
                    continue

            if page_num < max_pages:
                _random_delay(3, 7)

        browser.close()

    logger.info(f"Rigzone scrape complete: {len(jobs)} jobs for '{query}' in '{location}'")
    return jobs


def _extract_rigzone_card(card) -> dict | None:
    """Extract job data from a Rigzone job card."""
    job = {}

    # Title + URL
    title_el = card.query_selector(".heading h3 a")
    if title_el:
        job["title"] = (title_el.inner_text() or "").strip()
        href = title_el.get_attribute("href") or ""
        if href.startswith("/"):
            href = "https://www.rigzone.com" + href
        job["url"] = href
    else:
        return None

    # Company + Location from address element
    address_el = card.query_selector(".heading address")
    if address_el:
        addr_text = (address_el.inner_text() or "").strip()
        # Rigzone format: "CompanyName  Location" or just company
        # Try to split on multiple spaces or newlines
        parts = [p.strip() for p in addr_text.replace("\n", "  ").split("  ") if p.strip()]
        if len(parts) >= 2:
            job["company"] = parts[0]
            job["location"] = parts[-1]
        elif parts:
            job["company"] = parts[0]

    # Description snippet
    desc_el = card.query_selector(".description .text p")
    if desc_el:
        job["description"] = (desc_el.inner_text() or "").strip()

    # Experience requirement
    exp_el = card.query_selector("footer.details .experience")
    if exp_el:
        exp_text = (exp_el.inner_text() or "").strip()
        if exp_text:
            job["description"] = (job.get("description", "") + f"\nExperience: {exp_text}").strip()

    # Posted date
    time_el = card.query_selector("footer.details time")
    if time_el:
        job["posted_date"] = (time_el.inner_text() or "").replace("Posted:", "").strip()

    # Industry tag
    job["industry"] = "Oil & Gas"

    return job


# ═══════════════════════════════════════════════════════════════
# Scraper Registry + Pipeline
# ═══════════════════════════════════════════════════════════════

BOARD_SCRAPERS = {
    "indeed": scrape_indeed,
    "simplyhired": scrape_simplyhired,
    "rigzone": scrape_rigzone,
}


def run_scrape_for_profile(profile: dict, enabled_boards: list = None) -> list[dict]:
    """Run scrapes across all boards for a single search profile."""
    boards = profile.get("boards", ["indeed"])
    all_jobs = []

    for board in boards:
        # Skip boards that aren't enabled globally
        if enabled_boards and board not in enabled_boards:
            continue

        scraper = BOARD_SCRAPERS.get(board)
        if not scraper:
            logger.info(f"No scraper for board '{board}', skipping")
            continue

        try:
            jobs = scraper(profile, max_pages=2)
            all_jobs.extend(jobs)
        except Exception as e:
            logger.error(f"Scraper '{board}' failed for profile: {e}")

        # Delay between boards
        if board != boards[-1]:
            _random_delay(5, 10)

    return all_jobs


def run_full_scrape(settings: dict) -> dict:
    """Run scrapes for all enabled search profiles across all enabled boards."""
    from services.db import get_db, upsert_job

    profiles = settings.get("search_profiles", [])
    enabled = [p for p in profiles if p.get("enabled", True)]
    enabled_boards = settings.get("enabled_boards", ["indeed", "simplyhired"])

    results = {
        "profiles_run": 0,
        "jobs_found": 0,
        "jobs_new": 0,
        "errors": [],
        "boards_used": list(set(enabled_boards) & set(BOARD_SCRAPERS.keys())),
        "started_at": datetime.now().isoformat(),
    }

    conn = get_db()

    for profile in enabled:
        try:
            logger.info(f"Scraping profile: {profile.get('name', 'unnamed')}")
            jobs = run_scrape_for_profile(profile, enabled_boards)
            results["profiles_run"] += 1
            results["jobs_found"] += len(jobs)

            for job in jobs:
                new_id = upsert_job(conn, job)
                if new_id > 0:
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
