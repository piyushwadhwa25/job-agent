"""Fetchers for each job board. All return a flat list of dicts with
keys: source, company, title, url, raw_location, description, posted_date.
No AI, no cost -- these are plain HTTP + JSON/XML parsing.
posted_date is normalized to an ISO 'YYYY-MM-DD' string where available,
else "".
"""
import requests
import time
import json
import urllib.robotparser
from urllib.parse import urlparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "job-agent/1.0 (personal job search tool)"}
TIMEOUT = 15

_ROBOTS_CACHE: dict = {}


def _robots_allows(url: str) -> tuple[bool, float]:
    """Checks robots.txt for the URL's domain AT RUNTIME -- respects
    whatever the site currently allows, rather than a one-time manual
    check that could go stale. Cached per-domain so a run only fetches
    robots.txt once per site, not once per URL. Returns
    (allowed, crawl_delay_seconds). If robots.txt can't be fetched at
    all, we're conservative and treat that as NOT allowed."""
    parsed = urlparse(url)
    domain = f"{parsed.scheme}://{parsed.netloc}"
    if domain not in _ROBOTS_CACHE:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(f"{domain}/robots.txt")
        try:
            rp.read()
            _ROBOTS_CACHE[domain] = rp
        except Exception as e:
            print(f"  [robots.txt] couldn't fetch for {domain}, skipping to be safe: {e}")
            _ROBOTS_CACHE[domain] = None
    rp = _ROBOTS_CACHE[domain]
    if rp is None:
        return False, 0
    allowed = rp.can_fetch(HEADERS["User-Agent"], url)
    delay = rp.crawl_delay(HEADERS["User-Agent"]) or 1.0
    return allowed, delay


def fetch_jobpostings_via_jsonld(page_url: str, source_name: str) -> list[dict]:
    """Generic scraper for sites WITHOUT a public API, used only where
    robots.txt explicitly allows it. Extracts schema.org JobPosting
    structured data (JSON-LD) that many job boards embed for Google for
    Jobs SEO -- this is a documented, standardized format, not
    site-specific CSS-class guessing, and critically it often includes
    STRUCTURED applicantLocationRequirements (actual country list) and
    baseSalary, which is more reliable than anything we can parse from
    free text. If a given page doesn't embed this markup, this simply
    returns an empty list -- not every site does, and we don't fall back
    to guessing HTML structure for these (too fragile, too easy to
    silently break)."""
    allowed, delay = _robots_allows(page_url)
    if not allowed:
        print(f"  [{source_name}] robots.txt disallows {page_url}, skipping")
        return []
    time.sleep(delay)

    try:
        r = requests.get(page_url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        print(f"  [{source_name}] fetch failed for {page_url}: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except Exception:
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict) or item.get("@type") != "JobPosting":
                continue
            loc_reqs = item.get("applicantLocationRequirements", [])
            if isinstance(loc_reqs, dict):
                loc_reqs = [loc_reqs]
            countries = [c.get("name", "") for c in loc_reqs if isinstance(c, dict)]
            is_telecommute = item.get("jobLocationType") == "TELECOMMUTE"

            raw_location = ", ".join(countries) if countries else ("Remote" if is_telecommute else "")
            if is_telecommute and raw_location and "remote" not in raw_location.lower():
                raw_location = f"Remote - {raw_location}"

            salary_text = ""
            base_salary = item.get("baseSalary", {})
            if isinstance(base_salary, dict):
                val = base_salary.get("value", {})
                if isinstance(val, dict) and (val.get("minValue") or val.get("maxValue")):
                    cur = base_salary.get("currency", "")
                    salary_text = f"{cur} {val.get('minValue','')}-{val.get('maxValue','')}"

            description = item.get("description", "") or ""
            if salary_text:
                description = f"{description} Salary: {salary_text}."

            org = item.get("hiringOrganization", {})
            company = org.get("name", "") if isinstance(org, dict) else ""

            out.append({
                "source": source_name,
                "company": company,
                "title": item.get("title", ""),
                "url": item.get("url", "") or page_url,
                "raw_location": raw_location,
                "description": description,
                "posted_date": (item.get("datePosted", "") or "")[:10],
            })
    if not out:
        print(f"  [{source_name}] no JobPosting structured data found at {page_url} "
              f"(this site may not use schema.org markup)")
    return out


def fetch_arbeitnow() -> list[dict]:
    """Arbeitnow's public API. Confirmed documented, no auth needed.
    Europe-heavy but includes global remote roles. Has a structured
    'remote' boolean field set by the poster."""
    url = "https://www.arbeitnow.com/api/job-board-api"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  [arbeitnow] fetch failed: {e}")
        return []
    out = []
    for j in data.get("data", []):
        is_remote = j.get("remote", False)
        loc_text = j.get("location", "") or ""
        if is_remote and "remote" not in loc_text.lower():
            loc_text = f"Remote {loc_text}".strip()
        out.append({
            "source": "arbeitnow",
            "company": j.get("company_name", ""),
            "title": j.get("title", ""),
            "url": j.get("url", ""),
            "raw_location": loc_text or ("Remote" if is_remote else ""),
            "description": j.get("description", ""),
            "posted_date": _to_date_str(_parse_epoch_ms(j.get("created_at"))) if
                            str(j.get("created_at", "")).isdigit() else "",
        })
    return out


def fetch_job_page_location(url: str) -> str:
    """Best-effort: fetch the actual job page and pull the rendered
    location text (e.g. Greenhouse's '.job__location' div), since the
    jobs API's location field is sometimes empty or too generic (just
    "Remote") while the real page names a specific country. Only called
    on a small number of already-title-matched candidates, not the full
    firehose -- so the extra request per job is cheap in aggregate."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        el = soup.select_one(".job__location") or soup.select_one('[class*="location" i]')
        if el:
            return el.get_text(" ", strip=True)
    except Exception as e:
        print(f"  [page-location] fetch failed for {url}: {e}")
    return ""


def enrich_locations(jobs: list[dict], sources_to_enrich=("greenhouse",)) -> None:
    """Mutates jobs in place: for candidates from sources known to have
    unreliable API location fields, fetch the actual job page and fold
    its rendered location text into raw_location as the authoritative
    signal. Called AFTER title prefiltering so this only costs one
    extra request per real candidate, not per raw listing."""
    for j in jobs:
        if j.get("source") not in sources_to_enrich:
            continue
        page_loc = fetch_job_page_location(j["url"])
        if page_loc:
            j["raw_location"] = f"{j.get('raw_location','')} {page_loc}".strip()
        time.sleep(0.3)  # be polite, reduce chance of 429s from the same domain


def _to_date_str(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _parse_epoch_ms(ms) -> datetime | None:
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
            "source": "greenhouse",
            "company": slug,
            "title": j.get("title", ""),
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
            "source": "lever",
            "company": slug,
            "title": j.get("text", ""),
            "url": j.get("hostedUrl", ""),
            "raw_location": cats.get("location", ""),
            "description": j.get("descriptionPlain", ""),
            "posted_date": _to_date_str(_parse_epoch_ms(j.get("createdAt"))),
        })
    return out


def fetch_ashby(slug: str) -> list[dict]:
    """includeCompensation=true gets us STRUCTURED salary data straight
    from the company (when they've opted in), which is more reliable
    than regex-parsing description text.
    NOTE: compensationTiers field names below are best-effort -- check
    the next run's logs to confirm they're populating correctly."""
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
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
        description = j.get("descriptionHtml", "") or ""
        comp = j.get("compensation") or {}
        comp_tiers = comp.get("compensationTiers") or []
        if comp_tiers:
            tier = comp_tiers[0]
            lo = tier.get("minValue") or tier.get("additionalValue")
            hi = tier.get("maxValue")
            cur = tier.get("currencyCode", "")
            if lo or hi:
                description = f"{description} Salary: {cur} {lo}-{hi}."
        out.append({
            "source": "ashby",
            "company": slug,
            "title": j.get("title", ""),
            "url": j.get("jobUrl", ""),
            "raw_location": j.get("location", ""),
            "description": description,
            "posted_date": _to_date_str(_parse_iso(raw_date)),
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
            "posted_date": _to_date_str(_parse_iso(j.get("date", ""))),
        })
    return out


def fetch_weworkremotely() -> list[dict]:
    """WWR's combined RSS feed -- covers hundreds of companies at once,
    which is why this is the main lever for hitting a daily volume target
    without hand-maintaining a huge company list."""
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
            "source": "weworkremotely",
            "company": company.strip(),
            "title": title.strip(),
            "url": link,
            "raw_location": "Remote",
            "description": desc,
            "posted_date": posted_date,
        })
    return out


def fetch_himalayas() -> list[dict]:
    """Himalayas' public jobs API.
    NOTE: exact field names below are best-effort -- if this source comes
    back empty in the logs, check the live response shape at
    https://himalayas.app/jobs/api and adjust field lookups accordingly."""
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
            "source": "himalayas",
            "company": j.get("companyName", ""),
            "title": j.get("title", ""),
            "url": j.get("applicationLink") or j.get("guid", ""),
            "raw_location": loc_text,
            "description": j.get("description", "") or j.get("excerpt", ""),
            "posted_date": posted_date,
        })
    return out


def fetch_smartrecruiters(company_id: str) -> list[dict]:
    """SmartRecruiters' public postings API.
    NOTE: the postings list endpoint doesn't include full description
    text, only a summary."""
    url = f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, params={"limit": 100})
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  [smartrecruiters:{company_id}] fetch failed: {e}")
        return []
    out = []
    for j in data.get("content", []):
        loc = j.get("location", {}) or {}
        parts = []
        if loc.get("remote"):
            parts.append("Remote")
        if loc.get("country"):
            parts.append(loc["country"])
        loc_text = " - ".join(parts) if parts else "Unknown"
        out.append({
            "source": "smartrecruiters",
            "company": company_id,
            "title": j.get("name", ""),
            "url": j.get("ref", "") or f"https://jobs.smartrecruiters.com/{company_id}/{j.get('id','')}",
            "raw_location": loc_text,
            "description": "",
            "posted_date": _to_date_str(_parse_iso(j.get("releasedDate", ""))),
        })
    return out


def fetch_workable(account: str) -> list[dict]:
    """Workable's public jobs widget API."""
    url = f"https://apply.workable.com/api/v1/widget/accounts/{account}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  [workable:{account}] fetch failed: {e}")
        return []
    out = []
    for j in data.get("jobs", []):
        loc_parts = [j.get("city", ""), j.get("country", "")]
        if j.get("telecommuting"):
            loc_parts.insert(0, "Remote")
        out.append({
            "source": "workable",
            "company": account,
            "title": j.get("title", ""),
            "url": j.get("url", ""),
            "raw_location": " ".join(p for p in loc_parts if p),
            "description": j.get("description", ""),
            "posted_date": _to_date_str(_parse_iso(j.get("published_on", ""))),
        })
    return out


def fetch_remotive() -> list[dict]:
    """Remotive's public API, filtered to the 'product' category.
    High-value source: covers hundreds of companies automatically (no
    slug list to maintain), and provides an explicit
    'candidate_required_location' field (e.g. 'Worldwide', 'USA only')
    directly from the source."""
    url = "https://remotive.com/api/remote-jobs"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, params={"category": "product"})
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  [remotive] fetch failed: {e}")
        return []
    out = []
    for j in data.get("jobs", []):
        loc = j.get("candidate_required_location", "") or "Remote"
        desc = j.get("description", "")
        if j.get("salary"):
            desc = f"{desc} Salary: {j['salary']}."
        out.append({
            "source": "remotive",
            "company": j.get("company_name", ""),
            "title": j.get("title", ""),
            "url": j.get("url", ""),
            "raw_location": loc,
            "description": desc,
            "posted_date": _to_date_str(_parse_iso(j.get("publication_date", ""))),
        })
    return out


def fetch_jobicy() -> list[dict]:
    """Jobicy's public API, filtered to product-manager-relevant tags."""
    url = "https://jobicy.com/api/v2/remote-jobs"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT,
                          params={"count": 50, "tag": "product manager"})
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  [jobicy] fetch failed: {e}")
        return []
    out = []
    for j in data.get("jobs", []):
        salary_txt = ""
        if j.get("annualSalaryMin") or j.get("annualSalaryMax"):
            cur = j.get("salaryCurrency", "USD")
            salary_txt = f" Salary: {cur} {j.get('annualSalaryMin','')}-{j.get('annualSalaryMax','')}."
        out.append({
            "source": "jobicy",
            "company": j.get("companyName", ""),
            "title": j.get("jobTitle", ""),
            "url": j.get("url", ""),
            "raw_location": j.get("jobGeo", "") or "Remote",
            "description": (j.get("jobExcerpt", "") or "") + salary_txt,
            "posted_date": _to_date_str(_parse_iso(j.get("pubDate", ""))),
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
    for slug in companies.get("smartrecruiters", []):
        jobs += fetch_smartrecruiters(slug)
    for slug in companies.get("workable", []):
        jobs += fetch_workable(slug)
    jobs += fetch_remoteok()
    jobs += fetch_weworkremotely()
    jobs += fetch_himalayas()
    jobs += fetch_remotive()
    jobs += fetch_jobicy()
    jobs += fetch_arbeitnow()
    for target in companies.get("jsonld_sources", []):
        jobs += fetch_jobpostings_via_jsonld(target["url"], target["name"])
    return jobs
