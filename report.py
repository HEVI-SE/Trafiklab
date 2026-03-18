"""HTML report generator for deadhead analysis — dark theme."""

import os
from datetime import datetime

import pandas as pd

from config import DATA_DIR
from utils import html_escape


def _period_order():
    return ["FM-topp", "Bas", "EM-topp", "Natt"]


def _build_summary_stats(observed, planned, segments):
    """Build HTML for the summary statistics section."""
    total_obs = len(observed) if observed is not None and not observed.empty else 0
    total_plan = len(planned) if planned is not None and not planned.empty else 0
    total_seg = len(segments) if segments is not None and not segments.empty else 0
    n_vehicles = segments["vehicle_id"].nunique() if total_seg > 0 else 0

    avg_dur = observed["duration_min"].mean() if total_obs > 0 else 0
    avg_dist_km = (observed["move_m"].mean() / 1000) if total_obs > 0 else 0
    total_dead_km = (observed["move_m"].sum() / 1000) if total_obs > 0 else 0

    return f"""
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-value">{total_obs:,}</div>
        <div class="stat-label">Observerade tomk&ouml;rningar</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{total_plan:,}</div>
        <div class="stat-label">Planerade tomk&ouml;rningar</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{n_vehicles:,}</div>
        <div class="stat-label">Unika fordon</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{total_seg:,}</div>
        <div class="stat-label">Segment totalt</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{avg_dur:.1f} min</div>
        <div class="stat-label">Snittl&auml;ngd tomk&ouml;rning</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{avg_dist_km:.1f} km</div>
        <div class="stat-label">Snittdistans tomk&ouml;rning</div>
      </div>
      <div class="stat-card accent">
        <div class="stat-value">{total_dead_km:,.0f} km</div>
        <div class="stat-label">Total tomk&ouml;rningsdistans</div>
      </div>
    </div>
    """


def _build_deadhead_dropdown(observed):
    """Build the interactive dropdown with deadhead tables grouped by route pair and period."""
    if observed is None or observed.empty:
        return "<p class='empty'>Inga observerade tomk&ouml;rningar att visa.</p>"

    periods = _period_order()

    # Group by route pair (prev_route → next_route)
    observed = observed.copy()
    observed["route_pair"] = observed["prev_route"] + " &rarr; " + observed["next_route"]

    route_pairs = (
        observed.groupby("route_pair")
        .agg(count=("vehicle_id", "size"), total_km=("move_m", "sum"))
        .reset_index()
        .sort_values("count", ascending=False)
    )

    html_parts = []
    for _, rp_row in route_pairs.iterrows():
        pair = rp_row["route_pair"]
        count = int(rp_row["count"])
        total_km = rp_row["total_km"] / 1000

        subset = observed[observed["route_pair"] == pair].copy()

        # Build period sub-tables
        period_tabs = []
        period_contents = []
        pair_id = pair.replace(" ", "_").replace("&rarr;", "to").replace(";", "")

        for p_idx, period in enumerate(periods):
            p_data = subset[subset["period"] == period]
            p_count = len(p_data)
            active_cls = "active" if p_idx == 0 else ""

            period_tabs.append(
                f'<button class="period-tab {active_cls}" '
                f'onclick="switchPeriod(this, \'{pair_id}_{p_idx}\')">'
                f'{html_escape(period)} <span class="badge">{p_count}</span></button>'
            )

            if p_data.empty:
                table_html = f'<div id="{pair_id}_{p_idx}" class="period-content {active_cls}"><p class="empty">Inga tomk&ouml;rningar under {html_escape(period)}</p></div>'
            else:
                rows_html = ""
                for _, row in p_data.sort_values("deadhead_start").iterrows():
                    start_str = pd.to_datetime(row["deadhead_start"]).strftime("%H:%M") if pd.notna(row["deadhead_start"]) else "-"
                    end_str = pd.to_datetime(row["deadhead_end"]).strftime("%H:%M") if pd.notna(row["deadhead_end"]) else "-"
                    dur = f"{row['duration_min']:.0f}" if pd.notna(row.get("duration_min")) else "-"
                    dist = f"{row['move_m'] / 1000:.1f}" if pd.notna(row.get("move_m")) else "-"
                    speed = f"{row['speed_kmh']:.0f}" if pd.notna(row.get("speed_kmh")) else "-"
                    from_stop = html_escape(str(row.get("from_stop_observed", "-")))
                    to_stop = html_escape(str(row.get("to_stop_observed", "-")))
                    op = html_escape(str(row.get("operator", "-")))
                    vid = html_escape(str(row.get("vehicle_id", "-")))

                    rows_html += f"""<tr>
                      <td>{start_str}</td><td>{end_str}</td><td>{dur}</td>
                      <td>{dist}</td><td>{speed}</td>
                      <td>{from_stop}</td><td>{to_stop}</td>
                      <td>{op}</td><td class="vid">{vid}</td>
                    </tr>"""

                table_html = f"""<div id="{pair_id}_{p_idx}" class="period-content {active_cls}">
                  <table class="data-table">
                    <thead><tr>
                      <th>Start</th><th>Slut</th><th>Min</th>
                      <th>km</th><th>km/h</th>
                      <th>Fr&aring;n h&aring;llplats</th><th>Till h&aring;llplats</th>
                      <th>Operat&ouml;r</th><th>Fordon</th>
                    </tr></thead>
                    <tbody>{rows_html}</tbody>
                  </table>
                </div>"""

            period_contents.append(table_html)

        tabs_html = "\n".join(period_tabs)
        contents_html = "\n".join(period_contents)

        html_parts.append(f"""
        <div class="dropdown-item">
          <button class="dropdown-header" onclick="toggleDropdown(this)">
            <span class="arrow">&#9654;</span>
            <span class="route-pair">{pair}</span>
            <span class="meta">{count} tomk&ouml;rningar &middot; {total_km:.1f} km totalt</span>
          </button>
          <div class="dropdown-body">
            <div class="period-tabs">{tabs_html}</div>
            {contents_html}
          </div>
        </div>
        """)

    return "\n".join(html_parts)


def _build_operator_summary(observed):
    """Build operator summary table."""
    if observed is None or observed.empty:
        return ""

    op_stats = (
        observed.groupby("operator")
        .agg(
            count=("vehicle_id", "size"),
            avg_duration=("duration_min", "mean"),
            total_km=("move_m", "sum"),
            avg_speed=("speed_kmh", "mean"),
        )
        .reset_index()
        .sort_values("count", ascending=False)
    )

    rows = ""
    for _, r in op_stats.iterrows():
        rows += f"""<tr>
          <td>{html_escape(r['operator'])}</td>
          <td>{int(r['count']):,}</td>
          <td>{r['avg_duration']:.1f}</td>
          <td>{r['total_km'] / 1000:.1f}</td>
          <td>{r['avg_speed']:.0f}</td>
        </tr>"""

    return f"""
    <h2>Per operat&ouml;r</h2>
    <table class="data-table summary-table">
      <thead><tr>
        <th>Operat&ouml;r</th><th>Antal</th><th>Snitt min</th><th>Totalt km</th><th>Snitt km/h</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """


def generate_html_report(observed, planned, segments, date_str, output_path=None):
    """Generate a complete dark-themed HTML report and return the file path."""
    if output_path is None:
        output_path = os.path.join(DATA_DIR, f"tomkorning_rapport_{date_str}.html")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    summary_html = _build_summary_stats(observed, planned, segments)
    operator_html = _build_operator_summary(observed)
    dropdown_html = _build_deadhead_dropdown(observed)

    html = f"""<!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tomk&ouml;rningsrapport &mdash; {date_str}</title>
<style>
  :root {{
    --bg: #0d1117;
    --surface: #161b22;
    --surface2: #1c2129;
    --border: #30363d;
    --text: #e6edf3;
    --text-dim: #8b949e;
    --accent: #58a6ff;
    --accent2: #3fb950;
    --red: #f85149;
    --orange: #d29922;
    --radius: 8px;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
    padding: 2rem;
    max-width: 1400px;
    margin: 0 auto;
  }}
  h1 {{
    font-size: 1.8rem;
    font-weight: 600;
    margin-bottom: 0.25rem;
  }}
  h2 {{
    font-size: 1.3rem;
    font-weight: 600;
    margin: 2rem 0 1rem;
    color: var(--accent);
  }}
  .subtitle {{
    color: var(--text-dim);
    font-size: 0.9rem;
    margin-bottom: 2rem;
  }}
  .stats-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 1rem;
    margin-bottom: 2rem;
  }}
  .stat-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.25rem;
    text-align: center;
  }}
  .stat-card.accent {{
    border-color: var(--accent);
    background: rgba(88, 166, 255, 0.08);
  }}
  .stat-value {{
    font-size: 1.6rem;
    font-weight: 700;
    color: var(--text);
  }}
  .stat-card.accent .stat-value {{ color: var(--accent); }}
  .stat-label {{
    font-size: 0.8rem;
    color: var(--text-dim);
    margin-top: 0.25rem;
  }}
  .data-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
  }}
  .data-table th {{
    background: var(--surface2);
    color: var(--accent);
    font-weight: 600;
    text-align: left;
    padding: 0.6rem 0.75rem;
    border-bottom: 2px solid var(--border);
    position: sticky;
    top: 0;
    white-space: nowrap;
  }}
  .data-table td {{
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }}
  .data-table tbody tr:hover {{
    background: rgba(88, 166, 255, 0.06);
  }}
  .data-table .vid {{
    color: var(--text-dim);
    font-family: monospace;
    font-size: 0.8rem;
  }}
  .summary-table {{
    max-width: 700px;
  }}

  /* Dropdown */
  .dropdown-item {{
    margin-bottom: 2px;
  }}
  .dropdown-header {{
    width: 100%;
    display: flex;
    align-items: center;
    gap: 0.75rem;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 0.8rem 1rem;
    cursor: pointer;
    color: var(--text);
    font-size: 0.95rem;
    text-align: left;
    transition: background 0.15s;
  }}
  .dropdown-header:hover {{
    background: var(--surface2);
  }}
  .dropdown-header .arrow {{
    font-size: 0.7rem;
    transition: transform 0.2s;
    color: var(--text-dim);
    flex-shrink: 0;
  }}
  .dropdown-header.open .arrow {{
    transform: rotate(90deg);
  }}
  .dropdown-header .route-pair {{
    font-weight: 600;
    color: var(--accent);
  }}
  .dropdown-header .meta {{
    color: var(--text-dim);
    font-size: 0.8rem;
    margin-left: auto;
    white-space: nowrap;
  }}
  .dropdown-body {{
    display: none;
    background: var(--surface);
    border: 1px solid var(--border);
    border-top: none;
    border-radius: 0 0 var(--radius) var(--radius);
    padding: 1rem;
    max-height: 500px;
    overflow-y: auto;
  }}
  .dropdown-body.open {{
    display: block;
  }}

  /* Period tabs */
  .period-tabs {{
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1rem;
    flex-wrap: wrap;
  }}
  .period-tab {{
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.4rem 0.9rem;
    cursor: pointer;
    color: var(--text-dim);
    font-size: 0.85rem;
    transition: all 0.15s;
  }}
  .period-tab:hover {{
    color: var(--text);
    border-color: var(--text-dim);
  }}
  .period-tab.active {{
    background: var(--accent);
    color: var(--bg);
    border-color: var(--accent);
    font-weight: 600;
  }}
  .period-tab .badge {{
    font-size: 0.75rem;
    opacity: 0.8;
    margin-left: 0.25rem;
  }}
  .period-content {{
    display: none;
  }}
  .period-content.active {{
    display: block;
  }}
  .empty {{
    color: var(--text-dim);
    font-style: italic;
    padding: 1rem 0;
  }}

  /* Scrollbar */
  ::-webkit-scrollbar {{ width: 8px; height: 8px; }}
  ::-webkit-scrollbar-track {{ background: var(--bg); }}
  ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 4px; }}
  ::-webkit-scrollbar-thumb:hover {{ background: var(--text-dim); }}

  @media (max-width: 768px) {{
    body {{ padding: 1rem; }}
    .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
  }}
</style>
</head>
<body>

<h1>Tomk&ouml;rningsrapport</h1>
<p class="subtitle">{date_str} &middot; Genererad {now_str}</p>

{summary_html}
{operator_html}

<h2>Alla tomk&ouml;rningar per linjekombination</h2>
<p class="subtitle">Klicka p&aring; en rad f&ouml;r att se detaljer. Anv&auml;nd flikarna f&ouml;r att filtrera per trafikperiod.</p>

{dropdown_html}

<script>
function toggleDropdown(btn) {{
  btn.classList.toggle('open');
  const body = btn.nextElementSibling;
  body.classList.toggle('open');
}}

function switchPeriod(tabBtn, contentId) {{
  const parent = tabBtn.closest('.dropdown-body');
  parent.querySelectorAll('.period-tab').forEach(t => t.classList.remove('active'));
  parent.querySelectorAll('.period-content').forEach(c => c.classList.remove('active'));
  tabBtn.classList.add('active');
  document.getElementById(contentId).classList.add('active');
}}
</script>

</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"HTML-rapport sparad: {output_path}")
    return output_path
