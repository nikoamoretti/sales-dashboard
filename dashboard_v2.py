#!/usr/bin/env python3
"""Dashboard V2 — Supabase-powered sales outbound dashboard.

Generates a self-contained index.html for GitHub Pages.

Usage:
    python3 dashboard_v2.py
    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... python3 dashboard_v2.py
"""

import html as _html
import json
import sys
from datetime import datetime
from pathlib import Path

from dash_data import fetch_all

HERE = Path(__file__).parent


def _h(s) -> str:
    """HTML-escape a value for safe embedding."""
    return _html.escape(str(s or ""), quote=True)


def _j(obj) -> str:
    """JSON-serialize for embedding in a <script> tag."""
    return json.dumps(obj, default=str, ensure_ascii=False)


def _fmt_dur(seconds: int) -> str:
    if not seconds:
        return "—"
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def _fmt_delta(val, suffix="") -> str:
    """Format a WoW delta as colored HTML span."""
    try:
        v = float(str(val).replace("+", ""))
    except (ValueError, TypeError):
        return f'<span class="delta-neutral">—</span>'
    cls = "delta-up" if v > 0 else "delta-down" if v < 0 else "delta-neutral"
    sign = "+" if v > 0 else ""
    display = f"{sign}{v:g}{suffix}"
    arrow = "↑" if v > 0 else "↓" if v < 0 else "→"
    return f'<span class="{cls}">{arrow} {display}</span>'


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

def _styles() -> str:
    return """
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg-primary:   #0f1117;
  --bg-secondary: #1a1d27;
  --bg-card:      #222633;
  --bg-hover:     #2a2f42;
  --border:       #2d3348;
  --text-primary: #e8eaed;
  --text-secondary: #9aa0b4;
  --text-muted:   #5a6078;
  --accent-blue:  #4285f4;
  --accent-green: #34a853;
  --accent-red:   #ea4335;
  --accent-yellow:#fbbc04;
  --accent-purple:#a855f7;
  --accent-orange:#f97316;
  --accent-teal:  #00c4cc;
  --radius:       8px;
  --radius-sm:    4px;
  --shadow:       0 1px 3px rgba(0,0,0,.4), 0 4px 12px rgba(0,0,0,.3);
}

html { font-size: 16px; scroll-behavior: smooth; }

body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  background: var(--bg-primary);
  color: var(--text-primary);
  font-size: 0.875rem;
  line-height: 1.5;
  min-height: 100vh;
}

/* Skip link */
.skip-link {
  position: absolute; top: -100px; left: 1rem;
  background: var(--accent-blue); color: #fff;
  padding: .5rem 1rem; border-radius: var(--radius-sm);
  font-weight: 600; z-index: 9999; text-decoration: none;
}
.skip-link:focus { top: 1rem; }

/* ---- Layout ---- */
.app-wrapper { max-width: 1200px; margin: 0 auto; padding: 0 1rem 3rem; }

/* ---- Header ---- */
.app-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 1.25rem 0 1rem;
  border-bottom: 1px solid var(--border);
  gap: 1rem;
}
.app-header h1 {
  font-size: 1.25rem; font-weight: 700; color: var(--text-primary);
  display: flex; align-items: center; gap: .6rem;
}
.app-header h1 .logo-dot {
  width: 10px; height: 10px; border-radius: 50%;
  background: var(--accent-blue);
  box-shadow: 0 0 8px var(--accent-blue);
  flex-shrink: 0;
}
.header-meta { color: var(--text-muted); font-size: .75rem; text-align: right; }

/* ---- Tab bar ---- */
.tab-bar-wrap {
  position: sticky; top: 0; z-index: 100;
  background: var(--bg-primary);
  border-bottom: 1px solid var(--border);
  margin: 0 -1rem;
  padding: 0 1rem;
}
.tab-bar {
  display: flex; gap: .25rem; overflow-x: auto;
  scrollbar-width: none;
  -webkit-overflow-scrolling: touch;
}
.tab-bar::-webkit-scrollbar { display: none; }

.tab-btn {
  flex-shrink: 0;
  background: none; border: none; cursor: pointer;
  padding: .75rem 1rem;
  color: var(--text-secondary); font-size: .875rem; font-weight: 500;
  border-bottom: 2px solid transparent;
  transition: color .15s, border-color .15s;
  white-space: nowrap;
  font-family: inherit;
}
.tab-btn:hover { color: var(--text-primary); }
.tab-btn.active {
  color: var(--accent-blue); border-bottom-color: var(--accent-blue);
}
.tab-btn:focus-visible {
  outline: 2px solid var(--accent-blue); outline-offset: -2px; border-radius: 2px;
}

/* ---- Tab panels ---- */
.tab-panel { display: none; padding-top: 1.5rem; }
.tab-panel.active { display: block; }

/* ---- Cards ---- */
.card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.25rem;
  box-shadow: var(--shadow);
}

/* ---- Section heading ---- */
.section-heading {
  font-size: 1rem; font-weight: 600; color: var(--text-primary);
  margin-bottom: 1rem; display: flex; align-items: center; gap: .5rem;
}
.section-heading .sh-icon { font-size: .9rem; }

/* ---- KPI Cards ---- */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: .75rem;
  margin-bottom: 1.5rem;
}
.kpi-card {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 1rem;
  box-shadow: var(--shadow);
}
.kpi-value {
  font-size: 2rem; font-weight: 700; line-height: 1;
  font-variant-numeric: tabular-nums;
  color: var(--text-primary);
}
.kpi-label {
  font-size: .75rem; color: var(--text-secondary);
  margin-top: .35rem; text-transform: uppercase; letter-spacing: .04em;
}
.kpi-delta { font-size: .75rem; margin-top: .5rem; }
.delta-up   { color: var(--accent-green); font-weight: 600; }
.delta-down { color: var(--accent-red);   font-weight: 600; }
.delta-neutral { color: var(--text-muted); }

/* ---- Insight cards ---- */
.insights-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: .75rem;
  margin-bottom: 1.5rem;
}
.insight-card {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 1rem 1rem 1rem 1.25rem;
  box-shadow: var(--shadow);
  border-left-width: 3px;
  border-left-style: solid;
}
.insight-card.type-action_required { border-left-color: var(--accent-red); }
.insight-card.type-alert           { border-left-color: var(--accent-yellow); }
.insight-card.type-win             { border-left-color: var(--accent-green); }
.insight-card.type-experiment      { border-left-color: var(--accent-blue); }
.insight-card.type-coaching        { border-left-color: var(--accent-purple); }
.insight-card.type-strategic       { border-left-color: var(--text-muted); }

.insight-header { display: flex; align-items: center; gap: .5rem; margin-bottom: .5rem; flex-wrap: wrap; }
.insight-type-badge {
  font-size: .65rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: .06em; padding: .15rem .45rem;
  border-radius: 999px; flex-shrink: 0;
}
.insight-type-badge.type-action_required { background: rgba(234,67,53,.15); color: #ff6b6b; }
.insight-type-badge.type-alert           { background: rgba(251,188,4,.15); color: var(--accent-yellow); }
.insight-type-badge.type-win             { background: rgba(52,168,83,.15); color: var(--accent-green); }
.insight-type-badge.type-experiment      { background: rgba(66,133,244,.15); color: var(--accent-blue); }
.insight-type-badge.type-coaching        { background: rgba(168,85,247,.15); color: var(--accent-purple); }
.insight-type-badge.type-strategic       { background: rgba(90,96,120,.15); color: var(--text-secondary); }

.insight-severity {
  font-size: .65rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: .04em; color: var(--text-muted);
}
.insight-title { font-weight: 600; color: var(--text-primary); margin-bottom: .25rem; }
.insight-body  { color: var(--text-secondary); font-size: .8rem; line-height: 1.4; }
.insight-meta  { margin-top: .6rem; display: flex; gap: .5rem; flex-wrap: wrap; }
.insight-tag   {
  font-size: .65rem; padding: .15rem .45rem; border-radius: 999px;
  border: 1px solid var(--border); color: var(--text-muted);
}

/* ---- Channel comparison ---- */
.channel-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: .75rem;
  margin-bottom: 1.5rem;
}
.channel-card {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 1rem; text-align: center;
  box-shadow: var(--shadow);
}
.channel-icon { font-size: 1.5rem; margin-bottom: .35rem; }
.channel-name { font-size: .75rem; text-transform: uppercase; letter-spacing: .06em; color: var(--text-muted); }
.channel-main-metric { font-size: 1.5rem; font-weight: 700; margin: .4rem 0 .15rem; }
.channel-sub-metric  { font-size: .75rem; color: var(--text-secondary); }

/* ---- Chart containers ---- */
.chart-card { margin-bottom: 1.5rem; }
.chart-container { height: 320px; position: relative; }

/* ---- Tables ---- */
.table-wrap {
  overflow-x: auto;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  margin-bottom: 1.5rem;
}
table {
  width: 100%; border-collapse: collapse;
  font-size: .8rem;
}
th {
  background: var(--bg-secondary); padding: .65rem .9rem;
  text-align: left; color: var(--text-secondary);
  font-size: .7rem; text-transform: uppercase; letter-spacing: .05em;
  border-bottom: 1px solid var(--border);
  position: sticky; top: 0; z-index: 1;
  white-space: nowrap; user-select: none;
}
td {
  padding: .6rem .9rem; border-bottom: 1px solid var(--border);
  vertical-align: top; color: var(--text-primary);
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: var(--bg-hover); }

/* Expandable row detail */
.row-detail {
  display: none; padding: .75rem .9rem;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
}
.row-detail.visible { display: table-cell; }
.row-detail-inner { padding: .5rem .75rem; font-size: .8rem; color: var(--text-secondary); line-height: 1.5; }
.row-detail-inner strong { color: var(--text-primary); }

/* Clickable row trigger */
.expandable-row { cursor: pointer; }
.expandable-row td:first-child::before {
  content: "▶ "; font-size: .6rem; color: var(--text-muted); margin-right: .3rem;
}
.expandable-row.expanded td:first-child::before { content: "▼ "; }

/* ---- Badges ---- */
.badge {
  display: inline-block; padding: .15rem .5rem;
  border-radius: 999px; font-size: .65rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: .05em;
}
.badge-prospect    { background: rgba(90,96,120,.2); color: var(--text-muted); }
.badge-contacted   { background: rgba(66,133,244,.15); color: var(--accent-blue); }
.badge-interested  { background: rgba(0,196,204,.15); color: var(--accent-teal); }
.badge-meeting_booked { background: rgba(168,85,247,.2); color: var(--accent-purple); }
.badge-opportunity { background: rgba(52,168,83,.2); color: var(--accent-green); }
.badge-closed      { background: rgba(52,168,83,.3); color: var(--accent-green); }
.badge-disqualified{ background: rgba(234,67,53,.15); color: var(--accent-red); }

.badge-active    { background: rgba(52,168,83,.15); color: var(--accent-green); }
.badge-paused    { background: rgba(251,188,4,.15); color: var(--accent-yellow); }
.badge-completed { background: rgba(66,133,244,.15); color: var(--accent-blue); }
.badge-cancelled { background: rgba(90,96,120,.2); color: var(--text-muted); }

.badge-high   { background: rgba(234,67,53,.15); color: var(--accent-red); }
.badge-medium { background: rgba(251,188,4,.15); color: var(--accent-yellow); }
.badge-low    { background: rgba(90,96,120,.2); color: var(--text-muted); }
.badge-none   { background: rgba(90,96,120,.1); color: var(--text-muted); }

.badge-interested_s    { background: rgba(52,168,83,.15); color: var(--accent-green); }
.badge-not_interested  { background: rgba(234,67,53,.15); color: var(--accent-red); }
.badge-neutral         { background: rgba(90,96,120,.2); color: var(--text-muted); }
.badge-ooo             { background: rgba(251,188,4,.15); color: var(--accent-yellow); }

/* ---- Filter bar ---- */
.filter-bar {
  display: flex; gap: .5rem; flex-wrap: wrap;
  margin-bottom: 1rem; align-items: center;
}
.filter-bar input,
.filter-bar select {
  background: var(--bg-card); border: 1px solid var(--border);
  color: var(--text-primary); border-radius: var(--radius-sm);
  padding: .45rem .75rem; font-size: .8rem; font-family: inherit;
  outline: none; transition: border-color .15s;
}
.filter-bar input { flex: 1; min-width: 180px; }
.filter-bar select { min-width: 140px; }
.filter-bar input:focus,
.filter-bar select:focus { border-color: var(--accent-blue); }
.filter-bar input::placeholder { color: var(--text-muted); }

.filter-bar label { font-size: .75rem; color: var(--text-secondary); flex-shrink: 0; }

/* ---- Intel highlight cards ---- */
.intel-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: .75rem; margin-bottom: 1.5rem;
}
.intel-card {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 1rem;
  box-shadow: var(--shadow);
}
.intel-card-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: .5rem; }
.intel-company { font-weight: 600; color: var(--text-primary); }
.intel-contact { font-size: .75rem; color: var(--text-secondary); margin-bottom: .5rem; }
.intel-quote {
  font-style: italic; color: var(--text-secondary); font-size: .8rem;
  border-left: 2px solid var(--border); padding-left: .6rem; margin: .5rem 0;
}
.intel-action { font-size: .75rem; color: var(--text-secondary); }
.intel-action strong { color: var(--accent-blue); }

/* ---- Company cards ---- */
.company-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: .75rem; margin-bottom: 1.5rem;
}
.company-card {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 1rem;
  box-shadow: var(--shadow); cursor: pointer;
  transition: border-color .15s;
}
.company-card:hover { border-color: var(--accent-blue); }
.company-card:focus-visible { outline: 2px solid var(--accent-blue); }
.company-card-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: .5rem; }
.company-name { font-weight: 600; color: var(--text-primary); }
.company-meta { font-size: .75rem; color: var(--text-secondary); display: flex; gap: .75rem; margin: .35rem 0; flex-wrap: wrap; }
.company-channels { display: flex; gap: .3rem; margin: .35rem 0; }
.channel-badge {
  font-size: .65rem; padding: .15rem .45rem; border-radius: 999px;
  border: 1px solid var(--border); color: var(--text-secondary);
}
.channel-badge.ch-calls    { border-color: var(--accent-blue); color: var(--accent-blue); }
.channel-badge.ch-linkedin { border-color: var(--accent-teal); color: var(--accent-teal); }
.channel-badge.ch-email    { border-color: var(--accent-green); color: var(--accent-green); }
.company-intel-summary { margin-top: .5rem; font-size: .75rem; color: var(--text-secondary); }
.company-detail {
  display: none; margin-top: .75rem; padding-top: .75rem;
  border-top: 1px solid var(--border);
}
.company-detail.visible { display: block; }
.company-activity-item {
  display: flex; gap: .5rem; font-size: .75rem; color: var(--text-secondary);
  padding: .3rem 0; border-bottom: 1px solid var(--border);
}
.company-activity-item:last-child { border-bottom: none; }
.company-activity-date { color: var(--text-muted); flex-shrink: 0; width: 75px; }

/* ---- Experiment cards ---- */
.experiment-card {
  background: var(--bg-card); border: 1px solid var(--border);
  border-left: 3px solid var(--accent-blue);
  border-radius: var(--radius); padding: 1rem 1rem 1rem 1.25rem;
  box-shadow: var(--shadow); margin-bottom: .75rem;
}
.experiment-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: .5rem; }
.experiment-name { font-weight: 600; color: var(--text-primary); }
.experiment-hypothesis { color: var(--text-secondary); font-size: .8rem; margin-bottom: .5rem; }
.experiment-result { color: var(--text-secondary); font-size: .8rem; margin-top: .5rem; }
.experiment-meta { display: flex; gap: .5rem; flex-wrap: wrap; margin-top: .5rem; }
.experiment-meta-item { font-size: .7rem; color: var(--text-muted); }

/* ---- Empty state ---- */
.empty-state {
  text-align: center; padding: 3rem 1rem;
  color: var(--text-muted);
}
.empty-state .empty-icon { font-size: 2.5rem; margin-bottom: 1rem; }
.empty-state p { max-width: 380px; margin: 0 auto; line-height: 1.6; }

/* ---- Pagination ---- */
.pagination {
  display: flex; align-items: center; justify-content: space-between;
  padding: .75rem 0; gap: .5rem;
}
.pagination-info { color: var(--text-muted); font-size: .75rem; }
.pagination-controls { display: flex; gap: .35rem; }
.page-btn {
  background: var(--bg-card); border: 1px solid var(--border);
  color: var(--text-secondary); padding: .35rem .7rem;
  border-radius: var(--radius-sm); font-size: .75rem; cursor: pointer;
  font-family: inherit; transition: border-color .15s, color .15s;
}
.page-btn:hover:not(:disabled) { border-color: var(--accent-blue); color: var(--accent-blue); }
.page-btn.active { background: var(--accent-blue); color: #fff; border-color: var(--accent-blue); }
.page-btn:disabled { opacity: .4; cursor: not-allowed; }

/* ---- Footer ---- */
.app-footer {
  margin-top: 2rem; padding: 1.25rem 0;
  border-top: 1px solid var(--border);
  color: var(--text-muted); font-size: .75rem;
  display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap;
}

/* ---- Responsive ---- */
@media (max-width: 680px) {
  .kpi-grid { grid-template-columns: repeat(2, 1fr); }
  .channel-grid { grid-template-columns: 1fr; }
  .insights-grid { grid-template-columns: 1fr; }
  .intel-grid { grid-template-columns: 1fr; }
  .company-grid { grid-template-columns: 1fr; }
  .chart-container { height: 240px; }
  .app-header h1 { font-size: 1rem; }
}
@media (max-width: 420px) {
  .kpi-grid { grid-template-columns: 1fr 1fr; }
  .kpi-value { font-size: 1.5rem; }
}
</style>"""


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

def _header(data: dict) -> str:
    gen = data.get("generated_at", "")
    try:
        ts = datetime.fromisoformat(gen.replace("Z", "+00:00"))
        gen_fmt = ts.strftime("%b %d, %Y %H:%M UTC")
    except (ValueError, TypeError):
        gen_fmt = str(gen)[:16]
    return f"""
<header class="app-header" role="banner">
  <h1>
    <span class="logo-dot" aria-hidden="true"></span>
    Telegraph Outbound Central
  </h1>
  <div class="header-meta" role="status" aria-live="polite">
    Updated {_h(gen_fmt)}
  </div>
</header>"""


# ---------------------------------------------------------------------------
# Tab bar
# ---------------------------------------------------------------------------

def _tab_bar() -> str:
    tabs = [
        ("home",      "Home"),
        ("calling",   "Cold Calling"),
        ("outreach",  "Email & LinkedIn"),
        ("companies", "Companies"),
        ("experiments","Experiments"),
    ]
    buttons = ""
    for i, (tid, label) in enumerate(tabs):
        selected = "true" if i == 0 else "false"
        buttons += f"""
    <button class="tab-btn{'  active' if i == 0 else ''}"
            role="tab"
            id="tab-btn-{tid}"
            data-tab="{tid}"
            aria-controls="tab-{tid}"
            aria-selected="{selected}"
            onclick="switchTab('{tid}')"
            tabindex="{'0' if i == 0 else '-1'}"
    >{_h(label)}</button>"""
    return f"""
<div class="tab-bar-wrap">
  <div class="tab-bar" role="tablist" aria-label="Dashboard sections">
    {buttons}
  </div>
</div>"""


# ---------------------------------------------------------------------------
# Tab 1: Home
# ---------------------------------------------------------------------------

def _tab_home(data: dict) -> str:
    ov = data.get("overview", {})
    tw = ov.get("this_week", {})
    wow = ov.get("wow_deltas", {})
    insights = data.get("insights", [])

    # KPI cards
    def kpi(value, label, delta_key, suffix=""):
        raw_delta = wow.get(delta_key, 0)
        delta_html = _fmt_delta(raw_delta, suffix)
        return f"""
    <div class="kpi-card" role="article" aria-label="{_h(label)}: {_h(value)}">
      <div class="kpi-value" aria-hidden="true">{_h(value)}</div>
      <div class="kpi-label">{_h(label)}</div>
      <div class="kpi-delta" aria-label="Week over week change">{delta_html}</div>
    </div>"""

    dials       = tw.get("dials", 0)
    cr          = f"{tw.get('contact_rate', 0):.1f}%"
    meetings    = tw.get("meetings_booked", 0)
    inmails     = tw.get("inmails_sent", 0)
    inmail_rr   = f"{tw.get('inmail_reply_rate', 0):.1f}%"
    total_cos   = ov.get("total_companies", 0)

    kpi_html = f"""
  <section aria-labelledby="home-kpis-heading">
    <h2 class="section-heading" id="home-kpis-heading">
      <span class="sh-icon" aria-hidden="true">📊</span> This Week
    </h2>
    <div class="kpi-grid">
      {kpi(dials, "Total Dials", "dials")}
      {kpi(cr, "Contact Rate", "contact_rate", "")}
      {kpi(meetings, "Meetings Booked", "meetings_booked")}
      {kpi(inmails, "InMails Sent", "")}
      {kpi(inmail_rr, "InMail Reply Rate", "inmail_reply_rate", "")}
      {kpi(total_cos, "Total Companies", "")}
    </div>
  </section>"""

    # Insight cards
    type_icons = {
        "action_required": "🔔",
        "alert":           "⚠️",
        "win":             "🏆",
        "experiment":      "🧪",
        "coaching":        "💡",
        "strategic":       "🧭",
    }
    insight_cards = ""
    for ins in insights[:12]:
        ins_type = ins.get("type", "strategic")
        icon = type_icons.get(ins_type, "💬")
        co_tag = f'<span class="insight-tag">{_h(ins["company_name"])}</span>' if ins.get("company_name") else ""
        ch_tag = f'<span class="insight-tag">{_h(ins["channel"])}</span>' if ins.get("channel") else ""
        insight_cards += f"""
      <article class="insight-card type-{_h(ins_type)}" role="article">
        <div class="insight-header">
          <span class="insight-type-badge type-{_h(ins_type)}" aria-hidden="true">{_h(icon)} {_h(ins_type.replace("_"," "))}</span>
          <span class="insight-severity">{_h(ins.get("severity",""))}</span>
        </div>
        <div class="insight-title">{_h(ins.get("title",""))}</div>
        <div class="insight-body">{_h(ins.get("body",""))}</div>
        <div class="insight-meta">{co_tag}{ch_tag}</div>
      </article>"""

    if not insight_cards:
        insight_cards = '<div class="empty-state"><div class="empty-icon" aria-hidden="true">💡</div><p>No insights yet. They will appear here once the advisor runs.</p></div>'

    insights_html = f"""
  <section aria-labelledby="home-insights-heading">
    <h2 class="section-heading" id="home-insights-heading">
      <span class="sh-icon" aria-hidden="true">💡</span> Advisor Insights
    </h2>
    <div class="insights-grid" aria-live="polite">
      {insight_cards}
    </div>
  </section>"""

    # Channel comparison
    call_trends = data.get("call_trends", [])
    inmail_trends = data.get("inmail_trends", [])
    latest_call = call_trends[-1] if call_trends else {}
    latest_li   = inmail_trends[-1] if inmail_trends else {}

    inmail_stats = data.get("inmail_stats", {})
    email_seqs = data.get("email_sequences", [])

    ch_calls_metric = f"{latest_call.get('dials', 0)} dials"
    ch_calls_sub    = f"{latest_call.get('contact_rate', 0):.1f}% contact rate"
    ch_li_metric    = f"{latest_li.get('sent', 0)} sent"
    ch_li_sub       = f"{latest_li.get('reply_rate', 0):.1f}% reply rate"
    total_email_sent = sum(s.get("sent", 0) for s in email_seqs)
    ch_email_metric = f"{total_email_sent} sent" if total_email_sent else "—"
    ch_email_sub    = "Not connected" if not email_seqs else f"{len(email_seqs)} sequences"

    channel_html = f"""
  <section aria-labelledby="home-channels-heading">
    <h2 class="section-heading" id="home-channels-heading">
      <span class="sh-icon" aria-hidden="true">📡</span> Channels This Week
    </h2>
    <div class="channel-grid">
      <div class="channel-card" role="article" aria-label="Cold calls">
        <div class="channel-icon" aria-hidden="true">📞</div>
        <div class="channel-name">Cold Calls</div>
        <div class="channel-main-metric">{_h(ch_calls_metric)}</div>
        <div class="channel-sub-metric">{_h(ch_calls_sub)}</div>
      </div>
      <div class="channel-card" role="article" aria-label="Email">
        <div class="channel-icon" aria-hidden="true">✉️</div>
        <div class="channel-name">Email</div>
        <div class="channel-main-metric">{_h(ch_email_metric)}</div>
        <div class="channel-sub-metric">{_h(ch_email_sub)}</div>
      </div>
      <div class="channel-card" role="article" aria-label="LinkedIn">
        <div class="channel-icon" aria-hidden="true">💼</div>
        <div class="channel-name">LinkedIn</div>
        <div class="channel-main-metric">{_h(ch_li_metric)}</div>
        <div class="channel-sub-metric">{_h(ch_li_sub)}</div>
      </div>
    </div>
  </section>"""

    return f"""
<section id="tab-home"
         class="tab-panel active app-wrapper"
         role="tabpanel"
         aria-labelledby="tab-btn-home"
         aria-hidden="false">
  {kpi_html}
  {insights_html}
  {channel_html}
</section>"""


# ---------------------------------------------------------------------------
# Tab 2: Cold Calling
# ---------------------------------------------------------------------------

def _tab_calling(data: dict) -> str:
    call_log = data.get("call_log", [])

    # Category breakdown table
    cats = data.get("call_categories", {})
    cat_dict = cats.get("categories", {}) if isinstance(cats, dict) else {}
    total_calls = cats.get("total", sum(cat_dict.values())) if isinstance(cats, dict) else sum(cat_dict.values())
    cat_rows = ""
    for cat, cnt in sorted(cat_dict.items(), key=lambda x: -x[1])[:15]:
        pct = (cnt / total_calls * 100) if total_calls else 0
        cat_rows += f"""
          <tr>
            <td>{_h(cat)}</td>
            <td style="font-variant-numeric:tabular-nums">{_h(cnt)}</td>
            <td>
              <div style="display:flex;align-items:center;gap:.5rem;">
                <div style="flex:1;height:6px;background:var(--border);border-radius:3px;overflow:hidden;">
                  <div style="width:{pct:.1f}%;height:100%;background:var(--accent-blue);border-radius:3px;"></div>
                </div>
                <span style="color:var(--text-muted);font-size:.7rem;min-width:35px;text-align:right">{pct:.1f}%</span>
              </div>
            </td>
          </tr>"""

    cat_section = f"""
  <section aria-labelledby="calling-cats-heading">
    <h2 class="section-heading" id="calling-cats-heading">
      <span class="sh-icon" aria-hidden="true">📋</span> Category Breakdown
      <span style="margin-left:auto;font-size:.75rem;color:var(--text-muted);font-weight:400">{total_calls} total calls</span>
    </h2>
    <div class="card" style="margin-bottom:1.5rem;">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;">
        <div>
          <div class="table-wrap" style="margin-bottom:0;">
            <table>
              <thead><tr><th>Category</th><th>Count</th><th>Share</th></tr></thead>
              <tbody id="cat-table-body">{cat_rows}</tbody>
            </table>
          </div>
        </div>
        <div>
          <div class="chart-container" style="height:280px;">
            <canvas id="category-donut-chart" aria-label="Category distribution donut chart" role="img"></canvas>
          </div>
        </div>
      </div>
    </div>
  </section>"""

    # Call log table
    log_rows = ""
    for call in call_log[:50]:
        dur = _fmt_dur(call.get("duration_s", 0))
        summary = (call.get("summary") or "").replace("\n", " ").strip()[:200]
        summary_full = (call.get("summary") or "").strip()
        intel = call.get("intel") or {}

        # Inline detail content
        detail_parts = []
        if summary_full:
            detail_parts.append(f"<strong>Summary:</strong> {_h(summary_full)}")
        if intel.get("key_quote"):
            detail_parts.append(f'<em>"{_h(intel["key_quote"])}"</em>')
        if intel.get("next_action"):
            detail_parts.append(f"<strong>Next action:</strong> {_h(intel['next_action'])}")
        if intel.get("referral_name"):
            detail_parts.append(f"<strong>Referral:</strong> {_h(intel['referral_name'])} ({_h(intel.get('referral_role',''))})")
        if intel.get("commodities"):
            detail_parts.append(f"<strong>Commodities:</strong> {_h(intel['commodities'])}")
        detail_inner = " &nbsp;·&nbsp; ".join(detail_parts) if detail_parts else "No detail available."
        has_detail = bool(detail_parts)

        date_str = str(call.get("called_at") or call.get("date") or "")[:10]
        category = call.get("category", "")
        contact = call.get("contact_name", "—")
        company = call.get("company_name", "") or "—"
        call_id = _h(str(call.get("id", "")))

        if has_detail:
            log_rows += f"""
          <tr class="expandable-row"
              onclick="toggleCallRow(this)"
              onkeydown="if(event.key==='Enter'||event.key===' '){{event.preventDefault();toggleCallRow(this);}}"
              tabindex="0"
              aria-expanded="false"
              data-call-id="{call_id}"
              role="row">
            <td>{_h(date_str)}</td>
            <td>{_h(contact)}</td>
            <td>{_h(company)}</td>
            <td><span class="badge badge-{_h(category.lower().replace(' ','_'))}" style="font-size:.6rem">{_h(category)}</span></td>
            <td style="font-variant-numeric:tabular-nums">{_h(dur)}</td>
            <td style="color:var(--text-secondary);max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{_h(summary[:80] + ('…' if len(summary)>80 else ''))}</td>
          </tr>
          <tr class="detail-row" id="detail-{call_id}" style="display:none">
            <td colspan="6" class="row-detail">
              <div class="row-detail-inner">{detail_inner}</div>
            </td>
          </tr>"""
        else:
            log_rows += f"""
          <tr>
            <td>{_h(date_str)}</td>
            <td>{_h(contact)}</td>
            <td>{_h(company)}</td>
            <td><span class="badge" style="font-size:.6rem">{_h(category)}</span></td>
            <td style="font-variant-numeric:tabular-nums">{_h(dur)}</td>
            <td style="color:var(--text-secondary)">{_h(summary[:80])}</td>
          </tr>"""

    # Unique categories for filter
    all_cats = sorted(set(c.get("category", "") for c in call_log if c.get("category")))
    cat_options = '<option value="">All categories</option>'
    for c in all_cats:
        cat_options += f'<option value="{_h(c)}">{_h(c)}</option>'

    log_section = f"""
  <section aria-labelledby="calling-log-heading">
    <h2 class="section-heading" id="calling-log-heading">
      <span class="sh-icon" aria-hidden="true">📝</span> Call Log
      <span style="margin-left:auto;font-size:.75rem;color:var(--text-muted);font-weight:400"
            id="call-log-count">{len(call_log)} calls</span>
    </h2>
    <div class="filter-bar">
      <input type="search" id="call-search" placeholder="Search contact or company…"
             aria-label="Search calls by contact or company name"
             oninput="filterCallLog()">
      <select id="call-cat-filter" aria-label="Filter by category" onchange="filterCallLog()">
        {cat_options}
      </select>
    </div>
    <div class="table-wrap">
      <table aria-label="Call log">
        <thead>
          <tr>
            <th scope="col">Date</th>
            <th scope="col">Contact</th>
            <th scope="col">Company</th>
            <th scope="col">Category</th>
            <th scope="col">Duration</th>
            <th scope="col">Summary</th>
          </tr>
        </thead>
        <tbody id="call-log-body">
          {log_rows}
        </tbody>
      </table>
    </div>
    <div class="pagination" id="call-log-pagination" aria-label="Call log pagination">
      <span class="pagination-info" id="call-log-page-info"></span>
      <div class="pagination-controls" role="group" aria-label="Page navigation">
        <button class="page-btn" id="call-prev-btn" onclick="callLogPage(-1)" aria-label="Previous page">&#8249;</button>
        <span id="call-page-btns" style="display:flex;gap:.35rem;"></span>
        <button class="page-btn" id="call-next-btn" onclick="callLogPage(1)" aria-label="Next page">&#8250;</button>
      </div>
    </div>
  </section>"""

    # Intel highlights
    intel_list = data.get("call_intel", [])
    intel_cards = ""
    for item in intel_list[:8]:
        il = item.get("interest_level", "none")
        quote = item.get("key_quote", "")
        next_action = item.get("next_action", "")
        referral = item.get("referral_name", "")
        intel_cards += f"""
      <article class="intel-card" role="article">
        <div class="intel-card-header">
          <span class="intel-company">{_h(item.get("company",""))}</span>
          <span class="badge badge-{_h(il)}">{_h(il)}</span>
        </div>
        <div class="intel-contact">{_h(item.get("contact",""))}</div>
        {f'<div class="intel-quote">&ldquo;{_h(quote)}&rdquo;</div>' if quote else ''}
        {f'<div class="intel-action"><strong>Next:</strong> {_h(next_action)}</div>' if next_action else ''}
        {f'<div class="intel-action" style="margin-top:.25rem;">Referral: <strong>{_h(referral)}</strong></div>' if referral else ''}
      </article>"""

    intel_section = ""
    if intel_cards:
        intel_section = f"""
  <section aria-labelledby="calling-intel-heading">
    <h2 class="section-heading" id="calling-intel-heading">
      <span class="sh-icon" aria-hidden="true">🎯</span> Intel Highlights
    </h2>
    <div class="intel-grid">{intel_cards}</div>
  </section>"""

    return f"""
<section id="tab-calling"
         class="tab-panel app-wrapper"
         role="tabpanel"
         aria-labelledby="tab-btn-calling"
         aria-hidden="true">

  <section aria-labelledby="calling-trends-heading">
    <h2 class="section-heading" id="calling-trends-heading">
      <span class="sh-icon" aria-hidden="true">📈</span> Weekly Calling Trends
    </h2>
    <div class="card chart-card">
      <div class="chart-container">
        <canvas id="calling-trends-chart" aria-label="Weekly calling trends chart" role="img"></canvas>
      </div>
    </div>
  </section>

  {cat_section}
  {log_section}
  {intel_section}
</section>"""


# ---------------------------------------------------------------------------
# Tab 3: Email & LinkedIn
# ---------------------------------------------------------------------------

def _tab_outreach(data: dict) -> str:
    inmails = data.get("inmails", [])
    inmail_stats = data.get("inmail_stats", {})
    email_seqs = data.get("email_sequences", [])

    # Stats row
    total_sent    = inmail_stats.get("total_sent", 0)
    total_replied = inmail_stats.get("total_replied", 0)
    reply_rate    = inmail_stats.get("reply_rate", 0)
    if isinstance(reply_rate, float) and reply_rate <= 1:
        rr_pct = f"{reply_rate*100:.1f}%"
    else:
        rr_pct = f"{reply_rate:.1f}%"

    sentiments = inmail_stats.get("sentiment_breakdown", {})

    stats_html = f"""
  <section aria-labelledby="outreach-stats-heading">
    <h2 class="section-heading" id="outreach-stats-heading">
      <span class="sh-icon" aria-hidden="true">💼</span> LinkedIn InMail Stats
    </h2>
    <div class="kpi-grid" style="margin-bottom:1rem;">
      <div class="kpi-card">
        <div class="kpi-value">{total_sent}</div>
        <div class="kpi-label">Total Sent</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">{total_replied}</div>
        <div class="kpi-label">Replied</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">{rr_pct}</div>
        <div class="kpi-label">Reply Rate</div>
      </div>
    </div>
    <div class="card" style="margin-bottom:1.5rem;">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;align-items:center;">
        <div>
          <div class="section-heading" style="margin-bottom:.75rem;font-size:.875rem;">Sentiment Breakdown</div>"""

    for sent, cnt in sentiments.items():
        pct = (cnt / total_replied * 100) if total_replied else 0
        stats_html += f"""
          <div style="display:flex;align-items:center;gap:.75rem;margin-bottom:.5rem;">
            <span style="min-width:100px;color:var(--text-secondary);font-size:.8rem;">{_h(sent.replace('_',' ').title())}</span>
            <div style="flex:1;height:6px;background:var(--border);border-radius:3px;overflow:hidden;">
              <div style="width:{pct:.1f}%;height:100%;background:var(--accent-blue);border-radius:3px;"></div>
            </div>
            <span style="color:var(--text-muted);font-size:.75rem;min-width:30px;text-align:right">{cnt}</span>
          </div>"""

    stats_html += """
        </div>
        <div>
          <div class="chart-container" style="height:220px;">
            <canvas id="sentiment-donut-chart" aria-label="InMail sentiment breakdown" role="img"></canvas>
          </div>
        </div>
      </div>
    </div>
  </section>"""

    # InMail trends chart
    trends_html = f"""
  <section aria-labelledby="outreach-trends-heading">
    <h2 class="section-heading" id="outreach-trends-heading">
      <span class="sh-icon" aria-hidden="true">📈</span> InMail Weekly Trends
    </h2>
    <div class="card chart-card">
      <div class="chart-container">
        <canvas id="inmail-trends-chart" aria-label="Weekly InMail trends chart" role="img"></canvas>
      </div>
    </div>
  </section>"""

    # InMail table
    all_sentiments = sorted(set(im.get("reply_sentiment", "") or "" for im in inmails if im.get("reply_sentiment")))
    sent_options = '<option value="">All sentiments</option>'
    for s in all_sentiments:
        sent_options += f'<option value="{_h(s)}">{_h(s.replace("_"," ").title())}</option>'

    inmail_rows = ""
    for im in inmails:
        sent = im.get("reply_sentiment") or ""
        sent_badge = f'<span class="badge badge-{_h(sent.replace("-","_"))}">{_h(sent.replace("_"," ").title() if sent else "—")}</span>'
        replied_icon = '✓' if im.get("replied") else '—'
        replied_color = "var(--accent-green)" if im.get("replied") else "var(--text-muted)"
        inmail_rows += f"""
        <tr data-sentiment="{_h(sent)}">
          <td>{_h(str(im.get("sent_date","") or "")[:10])}</td>
          <td>{_h(im.get("contact_name",""))}</td>
          <td style="color:var(--text-secondary);font-size:.75rem">{_h(im.get("contact_title",""))}</td>
          <td>{_h(im.get("company_name",""))}</td>
          <td style="color:{replied_color};text-align:center">{replied_icon}</td>
          <td>{sent_badge}</td>
        </tr>"""

    inmail_table_html = f"""
  <section aria-labelledby="outreach-inmail-table-heading">
    <h2 class="section-heading" id="outreach-inmail-table-heading">
      <span class="sh-icon" aria-hidden="true">📨</span> InMail Log
      <span style="margin-left:auto;font-size:.75rem;color:var(--text-muted);font-weight:400">{len(inmails)} records</span>
    </h2>
    <div class="filter-bar">
      <select id="inmail-sent-filter" aria-label="Filter by sentiment" onchange="filterInmailTable()">
        {sent_options}
      </select>
    </div>
    <div class="table-wrap">
      <table aria-label="InMail log">
        <thead>
          <tr>
            <th scope="col">Date</th>
            <th scope="col">Recipient</th>
            <th scope="col">Title</th>
            <th scope="col">Company</th>
            <th scope="col" style="text-align:center">Replied</th>
            <th scope="col">Sentiment</th>
          </tr>
        </thead>
        <tbody id="inmail-table-body">
          {inmail_rows}
        </tbody>
      </table>
    </div>
    <div id="inmail-page-controls" class="page-controls" aria-live="polite"></div>
  </section>"""

    # Email sequences
    if email_seqs:
        seq_rows = ""
        for seq in email_seqs:
            or_ = seq.get("open_rate", 0)
            rr_ = seq.get("reply_rate", 0)
            seq_rows += f"""
        <tr>
          <td>{_h(seq.get("name",""))}</td>
          <td>{_h(seq.get("status",""))}</td>
          <td style="font-variant-numeric:tabular-nums">{_h(seq.get("sent",0))}</td>
          <td style="font-variant-numeric:tabular-nums">{_h(seq.get("opened",0))} <span style="color:var(--text-muted)">({or_:.1f}%)</span></td>
          <td style="font-variant-numeric:tabular-nums">{_h(seq.get("replied",0))} <span style="color:var(--text-muted)">({rr_:.1f}%)</span></td>
          <td style="color:var(--text-muted);font-size:.75rem">{_h(str(seq.get("snapshot_date",""))[:10])}</td>
        </tr>"""
        email_section = f"""
  <section aria-labelledby="outreach-email-heading">
    <h2 class="section-heading" id="outreach-email-heading">
      <span class="sh-icon" aria-hidden="true">✉️</span> Email Sequences
    </h2>
    <div class="table-wrap">
      <table aria-label="Email sequences">
        <thead>
          <tr>
            <th scope="col">Sequence</th>
            <th scope="col">Status</th>
            <th scope="col">Sent</th>
            <th scope="col">Opened</th>
            <th scope="col">Replied</th>
            <th scope="col">Snapshot</th>
          </tr>
        </thead>
        <tbody>{seq_rows}</tbody>
      </table>
    </div>
  </section>"""
    else:
        email_section = f"""
  <section aria-labelledby="outreach-email-heading">
    <h2 class="section-heading" id="outreach-email-heading">
      <span class="sh-icon" aria-hidden="true">✉️</span> Email Sequences
    </h2>
    <div class="card">
      <div class="empty-state">
        <div class="empty-icon" aria-hidden="true">✉️</div>
        <p>Email tracking not connected yet. Connect Apollo to see sequence performance.</p>
      </div>
    </div>
  </section>"""

    return f"""
<section id="tab-outreach"
         class="tab-panel app-wrapper"
         role="tabpanel"
         aria-labelledby="tab-btn-outreach"
         aria-hidden="true">
  {trends_html}
  {stats_html}
  {inmail_table_html}
  {email_section}
</section>"""


# ---------------------------------------------------------------------------
# Tab 4: Companies
# ---------------------------------------------------------------------------

def _tab_companies(data: dict) -> str:
    companies = data.get("companies", [])

    all_statuses = sorted(set(c.get("status", "prospect") for c in companies))
    status_options = '<option value="">All statuses</option>'
    for s in all_statuses:
        status_options += f'<option value="{_h(s)}">{_h(s.replace("_"," ").title())}</option>'

    all_channels = ["calls", "linkedin", "email"]
    ch_options = '<option value="">All channels</option>'
    for c in all_channels:
        ch_options += f'<option value="{_h(c)}">{_h(c.title())}</option>'

    cards = ""
    for co in companies[:120]:
        name = co.get("name", "")
        status = co.get("status", "prospect")
        channels = co.get("channels_touched") or co.get("channels") or []
        touches = co.get("total_touches", 0) or co.get("total_touches", 0)
        last_touch = str(co.get("last_touch_at") or co.get("last_touch") or "")[:10]
        intel = co.get("latest_intel")
        call_count = co.get("call_count", 0)
        inmail_count = co.get("inmail_count", 0)
        co_id = str(co.get("id", name))

        ch_badges = ""
        for ch in channels:
            ch_badges += f'<span class="channel-badge ch-{_h(ch)}">{_h(ch)}</span>'

        intel_html = ""
        if intel:
            il = intel.get("interest_level", "none")
            next_a = intel.get("next_action", "")
            intel_html = f"""
          <div class="company-intel-summary">
            <span class="badge badge-{_h(il)}" style="margin-right:.4rem;">{_h(il)}</span>
            {_h(next_a[:80]) if next_a else ""}
          </div>"""

        # Recent activity items
        activity_html = ""
        for call in (co.get("calls") or [])[:3]:
            cat = call.get("category", "")
            dt = str(call.get("called_at") or "")[:10]
            activity_html += f'<div class="company-activity-item"><span class="company-activity-date">{_h(dt)}</span><span>📞 {_h(cat)}</span></div>'
        for im in (co.get("inmails") or [])[:2]:
            dt = str(im.get("sent_date") or "")[:10]
            sent_label = im.get("reply_sentiment") or ("Replied" if im.get("replied") else "Sent")
            activity_html += f'<div class="company-activity-item"><span class="company-activity-date">{_h(dt)}</span><span>💼 InMail — {_h(str(sent_label))}</span></div>'

        # Channel list for filtering
        ch_list_str = " ".join(channels)
        safe_id = _h(co_id.replace(" ", "_"))

        cards += f"""
      <article class="company-card"
               role="button"
               tabindex="0"
               aria-expanded="false"
               data-status="{_h(status)}"
               data-channels="{_h(ch_list_str)}"
               data-name="{_h(name.lower())}"
               onclick="toggleCompanyCard(this)"
               onkeydown="if(event.key==='Enter'||event.key===' '){{event.preventDefault();toggleCompanyCard(this);}}">
        <div class="company-card-header">
          <span class="company-name">{_h(name)}</span>
          <span class="badge badge-{_h(status)}">{_h(status.replace('_',' ').title())}</span>
        </div>
        <div class="company-channels">{ch_badges}</div>
        <div class="company-meta">
          <span>{touches} touches</span>
          {f'<span>Last: {_h(last_touch)}</span>' if last_touch else ''}
          {f'<span>{call_count} calls</span>' if call_count else ''}
          {f'<span>{inmail_count} inmails</span>' if inmail_count else ''}
        </div>
        {intel_html}
        <div class="company-detail" id="co-detail-{safe_id}">
          {activity_html if activity_html else '<div style="color:var(--text-muted);font-size:.75rem;">No activity details available.</div>'}
        </div>
      </article>"""

    if not cards:
        cards = '<div class="empty-state"><div class="empty-icon" aria-hidden="true">🏢</div><p>No companies found. They will appear once call or LinkedIn data is synced.</p></div>'

    return f"""
<section id="tab-companies"
         class="tab-panel app-wrapper"
         role="tabpanel"
         aria-labelledby="tab-btn-companies"
         aria-hidden="true">

  <section aria-labelledby="companies-heading">
    <h2 class="section-heading" id="companies-heading">
      <span class="sh-icon" aria-hidden="true">🏢</span> Companies
      <span style="margin-left:auto;font-size:.75rem;color:var(--text-muted);font-weight:400"
            id="companies-count">{len(companies)} total</span>
    </h2>

    <div class="filter-bar">
      <input type="search" id="company-search" placeholder="Search by company name…"
             aria-label="Search companies by name"
             oninput="filterCompanies()">
      <select id="company-status-filter" aria-label="Filter by status" onchange="filterCompanies()">
        {status_options}
      </select>
      <select id="company-channel-filter" aria-label="Filter by channel" onchange="filterCompanies()">
        {ch_options}
      </select>
    </div>

    <div class="company-grid" id="company-grid" aria-live="polite">
      {cards}
    </div>

    <div class="pagination" id="company-pagination" aria-label="Company pagination">
      <span class="pagination-info" id="company-page-info"></span>
      <div class="pagination-controls" role="group" aria-label="Company page navigation">
        <button class="page-btn" id="co-prev-btn" onclick="companyPage(-1)" aria-label="Previous page">&#8249;</button>
        <span id="co-page-btns" style="display:flex;gap:.35rem;"></span>
        <button class="page-btn" id="co-next-btn" onclick="companyPage(1)" aria-label="Next page">&#8250;</button>
      </div>
    </div>
  </section>
</section>"""


# ---------------------------------------------------------------------------
# Tab 5: Experiments
# ---------------------------------------------------------------------------

def _tab_experiments(data: dict) -> str:
    experiments = data.get("experiments", [])
    insights = data.get("insights", [])
    exp_insights = [i for i in insights if i.get("type") == "experiment"]

    if not experiments:
        exp_section = """
  <div class="card">
    <div class="empty-state">
      <div class="empty-icon" aria-hidden="true">🧪</div>
      <p>No experiments tracked yet. Experiments are auto-detected from your outreach patterns,
         or you can add them manually in Supabase.</p>
    </div>
  </div>"""
    else:
        exp_cards = ""
        for exp in experiments:
            status = exp.get("status", "active")
            start = str(exp.get("start_date") or "")[:10]
            end   = str(exp.get("end_date") or "")[:10]
            date_range = f"{start}" + (f" — {end}" if end else "")
            result = exp.get("result_summary") or ""
            exp_cards += f"""
      <article class="experiment-card" role="article">
        <div class="experiment-header">
          <span class="experiment-name">{_h(exp.get("name",""))}</span>
          <span class="badge badge-{_h(status)}">{_h(status.title())}</span>
        </div>
        {f'<div class="experiment-hypothesis">{_h(exp.get("hypothesis",""))}</div>' if exp.get("hypothesis") else ''}
        <div class="experiment-meta">
          {f'<span class="experiment-meta-item">📡 {_h(exp.get("channel",""))}</span>' if exp.get("channel") else ''}
          {f'<span class="experiment-meta-item">📅 {_h(date_range)}</span>' if date_range else ''}
          {f'<span class="experiment-meta-item">📊 {_h(exp.get("metric",""))}</span>' if exp.get("metric") else ''}
        </div>
        {f'<div class="experiment-result"><strong>Result:</strong> {_h(result)}</div>' if result else ''}
      </article>"""
        exp_section = exp_cards

    insight_cards = ""
    for ins in exp_insights[:6]:
        insight_cards += f"""
      <article class="insight-card type-experiment" role="article">
        <div class="insight-header">
          <span class="insight-type-badge type-experiment">🧪 Experiment</span>
          <span class="insight-severity">{_h(ins.get("severity",""))}</span>
        </div>
        <div class="insight-title">{_h(ins.get("title",""))}</div>
        <div class="insight-body">{_h(ins.get("body",""))}</div>
      </article>"""

    exp_insights_section = ""
    if insight_cards:
        exp_insights_section = f"""
  <section aria-labelledby="exp-insights-heading">
    <h2 class="section-heading" id="exp-insights-heading">
      <span class="sh-icon" aria-hidden="true">💡</span> Experiment Advisor Notes
    </h2>
    <div class="insights-grid">{insight_cards}</div>
  </section>"""

    return f"""
<section id="tab-experiments"
         class="tab-panel app-wrapper"
         role="tabpanel"
         aria-labelledby="tab-btn-experiments"
         aria-hidden="true">

  <section aria-labelledby="experiments-heading">
    <h2 class="section-heading" id="experiments-heading">
      <span class="sh-icon" aria-hidden="true">🧪</span> Experiments
    </h2>
    {exp_section}
  </section>
  {exp_insights_section}
</section>"""


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

def _footer(data: dict) -> str:
    gen = data.get("generated_at", "")
    return f"""
<footer class="app-footer app-wrapper" role="contentinfo">
  <span>Telegraph Outbound Central</span>
  <span>Generated {_h(str(gen)[:19])}</span>
</footer>"""


# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------

def _scripts(data: dict) -> str:
    call_trends    = data.get("call_trends", [])
    inmail_trends  = data.get("inmail_trends", [])
    call_cats      = data.get("call_categories", {})
    inmail_stats   = data.get("inmail_stats", {})
    call_log       = data.get("call_log", [])
    companies      = data.get("companies", [])

    # Serialize data subsets
    call_trends_json  = _j(call_trends)
    inmail_trends_json = _j(inmail_trends)
    call_log_json     = _j(call_log)
    companies_json    = _j(companies)

    # Category chart data
    cat_dict = call_cats.get("categories", {}) if isinstance(call_cats, dict) else {}
    cat_labels = _j(list(cat_dict.keys()))
    cat_values = _j(list(cat_dict.values()))

    # Sentiment chart data
    sentiments = inmail_stats.get("sentiment_breakdown", {})
    sent_labels = _j(list(sentiments.keys()))
    sent_values = _j(list(sentiments.values()))

    return f"""
<script>
// ============================================================
// Embedded data
// ============================================================
const CALL_TRENDS   = {call_trends_json};
const INMAIL_TRENDS = {inmail_trends_json};
const CALL_LOG_DATA = {call_log_json};
const COMPANIES_DATA = {companies_json};

// ============================================================
// Tab switching
// ============================================================
let callingChartsRendered  = false;
let outreachChartsRendered = false;

function switchTab(tabId) {{
  document.querySelectorAll('.tab-panel').forEach(function(p) {{
    p.classList.remove('active');
    p.setAttribute('aria-hidden', 'true');
  }});
  document.querySelectorAll('.tab-btn').forEach(function(b) {{
    b.classList.remove('active');
    b.setAttribute('aria-selected', 'false');
    b.setAttribute('tabindex', '-1');
  }});
  var panel = document.getElementById('tab-' + tabId);
  var btn   = document.querySelector('[data-tab="' + tabId + '"]');
  if (panel) {{ panel.classList.add('active'); panel.setAttribute('aria-hidden', 'false'); }}
  if (btn)   {{ btn.classList.add('active'); btn.setAttribute('aria-selected', 'true'); btn.setAttribute('tabindex', '0'); }}

  // Lazy chart init
  if (tabId === 'calling'  && !callingChartsRendered)  initCallingCharts();
  if (tabId === 'outreach' && !outreachChartsRendered) initOutreachCharts();

  // Update URL hash
  history.replaceState(null, '', '#' + tabId);
}}

// Tab keyboard nav (arrow keys)
document.addEventListener('keydown', function(e) {{
  if (!e.target.classList.contains('tab-btn')) return;
  var tabs = Array.from(document.querySelectorAll('.tab-btn'));
  var idx  = tabs.indexOf(e.target);
  if (e.key === 'ArrowRight' && idx < tabs.length - 1) {{ tabs[idx+1].focus(); tabs[idx+1].click(); }}
  if (e.key === 'ArrowLeft'  && idx > 0)               {{ tabs[idx-1].focus(); tabs[idx-1].click(); }}
  if (e.key === 'Home') {{ tabs[0].focus(); tabs[0].click(); }}
  if (e.key === 'End')  {{ tabs[tabs.length-1].focus(); tabs[tabs.length-1].click(); }}
}});

// Hash routing
(function() {{
  function applyHash() {{
    var hash = location.hash.replace('#', '');
    if (hash && document.getElementById('tab-' + hash)) switchTab(hash);
  }}
  setTimeout(applyHash, 0);
  window.addEventListener('hashchange', applyHash);
}})();


// ============================================================
// Chart.js helpers
// ============================================================
function chartDefaults() {{
  return {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{
      legend: {{
        labels: {{ color: '#9aa0b4', font: {{ size: 11, family: "'Inter', sans-serif" }} }}
      }},
      tooltip: {{
        backgroundColor: '#222633',
        borderColor: '#2d3348',
        borderWidth: 1,
        titleColor: '#e8eaed',
        bodyColor: '#9aa0b4',
      }}
    }},
    scales: {{
      x: {{
        ticks: {{ color: '#9aa0b4', font: {{ size: 10 }} }},
        grid:  {{ color: '#2d3348' }}
      }},
      y: {{
        ticks: {{ color: '#9aa0b4', font: {{ size: 10 }} }},
        grid:  {{ color: '#2d3348' }}
      }}
    }}
  }};
}}

function initCallingCharts() {{
  callingChartsRendered = true;

  // --- Trends chart ---
  var trendCtx = document.getElementById('calling-trends-chart');
  if (trendCtx && CALL_TRENDS.length) {{
    var labels   = CALL_TRENDS.map(function(w) {{ return w.monday || ('Wk ' + w.week_num); }});
    var dials    = CALL_TRENDS.map(function(w) {{ return w.dials || 0; }});
    var contacts = CALL_TRENDS.map(function(w) {{ return w.contact_rate || 0; }});
    var meetings = CALL_TRENDS.map(function(w) {{ return w.meetings_booked || w.meetings || 0; }});
    var cfg = chartDefaults();
    new Chart(trendCtx, {{
      data: {{
        labels: labels,
        datasets: [
          {{
            type: 'bar', label: 'Dials', data: dials,
            backgroundColor: 'rgba(66,133,244,.4)', borderColor: 'rgba(66,133,244,.8)', borderWidth: 1,
            yAxisID: 'y',
          }},
          {{
            type: 'line', label: 'Contact Rate %', data: contacts,
            borderColor: '#34a853', backgroundColor: 'transparent',
            pointBackgroundColor: '#34a853', pointRadius: 4, tension: 0.3,
            yAxisID: 'y1',
          }},
          {{
            type: 'line', label: 'Meetings', data: meetings,
            borderColor: '#a855f7', backgroundColor: 'transparent',
            pointStyle: 'circle', pointRadius: 6, pointBackgroundColor: '#a855f7',
            tension: 0, yAxisID: 'y',
          }},
        ]
      }},
      options: Object.assign(cfg, {{
        scales: {{
          x: {{ ticks: {{ color: '#9aa0b4', font: {{ size: 10 }} }}, grid: {{ color: '#2d3348' }} }},
          y: {{
            type: 'linear', position: 'left',
            ticks: {{ color: '#9aa0b4', font: {{ size: 10 }} }},
            grid:  {{ color: '#2d3348' }},
            title: {{ display: true, text: 'Count', color: '#5a6078', font: {{ size: 10 }} }}
          }},
          y1: {{
            type: 'linear', position: 'right',
            ticks: {{ color: '#9aa0b4', font: {{ size: 10 }}, callback: function(v) {{ return v + '%'; }} }},
            grid:  {{ drawOnChartArea: false }},
            title: {{ display: true, text: 'Contact Rate %', color: '#5a6078', font: {{ size: 10 }} }}
          }}
        }}
      }})
    }});
  }}

  // --- Category donut chart ---
  var donutCtx = document.getElementById('category-donut-chart');
  var catLabels = {cat_labels};
  var catVals   = {cat_values};
  if (donutCtx && catLabels.length) {{
    var palette = ['#4285f4','#34a853','#fbbc04','#ea4335','#00c4cc','#a855f7','#f97316','#10b981','#6b7280','#ff6d00'];
    new Chart(donutCtx, {{
      type: 'doughnut',
      data: {{
        labels: catLabels,
        datasets: [{{ data: catVals, backgroundColor: palette, borderColor: '#222633', borderWidth: 2 }}]
      }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{
          legend: {{ position: 'right', labels: {{ color: '#9aa0b4', font: {{ size: 10 }}, boxWidth: 12, padding: 8 }} }},
          tooltip: {{ backgroundColor: '#222633', borderColor: '#2d3348', borderWidth: 1, titleColor: '#e8eaed', bodyColor: '#9aa0b4' }}
        }},
        cutout: '62%',
      }}
    }});
  }}
}}

function initOutreachCharts() {{
  outreachChartsRendered = true;

  // --- InMail trends chart ---
  var imCtx = document.getElementById('inmail-trends-chart');
  if (imCtx && INMAIL_TRENDS.length) {{
    var labels  = INMAIL_TRENDS.map(function(w) {{ return w.monday || ('Wk ' + w.week_num); }});
    var sent    = INMAIL_TRENDS.map(function(w) {{ return w.sent || 0; }});
    var replied = INMAIL_TRENDS.map(function(w) {{ return w.replied || 0; }});
    var rr      = INMAIL_TRENDS.map(function(w) {{ return w.reply_rate || 0; }});
    new Chart(imCtx, {{
      data: {{
        labels: labels,
        datasets: [
          {{
            type: 'bar', label: 'Sent', data: sent,
            backgroundColor: 'rgba(66,133,244,.4)', borderColor: 'rgba(66,133,244,.8)', borderWidth: 1,
            yAxisID: 'y',
          }},
          {{
            type: 'bar', label: 'Replied', data: replied,
            backgroundColor: 'rgba(52,168,83,.4)', borderColor: 'rgba(52,168,83,.8)', borderWidth: 1,
            yAxisID: 'y',
          }},
          {{
            type: 'line', label: 'Reply Rate %', data: rr,
            borderColor: '#fbbc04', backgroundColor: 'transparent',
            pointBackgroundColor: '#fbbc04', pointRadius: 4, tension: 0.3,
            yAxisID: 'y1',
          }},
        ]
      }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{
          legend: {{ labels: {{ color: '#9aa0b4', font: {{ size: 11 }} }} }},
          tooltip: {{ backgroundColor: '#222633', borderColor: '#2d3348', borderWidth: 1, titleColor: '#e8eaed', bodyColor: '#9aa0b4' }}
        }},
        scales: {{
          x: {{ ticks: {{ color: '#9aa0b4', font: {{ size: 10 }} }}, grid: {{ color: '#2d3348' }} }},
          y: {{
            type: 'linear', position: 'left',
            ticks: {{ color: '#9aa0b4', font: {{ size: 10 }} }}, grid: {{ color: '#2d3348' }},
            title: {{ display: true, text: 'Count', color: '#5a6078', font: {{ size: 10 }} }}
          }},
          y1: {{
            type: 'linear', position: 'right',
            ticks: {{ color: '#9aa0b4', font: {{ size: 10 }}, callback: function(v) {{ return v + '%'; }} }},
            grid: {{ drawOnChartArea: false }},
            title: {{ display: true, text: 'Reply Rate %', color: '#5a6078', font: {{ size: 10 }} }}
          }}
        }}
      }}
    }});
  }}

  // --- Sentiment donut ---
  var sentCtx = document.getElementById('sentiment-donut-chart');
  var sentLabels = {sent_labels};
  var sentVals   = {sent_values};
  if (sentCtx && sentLabels.length) {{
    var sentPalette = {{ interested: '#34a853', not_interested: '#ea4335', neutral: '#5a6078', ooo: '#fbbc04' }};
    var colors = sentLabels.map(function(l) {{ return sentPalette[l] || '#4285f4'; }});
    new Chart(sentCtx, {{
      type: 'doughnut',
      data: {{
        labels: sentLabels.map(function(l) {{ return l.replace(/_/g,' ').replace(/\\b\\w/g,function(c){{return c.toUpperCase();}}); }}),
        datasets: [{{ data: sentVals, backgroundColor: colors, borderColor: '#222633', borderWidth: 2 }}]
      }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{
          legend: {{ position: 'right', labels: {{ color: '#9aa0b4', font: {{ size: 10 }}, boxWidth: 12, padding: 8 }} }},
          tooltip: {{ backgroundColor: '#222633', borderColor: '#2d3348', borderWidth: 1, titleColor: '#e8eaed', bodyColor: '#9aa0b4' }}
        }},
        cutout: '60%',
      }}
    }});
  }}
}}


// ============================================================
// Call log: filter + pagination
// ============================================================
var callLogRows  = [];
var callLogPage_ = 0;
var callPageSize = 50;

function buildCallLogRows() {{
  var search = (document.getElementById('call-search').value || '').toLowerCase();
  var cat    = (document.getElementById('call-cat-filter').value || '');
  var tbody  = document.getElementById('call-log-body');
  if (!tbody) return;
  var allRows = Array.from(tbody.querySelectorAll('tr:not(.detail-row)'));
  callLogRows = allRows.filter(function(tr) {{
    var text = tr.textContent.toLowerCase();
    var matchSearch = !search || text.indexOf(search) !== -1;
    var matchCat    = !cat    || text.indexOf(cat.toLowerCase()) !== -1;
    return matchSearch && matchCat;
  }});
  callLogPage_ = 0;
  renderCallLogPage();
}}

function renderCallLogPage() {{
  var total  = callLogRows.length;
  var pages  = Math.max(1, Math.ceil(total / callPageSize));
  var start  = callLogPage_ * callPageSize;
  var end    = Math.min(start + callPageSize, total);

  var tbody = document.getElementById('call-log-body');
  if (!tbody) return;
  var allRows = Array.from(tbody.querySelectorAll('tr'));
  allRows.forEach(function(r) {{ r.style.display = 'none'; }});

  callLogRows.slice(start, end).forEach(function(tr) {{
    tr.style.display = '';
    // Also show detail row if expanded
    var callId = tr.dataset.callId;
    if (callId) {{
      var det = document.getElementById('detail-' + callId);
      if (det && tr.classList.contains('expanded')) det.style.display = '';
    }}
  }});

  var info = document.getElementById('call-log-page-info');
  if (info) info.textContent = total ? (start+1) + '–' + end + ' of ' + total : '0 results';

  // Page buttons
  var btnsEl = document.getElementById('call-page-btns');
  if (btnsEl) {{
    btnsEl.innerHTML = '';
    var maxBtns = 5;
    var startPage = Math.max(0, callLogPage_ - Math.floor(maxBtns/2));
    var endPage   = Math.min(pages, startPage + maxBtns);
    for (var p = startPage; p < endPage; p++) {{
      var btn = document.createElement('button');
      btn.className = 'page-btn' + (p === callLogPage_ ? ' active' : '');
      btn.textContent = p + 1;
      btn.setAttribute('aria-label', 'Page ' + (p+1));
      if (p === callLogPage_) btn.setAttribute('aria-current', 'page');
      (function(page) {{ btn.onclick = function() {{ callLogPage_ = page; renderCallLogPage(); }}; }})(p);
      btnsEl.appendChild(btn);
    }}
  }}

  var prev = document.getElementById('call-prev-btn');
  var next = document.getElementById('call-next-btn');
  if (prev) prev.disabled = callLogPage_ === 0;
  if (next) next.disabled = callLogPage_ >= pages - 1;
}}

function filterCallLog() {{ buildCallLogRows(); }}
function callLogPage(dir) {{
  var total = callLogRows.length;
  var pages = Math.max(1, Math.ceil(total / callPageSize));
  callLogPage_ = Math.max(0, Math.min(pages - 1, callLogPage_ + dir));
  renderCallLogPage();
}}

function toggleCallRow(tr) {{
  var callId = tr.dataset.callId;
  if (!callId) return;
  var det = document.getElementById('detail-' + callId);
  var expanded = tr.classList.toggle('expanded');
  tr.setAttribute('aria-expanded', expanded);
  if (det) det.style.display = expanded ? '' : 'none';
}}


// ============================================================
// InMail table filter + pagination
// ============================================================
var imRows = [];
var imPage_ = 0;
var imPageSize = 30;

function filterInmailTable() {{
  var filter = (document.getElementById('inmail-sent-filter').value || '').toLowerCase();
  var allRows = Array.from(document.querySelectorAll('#inmail-table-body tr'));
  imRows = allRows.filter(function(row) {{
    var sent = (row.dataset.sentiment || '').toLowerCase();
    return !filter || sent === filter;
  }});
  imPage_ = 0;
  renderImPage();
}}

function renderImPage() {{
  var allRows = Array.from(document.querySelectorAll('#inmail-table-body tr'));
  allRows.forEach(function(r) {{ r.style.display = 'none'; }});
  var start = imPage_ * imPageSize;
  var end   = start + imPageSize;
  for (var i = start; i < Math.min(end, imRows.length); i++) {{
    imRows[i].style.display = '';
  }}
  var ctrl = document.getElementById('inmail-page-controls');
  if (ctrl) {{
    var total = imRows.length;
    var pages = Math.ceil(total / imPageSize);
    ctrl.innerHTML = '<span>' + total + ' inmails</span>' +
      (imPage_ > 0 ? '<button onclick="imPage_--;renderImPage()">← Prev</button>' : '') +
      '<span>Page ' + (imPage_+1) + ' of ' + pages + '</span>' +
      (imPage_ < pages - 1 ? '<button onclick="imPage_++;renderImPage()">Next →</button>' : '');
  }}
}}

// Init on first tab view
(function() {{
  var allRows = Array.from(document.querySelectorAll('#inmail-table-body tr'));
  imRows = allRows;
  renderImPage();
}})()


// ============================================================
// Companies: filter + pagination
// ============================================================
var coVisible = [];
var coPage_   = 0;
var coPageSize = 30;

function buildCompanyCards() {{
  var search  = (document.getElementById('company-search').value || '').toLowerCase();
  var status  = (document.getElementById('company-status-filter').value || '').toLowerCase();
  var channel = (document.getElementById('company-channel-filter').value || '').toLowerCase();
  var grid    = document.getElementById('company-grid');
  if (!grid) return;

  var allCards = Array.from(grid.querySelectorAll('.company-card'));
  coVisible = allCards.filter(function(card) {{
    var name     = (card.dataset.name     || '').toLowerCase();
    var cstatus  = (card.dataset.status   || '').toLowerCase();
    var cchannels= (card.dataset.channels || '').toLowerCase();
    var mSearch  = !search  || name.indexOf(search) !== -1;
    var mStatus  = !status  || cstatus === status;
    var mChannel = !channel || cchannels.indexOf(channel) !== -1;
    return mSearch && mStatus && mChannel;
  }});
  coPage_ = 0;
  renderCompanyPage();
}}

function renderCompanyPage() {{
  var total = coVisible.length;
  var pages = Math.max(1, Math.ceil(total / coPageSize));
  var start = coPage_ * coPageSize;
  var end   = Math.min(start + coPageSize, total);

  var grid = document.getElementById('company-grid');
  if (!grid) return;
  var allCards = Array.from(grid.querySelectorAll('.company-card'));
  allCards.forEach(function(c) {{ c.style.display = 'none'; }});
  coVisible.slice(start, end).forEach(function(c) {{ c.style.display = ''; }});

  var info = document.getElementById('company-page-info');
  if (info) info.textContent = total ? (start+1) + '–' + end + ' of ' + total : '0 results';

  var btnsEl = document.getElementById('co-page-btns');
  if (btnsEl) {{
    btnsEl.innerHTML = '';
    var maxBtns = 5;
    var startPage = Math.max(0, coPage_ - Math.floor(maxBtns/2));
    var endPage   = Math.min(pages, startPage + maxBtns);
    for (var p = startPage; p < endPage; p++) {{
      var btn = document.createElement('button');
      btn.className = 'page-btn' + (p === coPage_ ? ' active' : '');
      btn.textContent = p + 1;
      btn.setAttribute('aria-label', 'Page ' + (p+1));
      if (p === coPage_) btn.setAttribute('aria-current', 'page');
      (function(page) {{ btn.onclick = function() {{ coPage_ = page; renderCompanyPage(); }}; }})(p);
      btnsEl.appendChild(btn);
    }}
  }}

  var prev = document.getElementById('co-prev-btn');
  var next = document.getElementById('co-next-btn');
  if (prev) prev.disabled = coPage_ === 0;
  if (next) next.disabled = coPage_ >= pages - 1;
}}

function filterCompanies() {{ buildCompanyCards(); }}
function companyPage(dir) {{
  var total = coVisible.length;
  var pages = Math.max(1, Math.ceil(total / coPageSize));
  coPage_ = Math.max(0, Math.min(pages - 1, coPage_ + dir));
  renderCompanyPage();
}}

function toggleCompanyCard(card) {{
  var expanded = card.getAttribute('aria-expanded') === 'true';
  card.setAttribute('aria-expanded', !expanded);
  var detailEl = card.querySelector('.company-detail');
  if (detailEl) detailEl.classList.toggle('visible', !expanded);
}}


// ============================================================
// Init on load
// ============================================================
window.addEventListener('DOMContentLoaded', function() {{
  // Init home tab charts (always visible)
  initCallingCharts();   // calling tab charts are also needed here if active
  // Init call log pagination
  var tbody = document.getElementById('call-log-body');
  if (tbody) {{
    callLogRows = Array.from(tbody.querySelectorAll('tr:not(.detail-row)'));
    renderCallLogPage();
  }}
  // Init company pagination
  buildCompanyCards();
}});
</script>"""


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_html(data: dict) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="Telegraph Outbound Central — multi-channel sales analytics dashboard">
  <title>Telegraph Outbound Central</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
  {_styles()}
</head>
<body>
  <a href="#main-content" class="skip-link">Skip to main content</a>
  {_header(data)}
  {_tab_bar()}
  <main id="main-content">
    {_tab_home(data)}
    {_tab_calling(data)}
    {_tab_outreach(data)}
    {_tab_companies(data)}
    {_tab_experiments(data)}
  </main>
  {_footer(data)}
  {_scripts(data)}
</body>
</html>"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def generate():
    print("Fetching data from Supabase...", file=sys.stderr)
    data = fetch_all()

    html = build_html(data)

    out = HERE / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"Generated {out} ({len(html):,} bytes)", file=sys.stderr)


if __name__ == "__main__":
    generate()
