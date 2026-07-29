"""Fetchers for each job board. All return a flat list of dicts with
keys: source, company, title, url, raw_location, description.
No AI, no cost -- these are plain HTTP + JSON/XML parsing.
"""
import requests

HEADERS = {"User-Agent": "job-agent/1.0 (personal job search tool)"}
TIMEOUT = 15


def fetch_greenhouse(slug: str) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  [greenhouse:{slug}] fetch failed: {e}")
        return []
    out = []
    for j in data.get("jobs", []):
        out.append({
            "source": "greenhouse",
            "company": slug,
            "title": j.get("title", ""),
            "url": j.get("absolute_url", ""),
            "raw_location": (j.get("location") or {}).get("name", ""),
            "description": j.get("content", ""),
        })
    return out


def fetch_lever(slug: str) -> list[dict]:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  [lever:{slug}] fetch failed: {e}")
        return []
    out = []
    for j in data:
        cats = j.get("categories", {})
        out.append({
            "source": "lever",
            "company": slug,
            "title": j.get("text", ""),
            "url": j.get("hostedUrl", ""),
            "raw_location": cats.get("location", ""),
            "description": j.get("descriptionPlain", ""),
        })
    return out


def fetch_ashby(slug: str) -> list[dict]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  [ashby:{slug}] fetch failed: {e}")
        return []
    out = []
    for j in data.get("jobs", []):
        out.append({
            "source": "ashby",
            "company": slug,
            "title": j.get("title", ""),
            "url": j.get("jobUrl", ""),
            "raw_location": j.get("location", ""),
            "description": j.get("descriptionHtml", ""),
        })
    return out


def fetch_remoteok() -> list[dict]:
    """RemoteOK's public JSON feed. First element is metadata, skip it."""
    url = "https://remoteok.com/api"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  [remoteok] fetch failed: {e}")
        return []
    out = []
    for j in data:
        if not isinstance(j, dict) or "position" not in j:
            continue
        out.append({
            "source": "remoteok",
            "company": j.get("company", ""),
            "title": j.get("position", ""),
            "url": j.get("url", ""),
            "raw_location": j.get("location", ""),
            "description": j.get("description", ""),
        })
    return out


def fetch_all(companies: dict) -> list[dict]:
    jobs = []
    for slug in companies.get("greenhouse", []):
        jobs += fetch_greenhouse(slug)
    for slug in companies.get("lever", []):
        jobs += fetch_lever(slug)
    for slug in companies.get("ashby", []):
        jobs += fetch_ashby(slug)
    jobs += fetch_remoteok()
    return jobs
