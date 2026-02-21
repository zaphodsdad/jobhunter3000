#!/usr/bin/env python3
"""
JobHunter3000 — Morning Digest Email (7:00 AM CT)
Sends an HTML summary of new jobs, top matches, pipeline status, and recent activity.

Usage:
    python3 scripts/morning_digest.py

Cron (7:00 AM CT = 13:00 UTC):
    0 13 * * * cd /root/jobhunter3000 && /root/jobhunter3000/.venv/bin/python scripts/morning_digest.py >> logs/digest.log 2>&1
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.db import get_db, get_followups_due
from services.settings import load_settings

# ── Config ────────────────────────────────────────────────
# Override via environment variables or edit here for your setup
EMAIL_TO = os.environ.get("JH3000_EMAIL_TO", "")
EMAIL_FROM = os.environ.get("JH3000_EMAIL_FROM", "")
LOG_FILE = "/root/jobhunter3000/logs/morning-digest.log"
APP_URL = os.environ.get("JH3000_APP_URL", "http://localhost:8001")


def get_digest_data():
    """Gather all data for the morning digest."""
    conn = get_db()
    settings = load_settings()

    # Time window: last 24 hours
    yesterday = (datetime.now() - timedelta(hours=24)).isoformat()
    min_score = settings.get("display_min_score", 40)

    # New jobs found in last 24h (only above display threshold)
    new_jobs = conn.execute(
        "SELECT * FROM jobs WHERE created_at > ? AND (score >= ? OR score IS NULL) ORDER BY score DESC",
        (yesterday, min_score),
    ).fetchall()
    new_jobs = [dict(r) for r in new_jobs]

    # Total new (for context — "X new, Y worth reviewing")
    total_new_raw = conn.execute(
        "SELECT COUNT(*) as cnt FROM jobs WHERE created_at > ?",
        (yesterday,),
    ).fetchone()["cnt"]

    # Score tier breakdown (last 24h)
    score_tiers = {}
    for label, lo, hi in [("80+", 80, 999), ("60-79", 60, 79), ("40-59", 40, 59), ("below 40", 0, 39)]:
        cnt = conn.execute(
            "SELECT COUNT(*) as cnt FROM jobs WHERE created_at > ? AND score >= ? AND score <= ?",
            (yesterday, lo, hi),
        ).fetchone()["cnt"]
        score_tiers[label] = cnt
    unscored = conn.execute(
        "SELECT COUNT(*) as cnt FROM jobs WHERE created_at > ? AND score IS NULL",
        (yesterday,),
    ).fetchone()["cnt"]
    score_tiers["unscored"] = unscored

    # Top matches (score >= 60) not yet applied
    top_matches = conn.execute(
        """SELECT * FROM jobs WHERE score >= 60 AND status NOT IN ('applied', 'rejected', 'offer', 'accepted', 'archived')
           ORDER BY score DESC LIMIT 10"""
    ).fetchall()
    top_matches = [dict(r) for r in top_matches]

    # Pipeline counts
    pipeline = {}
    rows = conn.execute("SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status").fetchall()
    for r in rows:
        pipeline[r["status"]] = r["cnt"]

    # Recent scrape runs in last 24h
    runs = conn.execute(
        "SELECT * FROM scrape_runs WHERE started_at > ? ORDER BY started_at DESC",
        (yesterday,),
    ).fetchall()
    runs = [dict(r) for r in runs]

    # Jobs awaiting action (scored above threshold, status still 'new')
    awaiting = conn.execute(
        "SELECT COUNT(*) as cnt FROM jobs WHERE score >= ? AND status = 'new'",
        (min_score,),
    ).fetchone()["cnt"]

    # Total stats
    total = conn.execute("SELECT COUNT(*) as cnt FROM jobs").fetchone()["cnt"]
    scored = conn.execute("SELECT COUNT(*) as cnt FROM jobs WHERE score IS NOT NULL").fetchone()["cnt"]
    avg_score = conn.execute("SELECT AVG(score) as avg FROM jobs WHERE score IS NOT NULL").fetchone()["avg"]

    # Top 5 freshest high-scoring jobs to apply to today
    top5_today = conn.execute(
        """SELECT * FROM jobs
           WHERE score >= 60 AND status = 'new'
           ORDER BY score DESC, created_at DESC LIMIT 5"""
    ).fetchall()
    top5_today = [dict(r) for r in top5_today]

    # Follow-ups due
    followups = get_followups_due(conn)

    conn.close()

    return {
        "new_jobs": new_jobs,
        "total_new_raw": total_new_raw,
        "score_tiers": score_tiers,
        "top_matches": top_matches,
        "top5_today": top5_today,
        "followups": followups,
        "pipeline": pipeline,
        "runs": runs,
        "awaiting_action": awaiting,
        "total_jobs": total,
        "total_scored": scored,
        "avg_score": round(avg_score, 1) if avg_score else 0,
        "min_score": min_score,
        "settings": settings,
    }


def build_email(data):
    """Build the HTML email body."""
    new_jobs = data["new_jobs"]
    top_matches = data["top_matches"]
    pipeline = data["pipeline"]
    runs = data["runs"]

    # Score color helper
    def score_color(s):
        if s is None:
            return "#666"
        if s >= 80:
            return "#4ade80"
        if s >= 60:
            return "#22d3ee"
        if s >= 40:
            return "#fbbf24"
        return "#6b7280"

    def score_bg(s):
        if s is None:
            return "rgba(107,114,128,0.12)"
        if s >= 80:
            return "rgba(74,222,128,0.15)"
        if s >= 60:
            return "rgba(34,211,238,0.15)"
        if s >= 40:
            return "rgba(251,191,36,0.15)"
        return "rgba(107,114,128,0.12)"

    # Header
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0; padding:0; background:#0f1117; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<div style="max-width:600px; margin:0 auto; padding:20px;">

    <!-- Header -->
    <div style="text-align:center; padding:20px 0 16px; border-bottom:1px solid #2a2d3a;">
        <h1 style="margin:0; font-size:22px; color:#e0e0e0; letter-spacing:0.5px;">
            Job<span style="color:#22d3ee;">Hunter</span>3000
        </h1>
        <p style="margin:4px 0 0; font-size:13px; color:#666;">
            Morning Briefing &mdash; {datetime.now().strftime('%A, %B %d, %Y')}
        </p>
    </div>
"""

    # Quick Stats Bar
    total_new = len(new_jobs)
    total_new_raw = data.get("total_new_raw", total_new)
    total_applied = pipeline.get("applied", 0)
    total_interviewing = pipeline.get("interviewing", 0)
    score_tiers = data.get("score_tiers", {})
    min_score = data.get("min_score", 40)
    html += f"""
    <!-- Quick Stats -->
    <div style="display:flex; justify-content:space-around; padding:16px 0; border-bottom:1px solid #2a2d3a;">
        <div style="text-align:center;">
            <div style="font-size:28px; font-weight:700; color:#22d3ee;">{total_new}</div>
            <div style="font-size:11px; color:#666; text-transform:uppercase; letter-spacing:0.5px;">Worth Reviewing</div>
            <div style="font-size:10px; color:#444;">of {total_new_raw} scraped</div>
        </div>
        <div style="text-align:center;">
            <div style="font-size:28px; font-weight:700; color:#a78bfa;">{total_applied}</div>
            <div style="font-size:11px; color:#666; text-transform:uppercase; letter-spacing:0.5px;">Applied</div>
        </div>
        <div style="text-align:center;">
            <div style="font-size:28px; font-weight:700; color:#fbbf24;">{total_interviewing}</div>
            <div style="font-size:11px; color:#666; text-transform:uppercase; letter-spacing:0.5px;">Interviewing</div>
        </div>
        <div style="text-align:center;">
            <div style="font-size:28px; font-weight:700; color:#4ade80;">{data['awaiting_action']}</div>
            <div style="font-size:11px; color:#666; text-transform:uppercase; letter-spacing:0.5px;">Need Review</div>
        </div>
    </div>

    <!-- Score Breakdown (24h) -->
    <div style="padding:12px 0; border-bottom:1px solid #2a2d3a;">
        <div style="font-size:11px; color:#666; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:8px;">
            Last 24h Score Breakdown
        </div>
        <div style="display:flex; justify-content:space-around; text-align:center;">
            <div>
                <span style="font-size:18px; font-weight:700; color:#4ade80;">{score_tiers.get('80+', 0)}</span>
                <div style="font-size:10px; color:#4ade80;">80+</div>
            </div>
            <div>
                <span style="font-size:18px; font-weight:700; color:#22d3ee;">{score_tiers.get('60-79', 0)}</span>
                <div style="font-size:10px; color:#22d3ee;">60-79</div>
            </div>
            <div>
                <span style="font-size:18px; font-weight:700; color:#fbbf24;">{score_tiers.get('40-59', 0)}</span>
                <div style="font-size:10px; color:#fbbf24;">40-59</div>
            </div>
            <div>
                <span style="font-size:18px; font-weight:700; color:#6b7280;">{score_tiers.get('below 40', 0)}</span>
                <div style="font-size:10px; color:#6b7280;">&lt;40</div>
            </div>
            <div>
                <span style="font-size:18px; font-weight:700; color:#444;">{score_tiers.get('unscored', 0)}</span>
                <div style="font-size:10px; color:#444;">pending</div>
            </div>
        </div>
        <div style="font-size:10px; color:#444; text-align:center; margin-top:6px;">
            Showing jobs scoring {min_score}+ &middot; Change threshold in Settings
        </div>
    </div>
"""

    # Top 5 to Apply To Today
    top5 = data.get("top5_today", [])
    if top5:
        html += """
    <!-- Top 5 Today -->
    <div style="padding:16px 0; border-bottom:1px solid #2a2d3a;">
        <h2 style="font-size:14px; color:#4ade80; text-transform:uppercase; letter-spacing:1px; margin:0 0 12px;">
            <span style="color:#22d3ee;">//</span> Top 5 to Apply To Today
        </h2>
        <p style="font-size:12px; color:#666; margin:0 0 10px;">These are your highest-scoring fresh jobs. Apply to these first.</p>
"""
        for i, job in enumerate(top5, 1):
            score = job.get("score", 0)
            fit = job.get("fit_summary", "")
            url = job.get("url", "")
            html += f"""
        <div style="background:#1a1d27; border:1px solid #2a2d3a; border-radius:8px; padding:12px; margin-bottom:6px;">
            <div style="display:flex; align-items:center; gap:10px;">
                <span style="display:inline-block; padding:3px 10px; font-size:14px; font-weight:700;
                             border-radius:6px; background:{score_bg(score)}; color:{score_color(score)};">
                    #{i} &middot; {score}
                </span>
                <div>
                    <div style="font-size:14px; font-weight:600; color:#e0e0e0;">{job.get('title', 'Unknown')}</div>
                    <div style="font-size:12px; color:#999;">{job.get('company', 'Unknown')} &middot; {job.get('location', '')}</div>
                </div>
            </div>
            {f'<div style="font-size:12px; color:#999; margin-top:4px;">{fit}</div>' if fit else ''}
            {f'<div style="margin-top:4px;"><a href="{url}" style="font-size:12px; color:#22d3ee;">View Posting</a> &middot; <a href="{APP_URL}/jobs/{job["id"]}" style="font-size:12px; color:#22d3ee;">Open in JH3000</a></div>' if url else ''}
        </div>
"""
        html += "    </div>\n"

    # Follow-ups Due
    followups = data.get("followups", [])
    if followups:
        html += f"""
    <!-- Follow-ups Due -->
    <div style="padding:16px 0; border-bottom:1px solid #2a2d3a;">
        <h2 style="font-size:14px; color:#fbbf24; text-transform:uppercase; letter-spacing:1px; margin:0 0 12px;">
            <span style="color:#22d3ee;">//</span> Follow-ups Due ({len(followups)})
        </h2>
"""
        for fu in followups[:5]:
            days = fu.get("days_since_applied", 0)
            urgency_color = "#f87171" if days >= 14 else "#fbbf24"
            urgency_text = "2nd follow-up due" if days >= 14 else "Follow up now"
            html += f"""
        <div style="font-size:13px; color:#999; padding:6px 0; border-bottom:1px solid #1a1d27;">
            <span style="color:{urgency_color}; font-weight:600;">{days}d</span>
            &mdash; {fu.get('title', '?')} at {fu.get('company', '?')}
            <span style="color:{urgency_color}; font-size:11px;"> ({urgency_text})</span>
        </div>
"""
        if len(followups) > 5:
            html += f'        <div style="font-size:11px; color:#666; padding:6px 0;">+ {len(followups) - 5} more</div>\n'
        html += "    </div>\n"

    # Top Matches section
    if top_matches:
        html += """
    <!-- Top Matches -->
    <div style="padding:16px 0;">
        <h2 style="font-size:14px; color:#e0e0e0; text-transform:uppercase; letter-spacing:1px; margin:0 0 12px;">
            <span style="color:#22d3ee;">//</span> Top Matches Awaiting Action
        </h2>
"""
        for job in top_matches[:7]:
            score = job.get("score", 0)
            pros = json.loads(job.get("pros", "[]") or "[]")
            fit = job.get("fit_summary", "")
            url = job.get("url", "")
            html += f"""
        <div style="background:#1a1d27; border:1px solid #2a2d3a; border-radius:8px; padding:14px; margin-bottom:8px;">
            <div style="display:flex; align-items:center; gap:10px; margin-bottom:6px;">
                <span style="display:inline-block; padding:3px 10px; font-size:14px; font-weight:700;
                             border-radius:6px; background:{score_bg(score)}; color:{score_color(score)};">
                    {score}
                </span>
                <div>
                    <div style="font-size:15px; font-weight:600; color:#e0e0e0;">
                        {job.get('title', 'Unknown')}
                    </div>
                    <div style="font-size:13px; color:#999;">
                        {job.get('company', 'Unknown')} &middot; {job.get('location', '')}
                        {' &middot; ' + job.get('salary_text', '') if job.get('salary_text') else ''}
                    </div>
                </div>
            </div>
            {f'<div style="font-size:13px; color:#999; margin-top:4px;">{fit}</div>' if fit else ''}
            {f'<div style="font-size:12px; color:#4ade80; margin-top:4px;">Pros: {"; ".join(pros[:3])}</div>' if pros else ''}
            {f'<div style="margin-top:6px;"><a href="{url}" style="font-size:12px; color:#22d3ee;">View Posting</a></div>' if url else ''}
        </div>
"""
        html += "    </div>\n"
    else:
        html += """
    <div style="padding:20px 0; text-align:center; color:#666; font-size:14px;">
        No high-scoring matches awaiting action. Keep hunting!
    </div>
"""

    # Scrape Run Summary
    if runs:
        html += """
    <!-- Recent Runs -->
    <div style="padding:16px 0; border-top:1px solid #2a2d3a;">
        <h2 style="font-size:14px; color:#e0e0e0; text-transform:uppercase; letter-spacing:1px; margin:0 0 12px;">
            <span style="color:#22d3ee;">//</span> Recon Activity (24h)
        </h2>
"""
        for run in runs:
            status_color = "#4ade80" if run.get("status") == "completed" else "#f87171"
            html += f"""
        <div style="font-size:13px; color:#999; padding:6px 0; border-bottom:1px solid #1a1d27;">
            <span style="color:{status_color}; font-weight:600;">{run.get('status', '?').upper()}</span>
            &mdash; Found {run.get('jobs_found', 0)} jobs, {run.get('jobs_new', 0)} new,
            {run.get('jobs_scored', 0)} scored, {run.get('notifications_sent', 0)} notifications
            {f" &mdash; {run.get('started_at', '')}" if run.get('started_at') else ''}
        </div>
"""
        html += "    </div>\n"

    # Pipeline Summary
    html += f"""
    <!-- Pipeline -->
    <div style="padding:16px 0; border-top:1px solid #2a2d3a;">
        <h2 style="font-size:14px; color:#e0e0e0; text-transform:uppercase; letter-spacing:1px; margin:0 0 12px;">
            <span style="color:#22d3ee;">//</span> Pipeline Status
        </h2>
        <table style="width:100%; font-size:13px; color:#999;" cellpadding="4" cellspacing="0">
            <tr><td>New / Unreviewed</td><td style="text-align:right; font-weight:600; color:#6c8bef;">{pipeline.get('new', 0)}</td></tr>
            <tr><td>Interested</td><td style="text-align:right; font-weight:600; color:#22d3ee;">{pipeline.get('interested', 0)}</td></tr>
            <tr><td>Applied</td><td style="text-align:right; font-weight:600; color:#a78bfa;">{pipeline.get('applied', 0)}</td></tr>
            <tr><td>Interviewing</td><td style="text-align:right; font-weight:600; color:#fbbf24;">{pipeline.get('interviewing', 0)}</td></tr>
            <tr><td>Offers</td><td style="text-align:right; font-weight:600; color:#4ade80;">{pipeline.get('offer', 0)}</td></tr>
            <tr><td>Rejected</td><td style="text-align:right; font-weight:600; color:#6b7280;">{pipeline.get('rejected', 0)}</td></tr>
        </table>
        <div style="font-size:12px; color:#666; margin-top:8px;">
            {data['total_jobs']} total jobs tracked &middot; {data['total_scored']} scored &middot; Avg score: {data['avg_score']}
        </div>
    </div>
"""

    # Footer with link
    html += f"""
    <!-- Footer -->
    <div style="padding:16px 0; border-top:1px solid #2a2d3a; text-align:center;">
        <a href="{APP_URL}/dashboard" style="display:inline-block; padding:10px 24px; background:#22d3ee;
           color:#0f1117; font-weight:600; font-size:14px; border-radius:6px; text-decoration:none;">
            Open Mission Control
        </a>
        <p style="font-size:11px; color:#444; margin-top:12px;">
            JobHunter3000 &mdash; Automated recon at {APP_URL}
        </p>
    </div>

</div>
</body>
</html>"""

    return html


def send_email(subject, html):
    """Send HTML email via msmtp."""
    msg = MIMEMultipart("related")
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg["Subject"] = subject

    msg.attach(MIMEText(html, "html"))

    raw = msg.as_string()
    try:
        proc = subprocess.run(
            ["msmtp", "-a", "gmail", EMAIL_TO],
            input=raw, capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            print(f"Email send failed: {proc.stderr}", file=sys.stderr)
        else:
            print(f"Digest email sent to {EMAIL_TO}")
    except Exception as e:
        print(f"Email error: {e}", file=sys.stderr)


def main():
    print(f"[{datetime.now().isoformat()}] Building morning digest...")

    data = get_digest_data()

    # Build subject line with key stats
    new_count = len(data["new_jobs"])
    top_score = max((j.get("score", 0) for j in data["top_matches"]), default=0)
    awaiting = data["awaiting_action"]
    tiers = data.get("score_tiers", {})
    hot = tiers.get("80+", 0)

    if hot > 0:
        subject = f"JH3000: {hot} hot matches (80+) | {awaiting} need review"
    elif top_score >= 60:
        subject = f"JH3000: {new_count} worth reviewing | Top: {top_score}/100"
    elif new_count > 0:
        subject = f"JH3000: {new_count} new (of {data.get('total_new_raw', new_count)} scraped) | {awaiting} to review"
    else:
        subject = f"JH3000: Morning briefing | {awaiting} awaiting review"

    html = build_email(data)
    send_email(subject, html)

    print(f"[{datetime.now().isoformat()}] Digest complete.")


if __name__ == "__main__":
    main()
