"""SQLite storage layer for the job agent."""
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).parent / "jobs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    raw_location TEXT,
    region_match TEXT,          -- which of europe/usa/singapore/uae matched
    remote_verdict TEXT,        -- 'yes' | 'no' | 'unclear'
    timezone_constrained TEXT,  -- 'yes' | 'no' | 'unknown' (informational only, not a filter)
    salary_range TEXT,          -- as stated in the listing, if any
    industry TEXT,
    classified_by TEXT,         -- 'rules' | 'ai' | null
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    status TEXT DEFAULT 'new'   -- 'new' | 'reviewed' | 'applied' | 'ignored'
);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(SCHEMA)
    return conn


def upsert_job(conn, job: dict):
    """Insert a job or refresh last_seen if it already exists (by URL)."""
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute(
        "SELECT id FROM jobs WHERE url = ?", (job["url"],)
    ).fetchone()
    if existing:
        conn.execute(
            """UPDATE jobs SET last_seen = ?,
               salary_range = COALESCE(NULLIF(?, ''), salary_range),
               industry = COALESCE(NULLIF(?, ''), industry)
               WHERE url = ?""",
            (now, job.get("salary_range", ""), job.get("industry", ""), job["url"]),
        )
        return "seen_again"
    conn.execute(
        """INSERT INTO jobs
           (source, company, title, url, raw_location, region_match,
            remote_verdict, timezone_constrained, salary_range, industry,
            classified_by, first_seen, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            job["source"], job["company"], job["title"], job["url"],
            job.get("raw_location", ""), job.get("region_match", ""),
            job.get("remote_verdict", "unclear"),
            job.get("timezone_constrained", "unknown"),
            job.get("salary_range", ""), job.get("industry", ""),
            job.get("classified_by"), now, now,
        ),
    )
    return "new"


def export_new_as_dicts(conn):
    cur = conn.execute(
        "SELECT company, title, url, raw_location, region_match, remote_verdict, "
        "salary_range, industry, timezone_constrained, first_seen "
        "FROM jobs WHERE status='new' ORDER BY first_seen DESC"
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
