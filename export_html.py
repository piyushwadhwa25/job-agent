"""Exports jobs.db into a single static HTML page (docs/index.html)."""
from pathlib import Path
from datetime import datetime, timezone, date
import db

OUT_PATH = Path(__file__).parent / "docs" / "index.html"

TIER_ORDER = {"100k+": 0, "60k-100k": 1, "non-usd": 2, "unspecified": 3, "": 3}
TIER_LABELS = {"100k+": "$100k+", "60k-100k": "$60-100k", "non-usd": "non-USD",
                "unspecified": "not listed", "": "not listed"}
TIER_CLASS = {"100k+": "tier-high", "60k-100k": "tier-mid", "non-usd": "tier-nonusd",
              "unspecified": "tier-unk", "": "tier-unk"}

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Senior Product Roles — Remote</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 16px;
         background: #0f1115; color: #e6e6e6; }}
  h1 {{ font-size: 1.3rem; margin-bottom: 4px; }}
  .meta {{ color: #9a9a9a; font-size: 0.85rem; margin-bottom: 16px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
  th, td {{ text-align: left; padding: 10px 8px; border-bottom: 1px solid #2a2d35; vertical-align: top; }}
  th {{ position: sticky; top: 0; background: #171a21; cursor: pointer; }}
  tr:hover {{ background: #171a21; }}
  a {{ color: #7dc4ff; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 0.75rem; }}
  .rules {{ background: #1e3a2a; color: #7fd99f; }}
  .ai {{ background: #2a2440; color: #b3a1ff; }}
  .fresh {{ background: #402a1e; color: #ffb37f; font-weight: 600; }}
  .tier-high {{ background: #1e3a2a; color: #7fd99f; font-weight: 600; }}
  .tier-mid {{ background: #2f3a1e; color: #c9d97f; }}
  .tier-nonusd {{ background: #1e2f3a; color: #7fc0d9; }}
  .tier-unk {{ background: #2a2a2a; color: #999; }}
  input[type=text] {{ width: 100%; padding: 8px; margin-bottom: 12px; border-radius: 6px;
         border: 1px solid #2a2d35; background: #171a21; color: #e6e6e6; box-sizing: border-box; }}
  @media (max-width: 600px) {{ .hide-mobile {{ display: none; }} }}
</style>
</head>
<body>
<h1>Senior Product Roles — Fully Remote, Global</h1>
<div class="meta">{count} listings · last updated {updated} · sorted by salary tier, then recency</div>
<input type="text" id="filter" placeholder="Filter by company, title, or industry...">
<table id="jobs">
<thead>
<tr>
  <th>Company</th><th>Title</th><th>Salary</th><th>Posted</th>
  <th class="hide-mobile">Region</th><th class="hide-mobile">Industry</th><th class="hide-mobile">Source</th>
</tr>
</thead>
<tbody>
{rows}
</tbody>
</table>
<script>
document.getElementById('filter').addEventListener('input', function() {{
  const q = this.value.toLowerCase();
  document.querySelectorAll('#jobs tbody tr').forEach(function(row) {{
    row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
  }});
}});
</script>
</body>
</html>
"""

ROW_TEMPLATE = """<tr>
  <td>{company}</td>
  <td><a href="{url}" target="_blank">{title}</a> <span class="badge {classified_by}">{classified_by}</span></td>
  <td><span class="badge {tier_class}">{tier_label}</span>{salary_detail}</td>
  <td>{posted}{fresh_badge}</td>
  <td class="hide-mobile">{region}</td>
  <td class="hide-mobile">{industry}</td>
  <td class="hide-mobile">{source}</td>
</tr>"""


def _date_ord(s):
    try:
        return date.fromisoformat(s).toordinal()
    except Exception:
        return 0


def build():
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT company, title, url, region_match, salary_range, salary_tier, "
        "industry, source, classified_by, posted_date, first_seen FROM jobs "
        "WHERE status != 'ignored'"
    ).fetchall()
    conn.close()

    today = datetime.now(timezone.utc).date()
    rows = sorted(rows, key=lambda r: (
        TIER_ORDER.get(r[5] or "", 3),
        0 if (r[9] or "") else 1,
        -_date_ord(r[9] or ""),
    ))

    row_html = []
    for r in rows:
        company, title, url, region, salary_range, tier, industry, source, \
            classified_by, posted_date_str, first_seen = r
        tier = tier or "unspecified"
        fresh_badge = ""
        if posted_date_str:
            try:
                posted = date.fromisoformat(posted_date_str)
                if (today - posted).days <= 1:
                    fresh_badge = ' <span class="badge fresh">new</span>'
            except ValueError:
                pass
        salary_detail = f" {salary_range}" if salary_range else ""
        row_html.append(ROW_TEMPLATE.format(
            company=company, title=title, url=url, region=region or "-",
            industry=industry or "-", source=source, classified_by=classified_by or "rules",
            tier_class=TIER_CLASS.get(tier, "tier-unk"), tier_label=TIER_LABELS.get(tier, "not listed"),
            salary_detail=salary_detail, posted=posted_date_str or "-", fresh_badge=fresh_badge,
        ))
    row_html = "\n".join(row_html)

    html = TEMPLATE.format(
        count=len(rows), updated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        rows=row_html or "<tr><td colspan=7>No listings yet.</td></tr>",
    )
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(html)
    (OUT_PATH.parent / ".nojekyll").touch()
    print(f"Wrote {OUT_PATH} ({len(rows)} rows)")


if __name__ == "__main__":
    build()
