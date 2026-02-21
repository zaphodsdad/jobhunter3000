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
# RemoteOK Scraper (JSON API — no browser needed)
# ═══════════════════════════════════════════════════════════════

def scrape_remoteok(profile: dict, max_pages: int = 1) -> list[dict]:
    """Scrape RemoteOK via their public JSON API.

    RemoteOK returns all recent remote jobs. We filter client-side by query keywords.
    max_pages is ignored (single API call returns all recent jobs).
    """
    import httpx
    import re

    query = profile.get("query", "")
    if not query:
        return []

    logger.info(f"RemoteOK: fetching API, will filter for '{query}'")

    try:
        resp = httpx.get(
            "https://remoteok.com/api",
            headers={"User-Agent": random.choice(USER_AGENTS)},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"RemoteOK API fetch failed: {e}")
        return []

    # First item is metadata, skip it
    listings = data[1:] if len(data) > 1 else []

    # Build keyword patterns from query (handle OR syntax)
    keywords = [kw.strip().lower() for kw in re.split(r'\s+OR\s+', query)]

    jobs = []
    for item in listings:
        if not item.get("position"):
            continue

        # Filter: does this job match any of our keywords?
        searchable = f"{item.get('position', '')} {item.get('company', '')} {' '.join(item.get('tags', []))} {item.get('description', '')[:500]}".lower()
        if not any(kw in searchable for kw in keywords):
            continue

        job = {
            "title": item.get("position", ""),
            "company": item.get("company", ""),
            "location": item.get("location", "") or "Remote",
            "url": item.get("apply_url") or f"https://remoteok.com/remote-jobs/{item.get('slug', '')}",
            "description": item.get("description", ""),
            "source": "remoteok",
            "external_id": str(item.get("id", "")),
            "scraped_at": datetime.now().isoformat(),
        }

        # Salary
        sal_min = item.get("salary_min", 0)
        sal_max = item.get("salary_max", 0)
        if sal_min and sal_max:
            job["salary_text"] = f"${sal_min:,} - ${sal_max:,}/year"
            job["salary_min"] = sal_min
            job["salary_max"] = sal_max
        elif sal_min:
            job["salary_text"] = f"${sal_min:,}+/year"
            job["salary_min"] = sal_min

        jobs.append(job)

    logger.info(f"RemoteOK scrape complete: {len(jobs)} jobs matched '{query}' from {len(listings)} total")
    return jobs


# ═══════════════════════════════════════════════════════════════
# Dice Scraper
# ═══════════════════════════════════════════════════════════════

def _build_dice_url(query: str, location: str = "", radius: int = 30,
                    page: int = 1) -> str:
    """Build a Dice search URL."""
    params = {"q": query, "countryCode": "US", "page": str(page)}
    if location:
        params["location"] = location
        params["radius"] = str(radius)
    return "https://www.dice.com/jobs?" + urllib.parse.urlencode(params)


def scrape_dice(profile: dict, max_pages: int = 2) -> list[dict]:
    """Scrape Dice for tech jobs matching a search profile.

    Dice is a React/Next.js app — we use JS evaluation to extract data
    since the DOM uses dynamic class names.
    """
    query = profile.get("query", "")
    location = profile.get("location", "")
    radius = profile.get("radius_miles", 30)

    if not query:
        return []

    jobs = []

    with sync_playwright() as p:
        browser, context = _launch_browser(p)
        page = context.new_page()

        for page_num in range(1, max_pages + 1):
            url = _build_dice_url(query, location, radius, page_num)
            logger.info(f"Dice: page {page_num}, query='{query}', location='{location}'")

            try:
                page.goto(url, wait_until="networkidle", timeout=45000)
                _random_delay(4, 7)
                page.wait_for_selector('a[href*="/job-detail/"]', timeout=15000)
            except Exception as e:
                logger.warning(f"Dice page load failed: {e}")
                break

            # Extract jobs via JS evaluation (React DOM has no stable CSS classes)
            # Card structure: invisible overlay <a> inside a card <div>
            # Card innerText: Company \n\n [Easy Apply|Apply Now] \n Title \n\n Location \n • \n Date \n\n Snippet
            extracted = page.evaluate("""() => {
                const links = document.querySelectorAll('a[href*="/job-detail/"]');
                const jobs = [];
                const seen = new Set();
                for (const link of links) {
                    const href = link.href;
                    if (seen.has(href)) continue;
                    seen.add(href);
                    // Card is the direct parent of the overlay link
                    const card = link.parentElement;
                    if (!card) continue;
                    const text = card.innerText || '';
                    // Parse the card text — split on double newlines for sections
                    const lines = text.split('\\n').map(l => l.trim()).filter(l => l);
                    let company = '', title = '', location = '', salary = '', snippet = '';
                    // First line is usually company name
                    if (lines.length > 0) company = lines[0];
                    // Find title — comes after "Easy Apply" or "Apply Now"
                    let titleIdx = -1;
                    for (let i = 0; i < lines.length; i++) {
                        if (lines[i] === 'Easy Apply' || lines[i] === 'Apply Now') {
                            titleIdx = i + 1;
                            break;
                        }
                    }
                    if (titleIdx >= 0 && titleIdx < lines.length) {
                        title = lines[titleIdx];
                        // Location follows title
                        if (titleIdx + 1 < lines.length && lines[titleIdx + 1] !== '•') {
                            location = lines[titleIdx + 1];
                        }
                    } else if (lines.length > 1) {
                        // Fallback: second line is title
                        title = lines[1];
                    }
                    // Look for salary anywhere in text
                    for (const l of lines) {
                        if ((l.includes('$') && (l.includes('/yr') || l.includes('/hr') || l.includes(',')))) {
                            salary = l;
                            break;
                        }
                    }
                    // Skip if no title
                    if (!title || title.length < 3) continue;
                    // Clean up company — remove if it matches title
                    if (company === title) company = '';
                    if (company === 'Easy Apply' || company === 'Apply Now') company = '';
                    jobs.push({title, url: href, company, location, salary});
                }
                return jobs;
            }""")

            if extracted:
                logger.info(f"Found {len(extracted)} Dice jobs on page {page_num}")
                for item in extracted:
                    job = {
                        "title": item["title"],
                        "url": item["url"],
                        "source": "dice",
                        "scraped_at": datetime.now().isoformat(),
                    }
                    if item.get("company"):
                        job["company"] = item["company"]
                    if item.get("location"):
                        job["location"] = item["location"]
                    if item.get("salary"):
                        job["salary_text"] = item["salary"]
                    jobs.append(job)
            else:
                logger.info(f"No Dice jobs found on page {page_num}")
                break

            if page_num < max_pages:
                _random_delay(3, 7)

        browser.close()

    logger.info(f"Dice scrape complete: {len(jobs)} jobs for '{query}' in '{location}'")
    return jobs


# ═══════════════════════════════════════════════════════════════
# ZipRecruiter Scraper
# ═══════════════════════════════════════════════════════════════

def _build_ziprecruiter_url(query: str, location: str = "", radius: int = 25,
                            salary_min: int = 0, page: int = 1) -> str:
    """Build a ZipRecruiter search URL."""
    params = {"search": query, "days": "14"}
    if location:
        params["location"] = location
        params["radius"] = str(radius)
    if page > 1:
        params["page"] = str(page)
    return "https://www.ziprecruiter.com/jobs-search?" + urllib.parse.urlencode(params)


def scrape_ziprecruiter(profile: dict, max_pages: int = 2) -> list[dict]:
    """Scrape ZipRecruiter for jobs. Note: ZipRecruiter has strong anti-bot,
    so this may not always work. Gracefully returns empty on blocks."""
    query = profile.get("query", "")
    location = profile.get("location", "")
    radius = profile.get("radius_miles", 25)

    if not query:
        return []

    jobs = []

    with sync_playwright() as p:
        browser, context = _launch_browser(p)
        page = context.new_page()

        for page_num in range(1, max_pages + 1):
            url = _build_ziprecruiter_url(query, location, radius, page=page_num)
            logger.info(f"ZipRecruiter: page {page_num}, query='{query}', location='{location}'")

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                _random_delay(3, 7)
                # Wait for job cards — ZipRecruiter uses various selectors
                page.wait_for_selector('.job_result_two_pane, .jobList article, [data-testid="job-result"]', timeout=15000)
            except Exception as e:
                logger.warning(f"ZipRecruiter page load failed (may be blocked): {e}")
                break

            # Try multiple card selectors
            cards = page.query_selector_all('.job_result_two_pane, .jobList article')
            if not cards:
                cards = page.query_selector_all('[class*="job_result"], [class*="JobCard"]')

            if not cards:
                logger.info(f"No ZipRecruiter cards found on page {page_num} (may be blocked)")
                break

            logger.info(f"Found {len(cards)} ZipRecruiter cards on page {page_num}")

            for card in cards:
                try:
                    job = _extract_ziprecruiter_card(card)
                    if job and job.get("url"):
                        job["source"] = "ziprecruiter"
                        job["scraped_at"] = datetime.now().isoformat()
                        jobs.append(job)
                except Exception as e:
                    logger.warning(f"Failed to extract ZipRecruiter card: {e}")

            if page_num < max_pages:
                _random_delay(4, 9)

        browser.close()

    logger.info(f"ZipRecruiter scrape complete: {len(jobs)} jobs for '{query}' in '{location}'")
    return jobs


def _extract_ziprecruiter_card(card) -> dict | None:
    """Extract job data from a ZipRecruiter job card."""
    job = {}

    # Title + URL
    title_el = card.query_selector('a[class*="job_link"], a.jobList-title, h2 a, [data-testid="job-title"] a')
    if not title_el:
        title_el = card.query_selector('a[href*="/jobs/"]')
    if title_el:
        job["title"] = (title_el.inner_text() or "").strip()
        href = title_el.get_attribute("href") or ""
        if href.startswith("/"):
            href = "https://www.ziprecruiter.com" + href
        job["url"] = href
    else:
        return None

    # Company
    company_el = card.query_selector('[class*="company"], .companyName, [data-testid="company-name"]')
    if company_el:
        job["company"] = (company_el.inner_text() or "").strip()

    # Location
    loc_el = card.query_selector('[class*="location"], .jobList-location, [data-testid="job-location"]')
    if loc_el:
        job["location"] = (loc_el.inner_text() or "").strip()

    # Salary
    salary_el = card.query_selector('[class*="salary"], .jobList-salary')
    if salary_el:
        job["salary_text"] = (salary_el.inner_text() or "").strip()

    # Snippet
    snippet_el = card.query_selector('[class*="snippet"], .jobList-description, p')
    if snippet_el:
        job["description"] = (snippet_el.inner_text() or "").strip()

    return job


# ═══════════════════════════════════════════════════════════════
# We Work Remotely Scraper
# ═══════════════════════════════════════════════════════════════

def scrape_weworkremotely(profile: dict, max_pages: int = 1) -> list[dict]:
    """Scrape We Work Remotely for remote jobs.

    WWR doesn't have great search — we scrape category pages and filter by query.
    max_pages is ignored (categories are single pages).
    """
    import re

    query = profile.get("query", "")
    if not query:
        return []

    # WWR category URLs to check for ops/IT/management roles
    categories = [
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs",
        "https://weworkremotely.com/categories/remote-full-stack-programming-jobs",
        "https://weworkremotely.com/categories/remote-customer-support-jobs",
        "https://weworkremotely.com/categories/remote-management-and-finance-jobs",
    ]

    # Build keyword patterns from query
    keywords = [kw.strip().lower() for kw in re.split(r'\s+OR\s+', query)]

    jobs = []
    seen_urls = set()

    with sync_playwright() as p:
        browser, context = _launch_browser(p)
        page = context.new_page()

        for cat_url in categories:
            logger.info(f"WWR: checking {cat_url.split('/')[-1]}")

            try:
                page.goto(cat_url, wait_until="domcontentloaded", timeout=30000)
                _random_delay(2, 4)
            except Exception as e:
                logger.warning(f"WWR page load failed: {e}")
                continue

            # WWR has clear CSS classes inside each link
            extracted = page.evaluate("""() => {
                const seen = new Set();
                const jobs = [];
                const links = document.querySelectorAll('a[href*="/remote-jobs/"]');
                for (const link of links) {
                    const href = link.getAttribute('href');
                    if (!href || seen.has(href) || href.includes('/categories/') || href.includes('utm_')) continue;
                    seen.add(href);
                    const titleEl = link.querySelector('h3.new-listing__header__title, h3');
                    const companyEl = link.querySelector('p.new-listing__company-name, .company');
                    const regionEl = link.querySelector('p.new-listing__company-headquarters, .region');
                    const title = titleEl ? titleEl.textContent.trim() : '';
                    const company = companyEl ? companyEl.textContent.trim() : '';
                    const region = regionEl ? regionEl.textContent.trim() : 'Remote';
                    if (!title || title.length < 3) continue;
                    jobs.push({title, company, region, href});
                }
                return jobs;
            }""")

            for item in (extracted or []):
                href = item["href"]
                if href.startswith("/"):
                    href = "https://weworkremotely.com" + href

                # Deduplicate across categories
                if href in seen_urls:
                    continue
                seen_urls.add(href)

                title = item["title"]
                company = item["company"]

                # Filter by keywords
                searchable = f"{title} {company}".lower()
                if not any(kw in searchable for kw in keywords):
                    continue

                jobs.append({
                    "title": title,
                    "company": company,
                    "location": item.get("region", "Remote"),
                    "url": href,
                    "source": "weworkremotely",
                    "scraped_at": datetime.now().isoformat(),
                })

            _random_delay(2, 5)

        browser.close()

    logger.info(f"WWR scrape complete: {len(jobs)} jobs matched '{query}'")
    return jobs


# ═══════════════════════════════════════════════════════════════
# USAJobs Scraper (REST API — needs API key)
# ═══════════════════════════════════════════════════════════════

def scrape_usajobs(profile: dict, max_pages: int = 1) -> list[dict]:
    """Scrape USAJobs via their public API. Requires usajobs_api_key in settings."""
    import httpx

    query = profile.get("query", "")
    location = profile.get("location", "")

    if not query:
        return []

    # Load API key from settings
    from services.settings import load_settings
    settings = load_settings()
    api_key = settings.get("usajobs_api_key", "")
    api_email = settings.get("usajobs_api_email", "")

    if not api_key:
        logger.info("USAJobs: no API key configured, skipping")
        return []

    logger.info(f"USAJobs: query='{query}', location='{location}'")

    params = {
        "Keyword": query,
        "ResultsPerPage": "50",
        "Fields": "Full",
        "DatePosted": "14",
        "WhoMayApply": "All",
        "SortField": "DatePosted",
        "SortDirection": "Desc",
    }
    if location:
        params["LocationName"] = location

    headers = {
        "Host": "data.usajobs.gov",
        "User-Agent": api_email or "jobhunter3000@example.com",
        "Authorization-Key": api_key,
    }

    try:
        resp = httpx.get(
            "https://data.usajobs.gov/api/Search",
            params=params,
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"USAJobs API failed: {e}")
        return []

    items = data.get("SearchResult", {}).get("SearchResultItems", [])
    jobs = []

    for item in items:
        match = item.get("MatchedObjectDescriptor", {})
        if not match:
            continue

        # Location
        locations = match.get("PositionLocation", [])
        loc_str = ", ".join(l.get("LocationName", "") for l in locations[:2]) if locations else ""

        # Salary
        remuneration = match.get("PositionRemuneration", [])
        salary_text = ""
        if remuneration:
            r = remuneration[0]
            sal_min = r.get("MinimumRange", "")
            sal_max = r.get("MaximumRange", "")
            rate = r.get("RateIntervalCode", "")
            if sal_min and sal_max:
                salary_text = f"${sal_min} - ${sal_max} {rate}"

        # Description
        desc = match.get("QualificationSummary", "")
        user_area = match.get("UserArea", {}).get("Details", {})
        if user_area.get("MajorDuties"):
            duties = user_area["MajorDuties"]
            if isinstance(duties, list):
                desc = "\n".join(duties)
            elif isinstance(duties, str):
                desc = duties

        job = {
            "title": match.get("PositionTitle", ""),
            "company": match.get("OrganizationName", ""),
            "location": loc_str,
            "url": match.get("PositionURI", ""),
            "description": desc,
            "salary_text": salary_text,
            "source": "usajobs",
            "external_id": match.get("PositionID", ""),
            "scraped_at": datetime.now().isoformat(),
        }

        if job["title"] and job["url"]:
            jobs.append(job)

    logger.info(f"USAJobs scrape complete: {len(jobs)} jobs for '{query}'")
    return jobs


# ═══════════════════════════════════════════════════════════════
# Scraper Registry + Pipeline
# ═══════════════════════════════════════════════════════════════

BOARD_SCRAPERS = {
    "indeed": scrape_indeed,
    "simplyhired": scrape_simplyhired,
    "rigzone": scrape_rigzone,
    "remoteok": scrape_remoteok,
    "dice": scrape_dice,
    "ziprecruiter": scrape_ziprecruiter,
    "weworkremotely": scrape_weworkremotely,
    "usajobs": scrape_usajobs,
}


def _should_exclude(job: dict, settings: dict) -> str | None:
    """Check if a job should be excluded based on anti-filters.

    Returns the reason string if excluded, None if the job passes.
    """
    title = (job.get("title") or "").lower()
    company = (job.get("company") or "").lower()
    description = (job.get("description") or "").lower()

    # Check excluded companies
    for exc in settings.get("exclude_companies", []):
        if exc and exc.lower() in company:
            return f"excluded company: {exc}"

    # Check excluded title keywords
    for exc in settings.get("exclude_title_keywords", []):
        if exc and exc.lower() in title:
            return f"excluded title keyword: {exc}"

    # Check excluded description keywords
    text = f"{title} {description}"
    for exc in settings.get("exclude_keywords", []):
        if exc and exc.lower() in text:
            return f"excluded keyword: {exc}"

    return None


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

            # Stamp every job with the search campaign name, apply anti-filters
            campaign_name = profile.get("name", profile.get("query", ""))
            excluded = 0
            for job in jobs:
                reason = _should_exclude(job, settings)
                if reason:
                    excluded += 1
                    logger.debug(f"Excluded: {job.get('title', '?')} — {reason}")
                    continue
                job["search_query"] = campaign_name
                new_id = upsert_job(conn, job)
                if new_id > 0:
                    results["jobs_new"] += 1
            if excluded:
                logger.info(f"Anti-filters excluded {excluded} jobs from '{campaign_name}'")

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


def run_custom_search(query: str, location: str, settings: dict) -> dict:
    """Run an ad-hoc search across enabled boards for a specific query.

    Builds a temporary profile from the given query/location, scrapes,
    stamps search_query, upserts, and scores. Returns summary dict.
    """
    from services.db import get_db, upsert_job

    enabled_boards = settings.get("enabled_boards", ["indeed", "simplyhired"])
    profile = {
        "query": query,
        "location": location or settings.get("default_location", ""),
        "radius_miles": settings.get("default_radius_miles", 30),
        "salary_min": settings.get("default_salary_min", 0),
        "boards": enabled_boards,
    }

    results = {
        "query": query,
        "location": profile["location"],
        "jobs_found": 0,
        "jobs_new": 0,
        "scored": 0,
        "errors": [],
        "started_at": datetime.now().isoformat(),
    }

    try:
        jobs = run_scrape_for_profile(profile, enabled_boards)
        results["jobs_found"] = len(jobs)
    except Exception as e:
        results["errors"].append(f"Scrape failed: {e}")
        return results

    conn = get_db()
    excluded = 0
    for job in jobs:
        reason = _should_exclude(job, settings)
        if reason:
            excluded += 1
            continue
        job["search_query"] = query
        new_id = upsert_job(conn, job)
        if new_id > 0:
            results["jobs_new"] += 1
    if excluded:
        results["excluded"] = excluded

    # Auto-score new jobs
    try:
        from services.scorer import score_jobs
        scored = score_jobs(conn, settings)
        results["scored"] = scored.get("scored", 0)
    except Exception as e:
        results["errors"].append(f"Scoring failed: {e}")

    conn.close()
    results["completed_at"] = datetime.now().isoformat()
    return results
