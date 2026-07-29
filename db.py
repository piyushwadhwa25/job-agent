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
    region_match TEXT,
    remote_verdict TEXT,
    availability TEXT,
    timezone_constrained TEXT,
    salary_range TEXT,
    salary_tier TEXT,
    industry TEXT,
    posted_date TEXT,
    classified_by TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    status TEXT DEFAULT 'new'
);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn):
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
    new_cols = {"availability": "TEXT", "posted_date": "TEXT", "salary_tier": "TEXT"}
    for col, coltype in new_cols.items():
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {coltype}")
    conn.commit()


def upsert_job(conn, job: dict):
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute("SELECT id FROM jobs WHERE url = ?", (job["url"],)).fetchone()
    if existing:
        conn.execute(
            """UPDATE jobs SET last_seen = ?,
               salary_range = COALESCE(NULLIF(?, ''), salary_range),
               salary_tier = COALESCE(NULLIF(?, ''), salary_tier),
               industry = COALESCE(NULLIF(?, ''), industry),
               posted_date = COALESCE(NULLIF(?, ''), posted_date)
               WHERE url = ?""",
            (now, job.get("salary_range", ""), job.get("salary_tier", ""),
             job.get("industry", ""), job.get("posted_date", ""), job["url"]),
        )
        return "seen_again"
    conn.execute(
        """INSERT INTO jobs
           (source, company, title, url, raw_location, region_match,
            remote_verdict, availability, timezone_constrained, salary_range,
            salary_tier, industry, posted_date, classified_by, first_seen, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            job["source"], job["company"], job["title"], job["url"],
            job.get("raw_location", ""), job.get("region_match", ""),
            job.get("remote_verdict", "unclear"), job.get("availability", "global"),
            job.get("timezone_constrained", "unknown"),
            job.get("salary_range", ""), job.get("salary_tier", "unspecified"),
            job.get("industry", ""), job.get("posted_date", ""),
            job.get("classified_by"), now, now,
        ),
    )
    return "new"


def export_new_as_dicts(conn):
    cur = conn.execute(
        "SELECT company, title, url, raw_location, region_match, remote_verdict, "
        "salary_range, salary_tier, industry, posted_date, timezone_constrained, first_seen "
        "FROM jobs WHERE status='new' ORDER BY first_seen DESC"
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
