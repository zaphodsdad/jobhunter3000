# JobHunter3000

Automated job search pipeline that scrapes job boards, scores listings against your profile using a local LLM, and sends push notifications for high-quality matches.

Built with Python, Playwright, Ollama, and SQLite.

## What It Does

1. **Scrapes job boards** on a schedule using Playwright (headless browser)
2. **Scores each job** against your profile using a local LLM (Ollama)
3. **Sends push notifications** for high-scoring matches with pros/cons summary
4. **Generates customized resumes and cover letters** on demand
5. **Finds direct contact emails** for hiring managers
6. **Tracks everything** in SQLite (applications, statuses, follow-ups)

## Architecture

```
Playwright Scraper → Dedup + SQLite → LLM Scoring → Push Notification
    (cron)              Store          (Ollama)       (if score > threshold)
                                                            │
                                                    ┌───────┴────────┐
                                                    │   On Approval  │
                                                    └───────┬────────┘
                                              ┌─────────────┼──────────────┐
                                              │             │              │
                                        Generate      Find Contact    Track
                                        Resume +      Emails          Application
                                        Cover Letter                  Status
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Scraping | Playwright (headless Chromium) |
| Scheduling | Cron |
| Job Scoring | Ollama (local LLM) |
| Resume/Cover Letter | Claude API or Ollama |
| Notifications | Pushover |
| Storage | SQLite |
| Contact Finding | Playwright + Hunter.io free tier |
| Language | Python 3.12 |

## Setup

1. Clone the repo
2. Copy `config/example-config.yaml` to `config.yaml` and fill in your details
3. Install dependencies: `pip install -r requirements.txt`
4. Install Playwright browsers: `playwright install chromium`
5. Set up your Ollama endpoint
6. Create `data/resumes/master-resume.md` with your full resume
7. Run `python scripts/setup-db.py` to initialize the database
8. Set up cron or run manually: `python scripts/run-scrape.py`

## Configuration

Copy `config/example-config.yaml` and customize:
- Search queries and job boards
- Location and salary filters
- Scoring model and thresholds
- Notification settings
- Exclude keywords and companies

## Project Structure

```
jobhunter3000/
├── src/
│   ├── scraper.py         # Playwright job board scrapers
│   ├── scorer.py          # LLM-based job scoring
│   ├── notifier.py        # Push notification sender
│   ├── generator.py       # Resume + cover letter generation
│   ├── contacts.py        # Email/contact finder
│   ├── tracker.py         # Application status tracking
│   ├── db.py              # SQLite models and queries
│   └── cli.py             # Command-line interface
├── scripts/
│   ├── run-scrape.py      # Cron entry point
│   ├── generate-app.py    # Generate application materials
│   └── setup-db.py        # Initialize database
├── data/
│   ├── resumes/           # Your resume(s) — gitignored
│   ├── cover-letters/     # Generated letters — gitignored
│   └── templates/         # Document templates
├── config/
│   └── example-config.yaml
├── logs/
└── tests/
```

## License

AGPL-3.0 — See [LICENSE](LICENSE) for full text.
