"""The only place AI is used. Batches ambiguous listings into a single
call so cost stays near-zero even at a few hundred jobs/week.
Uses Claude Haiku -- cheapest model, more than enough for this
structured-extraction task.
"""
import os
import json
import anthropic
import filters

MODEL = "claude-haiku-4-5-20251001"
BATCH_SIZE = 15  # keep prompts small; batching amortizes the fixed cost

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

SYSTEM = """You classify job listings for a candidate based in India who
ONLY wants:
- fully remote roles (hybrid/onsite are disqualifying; timezone overlap
  requirements are fine as long as the role itself is remote)
- globally open to apply from anywhere, INCLUDING India -- the company's
  HQ location does NOT disqualify a role by itself. But restriction can
  show up in TWO ways, both count as disqualifying:
  (a) explicit language: "must be a US citizen", "only open to candidates
      based in the UK", "we do not currently hire in India"
  (b) the location field itself simply names ONE country/region (e.g.
      "Remote - US", "Remote Canada", "CA Remote (BC & ON only)") with
      nothing elsewhere saying it's open globally/worldwide/anywhere.
      Companies naming one country almost always mean it, even without
      a formal citizenship sentence -- treat a bare single-country
      location tag as restricted UNLESS something explicitly says "open
      globally/worldwide/anywhere" or lists MULTIPLE countries/regions
      as eligible. Do not give the benefit of the doubt to a
      single-country tag just because no citizenship sentence was
      written -- in practice that tag alone means restricted.

The listings you see here have already had a first pass -- what reaches
you is genuinely unclear on remote status specifically (not location).
Location restriction should still be judged fresh per the rule above,
since it's a separate axis.

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
 "globally_open": "yes"|"no", "salary_range": "...", "industry": "..."}

Base your judgment only on the text given. If genuinely unclear on
either axis, prefer "no" -- false negatives are cheaper than false
positives here."""


def _build_batch_prompt(batch: list[dict]) -> str:
    items = []
    for i, j in enumerate(batch):
        text = f"{j.get('raw_location','')} | {j.get('description','')[:600]}"
        items.append(f"[{i}] Title: {j['title']}\nLocation/description: {text}")
    return "\n\n".join(items)


def classify_batch(jobs: list[dict]) -> list[dict]:
    """Mutates and returns jobs with remote_verdict/timezone_constrained
    filled in, dropping any the model marks as not fitting."""
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
            if v.get("remote_verdict") == "yes" and v.get("globally_open") == "yes":
                final_salary_text = v.get("salary_range", "") or job.get("salary_range", "")
                _, tier = filters.extract_salary(final_salary_text) if final_salary_text \
                    else (job.get("salary_range", ""), job.get("salary_tier", "unspecified"))
                if tier == "below-60k":
                    continue  # explicitly below the floor, drop
                full_text = f"{job.get('raw_location','')} {job.get('description','')}"
                job["remote_verdict"] = "yes"
                job["availability"] = "global"
                job["location_confidence"] = filters.location_confidence(
                    full_text, job.get('raw_location', ''), job.get('company', ''))
                job["salary_range"] = final_salary_text
                job["salary_tier"] = tier
                job["industry"] = v.get("industry", "") or job.get("industry", "")
                job["classified_by"] = "ai"
                results.append(job)
    return results
