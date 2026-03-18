"""HTML report generator for deadhead analysis — dark theme with line map view."""

import json
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
    """Build the interactive dropdown with deadhead tables grouped by stop pair and period."""
    if observed is None or observed.empty:
        return "<p class='empty'>Inga observerade tomk&ouml;rningar att visa.</p>"

    periods = _period_order()

    observed = observed.copy()
    observed["stop_pair"] = observed["from_stop_observed"] + " &rarr; " + observed["to_stop_observed"]

    stop_pairs = (
        observed.groupby("stop_pair")
        .agg(count=("vehicle_id", "size"), total_km=("move_m", "sum"))
        .reset_index()
        .sort_values("count", ascending=False)
    )

    html_parts = []
    for idx, rp_row in enumerate(stop_pairs.itertuples()):
        pair = rp_row.stop_pair
        count = int(rp_row.count)
        total_km = rp_row.total_km / 1000

        subset = observed[observed["stop_pair"] == pair].copy()

        period_tabs = []
        period_contents = []
        pair_id = f"sp_{idx}"

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
                    prev_rt = html_escape(str(row.get("prev_route", "-")))
                    next_rt = html_escape(str(row.get("next_route", "-")))
                    op = html_escape(str(row.get("operator", "-")))
                    vid = html_escape(str(row.get("vehicle_id", "-")))

                    rows_html += f"""<tr>
                      <td>{start_str}</td><td>{end_str}</td><td>{dur}</td>
                      <td>{dist}</td><td>{speed}</td>
                      <td>{prev_rt}</td><td>{next_rt}</td>
                      <td>{op}</td><td class="vid">{vid}</td>
                    </tr>"""

                table_html = f"""<div id="{pair_id}_{p_idx}" class="period-content {active_cls}">
                  <table class="data-table">
                    <thead><tr>
                      <th>Start</th><th>Slut</th><th>Min</th>
                      <th>km</th><th>km/h</th>
                      <th>F&ouml;reg. linje</th><th>N&auml;sta linje</th>
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


def _build_line_tab(line_stop_data):
    """Build the line view tab with Leaflet map and delay table."""
    if not line_stop_data:
        return "<p class='empty'>Ingen linjedata tillg&auml;nglig.</p>"

    # Build line selector options — group by line name, show directions
    line_names = sorted(set(v["name"] for v in line_stop_data.values()),
                        key=lambda x: (len(x), x))
    options_html = ""
    for name in line_names:
        options_html += f'<option value="{html_escape(name)}">{html_escape(name)}</option>\n'

    # Serialize data for JS
    js_data = json.dumps(line_stop_data, ensure_ascii=False)

    return f"""
    <div class="line-controls">
      <label for="lineSelect">V&auml;lj linje:</label>
      <select id="lineSelect" onchange="showLine(this.value)">
        <option value="">-- V&auml;lj --</option>
        {options_html}
      </select>
      <span id="lineInfo" class="line-info"></span>
    </div>
    <div id="lineMap" style="height:500px;border-radius:8px;border:1px solid var(--border);margin:1rem 0;"></div>
    <div id="lineStopTable"></div>
    """


def _leaflet_js(line_stop_data):
    """Generate the JavaScript for the Leaflet map and line view interactions."""
    js_data = json.dumps(line_stop_data, ensure_ascii=False)

    return f"""
    var lineData = {js_data};
    var map = null;
    var lineLayer = null;

    function initMap() {{
      if (map) return;
      map = L.map('lineMap').setView([59.33, 18.07], 11);
      L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
        attribution: '&copy; OpenStreetMap &copy; CARTO',
        maxZoom: 18,
      }}).addTo(map);
    }}

    function delayColor(d) {{
      if (d === null || d === undefined) return '#8b949e';
      if (d <= 30) return '#3fb950';
      if (d <= 60) return '#58a6ff';
      if (d <= 120) return '#d29922';
      if (d <= 300) return '#f0883e';
      return '#f85149';
    }}

    function delayLabel(d) {{
      if (d === null || d === undefined) return 'Ingen data';
      var sign = d >= 0 ? '+' : '';
      if (Math.abs(d) < 60) return sign + Math.round(d) + 's';
      return sign + (d/60).toFixed(1) + ' min';
    }}

    function showLine(name) {{
      initMap();
      if (lineLayer) {{
        map.removeLayer(lineLayer);
        lineLayer = null;
      }}
      document.getElementById('lineStopTable').innerHTML = '';
      document.getElementById('lineInfo').textContent = '';

      if (!name) return;

      lineLayer = L.featureGroup();
      var allKeys = Object.keys(lineData).filter(function(k) {{
        return lineData[k].name === name;
      }});

      if (allKeys.length === 0) return;

      var dirColors = ['#58a6ff', '#f0883e'];
      var tableRows = '';

      allKeys.forEach(function(key, dIdx) {{
        var info = lineData[key];
        var stops = info.stops;
        var coords = [];
        var dirLabel = info.direction === '0' ? 'Riktning A' : 'Riktning B';

        stops.forEach(function(s, i) {{
          if (s.lat === null || s.lon === null) return;
          coords.push([s.lat, s.lon]);
          var color = delayColor(s.avg_delay);
          var radius = 7;
          L.circleMarker([s.lat, s.lon], {{
            radius: radius,
            fillColor: color,
            color: '#0d1117',
            weight: 2,
            fillOpacity: 0.9,
          }}).bindPopup(
            '<b>' + s.stop_name + '</b><br>' +
            dirLabel + ', h\\u00e5llplats ' + s.seq + '<br>' +
            'F\\u00f6rsening: ' + delayLabel(s.avg_delay) +
            (s.n_obs > 0 ? ' (' + s.n_obs + ' obs)' : '')
          ).addTo(lineLayer);

          tableRows += '<tr>' +
            '<td>' + s.seq + '</td>' +
            '<td>' + s.stop_name + '</td>' +
            '<td style="color:' + color + ';font-weight:600">' + delayLabel(s.avg_delay) + '</td>' +
            '<td>' + s.n_obs + '</td>' +
            '<td>' + dirLabel + '</td></tr>';
        }});

        if (coords.length > 1) {{
          L.polyline(coords, {{color: dirColors[dIdx % 2], weight: 3, opacity: 0.6}}).addTo(lineLayer);
        }}
      }});

      lineLayer.addTo(map);
      if (lineLayer.getBounds().isValid()) {{
        map.fitBounds(lineLayer.getBounds(), {{padding: [30, 30]}});
      }}

      document.getElementById('lineInfo').textContent = allKeys.length + ' riktning(ar), ' +
        allKeys.reduce(function(s,k){{ return s + lineData[k].stops.length; }}, 0) + ' h\\u00e5llplatser';

      document.getElementById('lineStopTable').innerHTML =
        '<table class="data-table" style="margin-top:1rem"><thead><tr>' +
        '<th>#</th><th>H\\u00e5llplats</th><th>Snittf\\u00f6rsening</th><th>Obs</th><th>Riktning</th>' +
        '</tr></thead><tbody>' + tableRows + '</tbody></table>';
    }}
    """


def generate_html_report(observed, planned, segments, date_str,
                         line_stop_data=None, output_path=None):
    """Generate a complete dark-themed HTML report and return the file path."""
    if output_path is None:
        output_path = os.path.join(DATA_DIR, f"tomkorning_rapport_{date_str}.html")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    summary_html = _build_summary_stats(observed, planned, segments)
    operator_html = _build_operator_summary(observed)
    dropdown_html = _build_deadhead_dropdown(observed)

    has_line_tab = line_stop_data is not None and len(line_stop_data) > 0
    line_tab_html = _build_line_tab(line_stop_data) if has_line_tab else ""
    line_js = _leaflet_js(line_stop_data) if has_line_tab else ""

    leaflet_css = ""
    leaflet_scripts = ""
    line_tab_btn = ""
    line_panel_open = ""
    line_panel_heading = ""
    line_panel_legend = ""
    line_panel_close = ""
    if has_line_tab:
        leaflet_css = '<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>'
        leaflet_scripts = '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>'
        line_tab_btn = """<button class="top-tab" onclick="switchTopTab(this, 'linePanel')">Linjer</button>"""
        line_panel_open = """<div id="linePanel" class="tab-panel">"""
        line_panel_heading = """<h2>Linjevy med f&ouml;rsening per h&aring;llplats</h2>"""
        line_panel_legend = (
            """<div class="delay-legend">"""
            """<span><span class="dot" style="background:#3fb950"></span> &le;30s</span>"""
            """<span><span class="dot" style="background:#58a6ff"></span> 31-60s</span>"""
            """<span><span class="dot" style="background:#d29922"></span> 1-2 min</span>"""
            """<span><span class="dot" style="background:#f0883e"></span> 2-5 min</span>"""
            """<span><span class="dot" style="background:#f85149"></span> &gt;5 min</span>"""
            """<span><span class="dot" style="background:#8b949e"></span> Ingen data</span>"""
            """</div>"""
        )
        line_panel_close = """</div>"""

    html = f"""<!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tomk&ouml;rningsrapport &mdash; {date_str}</title>
{leaflet_css}
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

  /* Top-level tabs */
  .top-tabs {{
    display: flex;
    gap: 0;
    border-bottom: 2px solid var(--border);
    margin-bottom: 2rem;
  }}
  .top-tab {{
    padding: 0.75rem 1.5rem;
    cursor: pointer;
    color: var(--text-dim);
    font-size: 1rem;
    font-weight: 600;
    border: none;
    background: none;
    border-bottom: 2px solid transparent;
    margin-bottom: -2px;
    transition: all 0.15s;
  }}
  .top-tab:hover {{
    color: var(--text);
  }}
  .top-tab.active {{
    color: var(--accent);
    border-bottom-color: var(--accent);
  }}
  .tab-panel {{
    display: none;
  }}
  .tab-panel.active {{
    display: block;
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

  /* Line view */
  .line-controls {{
    display: flex;
    align-items: center;
    gap: 1rem;
    margin-bottom: 1rem;
  }}
  .line-controls label {{
    font-weight: 600;
    color: var(--text-dim);
  }}
  .line-controls select {{
    background: var(--surface);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.5rem 1rem;
    font-size: 0.95rem;
    cursor: pointer;
  }}
  .line-info {{
    color: var(--text-dim);
    font-size: 0.85rem;
  }}

  /* Delay legend */
  .delay-legend {{
    display: flex;
    gap: 1rem;
    flex-wrap: wrap;
    margin: 0.5rem 0 1rem;
    font-size: 0.8rem;
    color: var(--text-dim);
  }}
  .delay-legend span {{
    display: flex;
    align-items: center;
    gap: 0.3rem;
  }}
  .delay-legend .dot {{
    width: 12px;
    height: 12px;
    border-radius: 50%;
    display: inline-block;
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

  /* Leaflet overrides for dark theme */
  .leaflet-popup-content-wrapper {{
    background: var(--surface) !important;
    color: var(--text) !important;
    border-radius: var(--radius) !important;
    border: 1px solid var(--border) !important;
  }}
  .leaflet-popup-content {{ color: var(--text) !important; font-size: 0.85rem !important; }}
  .leaflet-popup-tip {{ background: var(--surface) !important; }}
</style>
</head>
<body>
{leaflet_scripts}

<h1>Tomk&ouml;rningsrapport</h1>
<p class="subtitle">{date_str} &middot; Genererad {now_str} &middot; Enbart buss</p>

<div class="top-tabs">
  <button class="top-tab active" onclick="switchTopTab(this, 'deadheadPanel')">Tomk&ouml;rningar</button>
  {line_tab_btn}
</div>

<div id="deadheadPanel" class="tab-panel active">
{summary_html}
{operator_html}

<h2>Tomk&ouml;rningar per h&aring;llplatspar</h2>
<p class="subtitle">Grupperat efter fr&aring;n/till-h&aring;llplats (oberoende av linje). Klicka f&ouml;r detaljer, flikar f&ouml;r trafikperiod.</p>

{dropdown_html}
</div>

{line_panel_open}
{line_panel_heading}
{line_panel_legend}
{line_tab_html}
{line_panel_close}

<script>
function switchTopTab(btn, panelId) {{
  document.querySelectorAll('.top-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById(panelId).classList.add('active');
  if (panelId === 'linePanel' && typeof map !== 'undefined' && map) {{
    setTimeout(function(){{ map.invalidateSize(); }}, 100);
  }}
}}

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

PLACEHOLDER_LINE_JS
</script>

</body>
</html>"""

    # Insert line JS (can't be in f-string due to backslash escapes in JS unicode)
    html = html.replace("PLACEHOLDER_LINE_JS", line_js if has_line_tab else "")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"HTML-rapport sparad: {output_path}")
    return output_path
