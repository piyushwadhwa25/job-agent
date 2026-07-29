"""Entry point. Run with: python3 main.py

Pipeline:
  1. Fetch raw listings from all sources          (cost: $0)
  2. Rule-based prefilter on title + region        (cost: $0)
  3. Rule-based remote/timezone classification     (cost: $0)
  4. AI classification, ONLY for what's left       (cost: fractions of a cent)
  5. Upsert everything into SQLite
"""
import json
import sys
from pathlib import Path

import sources
import filters
import classify
import db


def main():
    companies = json.loads((Path(__file__).parent / "companies.json").read_text())

    print("Fetching listings from all sources...")
    raw_jobs = sources.fetch_all(companies)
    print(f"  {len(raw_jobs)} raw listings fetched")

    candidates = filters.prefilter(raw_jobs)
    print(f"  {len(candidates)} pass title prefilter")

    print("Enriching location data from job pages (greenhouse)...")
    sources.enrich_locations(candidates, sources_to_enrich=("greenhouse",))

    resolved, needs_ai = filters.classify_with_rules(candidates, companies)
    print(f"  {len(resolved)} resolved by rules alone (no AI cost)")
    print(f"  {len(needs_ai)} ambiguous, sending to AI classifier")

    ai_resolved = classify.classify_batch(needs_ai) if needs_ai else []
    print(f"  {len(ai_resolved)} confirmed remote + async by AI")

    all_final = resolved + ai_resolved

    conn = db.get_conn()
    new_count = 0
    for job in all_final:
        result = db.upsert_job(conn, job)
        if result == "new":
            new_count += 1
    conn.commit()
    conn.close()

    print(f"\nDone. {new_count} new listings added to jobs.db "
          f"({len(all_final)} total matched this run).")

    import export_html
    export_html.build()


if __name__ == "__main__":
    sys.exit(main())
