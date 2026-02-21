# JobHunter3000 Master Plan

**Created:** 2026-02-21
**Based on:** Deep research across Reddit, Hacker News, 15 n8n workflows, 9 competitors, 20+ blog posts, 3 open-source repos.

---

## Validated Strategic Position

| Debate | Market Consensus | JH3000 Status |
|--------|-----------------|---------------|
| Quality vs. quantity | Quality wins. Spray-and-pray tools have 2.1-star reviews. | Score-first. Correct. |
| Cloud vs. local | Privacy is a real adoption blocker. | Local-first. Correct. |
| Subscription vs. one-time | Job seekers resent $29-50/mo subscriptions. | $49-99 one-time. Correct. |
| Auto-apply vs. targeted | Hiring managers report 99% of mass applications are garbage. | No auto-apply. Correct. |

---

## Phase 1: Quick Wins

Low effort, high impact. Use existing data and infrastructure. Can be done in a single sprint.

### 1.1 Ghost Job / Stale Listing Detection

**Demand:** 5/5 sources. #1 pain point on Reddit (10K+ upvotes). 40% of companies post fake jobs. No competitor does this.

**What:** Flag jobs likely to be ghost listings using:
- Posting age: >30 days = yellow warning, >60 days = red flag
- Repost detection: same company+title seen in DB before
- Description vagueness: generic language vs. specific skills/tools (LLM-scored during regular scoring)

**Implementation:**
- Add `days_listed` computed display in job detail + job list (from `posted_date` or `scraped_at`)
- Add `ghost_risk` field to scoring JSON output (low/medium/high) — extend scoring prompt
- Show ghost risk badge in Intel list view and job detail page
- Flag reposted jobs: query DB for same company+title with different IDs

**Files:** `services/scorer.py` (extend prompt), `services/db.py` (repost query), `templates/jobs.html`, `templates/job_detail.html`

---

### 1.2 Follow-Up Reminder System

**Demand:** 4/5 sources. Teal charges $29/mo for follow-up templates.

**What:** Auto-calculate follow-up dates after applying. Surface in digest and dashboard.
- 7 days after applying: first follow-up due
- 14 days: second follow-up due
- Show "Follow-ups Due" section on dashboard and in morning digest

**Implementation:**
- Compute from `applied_date` field (already exists in schema)
- Add "Follow-ups Due" query to `get_dashboard_stats()`
- Add follow-ups section to `morning_digest.py`
- Show follow-up badge on job cards in pipeline view

**Files:** `services/db.py`, `templates/dashboard.html`, `scripts/morning_digest.py`, `templates/pipeline.html`

---

### 1.3 Freshness Filter

**Demand:** 3/5 sources. Early applicants convert 2-3x better. The "56-year-old dev strategy" (1,284 upvotes): only apply to listings < a few days old.

**What:** Add "Posted" column and filter to Intel page. Options: All, Last 24h, Last 48h, Last 7 days.

**Implementation:**
- Use `posted_date` (from scraper) or fall back to `scraped_at`
- Add freshness dropdown to filter bar on Intel page
- Add `days_ago` computed field in `get_jobs()` or template

**Files:** `services/db.py` (freshness filter), `templates/jobs.html` (dropdown + display), `app.py` (pass param)

---

### 1.4 AI-Summarized Job Descriptions

**Demand:** 3/5 sources. Nearly free — add to existing scoring prompt.

**What:** Store a 2-3 sentence AI summary alongside each job. Show in list view for scannable browsing. Long JDs (2000+ words) become readable at a glance.

**Implementation:**
- Add `summary` field to scoring JSON output (extend the scoring prompt)
- Add `summary TEXT` column to jobs table (migration)
- Store during scoring alongside score/pros/cons
- Display in job list view below title/company

**Files:** `services/scorer.py` (extend prompt + store), `services/db.py` (migration), `templates/jobs.html` (display)

---

### 1.5 Enhanced Daily Digest (Top-5 Section)

**Demand:** 3/5 sources. Several n8n workflows send only the top 5 matches.

**What:** Add a "Top 5 to Apply To Today" section at the top of the morning digest. Highest-scoring, freshest, not-yet-applied jobs. Actionable and triage-focused.

**Implementation:**
- Query: score >= 60, status = 'new', ordered by score DESC, LIMIT 5
- Add section before the existing "Top Matches Awaiting Action"
- Include fit_summary for each

**Files:** `scripts/morning_digest.py`

---

## Phase 2: Core Monetizable Features

These are features competitors charge $24-50/mo for. Building them justifies the $49-99 price point.

### 2.1 ATS Keyword Match Display

**Demand:** 5/5 sources. The #1 monetized feature ($24-50/mo at Jobscan, Teal, Huntr, Rezi).

**What:** Show which keywords from the JD appear in the candidate's resume and which are missing. Categorize: hard skills, soft skills, tools/tech. Show match percentage.

**Implementation:**
- Extend scoring prompt: "Also extract the top 15 required keywords from the JD. For each, indicate if the candidate's resume contains a match. Categorize as hard_skill, soft_skill, or tool."
- Add `keyword_match` JSON field to jobs table
- Store during scoring alongside score/pros/cons
- Display in job detail page as matched (green) / missing (red) chips
- Show match percentage badge in job list view

**Files:** `services/scorer.py`, `services/db.py` (migration), `templates/job_detail.html`, `templates/jobs.html`

---

### 2.2 Interview Prep Question Generator

**Demand:** 4/5 sources. Careerflow ($24/mo) and Rezi ($29/mo) charge for this.

**What:** For jobs at "interested" or "applied" status, generate 10-15 interview questions based on JD + candidate profile. Include suggested talking points and "questions to ask the interviewer."

**Implementation:**
- New `POST /api/jobs/{job_id}/interview-prep` endpoint
- New `interview_prep TEXT` column on jobs table
- LLM prompt: generate questions grouped by category (behavioral, technical, situational) + talking points from candidate's experience + 3-5 smart questions to ask
- "Prep" button on job detail page
- Display as printable checklist

**Files:** `services/scorer.py` or new `services/interview_prep.py`, `app.py`, `services/db.py`, `templates/job_detail.html`

---

### 2.3 Analytics Dashboard

**Demand:** 4/5 sources. Huntr ($40/mo) and Careerflow ($24/mo) charge for this.

**What:** Visualize the data already in SQLite:
- Applications this week/month
- Response rate (interviews / applications)
- Stage conversion funnel (new -> interested -> applied -> interview -> offer)
- Score distribution chart
- Which boards produce the most interviews
- Average time-to-response
- Comparison against industry benchmarks (3% average callback rate)

**Implementation:**
- New `/analytics` page route
- New `templates/analytics.html` with Chart.js
- Queries against existing jobs table (group by status, source, date)
- No new data needed — all derivable from current schema

**Files:** `app.py`, new `templates/analytics.html`, `static/` (Chart.js if not using CDN)

---

### 2.4 Anti-Filters (Negative Keywords)

**Demand:** 3/5 sources. HN users specifically asked for this.

**What:** Exclude specific companies, job titles containing certain words, salary below a floor.
- "Exclude Companies" list in settings
- "Exclude Title Keywords" list in settings
- Apply during scraping (skip before upserting) and during display (filter in UI)

**Implementation:**
- Add `exclude_companies` and `exclude_title_keywords` to settings schema
- Apply in `run_full_scrape()`: skip jobs matching exclusions before upsert
- Add filter options to Intel page

**Files:** `services/settings.py`, `services/scraper.py`, `templates/settings.html`, `templates/jobs.html`

---

### 2.5 Gap Analysis in Job Scoring

**Demand:** 3/5 sources (was already task #10).

**What:** "You have X, they want Y" explanations. For each job, identify specific skill/experience gaps and transferable strengths.

**Implementation:**
- Extend scoring prompt: "List 3-5 specific gaps between the candidate and this role. For each gap, note if the candidate has a transferable skill that partially covers it."
- Add `gaps` JSON field to scoring output
- Display in job detail page as a "Gap Analysis" section

**Files:** `services/scorer.py`, `templates/job_detail.html`

---

## Phase 3: v1.0 Ship Features

Polish features that complete the product story for paying customers.

### 3.1 DOCX Template-Based Resume Generation

**Demand:** 3/5 sources (was task #8).

**What:** AI provides content as structured JSON. Merge into professional .docx templates using python-docx. User can swap templates without regenerating.

**Implementation:**
- Create 2-3 ATS-friendly .docx templates (single-column, Arial, no graphics)
- Change generator to output structured JSON (contact, summary, experience bullets, skills, education)
- Use python-docx to merge content into template
- Template selector in generation UI

**Files:** `services/generator.py`, new `data/templates/*.docx`, `templates/job_detail.html`

---

### 3.2 Resume-to-JD Tailoring Enhancement

**Demand:** 4/5 sources. Jobscan charges $50/mo for "One-Click Optimize."

**What:**
- After generating a tailored resume, show diff vs. master resume
- Tagged improvement suggestions: `[ADD]`, `[QUANTIFY]`, `[EMPHASIZE]`, `[REWORD]`
- Two-score system: score original resume, generate tailored version, re-score to show improvement

**Implementation:**
- Add `score_original` and `score_tailored` fields
- LLM generates tagged suggestions in scoring output
- Display before/after scores and suggestion list

**Files:** `services/scorer.py`, `services/generator.py`, `templates/job_detail.html`

---

### 3.3 AI Search Query Generation

**Demand:** 3/5 sources (was task #6).

**What:** Feed candidate profile to LLM, get back 5-10 search queries + alternate job titles. Auto-create campaigns. Already partially implemented via `suggest_searches()` in scorer.py.

**Implementation:**
- Connect existing `suggest_searches()` to a UI button
- Generate queries, present for user approval
- Auto-execute approved queries as search campaigns via Quick Search

**Files:** `app.py`, `templates/scraper.html` or new UI section

---

### 3.4 Resume Validation Gate

**Demand:** 2/5 sources (was task #9).

**What:** Check profile completeness before wasting LLM tokens on scoring. Flag: no work history, no skills, no location, no target roles.

**Implementation:**
- Validation function that checks candidate profile for required fields
- Warning banner on dashboard if profile is incomplete
- Skip scoring with helpful error message if profile fails validation

**Files:** `services/scorer.py`, `services/resumes.py`, `templates/dashboard.html`

---

### 3.5 Salary Estimation

**Demand:** 2/5 sources. #1 opacity complaint.

**What:** When a job doesn't list salary, LLM estimates range based on title, location, company size, industry.

**Implementation:**
- Add to scoring prompt: "If no salary is listed, estimate the likely range."
- Add `salary_estimate TEXT` field
- Display estimated range with "AI Estimate" badge

**Files:** `services/scorer.py`, `services/db.py`, `templates/job_detail.html`, `templates/jobs.html`

---

## Phase 4: v1.1 Expansion

Features that grow stickiness and deepen the moat.

### 4.1 Company Research Enrichment

**What:** For each company, store and display: industry, size, and a "company research" section. LLM generates brief research summary from the JD. Later phase: Glassdoor scraping.

**Files:** `services/db.py` (companies table), `services/scorer.py`, `templates/job_detail.html`

---

### 4.2 Hiring Manager Identification

**What:** For high-scoring jobs, LLM infers likely hiring manager title from JD. Generate LinkedIn search URL. Cold outreach template.

**Files:** new `services/outreach.py`, `app.py`, `templates/job_detail.html`

---

### 4.3 Networking / Contact CRM

**What:** Simple contact tracker linked to companies and jobs. Surface "You know someone here" when viewing relevant jobs.

**Files:** `services/db.py` (contacts table), new `templates/contacts.html`, `app.py`

---

### 4.4 Target Company Watchlist

**What:** User tags dream companies. Alert when any matching job appears from those companies.

**Files:** `services/db.py` (watched_companies table), `services/scraper.py`, `services/notifier.py`

---

### 4.5 Email Inbox Monitoring

**What:** IMAP polling + LLM classification. Auto-detect interview invites, rejections, offers. Update job status automatically.

**Files:** new `services/email_monitor.py`, `app.py`, cron job

---

### 4.6 Career Page Change Monitor

**What:** "Watch this URL" feature. Check company career pages daily. Alert on changes.

**Files:** new `services/page_watcher.py`, `services/db.py`, cron job

---

### 4.7 Resume Version Tracking + A/B Analytics

**What:** Link generated documents to jobs. Track which resume version gets callbacks. Show conversion rates per variant.

**Files:** `services/db.py`, `templates/analytics.html`

---

### 4.8 Browser Extension

**What:** Chrome extension captures job postings from any board (including LinkedIn). Sends to JH3000 for scoring. Already on product roadmap.

**Files:** new `extension/` directory

---

## What NOT to Build

- Auto-apply / mass submit (universally hated, 2.1 stars on Trustpilot)
- LinkedIn scraping (rate-limited, legally risky — browser extension is the answer)
- AI-invisible text tricks in resumes (ethically questionable, actively being detected)
- Paid API dependencies (budget is zero — everything runs on Ollama + Playwright + SQLite)

---

## Build Order Summary

| Order | Feature | Effort | Impact | Status |
|-------|---------|--------|--------|--------|
| 1.1 | Ghost job detection | Low | High | **Done** |
| 1.2 | Follow-up reminders | Low | High | **Done** |
| 1.3 | Freshness filter | Low | Medium | **Done** |
| 1.4 | AI-summarized JDs | Low | High | **Done** |
| 1.5 | Enhanced digest (Top 5) | Low | Medium | **Done** |
| 2.1 | ATS keyword match | Medium | Very High | **Done** |
| 2.2 | Interview prep generator | Medium | High | **Done** |
| 2.3 | Analytics dashboard | Medium | High | **Done** |
| 2.4 | Anti-filters | Low-Med | Medium | **Done** |
| 2.5 | Gap analysis in scoring | Low | Medium | **Done** |
| 3.1 | DOCX template resumes | High | High | Pending |
| 3.2 | Resume tailoring enhancement | Medium | High | Pending |
| 3.3 | AI search query generation | Low-Med | Medium | **Done** |
| 3.4 | Resume validation gate | Low | Medium | **Done** |
| 3.5 | Salary estimation | Low | Medium | **Done** |
| — | **Onboarding wizard** | Medium | **Critical** | **Next** |
| 4.1 | Company research | Medium | Medium | Pending |
| 4.2 | Hiring manager finder | Medium | High | Pending |
| 4.3 | Contact CRM | Medium | Medium | Pending |
| 4.4 | Company watchlist | Low-Med | Medium | Pending |
| 4.5 | Email inbox monitoring | High | Very High | Pending |
| 4.6 | Career page monitor | Medium | Medium | Pending |
| 4.7 | Resume version tracking | Low-Med | Medium | Pending |
| 4.8 | Browser extension | Very High | Very High | Pending |
