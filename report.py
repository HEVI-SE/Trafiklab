"""HTML report generator — light theme with golden accent, publication quality."""

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

def _build_summary_stats(observed, segments, dates=None, hours=None):
    total_obs = len(observed) if observed is not None and not observed.empty else 0

    if total_obs > 0:
        unique_pairs = observed.drop_duplicates(
            subset=["from_stop_observed", "to_stop_observed"]
        ).shape[0]
    else:
        unique_pairs = 0

    # Derive date range and day count from actual data
    if total_obs > 0 and "deadhead_start" in observed.columns:
        dh_dates = pd.to_datetime(observed["deadhead_start"], errors="coerce").dt.date
        unique_dates = dh_dates.dropna().unique()
        n_days = len(unique_dates)
        start_date = str(min(unique_dates))
        end_date = str(max(unique_dates))
        date_range = f"{start_date} &ndash; {end_date}" if start_date != end_date else start_date
    elif dates:
        n_days = len(dates)
        start_date = min(dates)
        end_date = max(dates)
        date_range = f"{start_date} &ndash; {end_date}" if start_date != end_date else start_date
    else:
        n_days = 0
        date_range = "-"

    if total_obs > 0:
        avg_dur = f"{observed['duration_min'].mean():.0f} min"
    else:
        avg_dur = "-"

    # Operator filter buttons with brand colors
    op_color_map = {
        "Keolis": "#1565c0",
        "Nobina": "#2e7d32",
        "VR Sverige": "#2e7d32",
        "Transdev": "#c62828",
        "Övrigt": "#D4A017",
    }
    op_html = ""
    if total_obs > 0:
        op_counts = observed["operator"].value_counts()
        btns = ['<button class="op-btn active" data-op="all" data-color="#D4A017" '
                'onclick="switchOperator(\'all\')" '
                'style="background:#D4A017;color:#fff;border-color:#D4A017">'
                'Alla <b>' + f'{total_obs}' + '</b></button>']
        for op, cnt in op_counts.items():
            op_str = html_escape(str(op))
            color = op_color_map.get(str(op), "#6b7280")
            btns.append(
                f'<button class="op-btn" data-op="{op_str}" data-color="{color}" '
                f'onclick="switchOperator(\'{op_str}\')">'
                f'{op_str} <b>{cnt}</b></button>'
            )
        op_html = '<div class="op-row">' + " ".join(btns) + "</div>"

    return f"""
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-value">{total_obs:,}</div>
        <div class="stat-label">Observerade tomk&ouml;rningar</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{unique_pairs:,}</div>
        <div class="stat-label">Unika h&aring;llplatspar</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{n_days}</div>
        <div class="stat-label">Analyserade dagar</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{avg_dur}</div>
        <div class="stat-label">Snitt restid</div>
      </div>
      <div class="stat-card accent">
        <div class="stat-value">{date_range}</div>
        <div class="stat-label">Analysperiod</div>
      </div>
    </div>
    {op_html}"""


def _build_deadhead_stop_view(observed):
    """Build stop-based deadhead view with operator filtering, Vardag/Helg and OSRM."""
    periods = _period_order()

    if observed is None or observed.empty:
        return "<p class='empty'>Inga tomk&ouml;rningar att visa.</p>"

    cols = ["from_stop_observed", "to_stop_observed", "duration_min", "period"]
    if "day_type" in observed.columns:
        cols.append("day_type")
    if "beräknad_körtid_min" in observed.columns:
        cols.append("beräknad_körtid_min")
    if "operator" in observed.columns:
        cols.append("operator")
    obs = observed[[c for c in cols if c in observed.columns]].copy()
    if "day_type" not in obs.columns:
        obs["day_type"] = "Vardag"
    if "operator" not in obs.columns:
        obs["operator"] = "Övrigt"

    obs = obs.dropna(subset=["from_stop_observed", "to_stop_observed"])
    obs = obs[obs["from_stop_observed"] != "-"]
    obs = obs[obs["to_stop_observed"] != "-"]

    if obs.empty:
        return "<p class='empty'>Inga tomk&ouml;rningar att visa.</p>"

    # OSRM lookup (global, not per-operator)
    osrm_agg = {}
    if "beräknad_körtid_min" in obs.columns:
        osrm_tmp = (
            obs.dropna(subset=["beräknad_körtid_min"])
            .groupby(["from_stop_observed", "to_stop_observed"])["beräknad_körtid_min"]
            .mean()
        )
        for (f, t), v in osrm_tmp.items():
            osrm_agg[(f, t)] = round(v, 1)

    operators = sorted(obs["operator"].unique().tolist())
    filter_keys = ["all"] + operators

    def _build_js_data(subset):
        agg = (
            subset.groupby(["from_stop_observed", "to_stop_observed", "period", "day_type"])
            .agg(avg_min=("duration_min", "mean"), count=("duration_min", "size"))
            .reset_index()
        )
        result = {}
        for from_stop, grp in agg.groupby("from_stop_observed"):
            to_stops = {}
            for _, row in grp.iterrows():
                to_s = row["to_stop_observed"]
                if to_s not in to_stops:
                    to_stops[to_s] = {
                        "to": to_s,
                        "vardag": {p: None for p in periods},
                        "helg": {p: None for p in periods},
                        "osrm": osrm_agg.get((from_stop, to_s)),
                    }
                day_key = "vardag" if row["day_type"] == "Vardag" else "helg"
                if row["period"] in to_stops[to_s][day_key]:
                    to_stops[to_s][day_key][row["period"]] = (
                        round(row["avg_min"], 1) if pd.notna(row["avg_min"]) else None
                    )
            result[from_stop] = sorted(to_stops.values(), key=lambda x: x["to"])
        return result

    # Build deadhead data per operator (+ "all")
    all_data = {}
    for op_key in filter_keys:
        subset = obs if op_key == "all" else obs[obs["operator"] == op_key]
        all_data[op_key] = _build_js_data(subset) if not subset.empty else {}

    # Build from_stop counts per (operator, day_type) for dropdown
    from_counts = {}
    for op_key in filter_keys:
        subset = obs if op_key == "all" else obs[obs["operator"] == op_key]
        from_counts[op_key] = {}
        for dt in ["vardag", "helg"]:
            dt_label = "Vardag" if dt == "vardag" else "Helg"
            dt_sub = subset[subset["day_type"] == dt_label]
            counts = dt_sub.groupby("from_stop_observed").size().to_dict()
            from_counts[op_key][dt] = {k: int(v) for k, v in counts.items()}

    return all_data, from_counts, operators


def _deadhead_js(all_data, from_counts):
    """Generate JS for deadhead view with operator filter, Vardag/Helg toggle, dynamic dropdown."""
    data_json = json.dumps(all_data, ensure_ascii=False)
    counts_json = json.dumps(from_counts, ensure_ascii=False)
    periods = _period_order()

    header_cols = ""
    for p in periods:
        header_cols += f"'<th>{p}</th>' + "
    header_cols += "'<th>Ber&auml;knad tid</th>' + "

    row_cells = ""
    for p in periods:
        row_cells += f"'<td>' + fmt(dayObj['{p}']) + '</td>' + "
    row_cells += "'<td class=\"dim\">' + fmt(d.osrm) + '</td>' + "

    return f"""
    var deadDataByOp = {data_json};
    var fromCountsByOpDay = {counts_json};
    var currentDayType = 'vardag';
    var currentOperator = 'all';

    function switchOperator(op) {{
      currentOperator = op;
      document.querySelectorAll('.op-btn').forEach(function(b) {{
        var isActive = b.dataset.op === op;
        b.classList.toggle('active', isActive);
        if (isActive) {{
          b.style.background = b.dataset.color;
          b.style.borderColor = b.dataset.color;
          b.style.color = '#fff';
        }} else {{
          b.style.background = '';
          b.style.borderColor = '';
          b.style.color = '';
        }}
      }});
      rebuildDropdown();
    }}

    function switchDayType(dt) {{
      currentDayType = dt;
      document.getElementById('dayVardag').className = 'pill' + (dt === 'vardag' ? ' active' : '');
      document.getElementById('dayHelg').className = 'pill' + (dt === 'helg' ? ' active' : '');
      rebuildDropdown();
    }}

    function rebuildDropdown() {{
      var sel = document.getElementById('fromStopSelect');
      var prev = sel.value;
      var counts = (fromCountsByOpDay[currentOperator] || {{}})[currentDayType] || {{}};
      var entries = Object.keys(counts).map(function(k) {{ return {{name:k, count:counts[k]}}; }});
      entries.sort(function(a,b) {{ return b.count - a.count; }});

      sel.innerHTML = '<option value="">-- V\\u00e4lj --</option>';
      entries.forEach(function(e) {{
        var opt = document.createElement('option');
        opt.value = e.name;
        opt.textContent = e.name + ' (' + e.count + ')';
        sel.appendChild(opt);
      }});

      // Restore previous selection if still available
      if (prev && counts[prev]) {{
        sel.value = prev;
        showFromStop(prev);
      }} else {{
        document.getElementById('deadheadTable').innerHTML = '';
      }}
    }}

    function showFromStop(name) {{
      var el = document.getElementById('deadheadTable');
      var data = deadDataByOp[currentOperator] || {{}};
      if (!name || !data[name]) {{
        el.innerHTML = '';
        return;
      }}
      var rows = data[name];
      var html = '<table class="data-table"><thead>' +
        '<tr><th>Till h&aring;llplats</th>' + {header_cols} '</tr>' +
        '</thead><tbody>';
      function fmt(v) {{
        if (v === null || v === undefined) return '<span class="dim">&ndash;</span>';
        return Math.round(v) + ' min';
      }}
      rows.forEach(function(d) {{
        var dayObj = d[currentDayType] || {{}};
        html += '<tr><td class="bold">' + d.to + '</td>' + {row_cells} '</tr>';
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
    <div class="controls-bar">
      <label for="lineSelect">V&auml;lj linje</label>
      <select id="lineSelect" onchange="showLine(this.value)">
        <option value="">-- V&auml;lj --</option>
        {options_html}
      </select>
      <div id="dirBtns" style="display:none">
        <button class="pill active" id="dirABtn" onclick="switchDir('A')">Riktning A</button>
        <button class="pill" id="dirBBtn" onclick="switchDir('B')">Riktning B</button>
      </div>
      <span id="lineInfo" class="meta"></span>
    </div>
    <div id="lineMap"></div>
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
      L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
        attribution: '&copy; OpenStreetMap &copy; CARTO',
        maxZoom: 18,
      }}).addTo(map);
    }}

    function delayColor(d) {{
      if (d === null || d === undefined) return '#b0b8c4';
      if (d <= 30) return '#16a34a';
      if (d <= 60) return '#2563eb';
      if (d <= 120) return '#d97706';
      if (d <= 300) return '#ea580c';
      return '#dc2626';
    }}

    function delayLabel(d) {{
      if (d === null || d === undefined) return 'Ingen data';
      var sign = d >= 0 ? '+' : '';
      if (Math.abs(d) < 60) return sign + Math.round(d) + 's';
      return sign + (d/60).toFixed(1) + ' min';
    }}

    function switchDir(dir) {{
      currentDir = dir;
      document.getElementById('dirABtn').className = 'pill' + (dir === 'A' ? ' active' : '');
      document.getElementById('dirBBtn').className = 'pill' + (dir === 'B' ? ' active' : '');
      renderLine();
    }}

    function showLine(name) {{
      initMap();
      currentLine = name;
      currentDir = 'A';
      document.getElementById('dirABtn').className = 'pill active';
      document.getElementById('dirBBtn').className = 'pill';

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
          radius: 7, fillColor: color, color: '#fff', weight: 2, fillOpacity: 0.9,
        }}).bindPopup(
          '<b>' + s.stop_name + '</b><br>' +
          'H\\u00e5llplats ' + s.seq + '<br>' +
          'F\\u00f6rsening: ' + delayLabel(s.avg_delay)
        ).addTo(lineLayer);

        tableRows += '<tr><td>' + s.seq + '</td>' +
          '<td>' + s.stop_name + '</td>' +
          '<td style="color:' + color + ';font-weight:600">' + delayLabel(s.avg_delay) + '</td></tr>';
      }});

      if (coords.length > 1) {{
        L.polyline(coords, {{color: '#D4A017', weight: 3, opacity: 0.6}}).addTo(lineLayer);
      }}

      lineLayer.addTo(map);
      if (lineLayer.getBounds().isValid()) {{
        map.fitBounds(lineLayer.getBounds(), {{padding: [30, 30]}});
      }}

      document.getElementById('lineInfo').textContent = stops.length + ' h\\u00e5llplatser';
      document.getElementById('lineStopTable').innerHTML =
        '<table class="data-table" style="margin-top:1.5rem"><thead><tr>' +
        '<th>#</th><th>H\\u00e5llplats</th>' +
        '<th>Snittf\\u00f6rsening</th>' +
        '</tr></thead><tbody>' + tableRows + '</tbody></table>';
    }}
    """


# ---------------------------------------------------------------------------
# Main report generator
# ---------------------------------------------------------------------------

def generate_html_report(observed, planned, segments, date_str,
                         line_stop_data=None, output_path=None,
                         dates=None, hours=None):
    """Generate a publication-quality light-themed HTML report."""
    if output_path is None:
        output_path = os.path.join(DATA_DIR, f"tomkorning_rapport_{date_str}.html")

    summary_html = _build_summary_stats(observed, segments, dates=dates, hours=hours)

    dh_result = _build_deadhead_stop_view(observed)
    if isinstance(dh_result, str):
        stop_options_html = ""
        deadhead_table_js = "var deadDataByOp={}; var fromCountsByOpDay={}; var currentOperator='all'; var currentDayType='vardag'; function showFromStop(){} function switchOperator(){} function switchDayType(){} function rebuildDropdown(){}"
    else:
        all_data, from_counts_data, operators = dh_result
        deadhead_table_js = _deadhead_js(all_data, from_counts_data)
        # Build initial dropdown (all operators, vardag)
        init_counts = from_counts_data.get("all", {}).get("vardag", {})
        sorted_stops = sorted(init_counts.items(), key=lambda x: -x[1])
        stop_options_html = ""
        for name, cnt in sorted_stops:
            esc = html_escape(name)
            stop_options_html += f'<option value="{esc}">{esc} ({cnt})</option>\n'

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
        line_tab_btn = '<button class="top-tab active" onclick="switchTopTab(this, \'linePanel\')">Linjer</button>'
        line_panel_html = (
            '<div id="linePanel" class="tab-panel active">'
            '<h2>Linjevy med f&ouml;rsening per h&aring;llplats</h2>'
            '<div class="legend">'
            '<span><span class="dot" style="background:#16a34a"></span> &le;30s</span>'
            '<span><span class="dot" style="background:#2563eb"></span> 31&ndash;60s</span>'
            '<span><span class="dot" style="background:#d97706"></span> 1&ndash;2 min</span>'
            '<span><span class="dot" style="background:#ea580c"></span> 2&ndash;5 min</span>'
            '<span><span class="dot" style="background:#dc2626"></span> &gt;5 min</span>'
            '<span><span class="dot" style="background:#b0b8c4"></span> Ingen data</span>'
            '</div>'
            + line_tab_html +
            '</div>'
        )

    dh_active = "" if has_line_tab else " active"
    dh_tab_active = "" if has_line_tab else " active"

    html = f"""<!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SL Bussanalys</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
{leaflet_css}
<style>
  :root {{
    --bg: #fafafa;
    --surface: #ffffff;
    --surface2: #f5f5f0;
    --border: #e5e5e0;
    --border-strong: #d0d0cb;
    --text: #1a1a1a;
    --text-dim: #6b7280;
    --accent: #F1C332;
    --accent-dark: #D4A017;
    --accent-bg: #fdf8e8;
    --accent-border: #f0d97a;
    --green: #16a34a;
    --red: #dc2626;
    --orange: #d97706;
    --radius: 10px;
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}

  body {{
    font-family:'Inter',system-ui,-apple-system,sans-serif;
    background:var(--bg); color:var(--text); line-height:1.6;
  }}

  /* ---- Top bar ---- */
  .topbar {{
    background:var(--surface);
    border-bottom:1px solid var(--border);
    padding:0 2rem;
  }}
  .topbar-inner {{
    max-width:1320px; margin:0 auto;
    display:flex; align-items:center; justify-content:space-between;
    height:56px;
  }}
  .brand {{
    font-weight:700; font-size:1.15rem; letter-spacing:-.02em;
    display:flex; align-items:center; gap:.5rem;
  }}
  .brand-mark {{
    background:var(--accent); color:#1a1a1a;
    font-weight:700; font-size:.75rem; padding:3px 8px;
    border-radius:4px; letter-spacing:.06em;
  }}
  .brand-sub {{ color:var(--text-dim); font-weight:400; font-size:.85rem; }}

  /* ---- Page ---- */
  .page {{ max-width:1320px; margin:0 auto; padding:2rem 2rem 1rem; }}

  /* ---- Tabs ---- */
  .top-tabs {{
    display:flex; gap:0;
    border-bottom:2px solid var(--border);
    margin-bottom:2rem;
  }}
  .top-tab {{
    padding:.7rem 1.5rem; cursor:pointer;
    color:var(--text-dim); font-size:.9rem; font-weight:600;
    border:none; background:none;
    border-bottom:2px solid transparent; margin-bottom:-2px;
    transition:all .15s;
  }}
  .top-tab:hover {{ color:var(--text); }}
  .top-tab.active {{ color:var(--accent-dark); border-bottom-color:var(--accent); }}
  .tab-panel {{ display:none; }}
  .tab-panel.active {{ display:block; }}

  /* ---- Section headings ---- */
  h2 {{
    font-size:1.1rem; font-weight:700; margin:2rem 0 .75rem;
    color:var(--text);
    display:flex; align-items:center; gap:.5rem;
  }}
  h2::before {{
    content:''; display:inline-block;
    width:4px; height:18px; border-radius:2px;
    background:var(--accent);
  }}
  .subtitle {{
    color:var(--text-dim); font-size:.84rem; margin-bottom:1.5rem;
    line-height:1.5;
  }}

  /* ---- Stats grid ---- */
  .stats-grid {{
    display:grid;
    grid-template-columns:repeat(auto-fit,minmax(155px,1fr));
    gap:.75rem; margin-bottom:1rem;
  }}
  .stat-card {{
    background:var(--surface); border:1px solid var(--border);
    border-radius:var(--radius); padding:1.15rem 1rem;
    text-align:center; transition:box-shadow .2s, transform .2s;
  }}
  .stat-card:hover {{
    box-shadow:0 4px 16px rgba(0,0,0,.06);
    transform:translateY(-2px);
  }}
  .stat-card.accent {{
    border-color:var(--accent-border);
    background:var(--accent-bg);
  }}
  .stat-value {{ font-size:1.5rem; font-weight:700; color:var(--text); }}
  .stat-card.accent .stat-value {{ color:var(--accent-dark); }}
  .stat-label {{
    font-size:.7rem; color:var(--text-dim);
    margin-top:.15rem; text-transform:uppercase;
    letter-spacing:.05em; font-weight:500;
  }}

  /* Operator filter buttons */
  .op-row {{
    display:flex; flex-wrap:wrap; gap:.4rem;
    margin-bottom:1.5rem;
  }}
  .op-btn {{
    display:inline-flex; align-items:center; gap:.35rem;
    background:var(--surface); border:2px solid var(--border);
    border-radius:20px; padding:.35rem .85rem;
    font-size:.78rem; color:var(--text-dim);
    cursor:pointer; transition:all .15s; font-family:inherit;
  }}
  .op-btn:hover {{ opacity:.85; }}
  .op-btn.active {{
    color:#fff; font-weight:600;
  }}
  .op-btn b {{ font-weight:700; }}

  /* ---- Tables ---- */
  .data-table {{ width:100%; border-collapse:collapse; font-size:.84rem; }}
  .data-table th {{
    background:var(--surface2); color:var(--text-dim);
    font-weight:600; text-align:left; font-size:.75rem;
    text-transform:uppercase; letter-spacing:.04em;
    padding:.6rem .75rem; border-bottom:2px solid var(--border);
    position:sticky; top:0; white-space:nowrap;
  }}
  .data-table td {{
    padding:.5rem .75rem; border-bottom:1px solid var(--border);
    white-space:nowrap;
  }}
  .data-table tbody tr:hover {{ background:var(--accent-bg); }}
  .data-table .bold {{ font-weight:600; }}
  .data-table .dim {{ color:var(--text-dim); }}

  /* ---- Pills / toggle buttons ---- */
  .pill {{
    background:var(--surface); border:1px solid var(--border);
    border-radius:20px; padding:.35rem .85rem;
    cursor:pointer; color:var(--text-dim); font-size:.82rem;
    font-weight:500; transition:all .15s;
  }}
  .pill:hover {{ border-color:var(--accent); color:var(--text); }}
  .pill.active {{
    background:var(--accent); color:#1a1a1a;
    border-color:var(--accent); font-weight:600;
  }}

  /* ---- Controls bar ---- */
  .controls-bar {{
    display:flex; align-items:center; gap:.75rem;
    flex-wrap:wrap; margin-bottom:1rem;
  }}
  .controls-bar label {{
    font-weight:600; color:var(--text-dim); font-size:.85rem;
  }}
  .controls-bar select {{
    background:var(--surface); color:var(--text);
    border:1px solid var(--border); border-radius:8px;
    padding:.45rem .9rem; font-size:.88rem;
    cursor:pointer; transition:border-color .2s;
    font-family:inherit;
  }}
  .controls-bar select:hover {{ border-color:var(--accent); }}
  .controls-bar select:focus {{ outline:none; border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-bg); }}
  .meta {{ color:var(--text-dim); font-size:.82rem; }}

  /* ---- Legend ---- */
  .legend {{
    display:flex; gap:.85rem; flex-wrap:wrap;
    margin:.5rem 0 1.25rem; font-size:.78rem; color:var(--text-dim);
  }}
  .legend span {{ display:flex; align-items:center; gap:.3rem; }}
  .legend .dot {{
    width:11px; height:11px; border-radius:50%;
    display:inline-block; border:1px solid rgba(0,0,0,.1);
  }}

  /* ---- Map ---- */
  #lineMap {{
    height:500px; border-radius:var(--radius);
    border:1px solid var(--border); margin:1rem 0;
    box-shadow:0 2px 8px rgba(0,0,0,.04);
  }}

  /* Leaflet popup override */
  .leaflet-popup-content-wrapper {{
    background:var(--surface)!important; color:var(--text)!important;
    border-radius:8px!important; box-shadow:0 4px 16px rgba(0,0,0,.12)!important;
    border:1px solid var(--border)!important;
  }}
  .leaflet-popup-content {{ color:var(--text)!important; font-size:.84rem!important; font-family:'Inter',sans-serif!important; }}
  .leaflet-popup-tip {{ background:var(--surface)!important; }}

  .empty {{ color:var(--text-dim); font-style:italic; padding:1rem 0; }}

  /* ---- Watermark logo ---- */
  .watermark {{
    position:fixed; bottom:-8%; left:-5%;
    width:45%; opacity:0.04;
    pointer-events:none; z-index:0;
    user-select:none;
  }}

  /* ---- Footer ---- */
  .footer {{
    text-align:center; padding:2rem 1rem 1.5rem;
    color:var(--text-dim); font-size:.78rem;
    border-top:1px solid var(--border); margin-top:3rem;
  }}
  .footer a {{ color:var(--accent-dark); text-decoration:none; font-weight:500; }}
  .footer a:hover {{ text-decoration:underline; }}

  /* ---- Responsive ---- */
  @media(max-width:768px) {{
    .topbar {{ padding:0 1rem; }}
    .page {{ padding:1.25rem 1rem .5rem; }}
    .stats-grid {{ grid-template-columns:repeat(2,1fr); }}
    #lineMap {{ height:350px; }}
  }}
</style>
</head>
<body>
{leaflet_scripts}

<div class="topbar">
  <div class="topbar-inner">
    <div class="brand">
      <span class="brand-mark">SL</span>
      Bussanalys
    </div>
    <span class="brand-sub">Tomk&ouml;rningar &amp; f&ouml;rseningar</span>
  </div>
</div>

<div class="page">

<div class="top-tabs">
  {line_tab_btn}
  <button class="top-tab{dh_tab_active}" onclick="switchTopTab(this, 'deadheadPanel')">Tomk&ouml;rningar</button>
</div>

{line_panel_html}

<div id="deadheadPanel" class="tab-panel{dh_active}">
{summary_html}

<h2>Tomk&ouml;rningar per h&aring;llplats</h2>
<p class="subtitle">V&auml;lj en avg&aring;ngsh&aring;llplats f&ouml;r att se genomsnittliga tomk&ouml;rningstider uppdelat per trafikperiod. Kolumnen <em>Ber&auml;knad tid</em> visar OSRM-baserad k&ouml;rtid som referensv&auml;rde.</p>

<div class="controls-bar">
  <label for="fromStopSelect">Fr&aring;n h&aring;llplats</label>
  <select id="fromStopSelect" onchange="showFromStop(this.value)">
    <option value="">-- V&auml;lj --</option>
    {stop_options_html}
  </select>
  <button class="pill active" id="dayVardag" onclick="switchDayType('vardag')">Vardag</button>
  <button class="pill" id="dayHelg" onclick="switchDayType('helg')">Helg</button>
</div>
<div id="deadheadTable" style="margin-top:1rem;overflow-x:auto;"></div>

</div>

<div class="footer">
  Kontakt: <a href="mailto:Hevi@gmail.com">Hevi@gmail.com</a>
</div>

<img src="logo.png" class="watermark" alt="">

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

// Auto-select line 1 on page load
document.addEventListener('DOMContentLoaded', function() {{
  var lineSel = document.getElementById('lineSelect');
  if (lineSel) {{
    var opts = Array.from(lineSel.options);
    var match = opts.find(function(o) {{ return o.value === '1'; }});
    if (match) {{
      lineSel.value = '1';
      showLine('1');
    }}
  }}
}});
</script>

</body>
</html>"""

    html = html.replace("PLACEHOLDER_DEADHEAD_JS", deadhead_table_js)
    html = html.replace("PLACEHOLDER_LINE_JS", line_js if has_line_tab else "")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"HTML-rapport sparad: {output_path}")
    return output_path
