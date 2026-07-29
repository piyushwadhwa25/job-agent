"""Pure rule-based filtering. No AI cost at all.
Goal: throw away >85% of noise with regex, so the AI step only
ever sees genuinely ambiguous cases.
"""
import re

TITLE_PATTERNS = [
    r"\bsenior product manager\b", r"\bsr\.?\s*product manager\b",
    r"\bsenior\b.*\bproduct\b", r"\bdirector\b.*\bproduct\b",
    r"\bvp\b.*\bproduct\b", r"\bhead of product\b",
    r"\bgroup product manager\b", r"\bprincipal product manager\b",
    r"\bchief product officer\b", r"\bcpo\b",
]
TITLE_RE = re.compile("|".join(TITLE_PATTERNS), re.IGNORECASE)

# Explicit exclusions to cut false positives (e.g. "Senior Product Designer")
TITLE_EXCLUDE_RE = re.compile(
    r"\b(designer|engineer|marketing|sales|analyst|data scientist|"
    r"customer success|support)\b", re.IGNORECASE
)

REGION_PATTERNS = {
    "europe": r"\b(europe|eu\b|uk\b|united kingdom|germany|france|spain|"
              r"netherlands|portugal|poland|italy|ireland|emea)\b",
    "usa": r"\b(usa\b|u\.s\.|united states|us\b|america)\b",
    "singapore": r"\bsingapore\b",
    "uae": r"\b(uae\b|united arab emirates|dubai|abu dhabi)\b",
}
REGION_RES = {k: re.compile(v, re.IGNORECASE) for k, v in REGION_PATTERNS.items()}

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

# Common ways salary ranges show up in job postings (kept deliberately loose
# -- false negatives here just mean an empty column, not a wrong filter).
SALARY_RE = re.compile(
    r"(?:USD|SGD|EUR|GBP|AED|\$|€|£)\s?\d[\d,]{2,}(?:\s?[kK])?"
    r"\s*(?:-|–|to)\s*"
    r"(?:USD|SGD|EUR|GBP|AED|\$|€|£)?\s?\d[\d,]{2,}(?:\s?[kK])?"
    r"|\d{2,3}[kK]\s*(?:-|–|to)\s*\d{2,3}[kK]"
)


def extract_salary(text: str) -> str:
    m = SALARY_RE.search(text)
    return m.group(0).strip() if m else ""


def title_matches(title: str) -> bool:
    if TITLE_EXCLUDE_RE.search(title):
        return False
    return bool(TITLE_RE.search(title))


def region_match(text: str) -> str | None:
    """Return first matching region, or None."""
    for region, pat in REGION_RES.items():
        if pat.search(text):
            return region
    return None


def remote_verdict(text: str) -> str:
    """'yes' | 'no' | 'unclear' based on plain keyword rules."""
    has_yes = bool(REMOTE_YES_RE.search(text))
    has_no = bool(REMOTE_NO_RE.search(text))
    if has_yes and not has_no:
        return "yes"
    if has_no:
        return "no"
    return "unclear"


def timezone_constrained(text: str) -> str:
    """'yes' | 'unknown' -- only flags explicit constraints; absence of
    a match does NOT mean unconstrained, hence 'unknown' not 'no'."""
    return "yes" if TZ_CONSTRAINT_RE.search(text) else "unknown"


def prefilter(jobs: list[dict]) -> list[dict]:
    """Stage 1: keep only jobs whose title looks like a senior product
    role AND whose location text mentions one of our target regions."""
    kept = []
    for j in jobs:
        if not title_matches(j["title"]):
            continue
        haystack = f"{j.get('raw_location','')} {j.get('description','')[:500]}"
        region = region_match(haystack)
        if not region:
            continue
        j["region_match"] = region
        kept.append(j)
    return kept


def classify_with_rules(jobs: list[dict], companies: dict | None = None) -> tuple[list[dict], list[dict]]:
    """Stage 2: apply remote rules. Focus is fully-remote only -- timezone
    is captured as metadata (still shown in the table) but no longer
    gates whether a listing is kept.
    Returns (resolved, needs_ai) -- resolved jobs already have a clear
    verdict and skip the AI step entirely."""
    industry_map = (companies or {}).get("industry_map", {})
    resolved, needs_ai = [], []
    for j in jobs:
        full_text = f"{j.get('raw_location','')} {j.get('description','')}"
        verdict = remote_verdict(full_text)
        j["remote_verdict"] = verdict
        j["timezone_constrained"] = timezone_constrained(full_text)  # informational only
        j["salary_range"] = extract_salary(full_text)
        j["industry"] = industry_map.get(j.get("company", "").lower(), "")

        if verdict == "no":
            continue  # not fully remote, drop entirely
        if verdict == "yes":
            j["classified_by"] = "rules"
            resolved.append(j)
        else:
            needs_ai.append(j)  # 'unclear' -- worth a second look
    return resolved, needs_ai
