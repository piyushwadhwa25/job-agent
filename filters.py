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

GLOBAL_OPEN_RE = re.compile(
    r"\b(work from anywhere|remote[\s-]?global|open to (?:all countries|"
    r"candidates worldwide|global candidates)|worldwide|anywhere in the world|"
    r"no location restriction|globally distributed)\b",
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

SALARY_WITH_CURRENCY_RE = re.compile(
    r"(?P<cur>USD|SGD|EUR|GBP|AED|\$|€|£)\s?"
    r"(?P<low>\d[\d,]{1,})(?:\s?[kK])?"
    r"\s*(?:-|–|to)\s*"
    r"(?:USD|SGD|EUR|GBP|AED|\$|€|£)?\s?"
    r"(?P<high>\d[\d,]{1,})(?:\s?[kK])?"
)
SALARY_BARE_K_RE = re.compile(
    r"(?P<low>\d{2,3})[kK]\s*(?:-|–|to)\s*(?P<high>\d{2,3})[kK]"
)

USD_MARKERS = {"USD", "$"}


def extract_salary(text: str) -> tuple[str, str]:
    """Returns (display_string, tier). tier is one of:
    '100k+' | '60k-100k' | 'below-60k' | 'non-usd' | 'unspecified'
    No currency conversion is ever performed."""
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
    hits = [region for region, pat in REGION_RES.items() if pat.search(text)]
    return ", ".join(hits) if hits else ""


def availability(raw_location: str, full_text: str) -> str:
    """'global' | 'restricted' -- whether the listing is open worldwide
    or limited to one country/region. Two ways a job gets flagged
    restricted:
    1. Explicit restriction language anywhere in the text (citizenship,
       "must be based in", India-excluded, etc.)
    2. The location FIELD itself names a specific country/region
       (e.g. "Remote - US", "Remote (UK)") with no explicit "open
       globally / worldwide / anywhere" language elsewhere to override
       it. This catches the common case where a company never writes a
       restriction sentence at all -- they just tag the req's location
       and leave it at that, which in practice usually means hiring is
       scoped to that country.
    Explicit global-open language always overrides a nominal location tag."""
    if RESTRICTION_RE.search(full_text):
        return "restricted"
    if raw_location and not GLOBAL_OPEN_RE.search(full_text):
        for _, pat in REGION_RES.items():
            if pat.search(raw_location):
                return "restricted"
    return "global"


def remote_verdict(text: str) -> str:
    has_yes = bool(REMOTE_YES_RE.search(text))
    has_no = bool(REMOTE_NO_RE.search(text))
    if has_yes and not has_no:
        return "yes"
    if has_no:
        return "no"
    return "unclear"


def timezone_constrained(text: str) -> str:
    return "yes" if TZ_CONSTRAINT_RE.search(text) else "unknown"


def prefilter(jobs: list[dict]) -> list[dict]:
    return [j for j in jobs if title_matches(j["title"])]


def classify_with_rules(jobs: list[dict], companies: dict | None = None) -> tuple[list[dict], list[dict]]:
    industry_map = (companies or {}).get("industry_map", {})
    resolved, needs_ai = [], []
    for j in jobs:
        full_text = f"{j.get('raw_location','')} {j.get('description','')}"
        verdict = remote_verdict(full_text)
        avail = availability(j.get('raw_location', ''), full_text)
        salary_range, salary_tier = extract_salary(full_text)
        j["remote_verdict"] = verdict
        j["availability"] = avail
        j["timezone_constrained"] = timezone_constrained(full_text)
        j["region_match"] = region_hint(full_text)
        j["salary_range"] = salary_range
        j["salary_tier"] = salary_tier
        j["industry"] = industry_map.get(j.get("company", "").lower(), "")

        if verdict == "no":
            continue
        if avail == "restricted":
            continue
        if salary_tier == "below-60k":
            continue
        if verdict == "yes":
            j["classified_by"] = "rules"
            resolved.append(j)
        else:
            needs_ai.append(j)
    return resolved, needs_ai
