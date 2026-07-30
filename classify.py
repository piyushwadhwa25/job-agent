"""The only place AI is used. Batches ambiguous listings into a single
call so cost stays near-zero. Uses Claude Haiku -- cheapest model.
"""
import os
import json
import anthropic
import filters

MODEL = "claude-haiku-4-5-20251001"
BATCH_SIZE = 15

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

SYSTEM = """You classify job listings for a candidate based in India who
ONLY wants:
- fully remote roles (hybrid/onsite are disqualifying; timezone overlap
  requirements are fine as long as the role itself is remote)
- roles they are eligible to apply for from India

IMPORTANT on location eligibility: every listing you see here has
ALREADY passed a filter that removed anything with explicit restriction
language (citizenship requirements, "we don't hire in India", etc). What's
left is genuinely ambiguous -- typically just a location field naming one
country (e.g. "Remote - US") with nothing else said either way. This is
extremely common even for roles that ARE open to India: many companies
tag a nominal HQ/payroll country without meaning to restrict candidates
at all, and most listings never bother to write "open worldwide" even
when they mean it.

So: DEFAULT TO "yes" (globally_open) for a bare single-country location
tag with no other signal. Only mark "no" if you see an ACTUAL restriction
signal beyond the bare tag -- repeated emphasis that only that country's
candidates will be considered, domestic-only visa/benefits language tied
to one specific country, explicit mention of needing local work
authorization, or similar. A location field simply naming one country and
nothing else is NOT a restriction signal by itself -- default open.

For remote status: if genuinely unclear whether it's remote at all (not
just unclear on location), prefer "no" -- that's a different, stricter
axis than location eligibility.

For each listing given, also try to extract, ONLY if explicitly stated in
the text (never guess or estimate):
- salary_range: the compensation range as written (e.g. "$120,000-$150,000"),
  or "" if not mentioned
- industry: a short 1-3 word industry label for the company if inferable
  from the text (e.g. "fintech", "healthcare", "e-commerce"), or "" if
  not inferable

Respond with ONLY a JSON array (no prose, no markdown fences), one object
per listing in the same order, each with exactly these fields:
{"id": <int index from input>, "remote_verdict": "yes"|"no",
 "globally_open": "yes"|"no", "salary_range": "...", "industry": "..."}"""


def _build_batch_prompt(batch: list[dict]) -> str:
    items = []
    for i, j in enumerate(batch):
        text = f"{j.get('raw_location','')} | {j.get('description','')[:600]}"
        items.append(f"[{i}] Title: {j['title']}\nLocation/description: {text}")
    return "\n\n".join(items)


def classify_batch(jobs: list[dict]) -> list[dict]:
    results = []
    for start in range(0, len(jobs), BATCH_SIZE):
        batch = jobs[start:start + BATCH_SIZE]
        if not batch:
            continue
        prompt = _build_batch_prompt(batch)
        try:
            resp = client.messages.create(
                model=MODEL, max_tokens=1000, system=SYSTEM,
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
            if v.get("remote_verdict") == "yes" and v.get("globally_open") == "yes":
                final_salary_text = v.get("salary_range", "") or job.get("salary_range", "")
                _, tier = filters.extract_salary(final_salary_text) if final_salary_text \
                    else (job.get("salary_range", ""), job.get("salary_tier", "unspecified"))
                if tier == "below-60k":
                    continue
                job["remote_verdict"] = "yes"
                job["availability"] = "global"
                full_text = f"{job.get('raw_location','')} {job.get('description','')}"
                job["location_confidence"] = filters.location_confidence(full_text)
                job["salary_range"] = final_salary_text
                job["salary_tier"] = tier
                job["industry"] = v.get("industry", "") or job.get("industry", "")
                job["classified_by"] = "ai"
                results.append(job)
    return results
