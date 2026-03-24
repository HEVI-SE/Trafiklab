"""HTML report generator — dark theme, Linjer tab (default) + Tomkörningar tab."""

import json
import os
from datetime import datetime

import pandas as pd

from config import DATA_DIR
from utils import html_escape


def _period_order():
    return ["FM-topp", "Bas", "EM-topp", "Natt"]


def _fmt_min(val):
    """Format a duration in minutes for display, or '-' if missing."""
    if val is None or pd.isna(val):
        return "-"
    return f"{val:.0f}"


# ---------------------------------------------------------------------------
# Tomkörningar tab helpers
# ---------------------------------------------------------------------------

def _build_summary_stats(observed, planned, segments):
    total_obs = len(observed) if observed is not None and not observed.empty else 0
    total_plan = len(planned) if planned is not None and not planned.empty else 0
    total_seg = len(segments) if segments is not None and not segments.empty else 0
    n_vehicles = segments["vehicle_id"].nunique() if total_seg > 0 else 0
    avg_dur = observed["duration_min"].mean() if total_obs > 0 else 0
    avg_dist_km = (observed["move_m"].mean() / 1000) if total_obs > 0 else 0
    total_dead_km = (observed["move_m"].sum() / 1000) if total_obs > 0 else 0

    return f"""
    <div class="stats-grid">
      <div class="stat-card"><div class="stat-value">{total_obs:,}</div><div class="stat-label">Observerade</div></div>
      <div class="stat-card"><div class="stat-value">{total_plan:,}</div><div class="stat-label">Planerade</div></div>
      <div class="stat-card"><div class="stat-value">{n_vehicles:,}</div><div class="stat-label">Fordon</div></div>
      <div class="stat-card"><div class="stat-value">{avg_dur:.1f} min</div><div class="stat-label">Snitt tid</div></div>
      <div class="stat-card"><div class="stat-value">{avg_dist_km:.1f} km</div><div class="stat-label">Snitt distans</div></div>
      <div class="stat-card accent"><div class="stat-value">{total_dead_km:,.0f} km</div><div class="stat-label">Total distans</div></div>
    </div>"""


def _build_deadhead_stop_view(observed, planned):
    """Build stop-based deadhead view: dropdown per from-stop, 8-col table per to-stop."""
    periods = _period_order()

    # Combine observed and planned
    all_dead = []
    if observed is not None and not observed.empty:
        obs = observed[["from_stop_observed", "to_stop_observed", "duration_min", "period"]].copy()
        obs["source"] = "obs"
        all_dead.append(obs)
    if planned is not None and not planned.empty:
        pla_cols = ["from_stop_observed", "to_stop_observed", "period"]
        # Use beräknad_körtid_min as duration for planned (no GTFS duration)
        if "beräknad_körtid_min" in planned.columns:
            pla = planned[pla_cols + ["beräknad_körtid_min"]].copy()
            pla = pla.rename(columns={"beräknad_körtid_min": "duration_min"})
        elif "duration_min" in planned.columns:
            pla = planned[pla_cols + ["duration_min"]].copy()
        else:
            pla = planned[pla_cols].copy()
            pla["duration_min"] = None
        pla["source"] = "plan"
        all_dead.append(pla)

    if not all_dead:
        return "<p class='empty'>Inga tomk&ouml;rningar att visa.</p>"

    combined = pd.concat(all_dead, ignore_index=True)
    combined = combined.dropna(subset=["from_stop_observed", "to_stop_observed"])
    combined = combined[combined["from_stop_observed"] != "-"]
    combined = combined[combined["to_stop_observed"] != "-"]

    # Count per from-stop
    from_counts = combined.groupby("from_stop_observed").size().reset_index(name="count")
    from_counts = from_counts.sort_values("count", ascending=False)

    # Build options for dropdown
    options_html = ""
    for _, r in from_counts.iterrows():
        name = html_escape(r["from_stop_observed"])
        cnt = int(r["count"])
        options_html += f'<option value="{name}">{name} ({cnt})</option>\n'

    # Aggregate: avg duration per (from, to, period, source)
    agg = (
        combined.groupby(["from_stop_observed", "to_stop_observed", "period", "source"])
        .agg(avg_min=("duration_min", "mean"), count=("duration_min", "size"))
        .reset_index()
    )

    # Build JS data: {from_stop: [{to_stop, fm_plan, fm_obs, bas_plan, bas_obs, ...}, ...]}
    js_data = {}
    for from_stop, grp in agg.groupby("from_stop_observed"):
        to_stops = {}
        for _, row in grp.iterrows():
            to_s = row["to_stop_observed"]
            if to_s not in to_stops:
                to_stops[to_s] = {"to": to_s}
                for p in periods:
                    to_stops[to_s][f"{p}_plan"] = None
                    to_stops[to_s][f"{p}_obs"] = None
            key = f"{row['period']}_{'plan' if row['source'] == 'plan' else 'obs'}"
            if key in to_stops[to_s]:
                to_stops[to_s][key] = round(row["avg_min"], 1) if pd.notna(row["avg_min"]) else None
        js_data[from_stop] = sorted(to_stops.values(), key=lambda x: x["to"])

    return options_html, js_data


def _deadhead_js(js_data):
    """Generate JS for the deadhead stop view."""
    data_json = json.dumps(js_data, ensure_ascii=False)
    periods = _period_order()

    # Build header columns
    header_cols = ""
    for p in periods:
        header_cols += f"'<th colspan=\"2\">{p}</th>' + "

    sub_header = ""
    for _ in periods:
        sub_header += "'<th>Plan</th><th>Obs</th>' + "

    # Build row cells
    row_cells = ""
    for p in periods:
        p_key = p
        row_cells += (
            f"'<td>' + fmt(d['{p_key}_plan']) + '</td>' + "
            f"'<td>' + fmt(d['{p_key}_obs']) + '</td>' + "
        )

    return f"""
    var deadData = {data_json};

    function showFromStop(name) {{
      var el = document.getElementById('deadheadTable');
      if (!name || !deadData[name]) {{
        el.innerHTML = '';
        return;
      }}
      var rows = deadData[name];
      var html = '<table class="data-table"><thead>' +
        '<tr><th rowspan="2">Till h&aring;llplats</th>' + {header_cols} '</tr>' +
        '<tr>' + {sub_header} '</tr></thead><tbody>';
      function fmt(v) {{
        if (v === null || v === undefined) return '-';
        return Math.round(v) + ' min';
      }}
      rows.forEach(function(d) {{
        html += '<tr><td style="font-weight:600">' + d.to + '</td>' + {row_cells} '</tr>';
      }});
      html += '</tbody></table>';
      el.innerHTML = html;
    }}
    """


# ---------------------------------------------------------------------------
# Linjer tab helpers
# ---------------------------------------------------------------------------

def _build_line_tab(line_stop_data):
    """Build the line view tab with selector, direction toggle, and map."""
    if not line_stop_data:
        return "<p class='empty'>Ingen linjedata tillg&auml;nglig.</p>"

    # Group lines: line_name -> list of direction keys
    line_dirs = {}
    for key, info in line_stop_data.items():
        name = info["name"]
        if name not in line_dirs:
            line_dirs[name] = []
        line_dirs[name].append(key)

    line_names = sorted(line_dirs.keys(), key=lambda x: (len(x), x))
    options_html = ""
    for name in line_names:
        options_html += f'<option value="{html_escape(name)}">{html_escape(name)}</option>\n'

    return f"""
    <div class="line-controls">
      <label for="lineSelect">V&auml;lj linje:</label>
      <select id="lineSelect" onchange="showLine(this.value)">
        <option value="">-- V&auml;lj --</option>
        {options_html}
      </select>
      <div id="dirBtns" style="display:none;margin-left:1rem">
        <button class="period-tab active" id="dirABtn" onclick="switchDir('A')">Riktning A</button>
        <button class="period-tab" id="dirBBtn" onclick="switchDir('B')">Riktning B</button>
      </div>
      <span id="lineInfo" class="line-info"></span>
    </div>
    <div id="lineMap" style="height:500px;border-radius:8px;border:1px solid var(--border);margin:1rem 0;"></div>
    <div id="lineStopTable"></div>
    """


def _leaflet_js(line_stop_data):
    """Generate JS for the Leaflet map with direction selector."""
    js_data = json.dumps(line_stop_data, ensure_ascii=False)

    return f"""
    var lineData = {js_data};
    var map = null;
    var lineLayer = null;
    var currentLine = '';
    var currentDir = 'A';

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

    function switchDir(dir) {{
      currentDir = dir;
      document.getElementById('dirABtn').className = 'period-tab' + (dir === 'A' ? ' active' : '');
      document.getElementById('dirBBtn').className = 'period-tab' + (dir === 'B' ? ' active' : '');
      renderLine();
    }}

    function showLine(name) {{
      initMap();
      currentLine = name;
      currentDir = 'A';
      document.getElementById('dirABtn').className = 'period-tab active';
      document.getElementById('dirBBtn').className = 'period-tab';

      // Check if line has two directions
      var keys = Object.keys(lineData).filter(function(k) {{ return lineData[k].name === name; }});
      document.getElementById('dirBtns').style.display = keys.length > 1 ? 'flex' : 'none';

      renderLine();
    }}

    function renderLine() {{
      if (lineLayer) {{ map.removeLayer(lineLayer); lineLayer = null; }}
      document.getElementById('lineStopTable').innerHTML = '';
      document.getElementById('lineInfo').textContent = '';
      if (!currentLine) return;

      lineLayer = L.featureGroup();
      var wantDir = currentDir === 'A' ? '0' : '1';
      var key = Object.keys(lineData).filter(function(k) {{
        return lineData[k].name === currentLine && lineData[k].direction === wantDir;
      }})[0];
      // Fallback to first available direction
      if (!key) {{
        key = Object.keys(lineData).filter(function(k) {{
          return lineData[k].name === currentLine;
        }})[0];
      }}
      if (!key) return;

      var info = lineData[key];
      var stops = info.stops;
      var coords = [];
      var tableRows = '';

      stops.forEach(function(s) {{
        if (s.lat === null || s.lon === null) return;
        coords.push([s.lat, s.lon]);
        var color = delayColor(s.avg_delay);
        L.circleMarker([s.lat, s.lon], {{
          radius: 7, fillColor: color, color: '#0d1117', weight: 2, fillOpacity: 0.9,
        }}).bindPopup(
          '<b>' + s.stop_name + '</b><br>' +
          'H' + String.fromCharCode(229) + 'llplats ' + s.seq + '<br>' +
          'F' + String.fromCharCode(246) + 'rsening: ' + delayLabel(s.avg_delay) +
          ''
        ).addTo(lineLayer);

        tableRows += '<tr><td>' + s.seq + '</td>' +
          '<td>' + s.stop_name + '</td>' +
          '<td style="color:' + color + ';font-weight:600">' + delayLabel(s.avg_delay) + '</td></tr>';
      }});

      if (coords.length > 1) {{
        L.polyline(coords, {{color: '#58a6ff', weight: 3, opacity: 0.7}}).addTo(lineLayer);
      }}

      lineLayer.addTo(map);
      if (lineLayer.getBounds().isValid()) {{
        map.fitBounds(lineLayer.getBounds(), {{padding: [30, 30]}});
      }}

      document.getElementById('lineInfo').textContent = stops.length + ' h' + String.fromCharCode(229) + 'llplatser';
      document.getElementById('lineStopTable').innerHTML =
        '<table class="data-table" style="margin-top:1rem"><thead><tr>' +
        '<th>#</th><th>H' + String.fromCharCode(229) + 'llplats</th>' +
        '<th>Snittf' + String.fromCharCode(246) + 'rsening</th>' +
        '</tr></thead><tbody>' + tableRows + '</tbody></table>';
    }}
    """


# ---------------------------------------------------------------------------
# Main report generator
# ---------------------------------------------------------------------------

def generate_html_report(observed, planned, segments, date_str,
                         line_stop_data=None, output_path=None):
    """Generate a complete dark-themed HTML report and return the file path."""
    if output_path is None:
        output_path = os.path.join(DATA_DIR, f"tomkorning_rapport_{date_str}.html")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    summary_html = _build_summary_stats(observed, planned, segments)

    # Deadhead stop view
    dh_result = _build_deadhead_stop_view(observed, planned)
    if isinstance(dh_result, str):
        stop_options_html = ""
        deadhead_table_js = "var deadData = {}; function showFromStop() {}"
    else:
        stop_options_html, js_data = dh_result
        deadhead_table_js = _deadhead_js(js_data)

    has_line_tab = line_stop_data is not None and len(line_stop_data) > 0
    line_tab_html = _build_line_tab(line_stop_data) if has_line_tab else ""
    line_js = _leaflet_js(line_stop_data) if has_line_tab else ""

    leaflet_css = ""
    leaflet_scripts = ""
    if has_line_tab:
        leaflet_css = '<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>'
        leaflet_scripts = '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>'

    line_tab_btn = ""
    line_panel_html = ""
    if has_line_tab:
        # Linjer is the default (active) tab
        line_tab_btn = '<button class="top-tab active" onclick="switchTopTab(this, \'linePanel\')">Linjer</button>'
        line_panel_html = (
            '<div id="linePanel" class="tab-panel active">'
            '<h2>Linjevy med f&ouml;rsening per h&aring;llplats</h2>'
            '<div class="delay-legend">'
            '<span><span class="dot" style="background:#3fb950"></span> &le;30s</span>'
            '<span><span class="dot" style="background:#58a6ff"></span> 31-60s</span>'
            '<span><span class="dot" style="background:#d29922"></span> 1-2 min</span>'
            '<span><span class="dot" style="background:#f0883e"></span> 2-5 min</span>'
            '<span><span class="dot" style="background:#f85149"></span> &gt;5 min</span>'
            '<span><span class="dot" style="background:#8b949e"></span> Ingen data</span>'
            '</div>'
            + line_tab_html +
            '</div>'
        )

    # Deadhead tab is secondary when line tab exists
    dh_active = "" if has_line_tab else " active"
    dh_tab_active = "" if has_line_tab else " active"

    html = f"""<!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rapport &mdash; {date_str}</title>
{leaflet_css}
<style>
  :root {{
    --bg: #0d1117; --surface: #161b22; --surface2: #1c2129;
    --border: #30363d; --text: #e6edf3; --text-dim: #8b949e;
    --accent: #58a6ff; --accent2: #3fb950; --red: #f85149; --orange: #d29922;
    --radius: 8px;
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
    background:var(--bg); color:var(--text); line-height:1.5; padding:2rem; max-width:1400px; margin:0 auto; }}
  h1 {{ font-size:1.8rem; font-weight:600; margin-bottom:.25rem; }}
  h2 {{ font-size:1.3rem; font-weight:600; margin:2rem 0 1rem; color:var(--accent); }}
  .subtitle {{ color:var(--text-dim); font-size:.9rem; margin-bottom:2rem; }}
  .stats-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:1rem; margin-bottom:2rem; }}
  .stat-card {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:1.25rem; text-align:center; }}
  .stat-card.accent {{ border-color:var(--accent); background:rgba(88,166,255,.08); }}
  .stat-value {{ font-size:1.5rem; font-weight:700; }}
  .stat-card.accent .stat-value {{ color:var(--accent); }}
  .stat-label {{ font-size:.8rem; color:var(--text-dim); margin-top:.25rem; }}
  .data-table {{ width:100%; border-collapse:collapse; font-size:.85rem; }}
  .data-table th {{ background:var(--surface2); color:var(--accent); font-weight:600; text-align:left;
    padding:.5rem .6rem; border-bottom:2px solid var(--border); position:sticky; top:0; white-space:nowrap; }}
  .data-table td {{ padding:.4rem .6rem; border-bottom:1px solid var(--border); white-space:nowrap; }}
  .data-table tbody tr:hover {{ background:rgba(88,166,255,.06); }}
  .top-tabs {{ display:flex; gap:0; border-bottom:2px solid var(--border); margin-bottom:2rem; }}
  .top-tab {{ padding:.75rem 1.5rem; cursor:pointer; color:var(--text-dim); font-size:1rem; font-weight:600;
    border:none; background:none; border-bottom:2px solid transparent; margin-bottom:-2px; transition:all .15s; }}
  .top-tab:hover {{ color:var(--text); }}
  .top-tab.active {{ color:var(--accent); border-bottom-color:var(--accent); }}
  .tab-panel {{ display:none; }}
  .tab-panel.active {{ display:block; }}
  .period-tab {{ background:var(--surface2); border:1px solid var(--border); border-radius:6px;
    padding:.4rem .9rem; cursor:pointer; color:var(--text-dim); font-size:.85rem; transition:all .15s; }}
  .period-tab:hover {{ color:var(--text); border-color:var(--text-dim); }}
  .period-tab.active {{ background:var(--accent); color:var(--bg); border-color:var(--accent); font-weight:600; }}
  .empty {{ color:var(--text-dim); font-style:italic; padding:1rem 0; }}
  .line-controls {{ display:flex; align-items:center; gap:1rem; margin-bottom:1rem; flex-wrap:wrap; }}
  .line-controls label {{ font-weight:600; color:var(--text-dim); }}
  .line-controls select {{ background:var(--surface); color:var(--text); border:1px solid var(--border);
    border-radius:6px; padding:.5rem 1rem; font-size:.95rem; cursor:pointer; }}
  .line-info {{ color:var(--text-dim); font-size:.85rem; }}
  .delay-legend {{ display:flex; gap:1rem; flex-wrap:wrap; margin:.5rem 0 1rem; font-size:.8rem; color:var(--text-dim); }}
  .delay-legend span {{ display:flex; align-items:center; gap:.3rem; }}
  .delay-legend .dot {{ width:12px; height:12px; border-radius:50%; display:inline-block; }}
  ::-webkit-scrollbar {{ width:8px; height:8px; }}
  ::-webkit-scrollbar-track {{ background:var(--bg); }}
  ::-webkit-scrollbar-thumb {{ background:var(--border); border-radius:4px; }}
  .leaflet-popup-content-wrapper {{ background:var(--surface)!important; color:var(--text)!important;
    border-radius:var(--radius)!important; border:1px solid var(--border)!important; }}
  .leaflet-popup-content {{ color:var(--text)!important; font-size:.85rem!important; }}
  .leaflet-popup-tip {{ background:var(--surface)!important; }}
  @media(max-width:768px) {{ body {{ padding:1rem; }} .stats-grid {{ grid-template-columns:repeat(2,1fr); }} }}
</style>
</head>
<body>
{leaflet_scripts}

<h1>SL Bussrapport</h1>
<p class="subtitle">{date_str} &middot; Genererad {now_str}</p>

<div class="top-tabs">
  {line_tab_btn}
  <button class="top-tab{dh_tab_active}" onclick="switchTopTab(this, 'deadheadPanel')">Tomk&ouml;rningar</button>
</div>

{line_panel_html}

<div id="deadheadPanel" class="tab-panel{dh_active}">
{summary_html}

<h2>Tomk&ouml;rningar per h&aring;llplats</h2>
<p class="subtitle">V&auml;lj en avg&aring;ngsh&aring;llplats f&ouml;r att se planerade och observerade tomk&ouml;rningstider per period.</p>

<div class="line-controls">
  <label for="fromStopSelect">Fr&aring;n h&aring;llplats:</label>
  <select id="fromStopSelect" onchange="showFromStop(this.value)">
    <option value="">-- V&auml;lj --</option>
    {stop_options_html}
  </select>
</div>
<div id="deadheadTable" style="margin-top:1rem;overflow-x:auto;"></div>

</div>

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

PLACEHOLDER_DEADHEAD_JS

PLACEHOLDER_LINE_JS
</script>

</body>
</html>"""

    # Insert JS blocks (can't be in f-string due to backslash/quote issues)
    html = html.replace("PLACEHOLDER_DEADHEAD_JS", deadhead_table_js)
    html = html.replace("PLACEHOLDER_LINE_JS", line_js if has_line_tab else "")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"HTML-rapport sparad: {output_path}")
    return output_path
