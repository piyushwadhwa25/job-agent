"""The only place AI is used. Batches ambiguous listings into a single
call so cost stays near-zero even at a few hundred jobs/week.
Uses Claude Haiku -- cheapest model, more than enough for this
structured-extraction task.

ARCHITECTURE NOTE (important, read before changing this file):
The AI's job here is EXTRACTION ONLY -- it never decides whether a
listing is kept. It extracts a short normalized_location phrase (what
does the listing literally say about where candidates can be located?)
and hands that back. The actual keep/drop decision is made by calling
filters.availability() -- the SAME function, with the SAME regex logic,
that decides every rules-resolved listing, and that's covered by
test_filters.py. This used to be split: the AI had its own independently
-worded judgment of "globally_open", which drifted out of sync with the
rules logic every time either side was tuned, causing repeated
regressions. Keeping AI to extraction-only and funneling everything
through one tested decision function fixes that at the architecture
level, not just patching the latest symptom.
"""
import os
import json
import anthropic
import filters

MODEL = "claude-haiku-4-5-20251001"
BATCH_SIZE = 15

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

SYSTEM = """You extract facts from job listings. You do NOT decide whether
a listing is eligible or a good match -- a separate deterministic system
applies that policy afterward. Your only job is accurate extraction.

For each listing, output:
- remote_verdict: "yes" if the role is remote (not hybrid/onsite), else
  "no". If genuinely unclear, use "no".
- normalized_location: a SHORT phrase (5 words max) summarizing what the
  listing literally says about candidate location eligibility. Use this
  vocabulary where it fits: "Worldwide", "Anywhere", "USA only",
  "Canada only", "UK only", "Europe only", "EMEA only", "APAC only",
  "India", "US and Canada", "Unclear". IMPORTANT: if the location field
  names one country/region and nothing else is said about eligibility,
  still output that country/region here (e.g. a location field of
  "Remote - US" with no other location text becomes "USA only") -- a
  bare single-country tag is meaningful information to pass along, don't
  leave this blank just because there's no separate eligibility
  sentence. Only use "Unclear" if there is truly no location signal at
  all (e.g. location field is just "Remote" with nothing else).
- salary_range: the compensation range exactly as written (e.g.
  "$120,000-$150,000"), or "" if not mentioned. Never estimate.
- industry: a short 1-3 word industry label if inferable from the text
  (e.g. "fintech", "healthcare", "e-commerce"), or "" if not inferable.

Respond with ONLY a JSON array (no prose, no markdown fences), one object
per listing in the same order, each with exactly these fields:
{"id": <int index from input>, "remote_verdict": "yes"|"no",
 "normalized_location": "...", "salary_range": "...", "industry": "..."}"""


def _build_batch_prompt(batch: list[dict]) -> str:
    items = []
    for i, j in enumerate(batch):
        text = f"{j.get('raw_location','')} | {j.get('description','')[:600]}"
        items.append(f"[{i}] Title: {j['title']}\nLocation/description: {text}")
    return "\n\n".join(items)


def classify_batch(jobs: list[dict]) -> list[dict]:
    """AI extracts facts; filters.availability() (same function used for
    every rules-resolved listing) makes the actual keep/drop decision."""
    results = []
    for start in range(0, len(jobs), BATCH_SIZE):
        batch = jobs[start:start + BATCH_SIZE]
        if not batch:
            continue
        prompt = _build_batch_prompt(batch)
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=1000,
                system=SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text.strip()
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            verdicts = json.loads(text)
        except Exception as e:
            print(f"  [classify] batch failed, skipping {len(batch)} jobs: {e}")
            continue

        for v in verdicts:
            idx = v.get("id")
            if idx is None or idx >= len(batch):
                continue
            job = batch[idx]

            if v.get("remote_verdict") != "yes":
                continue

            normalized_loc = v.get("normalized_location", "") or ""
            combined_raw_location = f"{job.get('raw_location','')} {normalized_loc}".strip()
            combined_full_text = f"{combined_raw_location} {job.get('description','')}"
            company_name = job.get('company', '')

            avail = filters.availability(combined_raw_location, combined_full_text, company_name)
            if avail == "restricted":
                continue

            salary_text = v.get("salary_range", "") or job.get("salary_range", "")
            if salary_text:
                _, tier = filters.extract_salary(salary_text)
            else:
                tier = job.get("salary_tier", "unspecified")
            if tier == "below-60k":
                continue

            job["remote_verdict"] = "yes"
            job["availability"] = avail
            job["location_confidence"] = filters.location_confidence(
                combined_full_text, combined_raw_location, company_name)
            job["salary_range"] = salary_text
            job["salary_tier"] = tier
            job["industry"] = v.get("industry", "") or job.get("industry", "")
            job["classified_by"] = "ai"
            results.append(job)
    return results
