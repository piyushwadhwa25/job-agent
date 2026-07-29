"""Exports jobs.db into a single static HTML page (docs/index.html).
Zero AI cost, zero extra dependencies. GitHub Pages serves this
directly from the repo, so you get a URL you can open on your phone
with no setup beyond one toggle in repo settings.
"""
from pathlib import Path
from datetime import datetime, timezone
import db

OUT_PATH = Path(__file__).parent / "docs" / "index.html"

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
  input[type=text] {{ width: 100%; padding: 8px; margin-bottom: 12px; border-radius: 6px;
         border: 1px solid #2a2d35; background: #171a21; color: #e6e6e6; box-sizing: border-box; }}
  @media (max-width: 600px) {{
    .hide-mobile {{ display: none; }}
  }}
</style>
</head>
<body>
<h1>Senior Product Roles — Fully Remote</h1>
<div class="meta">{count} listings · last updated {updated}</div>
<input type="text" id="filter" placeholder="Filter by company, title, or industry...">
<table id="jobs">
<thead>
<tr>
  <th>Company</th><th>Title</th><th class="hide-mobile">Region</th>
  <th>Salary</th><th class="hide-mobile">Industry</th><th class="hide-mobile">Source</th>
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
  <td class="hide-mobile">{region}</td>
  <td>{salary}</td>
  <td class="hide-mobile">{industry}</td>
  <td class="hide-mobile">{source}</td>
</tr>"""


def build():
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT company, title, url, region_match, salary_range, industry, "
        "source, classified_by FROM jobs WHERE status != 'ignored' "
        "ORDER BY first_seen DESC"
    ).fetchall()
    conn.close()

    row_html = "\n".join(
        ROW_TEMPLATE.format(
            company=r[0], title=r[1], url=r[2], region=r[3] or "-",
            salary=r[4] or "-", industry=r[5] or "-", source=r[6],
            classified_by=r[7] or "rules",
        )
        for r in rows
    )
    html = TEMPLATE.format(
        count=len(rows),
        updated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        rows=row_html or "<tr><td colspan=6>No listings yet.</td></tr>",
    )
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(html)
    (OUT_PATH.parent / ".nojekyll").touch()
    print(f"Wrote {OUT_PATH} ({len(rows)} rows)")


if __name__ == "__main__":
    build()
