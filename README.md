# Job Agent — Senior Product Roles, Fully Remote

Finds senior product manager / director / VP-level product roles that are
**fully remote** (timezone overlap requirements are OK, only hybrid/onsite
are excluded), based in Europe, USA, Singapore, or UAE. Captures salary
range and industry where the listing states them. Results land in a
SQLite DB (`jobs.db`).

## How it keeps AI cost near zero

| Stage | Method | Cost |
|---|---|---|
| Fetch listings | Greenhouse/Lever/Ashby APIs + RemoteOK | $0 |
| Title + region filter | Regex | $0 |
| Remote/timezone filter | Regex | $0 |
| Final check on ambiguous cases only | Claude Haiku, batched | ~$0.01–0.05/run |

In testing, roughly 85–90% of candidates get a confident yes/no from
rules alone. Only the genuinely unclear ones (a small fraction) go to
the model, batched 15-at-a-time to keep the per-call overhead low.

**Salary & industry** are extracted for free wherever possible:
- Salary: regex over the listing text (catches "$120,000-$150,000",
  "€80k-€100k" style ranges as written -- never estimated)
- Industry: looked up from `companies.json`'s `industry_map` (you fill
  this in once per company you add)

For listings that go to the AI step anyway (ambiguous remote status),
the same call also extracts salary/industry if visible -- no extra cost,
since it's already reading the text. Rule-resolved listings only get
industry from the map (no salary/industry AI lookup is ever triggered
just for those two fields -- keeping cost at $0 for the majority case).

## Setup

1. **Add companies to scrape.** Edit `companies.json`. Each entry is the
   company's slug on that ATS — check by visiting:
   - `https://boards.greenhouse.io/{slug}`
   - `https://jobs.lever.co/{slug}`
   - `https://jobs.ashbyhq.com/{slug}`

   The starter list is a small sample of remote-friendly companies —
   swap in your actual target list (BrowserStack, Atlassian, Duolingo,
   etc. — check which ATS each uses first).

2. **Get an Anthropic API key** from console.anthropic.com if you don't
   already have one, and add it as a GitHub Actions secret:
   `Settings → Secrets and variables → Actions → New repository secret`
   Name: `ANTHROPIC_API_KEY`

3. **Push this folder to a GitHub repo.** The workflow in
   `.github/workflows/scrape.yml` runs every Monday at 06:00 UTC (edit
   the cron line to change frequency) and commits the updated `jobs.db`
   back to the repo automatically.

4. **Run it manually anytime** from the repo's Actions tab
   ("Run workflow" button), or locally:
   ```
   pip install -r requirements.txt
   export ANTHROPIC_API_KEY=sk-...
   python3 main.py
   ```

## Querying results

```bash
sqlite3 jobs.db "SELECT company, title, salary_range, industry, region_match, url FROM jobs WHERE status='new' ORDER BY first_seen DESC;"
```

Or open `jobs.db` in any SQLite browser (DB Browser for SQLite, TablePlus,
or the SQLite VS Code extension) if you want a visual table instead of CLI.

Mark a listing as reviewed/applied/ignored:
```sql
UPDATE jobs SET status='applied' WHERE url='...';
```

## Extending

- **More sources**: add a `fetch_x()` function to `sources.py` following
  the same dict shape, call it from `fetch_all()`.
- **Broaden the target list**: LinkedIn and Wellfound don't offer clean
  public APIs — scraping them reliably needs a headless browser, which
  is a bigger lift than this v1. The ATS-API approach here covers a
  large share of companies that are seriously async-remote (they tend
  to use these platforms specifically because they don't gatekeep by
  timezone).
- **Lower cost further**: cache AI verdicts by URL hash so a job that's
  reposted doesn't get re-classified.
