"""Fetchers for each job board. All return a flat list of dicts with
keys: source, company, title, url, raw_location, description, posted_date.
No AI, no cost -- these are plain HTTP + JSON/XML parsing.
"""
import requests
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET

HEADERS = {"User-Agent": "job-agent/1.0 (personal job search tool)"}
TIMEOUT = 15


def _to_date_str(dt):
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _parse_epoch_ms(ms):
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)
    except Exception:
        return None


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
            "source": "greenhouse", "company": slug, "title": j.get("title", ""),
            "url": j.get("absolute_url", ""),
            "raw_location": (j.get("location") or {}).get("name", ""),
            "description": j.get("content", ""),
            "posted_date": _to_date_str(_parse_iso(j.get("updated_at", ""))),
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
            "source": "lever", "company": slug, "title": j.get("text", ""),
            "url": j.get("hostedUrl", ""), "raw_location": cats.get("location", ""),
            "description": j.get("descriptionPlain", ""),
            "posted_date": _to_date_str(_parse_epoch_ms(j.get("createdAt"))),
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
        raw_date = j.get("publishedAt") or j.get("publishedDate") or ""
        out.append({
            "source": "ashby", "company": slug, "title": j.get("title", ""),
            "url": j.get("jobUrl", ""), "raw_location": j.get("location", ""),
            "description": j.get("descriptionHtml", ""),
            "posted_date": _to_date_str(_parse_iso(raw_date)),
        })
    return out


def fetch_remoteok() -> list[dict]:
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
            "source": "remoteok", "company": j.get("company", ""),
            "title": j.get("position", ""), "url": j.get("url", ""),
            "raw_location": j.get("location", ""), "description": j.get("description", ""),
            "posted_date": _to_date_str(_parse_iso(j.get("date", ""))),
        })
    return out


def fetch_weworkremotely() -> list[dict]:
    url = "https://weworkremotely.com/remote-jobs.rss"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        print(f"  [weworkremotely] fetch failed: {e}")
        return []
    out = []
    for item in root.findall(".//item"):
        title_full = (item.findtext("title") or "").strip()
        company, _, title = title_full.partition(":")
        if not title:
            title, company = company, ""
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        pub_date_raw = item.findtext("pubDate") or ""
        posted_date = ""
        try:
            posted_date = _to_date_str(parsedate_to_datetime(pub_date_raw))
        except Exception:
            pass
        out.append({
            "source": "weworkremotely", "company": company.strip(), "title": title.strip(),
            "url": link, "raw_location": "Remote", "description": desc,
            "posted_date": posted_date,
        })
    return out


def fetch_himalayas() -> list[dict]:
    """NOTE: field names are best-effort -- check the live response shape
    at https://himalayas.app/jobs/api if this comes back empty."""
    url = "https://himalayas.app/jobs/api?limit=100"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  [himalayas] fetch failed: {e}")
        return []
    out = []
    for j in data.get("jobs", []):
        pub_raw = j.get("pubDate") or j.get("publishedAt") or ""
        posted_date = _to_date_str(_parse_iso(str(pub_raw))) if pub_raw else \
            _to_date_str(_parse_epoch_ms(pub_raw)) if str(pub_raw).isdigit() else ""
        restrictions = j.get("locationRestrictions") or []
        loc_text = "Remote - Global" if not restrictions else f"Remote - {', '.join(restrictions)}"
        out.append({
            "source": "himalayas", "company": j.get("companyName", ""),
            "title": j.get("title", ""),
            "url": j.get("applicationLink") or j.get("guid", ""),
            "raw_location": loc_text,
            "description": j.get("description", "") or j.get("excerpt", ""),
            "posted_date": posted_date,
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
    jobs += fetch_weworkremotely()
    jobs += fetch_himalayas()
    return jobs
