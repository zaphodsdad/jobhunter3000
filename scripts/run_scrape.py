#!/usr/bin/env python3
"""
JobHunter3000 — Cron pipeline entry point.
Scrape all enabled profiles → score new jobs → notify high-scoring matches.

Usage:
    python3 scripts/run_scrape.py

Cron example (3x daily at 7 AM, 3 PM, 11 PM CT):
    0 13,21,5 * * * cd /root/jobhunter3000 && /root/jobhunter3000/.venv/bin/python scripts/run_scrape.py >> logs/scrape.log 2>&1
"""

import json
import logging
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.settings import load_settings
from services.db import get_db
from services.scraper import run_full_scrape
from services.scorer import score_jobs
from services.notifier import notify_job_match

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("jobhunter3000.pipeline")


def main():
    logger.info("=" * 60)
    logger.info("JobHunter3000 pipeline starting")
    logger.info("=" * 60)

    settings = load_settings()

    # 1. Record the run
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO scrape_runs (started_at, status) VALUES (datetime('now'), 'running')"
    )
    run_id = cursor.lastrowid
    conn.commit()
    conn.close()

    errors = []

    # 2. Scrape
    logger.info("Phase 1: Scraping job boards...")
    try:
        scrape_results = run_full_scrape(settings)
        logger.info(
            f"Scrape complete: {scrape_results['jobs_found']} found, "
            f"{scrape_results['jobs_new']} new"
        )
        if scrape_results.get("errors"):
            errors.extend(scrape_results["errors"])
    except Exception as e:
        logger.error(f"Scrape failed: {e}")
        errors.append(f"Scrape: {e}")
        scrape_results = {"jobs_found": 0, "jobs_new": 0}

    # 3. Score
    logger.info("Phase 2: Scoring unscored jobs...")
    scored_count = 0
    try:
        conn = get_db()
        score_results = score_jobs(conn, settings)
        conn.close()
        scored_count = score_results.get("scored", 0)
        logger.info(f"Scored {scored_count} jobs")
        if score_results.get("errors"):
            errors.extend(score_results["errors"])
    except Exception as e:
        logger.error(f"Scoring failed: {e}")
        errors.append(f"Score: {e}")

    # 4. Notify
    logger.info("Phase 3: Sending notifications for high-scoring matches...")
    notified_count = 0
    try:
        conn = get_db()
        threshold = settings.get("notify_threshold", 60)
        rows = conn.execute(
            "SELECT * FROM jobs WHERE score >= ? AND notified = 0",
            (threshold,),
        ).fetchall()

        for row in rows:
            job = dict(row)
            score_data = {
                "score": job.get("score", 0),
                "pros": json.loads(job.get("pros", "[]") or "[]"),
                "cons": json.loads(job.get("cons", "[]") or "[]"),
                "fit_summary": job.get("fit_summary", ""),
            }
            result = notify_job_match(job, score_data, settings)
            if result.get("ok"):
                conn.execute(
                    "UPDATE jobs SET notified = 1 WHERE id = ?", (job["id"],)
                )
                conn.commit()
                notified_count += 1
                logger.info(
                    f"  Notified: {job['title']} at {job.get('company', '?')} "
                    f"(score: {job['score']})"
                )

        conn.close()
        logger.info(f"Sent {notified_count} notifications")
    except Exception as e:
        logger.error(f"Notification failed: {e}")
        errors.append(f"Notify: {e}")

    # 5. Update run record
    status = "error" if errors else "completed"
    conn = get_db()
    conn.execute(
        """UPDATE scrape_runs SET
           completed_at = datetime('now'),
           jobs_found = ?, jobs_new = ?, jobs_scored = ?,
           notifications_sent = ?, status = ?, error = ?
           WHERE id = ?""",
        (
            scrape_results.get("jobs_found", 0),
            scrape_results.get("jobs_new", 0),
            scored_count,
            notified_count,
            status,
            "; ".join(errors) if errors else None,
            run_id,
        ),
    )
    conn.commit()
    conn.close()

    logger.info("=" * 60)
    logger.info(
        f"Pipeline complete: {scrape_results.get('jobs_found', 0)} found, "
        f"{scrape_results.get('jobs_new', 0)} new, "
        f"{scored_count} scored, {notified_count} notified"
    )
    if errors:
        logger.warning(f"Errors: {len(errors)}")
        for err in errors:
            logger.warning(f"  - {err}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
