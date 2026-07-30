"""Pure rule-based filtering. No AI cost at all.
Goal: throw away >85% of noise with regex, so the AI step only
ever sees genuinely ambiguous cases.
"""
import re
import json
from pathlib import Path


def _load_companies_db() -> dict:
    try:
        path = Path(__file__).parent / "companies_db.json"
        return json.loads(path.read_text())
    except Exception as e:
        print(f"  [companies_db] failed to load, continuing without it: {e}")
        return {}


_COMPANIES_DB = _load_companies_db()
_CONFIRMED_COMPANIES = {c.lower() for c in
                         _COMPANIES_DB.get("confirmed_india_remote", {}).get("companies", [])}
_LIKELY_COMPANIES = {c.lower() for c in
                      _COMPANIES_DB.get("global_hiring_role_dependent", {}).get("companies", [])}
_BLOCKED_COMPANIES = {c.lower() for c in
                       _COMPANIES_DB.get("known_not_india_eligible", {}).get("companies", [])}


def _company_matches(company: str, name_set: set) -> bool:
    """Substring match both directions -- handles slug vs display-name
    variance (e.g. 'gitlab' vs 'GitLab', 'helpscout' vs 'Help Scout')."""
    if not company:
        return False
    c = company.lower().strip()
    return any(name in c or c in name for name in name_set if name)

# Functions that commonly appear as "Senior/Director/VP Product X" but are
# NOT product management -- must not match even though "product" appears.
_DISQUALIFY_SUFFIX = (
    r"(design(er)?|market(ing)?|counsel|legal|engineer(ing)?|data|content|"
    r"brand|ops|operations|analytics|program|support|success|sales|"
    r"communications?|finance|hr|people|talent|recruit(ing|er)?)"
)

TITLE_PATTERNS = [
    r"\bsenior product manager\b", r"\bsr\.?\s*product manager\b",
    # Seniority word must be tightly adjacent to "product" (only whitespace/
    # comma/dash/"of" in between) AND "product" must NOT be immediately
    # followed by a disqualifying function word -- this is what "Senior
    # Product Counsel" and "Director, Product Design" were slipping
    # through on before (the old ".*" matched across any distance).
    rf"\b(senior|sr\.?|director|group|principal)\b[\s,\-]*(of\s+)?product\b"
    rf"(?!\s*{_DISQUALIFY_SUFFIX})",
    rf"\bvp\b[\s,\-]*(of\s+)?product\b(?!\s*{_DISQUALIFY_SUFFIX})",
    r"\bhead of product\b", r"\bchief product officer\b", r"\bcpo\b",
]
TITLE_RE = re.compile("|".join(TITLE_PATTERNS), re.IGNORECASE)

# Belt-and-suspenders: catches any straggler the adjacency regex above
# might still let through.
TITLE_EXCLUDE_RE = re.compile(
    r"\b(designer|design|engineer|marketing|sales|analyst|data scientist|"
    r"customer success|support|counsel|legal|program manager)\b",
    re.IGNORECASE,
)

REGION_PATTERNS = {
    "europe": r"\beurope\b|\beu\b|\buk\b|\bunited kingdom\b|\bgermany\b|\bfrance\b|"
              r"\bspain\b|\bnetherlands\b|\bportugal\b|\bpoland\b|\bitaly\b|"
              r"\bireland\b|\bemea\b",
    "usa": r"\busa\b|u\.s\.|\bunited states\b|\bus\b|\bamerica\b",
    "canada": r"\bcanada\b|\bontario\b|\bbritish columbia\b|\bbc\b(?=[\s)&]*\bon\b)|"
              r"\bon\b(?=[\s)]*only)",
    "australia": r"\baustralia\b|\bau\b",
    "singapore": r"\bsingapore\b",
    "uae": r"\buae\b|\bunited arab emirates\b|\bdubai\b|\babu dhabi\b",
}
REGION_RES = {k: re.compile(v, re.IGNORECASE) for k, v in REGION_PATTERNS.items()}

# Explicit signals that a listing is NOT globally open -- restricted to one
# country/region only. Absence of these is treated as "globally open" by
# default, since most remote postings simply don't mention a restriction
# unless one exists.
RESTRICTION_RE = re.compile(
    r"\b(must be (?:based|located|residing) in the (?:united states|u\.s\.|usa|uk|"
    r"united kingdom|eu|europe)\b|"
    r"(?:us|usa|uk|eu) citizens? only\b|"
    r"must be authorized to work in the (?:united states|u\.s\.|usa|uk|united kingdom)\b|"
    r"(?:only (?:accepting|considering) candidates|open only to residents) "
    r"(?:based |located )?in\b|"
    r"local candidates only\b|"
    r"candidates must (?:currently )?reside in\b|"
    r"this role is (?:only )?(?:open to|available to) (?:us|usa|uk|eu)[\s-]?based\b|"
    r"(?:not|unable to|cannot|can't|currently unable to) (?:currently )?hir(?:e|ing) "
    r"(?:in|from) india\b|"
    r"excluding india\b|excluding candidates (?:based |located )?in india\b|"
    r"not available (?:to|for) (?:candidates )?(?:in |from )?india\b|"
    r"except india\b|"
    r"we do not (?:currently )?hire in india\b)",
    re.IGNORECASE,
)

# Explicit signals a listing IS deliberately global -- purely informational,
# not required for a job to pass.
GLOBAL_OPEN_RE = re.compile(
    r"\b(work from anywhere|remote[\s-]?global|open to (?:all countries|"
    r"candidates worldwide|global candidates)|worldwide|anywhere in the world|"
    r"no location restriction|globally distributed|remote[\s-]?anywhere|"
    r"\banywhere\b)\b",
    re.IGNORECASE,
)

# India named explicitly as an eligible location -- the strongest possible
# confirmation, since it removes all doubt.
INDIA_EXPLICIT_RE = re.compile(
    r"\b(india|apac|asia[\s-]?pacific)\b.{0,40}\b(eligible|welcome|open|hire|hiring)\b|"
    r"\b(eligible|welcome|open|hire|hiring)\b.{0,40}\bindia\b",
    re.IGNORECASE,
)

# Matches the location FIELD directly naming India -- e.g. "India Remote",
# "Remote, India", "Remote - India". This is the single strongest positive
# signal available: a company explicitly tagging a listing with India as
# the location means it is unambiguously open to India, full stop.
INDIA_LOCATION_TAG_RE = re.compile(r"\bindia\b", re.IGNORECASE)

# Mentions of a global employer-of-record platform strongly imply the
# company can legally hire in most countries including India, even if
# India isn't named directly.
EOR_PLATFORM_RE = re.compile(
    r"\b(deel|oyster ?hr|remote\.com|papaya global|globalization partners|"
    r"multiplier|velocity global|employer of record|\bEOR\b)\b",
    re.IGNORECASE,
)

REMOTE_YES_RE = re.compile(
    r"\b(fully remote|remote[\s-]?first|100% remote|work from anywhere|"
    r"anywhere in|distributed team|async[\s-]?first)\b", re.IGNORECASE
)
REMOTE_NO_RE = re.compile(
    r"\b(hybrid|on[\s-]?site|onsite|in[\s-]?office|relocat(e|ion) required)\b",
    re.IGNORECASE
)
TZ_CONSTRAINT_RE = re.compile(
    r"\b(must overlap|core hours|within \d+ hours? of|"
    r"pst|est|cet|gmt[\s+-]?\d|\d+[\s-]?hour overlap|timezone requirement)\b",
    re.IGNORECASE
)

# Captures a currency marker alongside the range so we can tell whether a
# figure is in USD (comparable to the $60k/$100k bar) or another currency
# (shown as-is, never converted, never used to drop a listing).
SALARY_WITH_CURRENCY_RE = re.compile(
    r"(?P<cur>USD|SGD|EUR|GBP|AED|\$|€|£)\s?"
    r"(?P<low>\d[\d,]{1,})(?:\s?[kK])?"
    r"\s*(?:-|–|to)\s*"
    r"(?:USD|SGD|EUR|GBP|AED|\$|€|£)?\s?"
    r"(?P<high>\d[\d,]{1,})(?:\s?[kK])?"
)
# Bare "100k - 150k" with no currency marker at all -- ambiguous, but most
# such listings on US/global boards default to USD in practice.
SALARY_BARE_K_RE = re.compile(
    r"(?P<low>\d{2,3})[kK]\s*(?:-|–|to)\s*(?P<high>\d{2,3})[kK]"
)

USD_MARKERS = {"USD", "$"}


def extract_salary(text: str) -> tuple[str, str]:
    """Returns (display_string, tier). tier is one of:
    '100k+' | '60k-100k' | 'below-60k' | 'non-usd' | 'unspecified'
    No currency conversion is ever performed -- non-USD figures are shown
    as-is and tagged 'non-usd' so they're never used to drop a listing."""
    m = SALARY_WITH_CURRENCY_RE.search(text)
    if m:
        display = m.group(0).strip()
        cur = m.group("cur")
        low_raw, high_raw = m.group("low"), m.group("high")
        is_k = bool(re.search(r"\dk\b", display, re.IGNORECASE))
        low = int(low_raw.replace(",", "")) * (1000 if is_k and len(low_raw) <= 3 else 1)
        high = int(high_raw.replace(",", "")) * (1000 if is_k and len(high_raw) <= 3 else 1)
        if cur.upper() in USD_MARKERS or cur == "$":
            top = max(low, high)
            if top >= 100_000:
                return display, "100k+"
            if top >= 60_000:
                return display, "60k-100k"
            return display, "below-60k"
        return display, "non-usd"

    m2 = SALARY_BARE_K_RE.search(text)
    if m2:
        display = m2.group(0).strip()
        high = int(m2.group("high")) * 1000
        if high >= 100_000:
            return display, "100k+"
        if high >= 60_000:
            return display, "60k-100k"
        return display, "below-60k"

    return "", "unspecified"


def title_matches(title: str) -> bool:
    if TITLE_EXCLUDE_RE.search(title):
        return False
    return bool(TITLE_RE.search(title))


def region_hint(text: str) -> str:
    """Informational only -- which region(s) get mentioned, if any.
    Does NOT gate whether a job is kept."""
    hits = [region for region, pat in REGION_RES.items() if pat.search(text)]
    return ", ".join(hits) if hits else ""


def availability(raw_location: str, full_text: str, company: str = "") -> str:
    """'global' | 'restricted' -- whether the listing is open worldwide
    or limited to one country/region. Checked in this order:
    1. Location field explicitly names India -- always 'global', full
       stop, overrides everything else.
    2. Explicit restriction language anywhere in the text.
    3. Company is on the known-not-India-eligible list (from research)
       -- treated as restricted even if the specific listing's text
       looks fine.
    4. The location FIELD names a specific country/region (e.g.
       "Remote - US") with no explicit "open globally/worldwide/anywhere"
       language elsewhere -- empirically means restricted in practice."""
    if INDIA_LOCATION_TAG_RE.search(raw_location or ""):
        return "global"
    if RESTRICTION_RE.search(full_text):
        return "restricted"
    if _company_matches(company, _BLOCKED_COMPANIES):
        return "restricted"
    if raw_location and not GLOBAL_OPEN_RE.search(full_text):
        for _, pat in REGION_RES.items():
            if pat.search(raw_location):
                return "restricted"
    return "global"


def location_confidence(full_text: str, raw_location: str = "", company: str = "") -> str:
    """'confirmed' | 'likely' | 'assumed' -- how solid the 'you can apply
    from India' read is, for jobs that already passed availability().
    Company-level research (companies_db.json) boosts confidence even
    when the specific listing's text doesn't mention India itself."""
    if INDIA_LOCATION_TAG_RE.search(raw_location or ""):
        return "confirmed"
    if INDIA_EXPLICIT_RE.search(full_text) or EOR_PLATFORM_RE.search(full_text):
        return "confirmed"
    if _company_matches(company, _CONFIRMED_COMPANIES):
        return "confirmed"
    if GLOBAL_OPEN_RE.search(full_text):
        return "likely"
    if _company_matches(company, _LIKELY_COMPANIES):
        return "likely"
    return "assumed"


BARE_REMOTE_MENTION_RE = re.compile(r"\bremote\b", re.IGNORECASE)

# Matches specific office addresses like "San Francisco, CA" or "New York, NY"
# -- "City, ST" or "City, Country" patterns. When the location field itself
# looks like this AND doesn't say "remote", that's the ground truth: it's
# an office job, full stop, regardless of generic "we support remote work"
# boilerplate that companies often paste into every job description's
# benefits section (which was fooling both the rules and the AI).
SPECIFIC_OFFICE_RE = re.compile(r"\b[A-Za-z][A-Za-z\s]{1,30},\s*[A-Za-z]{2,}\b")


def remote_verdict(raw_location: str, full_text: str) -> str:
    """'yes' | 'no' | 'unclear'. The location field is treated as ground
    truth over the free-text description: generic "we're remote-friendly"
    boilerplate buried in a benefits section was causing genuinely
    office-based roles (location field = a specific city) to be classified
    as remote. If the location field names a specific office and doesn't
    itself say "remote", that's a hard 'no' -- no amount of boilerplate
    elsewhere overrides it."""
    loc = raw_location or ""
    loc_says_remote = bool(BARE_REMOTE_MENTION_RE.search(loc))
    if SPECIFIC_OFFICE_RE.search(loc) and not loc_says_remote:
        return "no"

    has_yes = bool(REMOTE_YES_RE.search(full_text))
    has_no = bool(REMOTE_NO_RE.search(full_text))
    if has_yes and not has_no:
        return "yes"
    if has_no:
        return "no"
    if not (loc_says_remote or BARE_REMOTE_MENTION_RE.search(full_text)):
        return "no"
    return "unclear"


def timezone_constrained(text: str) -> str:
    """'yes' | 'unknown' -- only flags explicit constraints; absence of
    a match does NOT mean unconstrained, hence 'unknown' not 'no'."""
    return "yes" if TZ_CONSTRAINT_RE.search(text) else "unknown"


def prefilter(jobs: list[dict]) -> list[dict]:
    """Stage 1: keep only jobs whose title looks like a senior product
    role. Region is no longer a requirement -- we want globally-open
    roles regardless of where the company itself is based."""
    return [j for j in jobs if title_matches(j["title"])]


def classify_with_rules(jobs: list[dict], companies: dict | None = None) -> tuple[list[dict], list[dict]]:
    """Stage 2: apply remote + global-availability + salary-bar rules.
    A job must be (a) remote, (b) not restricted to a single country
    (via explicit language OR a bare single-country location tag), and
    (c) not explicitly stated below $60k USD, to be kept. Company HQ
    location is irrelevant either way.
    Returns (resolved, needs_ai) -- resolved jobs already have a clear
    verdict and skip the AI step entirely."""
    industry_map = (companies or {}).get("industry_map", {})
    resolved, needs_ai = [], []
    for j in jobs:
        full_text = f"{j.get('raw_location','')} {j.get('description','')}"
        company_name = j.get('company', '')
        verdict = remote_verdict(j.get('raw_location', ''), full_text)
        avail = availability(j.get('raw_location', ''), full_text, company_name)
        salary_range, salary_tier = extract_salary(full_text)
        j["remote_verdict"] = verdict
        j["availability"] = avail
        j["location_confidence"] = location_confidence(full_text, j.get('raw_location', ''), company_name)
        j["timezone_constrained"] = timezone_constrained(full_text)  # informational only
        j["region_match"] = region_hint(full_text)  # informational only
        j["salary_range"] = salary_range
        j["salary_tier"] = salary_tier
        j["industry"] = industry_map.get(j.get("company", "").lower(), "")

        if verdict == "no":
            continue  # no remote language, or explicitly onsite/hybrid -- drop
        if avail == "restricted":
            continue  # single-country tag or explicit restriction -- drop
        if salary_tier == "below-60k":
            continue  # explicitly stated below your floor, drop entirely
        if verdict == "yes":
            j["classified_by"] = "rules"
            resolved.append(j)
        else:
            needs_ai.append(j)  # remote status 'unclear' -- worth a second look
    return resolved, needs_ai
