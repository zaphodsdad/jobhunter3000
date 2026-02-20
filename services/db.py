"""
SQLite database — schema, connection, queries.
"""

import json
import os
import sqlite3
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "jobs.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT,
    source TEXT NOT NULL,
    url TEXT,
    title TEXT NOT NULL,
    company TEXT,
    location TEXT,
    industry TEXT,
    salary_min REAL,
    salary_max REAL,
    salary_text TEXT,
    description TEXT,
    posted_date TEXT,
    applied_date TEXT,
    scraped_at TEXT,
    score INTEGER,
    score_details TEXT,
    pros TEXT,
    cons TEXT,
    fit_summary TEXT,
    status TEXT DEFAULT 'new',
    notified INTEGER DEFAULT 0,
    resume_used TEXT,
    resume_path TEXT,
    cover_letter_path TEXT,
    contact_name TEXT,
    contact_email TEXT,
    contact_title TEXT,
    followed_up_at TEXT,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS resumes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    original_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_type TEXT,
    content_text TEXT,
    analysis TEXT,
    best_for TEXT,
    uploaded_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    source TEXT,
    query TEXT,
    jobs_found INTEGER DEFAULT 0,
    jobs_new INTEGER DEFAULT 0,
    jobs_scored INTEGER DEFAULT 0,
    notifications_sent INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running',
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(score DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);
CREATE INDEX IF NOT EXISTS idx_jobs_url ON jobs(url);
"""


def get_db(db_path: str = None) -> sqlite3.Connection:
    """Get a database connection with Row factory."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_tables(conn: sqlite3.Connection):
    """Create tables if they don't exist."""
    conn.executescript(SCHEMA)
    conn.commit()


def get_pipeline_counts(conn: sqlite3.Connection) -> dict:
    """Get count of jobs by status."""
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status"
    ).fetchall()
    counts = {row["status"]: row["cnt"] for row in rows}
    return counts


def get_dashboard_stats(conn: sqlite3.Connection) -> dict:
    """Get aggregate stats for the dashboard."""
    total = conn.execute("SELECT COUNT(*) as c FROM jobs").fetchone()["c"]
    applied = conn.execute(
        "SELECT COUNT(*) as c FROM jobs WHERE status IN ('applied', 'interviewing', 'offer', 'accepted')"
    ).fetchone()["c"]
    interviewing = conn.execute(
        "SELECT COUNT(*) as c FROM jobs WHERE status IN ('interviewing', 'offer', 'accepted')"
    ).fetchone()["c"]
    rejected = conn.execute(
        "SELECT COUNT(*) as c FROM jobs WHERE status = 'rejected'"
    ).fetchone()["c"]
    active = conn.execute(
        "SELECT COUNT(*) as c FROM jobs WHERE status IN ('interested', 'applied', 'interviewing')"
    ).fetchone()["c"]

    # Response rate: (interviewing + offer + accepted) / applied
    response_rate = 0
    if applied > 0:
        response_rate = round(interviewing / applied * 100, 1)

    # Top scored job
    top_job = conn.execute(
        "SELECT title, company, score FROM jobs WHERE score IS NOT NULL ORDER BY score DESC LIMIT 1"
    ).fetchone()

    # Recent jobs (last 10 by created_at)
    recent = conn.execute(
        "SELECT id, title, company, status, score, created_at FROM jobs ORDER BY created_at DESC LIMIT 10"
    ).fetchall()

    return {
        "total": total,
        "applied": applied,
        "interviewing": interviewing,
        "rejected": rejected,
        "active_pipeline": active,
        "response_rate": response_rate,
        "top_job": dict(top_job) if top_job else None,
        "recent": [dict(r) for r in recent],
        "pipeline_counts": get_pipeline_counts(conn),
    }


def get_jobs(conn: sqlite3.Connection, status: str = None, source: str = None,
             sort: str = "created_at", order: str = "desc",
             limit: int = 100, offset: int = 0,
             min_score: int = None) -> list[dict]:
    """Get paginated job list with optional filters."""
    where_parts = []
    params = []

    if status:
        where_parts.append("status = ?")
        params.append(status)
    else:
        # Hide archived jobs unless explicitly filtering for them
        where_parts.append("status != 'archived'")
    if source:
        where_parts.append("source = ?")
        params.append(source)
    if min_score is not None and min_score > 0:
        where_parts.append("(score >= ? OR score IS NULL)")
        params.append(min_score)

    where_clause = " AND ".join(where_parts) if where_parts else "1=1"

    # Whitelist sort columns
    valid_sorts = {"created_at", "score", "title", "company", "status", "location"}
    if sort not in valid_sorts:
        sort = "created_at"
    if order not in ("asc", "desc"):
        order = "desc"

    # Push NULLs to bottom regardless of sort direction
    if sort == "score":
        order_clause = f"CASE WHEN score IS NULL THEN 1 ELSE 0 END, score {order}"
    else:
        order_clause = f"{sort} {order}"

    query = f"""
        SELECT * FROM jobs
        WHERE {where_clause}
        ORDER BY {order_clause}
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_job(conn: sqlite3.Connection, job_id: int) -> dict | None:
    """Get a single job by ID."""
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def update_job_status(conn: sqlite3.Connection, job_id: int, new_status: str) -> bool:
    """Update a job's status."""
    valid_statuses = {"new", "interested", "applied", "interviewing", "rejected", "offer", "accepted", "archived"}
    if new_status not in valid_statuses:
        return False

    updates = {"status": new_status, "updated_at": datetime.now().isoformat()}
    if new_status == "applied":
        updates["applied_date"] = datetime.now().isoformat()

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    params = list(updates.values()) + [job_id]
    conn.execute(f"UPDATE jobs SET {set_clause} WHERE id = ?", params)
    conn.commit()
    return True


def update_job(conn: sqlite3.Connection, job_id: int, data: dict) -> bool:
    """Update arbitrary fields on a job."""
    allowed = {
        "title", "company", "location", "industry", "url", "description",
        "salary_text", "salary_min", "salary_max", "status", "notes",
        "resume_used", "resume_path", "cover_letter_path",
        "contact_name", "contact_email", "contact_title",
        "score", "score_details", "pros", "cons", "fit_summary",
        "applied_date", "followed_up_at",
    }
    to_update = {k: v for k, v in data.items() if k in allowed}
    if not to_update:
        return False

    to_update["updated_at"] = datetime.now().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in to_update)
    params = list(to_update.values()) + [job_id]
    conn.execute(f"UPDATE jobs SET {set_clause} WHERE id = ?", params)
    conn.commit()
    return True


def upsert_job(conn: sqlite3.Connection, job_data: dict) -> int:
    """Insert a job, or skip if URL already exists. Returns job ID or -1 if skipped."""
    if job_data.get("url"):
        existing = conn.execute(
            "SELECT id FROM jobs WHERE url = ?", (job_data["url"],)
        ).fetchone()
        if existing:
            return -1

    cols = [k for k in job_data if job_data[k] is not None]
    placeholders = ", ".join("?" for _ in cols)
    col_names = ", ".join(cols)
    values = [job_data[k] for k in cols]

    cursor = conn.execute(
        f"INSERT INTO jobs ({col_names}) VALUES ({placeholders})", values
    )
    conn.commit()
    return cursor.lastrowid


def get_sources(conn: sqlite3.Connection) -> list[str]:
    """Get distinct job sources."""
    rows = conn.execute("SELECT DISTINCT source FROM jobs ORDER BY source").fetchall()
    return [row["source"] for row in rows]


def get_statuses(conn: sqlite3.Connection) -> list[str]:
    """Get distinct job statuses."""
    rows = conn.execute("SELECT DISTINCT status FROM jobs ORDER BY status").fetchall()
    return [row["status"] for row in rows]
