#!/usr/bin/env python3
"""Dashboard V2 — Supabase-powered sales outbound dashboard.

Generates a self-contained index.html for GitHub Pages.

Usage:
    python3 dashboard_v2.py
    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... python3 dashboard_v2.py
"""

import html as _html
import json
import re as _re
import sys
from datetime import datetime, timedelta
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
    return f'<span class="{cls}">{display}</span>'


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
  --text-muted:   #8b92a0;
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
  font-size: .8rem; color: var(--text-secondary);
  margin-top: .35rem;
}
.kpi-delta { font-size: .75rem; margin-top: .5rem; color: var(--text-muted); }
.kpi-delta .delta-context { font-size: .7rem; color: var(--text-muted); }
.delta-up   { color: var(--accent-green); }
.delta-down { color: var(--text-secondary); }
.delta-neutral { color: var(--text-muted); }
.kpi-card-muted .kpi-value { color: var(--text-muted); }
.kpi-card-muted .kpi-label { color: var(--text-muted); }

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
  cursor: pointer; transition: background .2s;
}
.insight-card:hover { background: var(--bg-hover); }
.insight-card.type-action_required { border-left-color: var(--accent-orange); }
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
.insight-type-badge.type-action_required { background: rgba(249,115,22,.15); color: var(--accent-orange); }
.insight-type-badge.type-alert           { background: rgba(180,140,60,.15); color: #b8a060; }
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
.insight-chevron { font-size: .7rem; color: var(--text-muted); margin-right: .2rem; }
.show-all-btn {
  background: transparent; color: var(--accent-blue);
  border: 1px solid var(--border); padding: .5rem 1rem;
  border-radius: var(--radius); cursor: pointer;
  margin-top: .75rem; font-size: .8rem; font-family: inherit;
  transition: border-color .15s;
}
.show-all-btn:hover { border-color: var(--accent-blue); }

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
  padding: .75rem .9rem;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
}
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
.badge-do_not_contact { background: rgba(234,67,53,.25); color: var(--accent-red); }
.badge-not_interested { background: rgba(234,67,53,.15); color: var(--accent-red); }
.badge-exhausted     { background: rgba(251,188,4,.15); color: var(--accent-orange); }

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

/* ---- View toggle ---- */
.view-toggle { display:inline-flex; background:var(--bg-card); border:1px solid var(--border); border-radius:var(--radius); overflow:hidden; }
.view-toggle-btn { background:transparent; border:none; color:var(--text-muted); padding:.35rem .5rem; cursor:pointer; display:flex; align-items:center; transition:all .15s; }
.view-toggle-btn:hover { color:var(--text-primary); }
.view-toggle-btn.active { background:var(--accent-blue); color:#fff; }

/* ---- Company cards ---- */
.company-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
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
.company-card.has-renewal { border-left: 3px solid var(--accent-orange); }
.company-card.has-action { border-left: 3px solid var(--accent-blue); }
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
.company-crm-row {
  display: flex; gap: .5rem; font-size: .75rem; color: var(--text-secondary);
  margin: .25rem 0; flex-wrap: wrap; align-items: center;
}
.company-crm-row .crm-label { color: var(--text-muted); min-width: 60px; }
.company-crm-row .crm-value { color: var(--text-primary); }
.company-renewal-badge {
  font-size: .65rem; padding: .15rem .5rem; border-radius: 999px;
  background: rgba(245, 158, 11, 0.1); color: var(--accent-orange);
  border: 1px solid var(--accent-orange);
}
.company-renewal-badge.overdue {
  background: rgba(239, 68, 68, 0.1); color: var(--accent-red);
  border-color: var(--accent-red);
}
.company-next-action {
  font-size: .75rem; color: var(--accent-blue);
  margin: .35rem 0; padding: .4rem .6rem;
  background: rgba(59, 130, 246, 0.06); border-radius: var(--radius-sm);
}
.company-next-action .action-date { color: var(--text-muted); margin-left: .5rem; }
.company-detail {
  display: none; margin-top: .75rem; padding-top: .75rem;
  border-top: 1px solid var(--border);
}
.company-detail.visible { display: block; }
.company-detail-section { margin-bottom: .5rem; }
.company-detail-section-title { font-size: .65rem; text-transform: uppercase; letter-spacing: .05em; color: var(--text-muted); margin-bottom: .25rem; }
.company-activity-item {
  display: flex; gap: .5rem; font-size: .75rem; color: var(--text-secondary);
  padding: .3rem 0; border-bottom: 1px solid var(--border);
}
.company-activity-item:last-child { border-bottom: none; }
.company-activity-date { color: var(--text-muted); flex-shrink: 0; width: 75px; }
.company-notes { font-size: .75rem; color: var(--text-secondary); font-style: italic; padding: .35rem 0; }
.company-sort-bar { display: flex; gap: .5rem; margin-bottom: .5rem; align-items: center; }
.company-sort-bar label { font-size: .75rem; color: var(--text-muted); }
.company-sort-bar select { font-size: .75rem; }

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
  .pipeline-bar { flex-wrap: wrap; }
}

/* ---- Pipeline bar ---- */
.pipeline-bar {
  display: flex; align-items: stretch; gap: 0;
  margin-bottom: 1.5rem; border-radius: var(--radius);
  overflow: hidden; border: 1px solid var(--border);
  background: var(--bg-card); box-shadow: var(--shadow);
}
.pipeline-segment {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  padding: .75rem .5rem; position: relative;
  min-width: 0;
}
.pipeline-segment + .pipeline-segment {
  border-left: 1px solid var(--border);
}
.pipeline-segment .pipe-count {
  font-size: 1.5rem; font-weight: 700; line-height: 1;
  font-variant-numeric: tabular-nums;
}
.pipeline-segment .pipe-label {
  font-size: .65rem; text-transform: uppercase; letter-spacing: .05em;
  margin-top: .25rem; color: var(--text-secondary);
}
.pipeline-segment .pipe-arrow {
  position: absolute; right: -6px; top: 50%; transform: translateY(-50%);
  color: var(--text-muted); font-size: .7rem; z-index: 1;
}
.pipeline-segment.ps-prospect   .pipe-count { color: var(--text-muted); }
.pipeline-segment.ps-contacted  .pipe-count { color: var(--accent-blue); }
.pipeline-segment.ps-interested .pipe-count { color: var(--accent-teal); }
.pipeline-segment.ps-meeting    .pipe-count { color: var(--accent-purple); }

/* ---- Pipeline detail table ---- */
.pipeline-table { width: 100%; border-collapse: collapse; font-size: .82rem; }
.pipeline-table th { text-align: left; padding: .5rem .6rem; color: var(--text-muted); font-size: .72rem; text-transform: uppercase; letter-spacing: .04em; border-bottom: 2px solid var(--border); position: sticky; top: 0; background: var(--bg-card); z-index: 1; }
.pipeline-table td { padding: .45rem .6rem; border-bottom: 1px solid var(--border); vertical-align: top; }
.pipe-stage-row td { background: var(--bg-surface); }
.pipe-stage-header { font-weight: 700; font-size: .78rem; color: var(--text-primary); padding: .6rem .6rem .4rem !important; letter-spacing: .02em; }
.pipe-deal-row:hover td { background: rgba(66,133,244,.04); }
.pipe-company { font-weight: 600; color: var(--text-primary); white-space: nowrap; }
.pipe-source { color: var(--text-muted); white-space: nowrap; }
.pipe-contact { color: var(--text-secondary); }
.pipe-industry { color: var(--text-muted); font-size: .78rem; }
.pipe-next { color: var(--text-secondary); max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pipe-meeting_booked .pipe-company { color: var(--accent-purple); }
.pipe-interested .pipe-company { color: var(--accent-teal); }
.pipe-prospect .pipe-source { color: var(--accent-blue); font-weight: 600; }

/* ---- Action queue ---- */
.action-queue {
  display: flex; flex-direction: column; gap: .5rem;
  margin-bottom: 1.5rem;
}
.action-item {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: .75rem 1rem;
  box-shadow: var(--shadow); display: flex; align-items: center;
  gap: .75rem; flex-wrap: wrap;
}
.action-item:hover { border-color: var(--accent-blue); }
.action-item .ai-company {
  font-weight: 600; color: var(--text-primary); min-width: 140px;
}
.action-item .ai-action {
  flex: 1; color: var(--text-secondary); font-size: .8rem;
  min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.action-item .ai-date {
  font-size: .7rem; color: var(--text-muted); flex-shrink: 0;
}

/* ---- Week summary (compact) ---- */
.week-summary {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: .75rem 1rem;
  box-shadow: var(--shadow); margin-bottom: 1.5rem;
  font-size: .85rem; color: var(--text-secondary); line-height: 1.6;
}
.week-summary strong { color: var(--text-primary); }
.week-summary .ws-metric { font-variant-numeric: tabular-nums; }
.week-summary .ws-prev { font-size: .75rem; color: var(--text-muted); }

/* ---- Company knowledge section ---- */
.company-knowledge {
  margin: .5rem 0; display: flex; flex-direction: column; gap: .2rem;
}
.company-knowledge .ck-row {
  font-size: .8rem; color: var(--text-secondary); display: flex; gap: .4rem;
  align-items: baseline;
}
.company-knowledge .ck-label {
  color: var(--text-muted); font-size: .7rem; min-width: 55px; flex-shrink: 0;
}
.company-knowledge .ck-value { color: var(--text-primary); }

/* ---- Company meta line (compact) ---- */
.company-meta-line {
  font-size: .7rem; color: var(--text-muted); margin: .35rem 0;
}

/* ---- Conversion funnel ---- */
.funnel-wrap {
  display: flex; align-items: flex-start; justify-content: center; gap: 0;
  padding: 1rem .5rem; background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius); box-shadow: var(--shadow);
}
.funnel-stage {
  display: flex; align-items: center; flex: 1; min-width: 0;
}
.funnel-box {
  flex: 1; min-width: 0; padding: .75rem .5rem; border-radius: var(--radius);
  text-align: center; transition: transform .15s;
}
.funnel-box:hover { transform: translateY(-2px); }
.funnel-value {
  font-size: 1.35rem; font-weight: 700; line-height: 1.2;
  font-variant-numeric: tabular-nums; white-space: nowrap;
}
.funnel-label {
  font-size: .65rem; color: var(--text-muted); text-transform: uppercase;
  letter-spacing: .06em; margin-top: .2rem;
}
.funnel-arrow {
  display: flex; flex-direction: column; align-items: center; gap: .1rem;
  padding: 0 .15rem; flex-shrink: 0;
}
.funnel-arrow-svg { width: 18px; height: 18px; opacity: .4; }
.funnel-cvr {
  font-size: .6rem; color: var(--text-muted); white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
@media (max-width: 700px) {
  .funnel-wrap { flex-direction: column; align-items: stretch; gap: .25rem; }
  .funnel-stage { flex-direction: column; }
  .funnel-box { padding: .5rem .75rem; display: flex; align-items: center; gap: .5rem; text-align: left; }
  .funnel-value { font-size: 1.1rem; }
  .funnel-arrow { flex-direction: row; padding: .15rem 0; }
  .funnel-arrow-svg { transform: rotate(90deg); width: 14px; height: 14px; }
}
@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: .3; }
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
        ("home",       "Home"),
        ("calling",    "Calling"),
        ("email",      "Email"),
        ("linkedin",   "LinkedIn"),
        ("companies",  "Companies"),
        ("pipeline",   "Pipeline"),
        ("experiments","Channel Performance"),
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
    lw = ov.get("last_week", {})
    insights = data.get("insights", [])
    companies = data.get("companies", [])

    # Week label
    wk_num = tw.get("week_num")
    wk_label = f"Week {wk_num}" if wk_num else "This Week"

    # ------------------------------------------------------------------
    # Helper: WoW delta arrow
    # ------------------------------------------------------------------
    def _wow_delta(current, previous, is_pct=False):
        """Return HTML span with green up-arrow, red down-arrow, or muted dash."""
        try:
            c = float(current or 0)
            p = float(previous or 0)
        except (ValueError, TypeError):
            return ""
        diff = c - p
        if is_pct:
            diff_display = f"{abs(diff):.1f}%"
        else:
            diff_display = f"{abs(diff):g}"
        if diff > 0:
            return f'<span style="color:#34a853;font-size:.75rem;">\u25b2 +{diff_display}</span>'
        elif diff < 0:
            return f'<span style="color:#ea4335;font-size:.75rem;">\u25bc -{diff_display}</span>'
        else:
            return f'<span style="color:var(--text-muted);font-size:.75rem;">\u2014 0</span>'

    def _scorecard_card(label, current_display, prev_display=None, delta_html=""):
        """Single metric card for the WoW scorecard grid."""
        prev_line = f'<div style="font-size:.75rem;color:var(--text-muted);margin-top:2px;">{_h(str(prev_display))} last wk</div>' if prev_display is not None else ""
        delta_line = f'<div style="margin-top:2px;">{delta_html}</div>' if delta_html else ""
        return f"""
      <div class="kpi-card" role="article" aria-label="{_h(label)}: {_h(str(current_display))}">
        <div class="kpi-value">{_h(str(current_display))}</div>
        <div class="kpi-label">{_h(label)}</div>
        {prev_line}
        {delta_line}
      </div>"""

    # ------------------------------------------------------------------
    # 1. WoW Scorecard — replaces funnel bar + week summary
    # ------------------------------------------------------------------
    dials       = tw.get("dials", 0)
    cr          = tw.get("contact_rate", 0)
    meetings    = tw.get("meetings_booked", 0)
    inmails_sent = tw.get("inmails_sent", 0)
    inmail_rr   = tw.get("inmail_reply_rate", 0)

    lw_dials    = lw.get("dials", 0)
    lw_cr       = lw.get("contact_rate", 0)
    lw_meetings = lw.get("meetings_booked", 0)
    lw_inmails  = lw.get("inmails_sent", 0)
    lw_rr       = lw.get("inmail_reply_rate", 0)

    deal_pipe = data.get("deal_pipeline", {}).get("metrics", {})
    pipe_value = deal_pipe.get("total_value", 0)
    pipe_meetings = deal_pipe.get("meetings_booked_count", 0)
    pipe_deals = deal_pipe.get("deal_count", 0)

    # Format pipeline value as $XXk or $X.Xm
    if pipe_value >= 1_000_000:
        pipe_value_display = f"${pipe_value / 1_000_000:.1f}m"
    elif pipe_value >= 1_000:
        pipe_value_display = f"${pipe_value / 1_000:.0f}k"
    elif pipe_value > 0:
        pipe_value_display = f"${pipe_value:,.0f}"
    else:
        pipe_value_display = "$0"

    scorecard_html = f"""
  <section aria-labelledby="home-scorecard-heading">
    <h2 class="section-heading" id="home-scorecard-heading">
      <span class="sh-icon" aria-hidden="true">📊</span> {_h(wk_label)}
    </h2>
    <div class="kpi-grid" style="grid-template-columns:repeat(4,1fr);">
      {_scorecard_card("Dials", dials, lw_dials, _wow_delta(dials, lw_dials))}
      {_scorecard_card("Contact Rate", f"{cr:.1f}%", f"{lw_cr:.1f}%", _wow_delta(cr, lw_cr, is_pct=True))}
      {_scorecard_card("Meetings", meetings, lw_meetings, _wow_delta(meetings, lw_meetings))}
      {_scorecard_card("InMails Sent", inmails_sent, lw_inmails, _wow_delta(inmails_sent, lw_inmails))}
      {_scorecard_card("InMail Reply Rate", f"{inmail_rr:.1f}%", f"{lw_rr:.1f}%", _wow_delta(inmail_rr, lw_rr, is_pct=True))}
      {_scorecard_card("Pipeline Value", pipe_value_display)}
      {_scorecard_card("Meetings Booked Total", pipe_meetings)}
      {_scorecard_card("Deals Created", pipe_deals)}
    </div>
  </section>"""

    # ------------------------------------------------------------------
    # 2. Action queue — companies needing attention
    # ------------------------------------------------------------------
    action_candidates = []
    for co in companies:
        status = (co.get("status") or "").lower()
        if status != "interested":
            continue
        # Must have a next_action (from CRM field or latest intel)
        na = co.get("next_action") or ""
        if not na and co.get("latest_intel"):
            na = co["latest_intel"].get("next_action") or ""
        if not na:
            continue
        action_candidates.append({
            "name": co.get("name", ""),
            "status": status,
            "next_action": na,
            "last_touch": str(co.get("last_touch_at") or "")[:10],
        })

    # Also add companies with upcoming contract renewals
    from datetime import date as _date
    today_str = _date.today().isoformat()
    renewal_cutoff = (_date.today() + timedelta(days=90)).isoformat()
    for co in companies:
        rd = str(co.get("contract_renewal_date") or "")[:10]
        if rd and rd <= renewal_cutoff and rd >= "2020-01-01":
            # Avoid duplicates
            if any(a["name"] == co.get("name") for a in action_candidates):
                continue
            action_candidates.append({
                "name": co.get("name", ""),
                "status": (co.get("status") or "prospect").lower(),
                "next_action": f"Renewal {rd}" + (" (overdue)" if rd <= today_str else ""),
                "last_touch": str(co.get("last_touch_at") or "")[:10],
            })

    # Sort by most recent touch first
    action_candidates.sort(key=lambda a: a.get("last_touch") or "", reverse=True)

    action_items_html = ""
    for item in action_candidates[:8]:
        st = item["status"]
        action_items_html += f"""
      <div class="action-item">
        <span class="ai-company">{_h(item["name"])}</span>
        <span class="badge badge-{_h(st)}">{_h(st.replace("_"," ").title())}</span>
        <span class="ai-action" title="{_h(item["next_action"])}">{_h(item["next_action"][:120])}</span>
        <span class="ai-date">{_h(item["last_touch"]) if item["last_touch"] else ""}</span>
      </div>"""

    if action_items_html:
        action_queue_html = f"""
  <section aria-labelledby="home-actions-heading">
    <h2 class="section-heading" id="home-actions-heading">
      <span class="sh-icon" aria-hidden="true">🎯</span> Follow-Up Queue
    </h2>
    <div class="action-queue">
      {action_items_html}
    </div>
  </section>"""
    else:
        action_queue_html = ""

    # ------------------------------------------------------------------
    # 3. Advisor Insights
    # ------------------------------------------------------------------
    type_icons = {
        "action_required": "🔔",
        "alert":           "⚠️",
        "win":             "🏆",
        "experiment":      "🧪",
        "coaching":        "💡",
        "strategic":       "🧭",
    }
    top_cards = ""
    extra_cards = ""
    for idx, ins in enumerate(insights[:12]):
        ins_type = ins.get("type", "strategic")
        icon = type_icons.get(ins_type, "💬")
        co_tag = f'<span class="insight-tag">{_h(ins["company_name"])}</span>' if ins.get("company_name") else ""
        ch_tag = f'<span class="insight-tag">{_h(ins["channel"])}</span>' if ins.get("channel") else ""
        card = f"""
      <article class="insight-card type-{_h(ins_type)}" role="article" onclick="this.classList.toggle('expanded');var b=this.querySelector('.insight-body');b.style.display=b.style.display==='block'?'none':'block';var ch=this.querySelector('.insight-chevron');ch.textContent=ch.textContent==='▸'?'▾':'▸';">
        <div class="insight-header">
          <span class="insight-type-badge type-{_h(ins_type)}" aria-hidden="true">{_h(icon)} {_h(ins_type.replace("_"," "))}</span>
          <span class="insight-severity">{_h(ins.get("severity",""))}</span>
        </div>
        <div class="insight-title"><span class="insight-chevron" aria-hidden="true">▸</span> {_h(ins.get("title",""))}</div>
        <div class="insight-body" style="display:none">{_h(ins.get("body",""))}</div>
        <div class="insight-meta">{co_tag}{ch_tag}</div>
      </article>"""
        if idx < 3:
            top_cards += card
        else:
            extra_cards += card

    if not top_cards and not extra_cards:
        insights_section_inner = '<div class="empty-state"><div class="empty-icon" aria-hidden="true">💡</div><p>No insights yet. They will appear here once the advisor runs.</p></div>'
        show_all_btn = ""
    else:
        total_insights = len(insights[:12])
        hidden_div = f'<div class="insights-hidden" style="display:none">{extra_cards}</div>' if extra_cards else ""
        show_all_btn = f'<button class="show-all-btn" onclick="toggleInsights(this)">Show all {total_insights} insights ▾</button>' if extra_cards else ""
        insights_section_inner = top_cards + hidden_div

    insights_html = f"""
  <section aria-labelledby="home-insights-heading">
    <h2 class="section-heading" id="home-insights-heading">
      <span class="sh-icon" aria-hidden="true">💡</span> Advisor Insights
    </h2>
    <div class="insights-grid" aria-live="polite">
      {insights_section_inner}
    </div>
    {show_all_btn}
  </section>"""

    # ------------------------------------------------------------------
    # 4. Channels This Week
    # ------------------------------------------------------------------
    call_trends = data.get("call_trends", [])
    inmail_trends = data.get("inmail_trends", [])
    latest_call = call_trends[-1] if call_trends else {}
    latest_li   = inmail_trends[-1] if inmail_trends else {}

    inmail_stats = data.get("inmail_stats", {})
    email_seqs_raw = data.get("email_sequences", [])
    # Deduplicate: latest snapshot per sequence
    _home_latest: dict[str, dict] = {}
    for s in email_seqs_raw:
        n = s.get("sequence_name", "")
        sd = s.get("snapshot_date", "")
        if n not in _home_latest or sd > _home_latest[n].get("snapshot_date", ""):
            _home_latest[n] = s
    home_email_deduped = list(_home_latest.values())

    ch_calls_metric = f"{latest_call.get('dials', 0)} dials"
    ch_calls_sub    = f"{latest_call.get('contact_rate', 0):.1f}% contact rate"
    ch_li_metric    = f"{latest_li.get('sent', 0)} sent"
    ch_li_sub       = f"{latest_li.get('reply_rate', 0):.1f}% reply rate"
    total_email_sent = sum(s.get("sent", 0) for s in home_email_deduped)
    ch_email_metric = f"{total_email_sent} sent" if total_email_sent else "\u2014"
    ch_email_sub    = "Not connected" if not home_email_deduped else f"{len(home_email_deduped)} sequences"

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
  {insights_html}
  {scorecard_html}
  {action_queue_html}
  {channel_html}
</section>"""


# ---------------------------------------------------------------------------
# Tab 2: Activity (merged Cold Calling + Email & LinkedIn)
# ---------------------------------------------------------------------------

def _tab_calling(data: dict) -> str:
    """Tab: Calling — trends, categories, daily/weekly stats, call log, intel."""
    # =================================================================
    # Section 1: Calling — trends chart + category breakdown
    # =================================================================
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

    calling_section = f"""
  <!-- Live Today banner -->
  <div id="live-today-banner" class="card" style="padding:1rem 1.25rem;margin-bottom:1.5rem;border-left:3px solid var(--accent-green);display:none;">
    <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.75rem;">
      <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--accent-green);animation:pulse-dot 2s infinite;"></span>
      <span style="font-weight:600;font-size:.9rem;color:var(--text-primary);">Live Today</span>
      <span id="live-timestamp" style="margin-left:auto;font-size:.7rem;color:var(--text-muted);"></span>
    </div>
    <div style="display:grid;grid-template-columns:repeat(6,1fr);gap:1rem;text-align:center;">
      <div>
        <div id="live-dials" style="font-size:1.75rem;font-weight:700;color:var(--text-primary);">—</div>
        <div style="font-size:.7rem;color:var(--text-muted);">Dials</div>
      </div>
      <div>
        <div id="live-contacts" style="font-size:1.75rem;font-weight:700;color:var(--text-primary);">—</div>
        <div style="font-size:.7rem;color:var(--text-muted);">Contacts</div>
      </div>
      <div>
        <div id="live-contact-pct" style="font-size:1.75rem;font-weight:700;color:var(--text-primary);">—</div>
        <div style="font-size:.7rem;color:var(--text-muted);">Contact %</div>
      </div>
      <div>
        <div id="live-interested" style="font-size:1.75rem;font-weight:700;color:var(--accent-green);">—</div>
        <div style="font-size:.7rem;color:var(--text-muted);">Interested</div>
      </div>
      <div>
        <div id="live-meetings" style="font-size:1.75rem;font-weight:700;color:var(--accent-blue);">—</div>
        <div style="font-size:.7rem;color:var(--text-muted);">Meetings</div>
      </div>
      <div>
        <div id="live-vms" style="font-size:1.75rem;font-weight:700;color:var(--text-primary);">—</div>
        <div style="font-size:.7rem;color:var(--text-muted);">VMs Left</div>
      </div>
    </div>
    <div id="live-recent" style="margin-top:.75rem;border-top:1px solid var(--border);padding-top:.6rem;font-size:.75rem;color:var(--text-secondary);"></div>
  </div>

  <section aria-labelledby="activity-calling-heading">
    <h2 class="section-heading" id="activity-calling-heading">
      <span class="sh-icon" aria-hidden="true">📞</span> Calling
    </h2>

    <div class="card chart-card">
      <div class="chart-container">
        <canvas id="calling-trends-chart" aria-label="Weekly calling trends chart" role="img"></canvas>
      </div>
    </div>

    <div class="card" style="margin-bottom:1.5rem;">
      <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.75rem;">
        <span style="font-weight:600;color:var(--text-primary);font-size:.875rem;">Category Breakdown</span>
        <span style="margin-left:auto;font-size:.75rem;color:var(--text-muted);font-weight:400">{total_calls} total calls</span>
      </div>
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

    # =================================================================
    # Section 1b: Cold Calling Stats — daily & weekly tables
    # =================================================================
    daily_stats = data.get("daily_calling_stats", [])
    weekly_stats = data.get("weekly_calling_stats", [])

    def _fmt_dur(s: int) -> str:
        """Format seconds as M:SS."""
        if not s:
            return "—"
        return f"{s // 60}:{s % 60:02d}"

    # --- Weekly table rows ---
    today_str = datetime.now().strftime("%Y-%m-%d")
    # Determine current week_num from weekly stats
    current_week = weekly_stats[-1]["week"] if weekly_stats else 0

    weekly_rows_html = ""
    wk_totals = {"dials": 0, "contacts": 0, "interested": 0, "meetings": 0, "vms": 0, "referrals": 0, "not_interested": 0, "dur_sum": 0, "dur_count": 0}
    for wk in weekly_stats:
        is_current = wk["week"] == current_week
        hl = ' style="border-left:3px solid var(--accent-blue);background:rgba(59,130,246,0.06);"' if is_current else ""
        wk_totals["dials"] += wk["dials"]
        wk_totals["contacts"] += wk["contacts"]
        wk_totals["interested"] += wk["interested"]
        wk_totals["meetings"] += wk["meetings"]
        wk_totals["vms"] += wk["vms"]
        wk_totals["referrals"] += wk["referrals"]
        wk_totals["not_interested"] += wk["not_interested"]
        if wk["avg_duration_s"]:
            wk_totals["dur_sum"] += wk["avg_duration_s"] * wk["contacts"]
            wk_totals["dur_count"] += wk["contacts"]
        weekly_rows_html += f"""
              <tr{hl}>
                <td style="font-weight:{'600' if is_current else '400'}">Week {wk['week']}{'  ◀' if is_current else ''}</td>
                <td>{wk['dials']}</td>
                <td>{wk['contacts']}</td>
                <td>{wk['contact_pct']:.1f}%</td>
                <td style="color:var(--accent-green)">{wk['interested']}</td>
                <td style="color:var(--accent-blue)">{wk['meetings']}</td>
                <td>{wk['vms']}</td>
                <td>{wk['referrals']}</td>
                <td>{wk['not_interested']}</td>
                <td>{_fmt_dur(wk['avg_duration_s'])}</td>
              </tr>"""

    wk_total_contact_pct = round(wk_totals["contacts"] / wk_totals["dials"] * 100, 1) if wk_totals["dials"] else 0
    wk_total_avg_dur = round(wk_totals["dur_sum"] / wk_totals["dur_count"]) if wk_totals["dur_count"] else 0
    weekly_rows_html += f"""
              <tr style="font-weight:600;border-top:2px solid var(--border);">
                <td>Total</td>
                <td>{wk_totals['dials']}</td>
                <td>{wk_totals['contacts']}</td>
                <td>{wk_total_contact_pct:.1f}%</td>
                <td style="color:var(--accent-green)">{wk_totals['interested']}</td>
                <td style="color:var(--accent-blue)">{wk_totals['meetings']}</td>
                <td>{wk_totals['vms']}</td>
                <td>{wk_totals['referrals']}</td>
                <td>{wk_totals['not_interested']}</td>
                <td>{_fmt_dur(wk_total_avg_dur)}</td>
              </tr>"""

    # --- Daily table rows ---
    daily_rows_html = ""
    d_totals = {"dials": 0, "contacts": 0, "interested": 0, "meetings": 0, "vms": 0, "dur_sum": 0, "dur_count": 0}
    for d in daily_stats:
        is_today = d["date"] == today_str
        hl = ' style="border-left:3px solid var(--accent-green);background:rgba(16,185,129,0.06);"' if is_today else ""
        d_totals["dials"] += d["dials"]
        d_totals["contacts"] += d["contacts"]
        d_totals["interested"] += d["interested"]
        d_totals["meetings"] += d["meetings"]
        d_totals["vms"] += d["vms"]
        if d["avg_duration_s"]:
            d_totals["dur_sum"] += d["avg_duration_s"] * d["contacts"]
            d_totals["dur_count"] += d["contacts"]
        # Format date as Mon 2/26
        try:
            dt = datetime.strptime(d["date"], "%Y-%m-%d")
            day_label = dt.strftime("%a %-m/%-d")
        except Exception:
            day_label = d["date"]
        daily_rows_html += f"""
              <tr{hl}>
                <td style="font-weight:{'600' if is_today else '400'};white-space:nowrap">{day_label}{'  ◀' if is_today else ''}</td>
                <td>{d['dials']}</td>
                <td>{d['contacts']}</td>
                <td>{d['contact_pct']:.1f}%</td>
                <td style="color:var(--accent-green)">{d['interested']}</td>
                <td style="color:var(--accent-blue)">{d['meetings']}</td>
                <td>{d['vms']}</td>
                <td>{_fmt_dur(d['avg_duration_s'])}</td>
              </tr>"""

    d_total_contact_pct = round(d_totals["contacts"] / d_totals["dials"] * 100, 1) if d_totals["dials"] else 0
    d_total_avg_dur = round(d_totals["dur_sum"] / d_totals["dur_count"]) if d_totals["dur_count"] else 0
    daily_rows_html += f"""
              <tr style="font-weight:600;border-top:2px solid var(--border);">
                <td>Total</td>
                <td>{d_totals['dials']}</td>
                <td>{d_totals['contacts']}</td>
                <td>{d_total_contact_pct:.1f}%</td>
                <td style="color:var(--accent-green)">{d_totals['interested']}</td>
                <td style="color:var(--accent-blue)">{d_totals['meetings']}</td>
                <td>{d_totals['vms']}</td>
                <td>{_fmt_dur(d_total_avg_dur)}</td>
              </tr>"""

    calling_stats_section = f"""
  <section aria-labelledby="activity-calling-stats-heading">
    <h2 class="section-heading" id="activity-calling-stats-heading">
      <span class="sh-icon" aria-hidden="true">📊</span> Cold Calling Stats
    </h2>

    <div class="card" style="margin-bottom:1.5rem;">
      <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.75rem;">
        <span style="font-weight:600;color:var(--text-primary);font-size:.875rem;">Weekly Summary</span>
        <span style="margin-left:auto;font-size:.7rem;color:var(--text-muted);background:var(--bg-card);border:1px solid var(--border);padding:.15rem .5rem;border-radius:9999px;">by week</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Week</th><th>Dials</th><th>Contacts</th><th>Contact&nbsp;%</th>
              <th>Interested</th><th>Meetings</th><th>VMs</th>
              <th>Referrals</th><th>Not&nbsp;Int.</th><th>Avg&nbsp;Dur</th>
            </tr>
          </thead>
          <tbody>{weekly_rows_html}
          </tbody>
        </table>
      </div>
    </div>

    <div class="card" style="margin-bottom:1.5rem;">
      <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.75rem;">
        <span style="font-weight:600;color:var(--text-primary);font-size:.875rem;">Daily Breakdown</span>
        <span style="margin-left:auto;font-size:.7rem;color:var(--text-muted);background:var(--bg-card);border:1px solid var(--border);padding:.15rem .5rem;border-radius:9999px;">last {len(daily_stats)} days</span>
      </div>
      <div class="table-wrap" style="max-height:500px;overflow-y:auto;">
        <table>
          <thead style="position:sticky;top:0;background:var(--bg-card);z-index:1;">
            <tr>
              <th>Date</th><th>Dials</th><th>Contacts</th><th>Contact&nbsp;%</th>
              <th>Interested</th><th>Meetings</th><th>VMs</th><th>Avg&nbsp;Dur</th>
            </tr>
          </thead>
          <tbody>{daily_rows_html}
          </tbody>
        </table>
      </div>
    </div>
  </section>"""

    # =================================================================
    # Call Log
    # =================================================================
    log_rows = ""
    for call in call_log:
        dur = _fmt_dur(call.get("duration_s", 0))
        _raw_notes = _re.sub(r'<[^>]+>', ' ', (call.get("notes") or ""))
        _raw_notes = _re.sub(r'\s+', ' ', _raw_notes).strip()
        _raw_summary = _re.sub(r'<[^>]+>', ' ', (call.get("summary") or ""))
        # Strip markdown: headers (## Summary, ## Key notes, etc.), --- rules, ** bold **
        _raw_summary = _re.sub(r'#{1,4}\s+[A-Za-z].*?(?:\n|$)', '', _raw_summary)
        _raw_summary = _re.sub(r'-{3,}', '', _raw_summary)
        _raw_summary = _re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', _raw_summary)
        _raw_summary = _re.sub(r'^[\s\-\*]+', '', _raw_summary)
        _raw_summary = _re.sub(r'\s+', ' ', _raw_summary).strip()
        notes_full = _raw_notes
        summary_full = _raw_summary
        # Show notes first (Adam's input); fall back to cleaned AI summary
        display_text = (_raw_notes or _raw_summary)[:200]
        intel = call.get("intel") or {}

        detail_parts = []
        if notes_full:
            detail_parts.append(f"<strong>Notes:</strong> {_h(notes_full)}")
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
        if intel.get("challenges"):
            detail_parts.append(f"<strong>Challenges:</strong> {_h(intel['challenges'])}")
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
              data-category="{_h(category)}"
              role="row">
            <td>{_h(date_str)}</td>
            <td>{_h(contact)}</td>
            <td>{_h(company)}</td>
            <td><span class="badge badge-{_h(category.lower().replace(' ','_'))}" style="font-size:.6rem">{_h(category)}</span></td>
            <td style="font-variant-numeric:tabular-nums">{_h(dur)}</td>
            <td style="color:var(--text-secondary);max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{_h(display_text[:80] + ('…' if len(display_text)>80 else ''))}</td>
          </tr>
          <tr class="detail-row" id="detail-{call_id}" style="display:none">
            <td colspan="6" class="row-detail">
              <div class="row-detail-inner">{detail_inner}</div>
            </td>
          </tr>"""
        else:
            log_rows += f"""
          <tr data-category="{_h(category)}">
            <td>{_h(date_str)}</td>
            <td>{_h(contact)}</td>
            <td>{_h(company)}</td>
            <td><span class="badge" style="font-size:.6rem">{_h(category)}</span></td>
            <td style="font-variant-numeric:tabular-nums">{_h(dur)}</td>
            <td style="color:var(--text-secondary)">{_h(display_text[:80])}</td>
          </tr>"""

    all_cats = sorted(set(c.get("category", "") for c in call_log if c.get("category")))
    cat_options = '<option value="">All categories</option>'
    for c in all_cats:
        cat_options += f'<option value="{_h(c)}">{_h(c)}</option>'

    call_log_section = f"""
  <section aria-labelledby="activity-calllog-heading">
    <h2 class="section-heading" id="activity-calllog-heading">
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

    # =================================================================
    # Intel highlights (from call intel)
    # =================================================================
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
  <section aria-labelledby="activity-intel-heading">
    <h2 class="section-heading" id="activity-intel-heading">
      <span class="sh-icon" aria-hidden="true">🎯</span> Intel Highlights
    </h2>
    <div class="intel-grid">{intel_cards}</div>
  </section>"""

    # =================================================================
    # Assemble Calling tab
    # =================================================================
    return f"""
<section id="tab-calling"
         class="tab-panel app-wrapper"
         role="tabpanel"
         aria-labelledby="tab-btn-calling"
         aria-hidden="true">
  {calling_section}
  {calling_stats_section}
  {call_log_section}
  {intel_section}
</section>"""


# ---------------------------------------------------------------------------
# Tab 3: Email
# ---------------------------------------------------------------------------

def _tab_email(data: dict) -> str:
    """Tab: Email — Apollo sequence KPIs + sequence breakdown table."""
    email_seqs = data.get("email_sequences", [])

    # Deduplicate email sequences: keep only the latest snapshot per sequence name
    _latest_seqs: dict[str, dict] = {}
    for s in email_seqs:
        name = s.get("sequence_name", "")
        snap = s.get("snapshot_date", "")
        if name not in _latest_seqs or snap > _latest_seqs[name].get("snapshot_date", ""):
            _latest_seqs[name] = s
    email_seqs_deduped = list(_latest_seqs.values())

    # Email aggregates from deduplicated sequences
    em_total_sent    = sum(s.get("sent", 0) for s in email_seqs_deduped)
    em_total_opened  = sum(s.get("opened", 0) for s in email_seqs_deduped)
    em_total_replied = sum(s.get("replied", 0) for s in email_seqs_deduped)
    em_open_rate     = (em_total_opened / em_total_sent * 100) if em_total_sent else 0
    em_reply_rate    = (em_total_replied / em_total_sent * 100) if em_total_sent else 0

    em_kpi_value_style = "color:var(--text-muted)" if not email_seqs else ""

    # Email sequences table rows
    seq_rows = ""
    if email_seqs_deduped:
        for seq in sorted(email_seqs_deduped, key=lambda s: s.get("sent", 0), reverse=True):
            or_ = seq.get("open_rate", 0)
            rr_ = seq.get("reply_rate", 0)
            seq_rows += f"""
        <tr>
          <td>{_h(seq.get("sequence_name",""))}</td>
          <td>{_h(seq.get("status",""))}</td>
          <td style="font-variant-numeric:tabular-nums">{_h(seq.get("sent",0))}</td>
          <td style="font-variant-numeric:tabular-nums">{_h(seq.get("opened",0))} <span style="color:var(--text-secondary)">({or_:.1f}%)</span></td>
          <td style="font-variant-numeric:tabular-nums">{_h(seq.get("replied",0))} <span style="color:var(--text-secondary)">({rr_:.1f}%)</span></td>
          <td style="color:var(--text-secondary);font-size:.75rem">{_h(str(seq.get("snapshot_date",""))[:10])}</td>
        </tr>"""
        seq_table_html = f"""
    <div class="card" style="margin-top:1.5rem;">
      <div style="font-size:.75rem;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--text-muted);margin-bottom:.75rem;">Sequence Breakdown</div>
      <div class="table-wrap">
        <table aria-label="Email sequences by name">
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
    </div>"""
    else:
        seq_table_html = """
    <div style="margin-top:1.5rem;padding:1.25rem;text-align:center;color:var(--text-muted);font-size:.85rem;">
      No sequence data — connect Apollo to see per-sequence breakdown.
    </div>"""

    return f"""
<section id="tab-email"
         class="tab-panel app-wrapper"
         role="tabpanel"
         aria-labelledby="tab-btn-email"
         aria-hidden="true">
  <section>
    <h2 class="section-heading">
      <span class="sh-icon" aria-hidden="true">✉️</span> Email Sequences
      <span style="margin-left:auto;font-size:.7rem;color:var(--text-muted);font-weight:500;background:var(--bg-secondary);padding:.15rem .45rem;border-radius:.25rem;">all time</span>
    </h2>

    <div class="card" style="padding:1.25rem;margin-bottom:1.5rem;">
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:1.5rem;text-align:center;">
        <div>
          <div style="font-size:2rem;font-weight:700;color:var(--text-primary);{em_kpi_value_style}">{em_total_sent if email_seqs else "—"}</div>
          <div style="font-size:.75rem;color:var(--text-muted);margin-top:.2rem;">Sent</div>
        </div>
        <div>
          <div style="font-size:2rem;font-weight:700;color:var(--text-primary);{em_kpi_value_style}">{em_total_opened if email_seqs else "—"}</div>
          <div style="font-size:.75rem;color:var(--text-muted);margin-top:.2rem;">Opened</div>
        </div>
        <div>
          <div style="font-size:2rem;font-weight:700;color:var(--accent-blue);{em_kpi_value_style}">{f"{em_open_rate:.1f}%" if email_seqs else "—"}</div>
          <div style="font-size:.75rem;color:var(--text-muted);margin-top:.2rem;">Open Rate</div>
        </div>
        <div>
          <div style="font-size:2rem;font-weight:700;color:var(--accent-blue);{em_kpi_value_style}">{f"{em_reply_rate:.1f}%" if email_seqs else "—"}</div>
          <div style="font-size:.75rem;color:var(--text-muted);margin-top:.2rem;">Reply Rate</div>
        </div>
      </div>
      <div style="border-top:1px solid var(--border);margin-top:1.25rem;padding-top:1rem;">
        <div style="display:flex;gap:2rem;">
          <div>
            <span style="font-size:.85rem;font-weight:600;color:var(--text-primary);">{em_total_replied if email_seqs else "—"}</span>
            <span style="font-size:.75rem;color:var(--text-muted);margin-left:.3rem;">Replied</span>
          </div>
          <div>
            <span style="font-size:.85rem;font-weight:600;color:var(--text-primary);">{len(email_seqs_deduped)}</span>
            <span style="font-size:.75rem;color:var(--text-muted);margin-left:.3rem;">Active Sequences</span>
          </div>
        </div>
      </div>
    </div>

    {seq_table_html}
  </section>
</section>"""


# ---------------------------------------------------------------------------
# Tab 4: LinkedIn
# ---------------------------------------------------------------------------

def _tab_linkedin(data: dict) -> str:
    """Tab: LinkedIn — InMail KPIs, trends, sentiment, and InMail log."""
    inmails = data.get("inmails", [])
    inmail_stats = data.get("inmail_stats", {})

    # LinkedIn (InMail) aggregates — all-time
    li_total_sent    = inmail_stats.get("total_sent", 0)
    li_total_replied = inmail_stats.get("total_replied", 0)
    li_reply_rate    = inmail_stats.get("reply_rate", 0)
    if isinstance(li_reply_rate, float) and li_reply_rate <= 1:
        li_rr_pct = f"{li_reply_rate*100:.1f}%"
    else:
        li_rr_pct = f"{li_reply_rate:.1f}%"

    sentiments = inmail_stats.get("sentiment_breakdown", {})

    # Sentiment bar rows
    sentiment_bars = ""
    for sent_label, cnt in sentiments.items():
        pct = (cnt / li_total_replied * 100) if li_total_replied else 0
        sentiment_bars += f"""
              <div style="display:flex;align-items:center;gap:.75rem;margin-bottom:.5rem;">
                <span style="min-width:100px;color:var(--text-secondary);font-size:.8rem;">{_h(sent_label.replace('_',' ').title())}</span>
                <div style="flex:1;height:6px;background:var(--border);border-radius:3px;overflow:hidden;">
                  <div style="width:{pct:.1f}%;height:100%;background:var(--accent-blue);border-radius:3px;"></div>
                </div>
                <span style="color:var(--text-secondary);font-size:.75rem;min-width:30px;text-align:right">{cnt}</span>
              </div>"""

    # InMail Log rows
    all_sentiments_list = sorted(set(im.get("reply_sentiment", "") or "" for im in inmails if im.get("reply_sentiment")))
    sent_options = '<option value="">All sentiments</option>'
    for s in all_sentiments_list:
        sent_options += f'<option value="{_h(s)}">{_h(s.replace("_"," ").title())}</option>'

    inmail_rows = ""
    for im in inmails:
        sent = im.get("reply_sentiment") or ""
        sent_badge = f'<span class="badge badge-{_h(sent.replace("-","_"))}">{_h(sent.replace("_"," ").title() if sent else "—")}</span>'
        replied_icon = '\u2713' if im.get("replied") else '\u2014'
        replied_color = "var(--accent-green)" if im.get("replied") else "var(--text-muted)"
        inmail_rows += f"""
        <tr data-sentiment="{_h(sent)}">
          <td>{_h(str(im.get("sent_date","") or "")[:10])}</td>
          <td>{_h(im.get("contact_name",""))}</td>
          <td style="color:var(--text-secondary);font-size:.75rem;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="{_h(im.get("contact_title",""))}">{_h((im.get("contact_title","") or "")[:50] + ("..." if len(im.get("contact_title","") or "") > 50 else ""))}</td>
          <td>{_h(im.get("company_name",""))}</td>
          <td style="color:{replied_color};text-align:center">{replied_icon}</td>
          <td>{sent_badge}</td>
        </tr>"""

    return f"""
<section id="tab-linkedin"
         class="tab-panel app-wrapper"
         role="tabpanel"
         aria-labelledby="tab-btn-linkedin"
         aria-hidden="true">
  <section>
    <h2 class="section-heading">
      <span class="sh-icon" aria-hidden="true">💼</span> LinkedIn InMail
      <span style="margin-left:auto;font-size:.7rem;color:var(--text-muted);font-weight:500;background:var(--bg-secondary);padding:.15rem .45rem;border-radius:.25rem;">all time</span>
    </h2>

    <div class="card" style="padding:1.25rem;margin-bottom:1.5rem;">
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:1.5rem;text-align:center;margin-bottom:1.25rem;">
        <div>
          <div style="font-size:2rem;font-weight:700;color:var(--text-primary);">{li_total_sent}</div>
          <div style="font-size:.75rem;color:var(--text-muted);margin-top:.2rem;">Sent</div>
        </div>
        <div>
          <div style="font-size:2rem;font-weight:700;color:var(--text-primary);">{li_total_replied}</div>
          <div style="font-size:.75rem;color:var(--text-muted);margin-top:.2rem;">Replied</div>
        </div>
        <div>
          <div style="font-size:2rem;font-weight:700;color:var(--accent-blue);">{li_rr_pct}</div>
          <div style="font-size:.75rem;color:var(--text-muted);margin-top:.2rem;">Reply Rate</div>
        </div>
      </div>
      <div style="border-top:1px solid var(--border);padding-top:1rem;">
        <div style="font-size:.7rem;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--text-muted);margin-bottom:.6rem;">Reply Sentiment</div>
        <div style="display:grid;grid-template-columns:1fr auto;gap:.75rem;align-items:center;">
          <div>{sentiment_bars if sentiment_bars else '<div style="color:var(--text-muted);font-size:.8rem;">No replies yet.</div>'}</div>
          <div style="width:100px;height:100px;">
            <canvas id="sentiment-donut-chart" aria-label="InMail sentiment breakdown" role="img"></canvas>
          </div>
        </div>
      </div>
    </div>

    <!-- Trend chart -->
    <div class="card chart-card" style="margin-bottom:1.5rem;">
      <div class="chart-container">
        <canvas id="inmail-trends-chart" aria-label="Weekly InMail trends chart" role="img"></canvas>
      </div>
    </div>
  </section>

  <section aria-labelledby="linkedin-inmail-log-heading">
    <h2 class="section-heading" id="linkedin-inmail-log-heading">
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
  </section>
</section>"""


# ---------------------------------------------------------------------------
# Tab 5: Companies
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

    # Knowledge-filter: has intel
    knowledge_options = '<option value="">All companies</option><option value="has_provider">Has provider</option><option value="has_commodities">Has commodities</option><option value="has_contact">Has contact</option>'

    from datetime import date as _date
    today_str = _date.today().isoformat()

    # Build date options from unique last_touch dates
    all_dates = sorted(set(
        str(co.get("last_touch_at") or "")[:10]
        for co in companies if co.get("last_touch_at")
    ), reverse=True)

    date_options = '<option value="" selected>All dates</option>'
    date_options += f'<option value="{today_str}">Today ({today_str})</option>'
    from datetime import timedelta as _td
    yesterday_str = (_date.today() - _td(days=1)).isoformat()
    if yesterday_str in all_dates:
        date_options += f'<option value="{yesterday_str}">Yesterday ({yesterday_str})</option>'
    # Last 5 unique dates (excluding today/yesterday already shown)
    for d in all_dates:
        if d != today_str and d != yesterday_str:
            date_options += f'<option value="{_h(d)}">{_h(d)}</option>'

    # Table rows — expandable with full intel detail
    table_rows = ""
    for idx, co in enumerate(companies):
        name = co.get("name", "")
        status = co.get("status", "prospect")
        channels = co.get("channels_touched") or co.get("channels") or []
        last_touch = str(co.get("last_touch_at") or co.get("last_touch") or "")[:10]
        provider = co.get("current_provider") or ""
        commodities = co.get("commodities") or ""
        contact_name = co.get("contact_name") or ""
        contact_role = co.get("contact_role") or ""
        next_action = co.get("next_action") or ""
        co_notes = co.get("notes") or ""
        ch_list_str = " ".join(channels)
        intel = co.get("latest_intel") or {}
        co_calls = co.get("calls") or []

        contact_display = _h(contact_name)
        if contact_role:
            contact_display += f'<br><span style="font-size:.7rem;color:var(--text-muted)">{_h(contact_role)}</span>'

        # Build detail panel content
        detail_parts = []
        # Key quote — the most important thing
        kq = intel.get("key_quote")
        if kq:
            detail_parts.append(f'<div style="margin-bottom:.5rem;padding:.5rem .75rem;border-left:3px solid var(--accent-blue);background:rgba(59,130,246,.08);border-radius:0 .25rem .25rem 0"><em>"{_h(kq)}"</em></div>')
        # Challenges
        challenges = intel.get("challenges")
        if challenges:
            detail_parts.append(f'<div style="margin-bottom:.4rem"><strong style="color:var(--accent-orange,#f59e0b)">Challenges:</strong> {_h(challenges)}</div>')
        # Objection
        obj = intel.get("objection")
        if obj:
            detail_parts.append(f'<div style="margin-bottom:.4rem"><strong style="color:var(--accent-red)">Objection:</strong> {_h(obj)}</div>')
        # Call notes from most recent call (Adam's raw notes)
        for c in co_calls:
            raw_n = _re.sub(r'<[^>]+>', ' ', c.get("notes") or "")
            raw_n = _re.sub(r'\s+', ' ', raw_n).strip()
            if raw_n:
                cdate = str(c.get("called_at") or "")[:10]
                ccontact = c.get("contact_name") or ""
                detail_parts.append(f'<div style="margin-bottom:.4rem"><strong>Call notes ({_h(cdate)} — {_h(ccontact)}):</strong> {_h(raw_n)}</div>')
                break  # only most recent with notes
        # AI summary from most recent call (cleaned)
        for c in co_calls:
            raw_s = _re.sub(r'<[^>]+>', ' ', c.get("summary") or "")
            raw_s = _re.sub(r'#{1,4}\s+[A-Za-z].*?(?:\n|$)', '', raw_s)
            raw_s = _re.sub(r'-{3,}', '', raw_s)
            raw_s = _re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', raw_s)
            raw_s = _re.sub(r'\s+', ' ', raw_s).strip()
            if raw_s:
                cdate = str(c.get("called_at") or "")[:10]
                detail_parts.append(f'<div style="margin-bottom:.4rem;color:var(--text-secondary)"><strong>AI summary ({_h(cdate)}):</strong> {_h(raw_s[:300])}</div>')
                break
        # Provider / commodities if not in table header
        if provider and commodities:
            detail_parts.append(f'<div style="margin-bottom:.3rem"><strong>Ships:</strong> {_h(commodities)} &nbsp;|&nbsp; <strong>Current provider:</strong> {_h(provider)}</div>')

        has_detail = bool(detail_parts)
        detail_html = "".join(detail_parts) if detail_parts else ""
        row_id = f"co-{idx}"

        if has_detail:
            table_rows += f"""
          <tr class="expandable-row" data-status="{_h(status)}" data-channels="{_h(ch_list_str)}"
              data-name="{_h(name.lower())}"
              data-lasttouch="{_h(last_touch)}"
              data-has-provider="{"1" if provider else "0"}"
              data-has-commodities="{"1" if commodities else "0"}"
              data-has-contact="{"1" if contact_name else "0"}"
              data-co-id="{row_id}"
              onclick="toggleCompanyRow(this)"
              style="cursor:pointer">
            <td style="font-weight:600;color:var(--text-primary);white-space:nowrap">{_h(name)}</td>
            <td><span class="badge badge-{_h(status)}" style="font-size:.65rem">{_h(status.replace('_',' ').title())}</span></td>
            <td style="color:var(--text-secondary);font-size:.8rem;white-space:nowrap">{_h(last_touch)}</td>
            <td style="color:var(--text-secondary);font-size:.8rem">{_h(provider)}</td>
            <td style="color:var(--text-secondary);font-size:.8rem">{_h(commodities[:50])}</td>
            <td style="font-size:.8rem">{contact_display}</td>
            <td style="color:var(--accent-blue);font-size:.75rem">{_h(next_action)}</td>
          </tr>
          <tr class="detail-row" id="{row_id}" style="display:none">
            <td colspan="7" class="row-detail"><div class="row-detail-inner" style="font-size:.8rem;line-height:1.5">{detail_html}</div></td>
          </tr>"""
        else:
            table_rows += f"""
          <tr data-status="{_h(status)}" data-channels="{_h(ch_list_str)}"
              data-name="{_h(name.lower())}"
              data-lasttouch="{_h(last_touch)}"
              data-has-provider="{"1" if provider else "0"}"
              data-has-commodities="{"1" if commodities else "0"}"
              data-has-contact="{"1" if contact_name else "0"}">
            <td style="font-weight:600;color:var(--text-primary);white-space:nowrap">{_h(name)}</td>
            <td><span class="badge badge-{_h(status)}" style="font-size:.65rem">{_h(status.replace('_',' ').title())}</span></td>
            <td style="color:var(--text-secondary);font-size:.8rem;white-space:nowrap">{_h(last_touch)}</td>
            <td style="color:var(--text-secondary);font-size:.8rem">{_h(provider)}</td>
            <td style="color:var(--text-secondary);font-size:.8rem">{_h(commodities[:50])}</td>
            <td style="font-size:.8rem">{contact_display}</td>
            <td style="color:var(--text-muted);font-size:.75rem">—</td>
          </tr>"""

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
      <select id="company-knowledge-filter" aria-label="Filter by knowledge" onchange="filterCompanies()">
        {knowledge_options}
      </select>
      <select id="company-date-filter" aria-label="Filter by date" onchange="filterCompanies()">
        {date_options}
      </select>
      <select id="company-sort" aria-label="Sort companies" onchange="filterCompanies()">
        <option value="recent" selected>Most recent</option>
        <option value="name">Name A-Z</option>
      </select>
    </div>

    <div class="table-wrap" id="company-table-wrap">
      <table class="data-table" id="company-table">
        <thead>
          <tr>
            <th>Company</th>
            <th>Status</th>
            <th>Last Touch</th>
            <th>Provider</th>
            <th>Commodities</th>
            <th>Contact</th>
            <th>Next Action</th>
          </tr>
        </thead>
        <tbody>{table_rows}</tbody>
      </table>
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
# Tab 5: Pipeline (HubSpot Deals)
# ---------------------------------------------------------------------------

def _tab_pipeline(data: dict) -> str:
    dp = data.get("deal_pipeline", {})
    deals = dp.get("deals", [])
    by_stage = dp.get("by_stage", {})
    stage_order = dp.get("stage_order", [])
    meetings_booked = dp.get("meetings_booked", [])
    metrics = dp.get("metrics", {})

    total_value = metrics.get("total_value", 0)
    weighted_value = metrics.get("weighted_value", 0)
    deal_count = metrics.get("deal_count", 0)
    avg_deal = metrics.get("avg_deal", 0)
    mtg_count = metrics.get("meetings_booked_count", 0)

    mars_count = sum(1 for d in deals if d.get("channel") == "MARS")
    cold_count = sum(1 for d in deals if d.get("channel") == "Cold Call")

    # ------------------------------------------------------------------
    # Funnel data extraction
    # ------------------------------------------------------------------
    _cc = data.get("channel_comparison", {})
    _calls_cc = _cc.get("calls", {})
    _email_cc = _cc.get("email", {})
    _li_cc = _cc.get("linkedin", {})

    funnel_touches = ((_calls_cc.get("volume") or 0)
                      + (_email_cc.get("volume") or 0)
                      + (_li_cc.get("volume") or 0))
    funnel_responses = ((_calls_cc.get("responses") or 0)
                        + (_email_cc.get("responses") or 0)
                        + (_li_cc.get("responses") or 0))
    funnel_interested = ((_calls_cc.get("interested") or 0)
                         + (_li_cc.get("interested") or 0))
    funnel_meetings = mtg_count
    funnel_deals = deal_count
    funnel_pipeline = total_value

    def _cvr(num, denom):
        return round(num / denom * 100, 1) if denom else 0

    cvr_1 = _cvr(funnel_responses, funnel_touches)
    cvr_2 = _cvr(funnel_interested, funnel_responses)
    cvr_3 = _cvr(funnel_meetings, funnel_interested)
    cvr_4 = _cvr(funnel_deals, funnel_meetings)
    cvr_5 = _cvr(funnel_deals, funnel_touches)

    if funnel_pipeline >= 1_000_000:
        pipeline_str = f"${funnel_pipeline / 1_000_000:.1f}M"
    elif funnel_pipeline >= 1_000:
        pipeline_str = f"${funnel_pipeline / 1_000:.0f}K"
    else:
        pipeline_str = f"${funnel_pipeline:,.0f}"

    # ------------------------------------------------------------------
    # 1. KPI row
    # ------------------------------------------------------------------
    kpi_html = f"""
  <section aria-labelledby="pipeline-kpi-heading">
    <h2 class="section-heading" id="pipeline-kpi-heading">
      <span class="sh-icon" aria-hidden="true">💰</span> Pipeline Summary
    </h2>
    <div class="kpi-grid" style="margin-bottom:1.5rem;">
      <div class="kpi-card">
        <div class="kpi-value" style="font-size:1.6rem">${total_value:,.0f}</div>
        <div class="kpi-label">Pipeline Value</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value" style="font-size:1.6rem">${weighted_value:,.0f}</div>
        <div class="kpi-label">Weighted</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">{mtg_count}</div>
        <div class="kpi-label">Meetings Booked</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">{deal_count}</div>
        <div class="kpi-label">Deals Created</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value" style="font-size:1.3rem;">
          <span style="color:#a855f7;">{mars_count} MARS</span>
          <span style="color:var(--text-muted);font-size:.85rem;margin:0 .2rem;">/</span>
          <span style="color:#4285f4;">{cold_count} Cold</span>
        </div>
        <div class="kpi-label">Source Split</div>
      </div>
    </div>
  </section>"""

    # ------------------------------------------------------------------
    # 1b. Conversion funnel
    # ------------------------------------------------------------------
    # (value, label, css-color, bg-rgba, border-rgba)
    funnel_stages = [
        (f"{funnel_touches:,}", "Touches", "var(--accent-blue)", "rgba(66,133,244,.10)", "rgba(66,133,244,.25)"),
        (f"{funnel_responses:,}", "Responses", "var(--accent-teal)", "rgba(0,196,204,.10)", "rgba(0,196,204,.25)"),
        (f"{funnel_interested:,}", "Interested", "var(--accent-purple)", "rgba(168,85,247,.10)", "rgba(168,85,247,.25)"),
        (f"{funnel_meetings}", "Meetings", "var(--accent-orange)", "rgba(249,115,22,.10)", "rgba(249,115,22,.25)"),
        (f"{funnel_deals}", "Deals", "var(--accent-green)", "rgba(52,168,83,.10)", "rgba(52,168,83,.25)"),
        (pipeline_str, "Pipeline", "var(--accent-yellow)", "rgba(251,188,4,.10)", "rgba(251,188,4,.25)"),
    ]
    cvr_vals = [cvr_1, cvr_2, cvr_3, cvr_4, cvr_5]

    stage_cards = ""
    for i, (value, label, color, bg, border) in enumerate(funnel_stages):
        stage_cards += f"""
        <div class="funnel-stage">
          <div class="funnel-box" style="background:{bg};border:1px solid {border};">
            <div class="funnel-value" style="color:{color};">{value}</div>
            <div class="funnel-label">{label}</div>
          </div>"""
        if i < len(funnel_stages) - 1:
            stage_cards += f"""
          <div class="funnel-arrow">
            <svg class="funnel-arrow-svg" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" stroke-width="2"><path d="M5 12h14m-5-5 5 5-5 5"/></svg>
            <span class="funnel-cvr">{cvr_vals[i]}%</span>
          </div>"""
        stage_cards += "\n        </div>"

    funnel_html = f"""
  <section aria-labelledby="pipeline-funnel-heading" style="margin-bottom:1.5rem;">
    <h2 class="section-heading" id="pipeline-funnel-heading">
      <span class="sh-icon" aria-hidden="true">&#x1F50D;</span> Full-Funnel Conversion
      <span style="margin-left:auto;font-size:.7rem;color:var(--text-muted);font-weight:400;">{cvr_5}% touches-to-deal</span>
    </h2>
    <div class="funnel-wrap">
      {stage_cards}
    </div>
  </section>"""

    # ------------------------------------------------------------------
    # 2. Pipeline table — one flat table sorted by amount desc
    # ------------------------------------------------------------------
    stage_colors = {
        "Demo": "var(--accent-blue)",
        "Introductory Call": "var(--accent-teal)",
        "Qualified": "var(--accent-purple)",
        "Pilot": "var(--accent-green)",
        "Proposal": "var(--accent-orange)",
        "Nurture": "var(--accent-yellow)",
        "Backlog": "var(--text-muted)",
        "Blocked / Stale": "var(--accent-red, #ef4444)",
        "Closed Won": "#22c55e",
    }
    stage_bg = {
        "Demo": "rgba(66,133,244,.12)",
        "Introductory Call": "rgba(0,196,204,.12)",
        "Qualified": "rgba(168,85,247,.12)",
        "Pilot": "rgba(52,168,83,.12)",
        "Proposal": "rgba(249,115,22,.12)",
        "Nurture": "rgba(251,188,4,.12)",
        "Backlog": "rgba(90,96,120,.12)",
        "Blocked / Stale": "rgba(239,68,68,.12)",
        "Closed Won": "rgba(34,197,94,.12)",
    }

    # Sort deals: amount desc (no-deal entries last)
    sorted_deals = sorted(deals, key=lambda d: -(d["amount"] or 0))

    table_rows = ""
    for deal in sorted_deals:
        channel = deal.get("channel", "Cold Call")
        if channel == "MARS":
            src_badge = '<span style="display:inline-block;padding:.15rem .5rem;border-radius:999px;font-size:.6rem;font-weight:600;background:rgba(168,85,247,.15);color:#a855f7;">MARS</span>'
        else:
            src_badge = '<span style="display:inline-block;padding:.15rem .5rem;border-radius:999px;font-size:.6rem;font-weight:600;background:rgba(66,133,244,.15);color:#4285f4;">Cold Call</span>'

        company = deal["company_name"] or deal["name"]
        amount = deal["amount"]
        amount_str = f"${amount:,.0f}" if amount else "\u2014"
        stage_label = deal["stage_label"]
        color = stage_colors.get(stage_label, "var(--text-muted)")
        bg = stage_bg.get(stage_label, "rgba(90,96,120,.08)")
        stage_badge = f'<span style="display:inline-block;padding:.15rem .5rem;border-radius:999px;font-size:.65rem;font-weight:600;background:{bg};color:{color};">{_h(stage_label)}</span>' if stage_label and stage_label != "\u2014" else "\u2014"
        close = _h(deal["close_date"][:10]) if deal.get("close_date") else "\u2014"

        table_rows += f"""
          <tr class="pipe-deal-row" style="cursor:default;">
            <td style="font-weight:600;color:var(--text-primary);">{_h(company)}</td>
            <td>{src_badge}</td>
            <td style="font-variant-numeric:tabular-nums;text-align:right;font-weight:500;color:var(--text-primary);">{amount_str}</td>
            <td>{stage_badge}</td>
            <td style="font-variant-numeric:tabular-nums;color:var(--text-secondary);">{close}</td>
          </tr>"""

    pipeline_html = f"""
  <section aria-labelledby="pipeline-deals-heading">
    <h2 class="section-heading" id="pipeline-deals-heading">
      <span class="sh-icon" aria-hidden="true">🏗️</span> Pipeline ({len(deals)})
    </h2>
    <div class="table-wrap">
      <table class="pipeline-table" aria-label="Outbound pipeline" id="deal-pipeline-table">
        <thead><tr>
          <th scope="col">Company</th>
          <th scope="col">Source</th>
          <th scope="col" style="text-align:right">Amount</th>
          <th scope="col">Stage</th>
          <th scope="col">Close Date</th>
        </tr></thead>
        <tbody id="deal-table-body">{table_rows}</tbody>
      </table>
    </div>
  </section>"""

    chart_html = """
  <section aria-labelledby="pipeline-chart-heading" style="margin-bottom:1.5rem;">
    <h2 class="section-heading" id="pipeline-chart-heading">
      <span class="sh-icon" aria-hidden="true">📊</span> Pipeline by Stage
    </h2>
    <div style="max-width:600px;margin:0 auto;">
      <canvas id="pipeline-stage-chart" height="260"></canvas>
    </div>
  </section>"""

    return f"""
<section id="tab-pipeline"
         class="tab-panel app-wrapper"
         role="tabpanel"
         aria-labelledby="tab-btn-pipeline"
         aria-hidden="true">
  {kpi_html}
  {funnel_html}
  {chart_html}
  {pipeline_html}
</section>"""


# ---------------------------------------------------------------------------
# Tab 6: Experiments / Channel Performance
# ---------------------------------------------------------------------------

def _tab_experiments(data: dict) -> str:
    cc = data.get("channel_comparison", {})
    calls_data = cc.get("calls", {})
    email_data = cc.get("email", {})
    li_data = cc.get("linkedin", {})

    # Comparison table rows
    def _metric_row(label, calls_val, email_val, li_val, fmt="d"):
        def _fmt(v):
            if v is None:
                return "—"
            if fmt == "pct":
                return f"{v:.1f}%"
            return str(v)
        return f"""
          <tr>
            <td style="font-weight:500">{_h(label)}</td>
            <td style="font-variant-numeric:tabular-nums;text-align:right">{_fmt(calls_val)}</td>
            <td style="font-variant-numeric:tabular-nums;text-align:right">{_fmt(email_val)}</td>
            <td style="font-variant-numeric:tabular-nums;text-align:right">{_fmt(li_val)}</td>
          </tr>"""

    table_rows = ""
    table_rows += _metric_row("Volume", calls_data.get("volume"), email_data.get("volume"), li_data.get("volume"))
    table_rows += _metric_row("Responses", calls_data.get("responses"), email_data.get("responses"), li_data.get("responses"))
    table_rows += _metric_row("Response rate", calls_data.get("response_rate"), email_data.get("response_rate"), li_data.get("response_rate"), "pct")
    table_rows += _metric_row("Interested", calls_data.get("interested"), email_data.get("interested"), li_data.get("interested"))
    table_rows += _metric_row("Meetings booked", calls_data.get("meetings"), email_data.get("meetings"), li_data.get("meetings"))

    # Meeting rate: meetings per 100 volume (the real conversion metric)
    def _mtg_rate(ch):
        vol = ch.get("volume", 0)
        mtg = ch.get("meetings", 0)
        return round(mtg / vol * 100, 2) if vol else 0
    calls_mtg = _mtg_rate(calls_data)
    email_mtg = _mtg_rate(email_data)
    li_mtg = _mtg_rate(li_data)
    table_rows += _metric_row("Meeting rate (per 100)", calls_mtg, email_mtg, li_mtg, "pct")

    # Best channel callout — by meeting rate, fall back to response rate
    mtg_rates = [("Cold Calls", calls_mtg), ("Email", email_mtg), ("LinkedIn", li_mtg)]
    mtg_active = [(n, r) for n, r in mtg_rates if r > 0]
    if mtg_active:
        best = max(mtg_active, key=lambda x: x[1])
        best_html = f'<div style="margin-top:1rem;padding:.75rem 1rem;background:rgba(52,168,83,0.08);border-radius:var(--radius);border-left:3px solid var(--accent-green);font-size:.85rem;color:var(--text-secondary);">Best meeting conversion: <strong style="color:var(--text-primary)">{_h(best[0])}</strong> at {best[1]:.2f} per 100 outreach</div>'
    else:
        resp_rates = [("Cold Calls", calls_data.get("response_rate", 0)), ("Email", email_data.get("response_rate", 0)), ("LinkedIn", li_data.get("response_rate", 0))]
        resp_active = [(n, r) for n, r in resp_rates if r > 0]
        best = max(resp_active, key=lambda x: x[1]) if resp_active else None
        best_html = f'<div style="margin-top:1rem;padding:.75rem 1rem;background:rgba(52,168,83,0.08);border-radius:var(--radius);border-left:3px solid var(--accent-green);font-size:.85rem;color:var(--text-secondary);">Highest response rate: <strong style="color:var(--text-primary)">{_h(best[0])}</strong> at {best[1]:.1f}%</div>' if best else ""

    # Experiments section (if any exist)
    experiments = data.get("experiments", [])
    exp_section = ""
    if experiments:
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
          {f'<span class="experiment-meta-item">{_h(exp.get("channel",""))}</span>' if exp.get("channel") else ''}
          {f'<span class="experiment-meta-item">{_h(date_range)}</span>' if date_range else ''}
        </div>
        {f'<div class="experiment-result"><strong>Result:</strong> {_h(result)}</div>' if result else ''}
      </article>"""
        exp_section = f"""
  <section aria-labelledby="experiments-heading" style="margin-top:1.5rem;">
    <h2 class="section-heading" id="experiments-heading">
      <span class="sh-icon" aria-hidden="true">🧪</span> Active Experiments
    </h2>
    {exp_cards}
  </section>"""

    return f"""
<section id="tab-experiments"
         class="tab-panel app-wrapper"
         role="tabpanel"
         aria-labelledby="tab-btn-experiments"
         aria-hidden="true">

  <section aria-labelledby="channel-compare-heading">
    <h2 class="section-heading" id="channel-compare-heading">
      <span class="sh-icon" aria-hidden="true">📊</span> Channel Efficiency
    </h2>

    <div class="card chart-card" style="margin-bottom:1.5rem;">
      <div class="chart-container" style="height:300px;">
        <canvas id="channel-compare-chart" aria-label="Channel efficiency comparison" role="img"></canvas>
      </div>
    </div>

    <div class="table-wrap">
      <table aria-label="Channel comparison">
        <thead>
          <tr>
            <th scope="col">Metric</th>
            <th scope="col" style="text-align:right">Cold Calls</th>
            <th scope="col" style="text-align:right">Email</th>
            <th scope="col" style="text-align:right">LinkedIn</th>
          </tr>
        </thead>
        <tbody>{table_rows}</tbody>
      </table>
    </div>

    {best_html}
  </section>

  {exp_section}
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
    deal_pipeline  = data.get("deal_pipeline", {})

    # Serialize data subsets
    call_trends_json  = _j(call_trends)
    inmail_trends_json = _j(inmail_trends)
    call_log_json     = _j(call_log)
    companies_json    = _j(companies)
    channel_compare_json = _j(data.get("channel_comparison", {}))
    deal_pipeline_json = _j(deal_pipeline)

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
const CHANNEL_COMPARE = {channel_compare_json};
const DEAL_PIPELINE = {deal_pipeline_json};

// ============================================================
// Tab switching
// ============================================================
let callingChartsRendered  = false;
let linkedinChartsRendered = false;
let channelChartRendered   = false;
let pipelineChartRendered  = false;

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
  if (tabId === 'calling'     && !callingChartsRendered)  {{ initCallingCharts();  callingChartsRendered = true; }}
  if (tabId === 'linkedin'    && !linkedinChartsRendered) {{ initOutreachCharts(); linkedinChartsRendered = true; }}
  if (tabId === 'pipeline'    && !pipelineChartRendered)  initPipelineChart();
  if (tabId === 'experiments' && !channelChartRendered)   initChannelChart();

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
            type: 'linear', position: 'left', min: 0,
            ticks: {{ color: '#9aa0b4', font: {{ size: 10 }} }},
            grid:  {{ color: '#2d3348' }},
            title: {{ display: true, text: 'Count', color: '#5a6078', font: {{ size: 10 }} }}
          }},
          y1: {{
            type: 'linear', position: 'right', min: 0,
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
            type: 'line', label: 'Reply Rate %', data: rr,
            borderColor: '#34a853', backgroundColor: 'transparent',
            pointBackgroundColor: '#34a853', pointRadius: 4, tension: 0.3,
            yAxisID: 'y1',
          }},
          {{
            type: 'line', label: 'Replied', data: replied,
            borderColor: '#a855f7', backgroundColor: 'transparent',
            pointStyle: 'circle', pointRadius: 6, pointBackgroundColor: '#a855f7',
            tension: 0, yAxisID: 'y',
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
            type: 'linear', position: 'left', min: 0,
            ticks: {{ color: '#9aa0b4', font: {{ size: 10 }} }}, grid: {{ color: '#2d3348' }},
            title: {{ display: true, text: 'Count', color: '#5a6078', font: {{ size: 10 }} }}
          }},
          y1: {{
            type: 'linear', position: 'right', min: 0,
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
// Pipeline Chart
// ============================================================
function initPipelineChart() {{
  pipelineChartRendered = true;
  var ctx = document.getElementById('pipeline-stage-chart');
  if (!ctx || !DEAL_PIPELINE || !DEAL_PIPELINE.by_stage) return;

  var stageOrder = DEAL_PIPELINE.stage_order || [];
  var byStage = DEAL_PIPELINE.by_stage || {{}};
  var stageColors = {{
    'Demo': '#4285f4',
    'Introductory Call': '#00c4cc',
    'Qualified': '#a855f7',
    'Pilot': '#34a853',
    'Proposal': '#f97316',
    'Nurture': '#fbbc04',
    'Backlog': '#5a6078',
    'Blocked / Stale': '#ef4444',
    'Closed Won': '#22c55e',
  }};

  var labels = [];
  var values = [];
  var counts = [];
  var colors = [];

  stageOrder.forEach(function(stage) {{
    var deals = byStage[stage];
    if (!deals || deals.length === 0) return;
    var total = deals.reduce(function(sum, d) {{ return sum + (d.amount || 0); }}, 0);
    labels.push(stage);
    values.push(total);
    counts.push(deals.length);
    colors.push(stageColors[stage] || '#5a6078');
  }});

  var cfg = chartDefaults();
  new Chart(ctx, {{
    type: 'bar',
    data: {{
      labels: labels,
      datasets: [{{
        label: 'Pipeline Value ($)',
        data: values,
        backgroundColor: colors.map(function(c) {{ return c + 'AA'; }}),
        borderColor: colors,
        borderWidth: 1,
        borderRadius: 4,
      }}]
    }},
    options: Object.assign(cfg, {{
      indexAxis: 'y',
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          backgroundColor: '#222633',
          borderColor: '#2d3348',
          borderWidth: 1,
          titleColor: '#e8eaed',
          bodyColor: '#9aa0b4',
          callbacks: {{
            label: function(ctx) {{
              var val = ctx.raw || 0;
              var count = counts[ctx.dataIndex] || 0;
              return '$' + val.toLocaleString() + ' (' + count + ' deal' + (count !== 1 ? 's' : '') + ')';
            }}
          }}
        }}
      }},
      scales: {{
        x: {{
          min: 0,
          ticks: {{
            color: '#9aa0b4',
            font: {{ size: 10 }},
            callback: function(v) {{
              if (v >= 1000000) return '$' + (v/1000000).toFixed(1) + 'M';
              if (v >= 1000) return '$' + (v/1000).toFixed(0) + 'K';
              return '$' + v;
            }}
          }},
          grid: {{ color: '#2d3348' }},
          title: {{ display: true, text: 'Deal Value', color: '#5a6078', font: {{ size: 10 }} }}
        }},
        y: {{
          ticks: {{ color: '#e8eaed', font: {{ size: 11 }} }},
          grid: {{ display: false }},
        }}
      }}
    }})
  }});
}}


// ============================================================
// Deal table filter
// ============================================================
function filterDeals() {{
  var search = (document.getElementById('deal-search').value || '').toLowerCase();
  var stage  = document.getElementById('deal-stage-filter').value || '';
  var tbody  = document.getElementById('deal-table-body');
  if (!tbody) return;

  var allRows = Array.from(tbody.querySelectorAll('tr'));
  var currentStage = '';
  var stageVisible = false;

  allRows.forEach(function(row) {{
    // Stage header rows have the pipe-stage-row class
    if (row.classList.contains('pipe-stage-row')) {{
      var headerText = row.textContent || '';
      currentStage = headerText.trim().split('\\n')[0].trim();
      // Defer visibility -- will show if any child rows match
      row.style.display = 'none';
      row._matchedChildren = 0;
      return;
    }}

    // Deal row
    var text = row.textContent.toLowerCase();
    var matchSearch = !search || text.indexOf(search) !== -1;
    var matchStage = !stage || currentStage.indexOf(stage) !== -1;
    var visible = matchSearch && matchStage;
    row.style.display = visible ? '' : 'none';

    // Track if this stage header should show
    if (visible) {{
      // Find the preceding stage header and show it
      var prev = row.previousElementSibling;
      while (prev) {{
        if (prev.classList && prev.classList.contains('pipe-stage-row')) {{
          prev.style.display = '';
          break;
        }}
        prev = prev.previousElementSibling;
      }}
    }}
  }});
}}


// ============================================================
// Channel Comparison Chart
// ============================================================
function initChannelChart() {{
  channelChartRendered = true;
  var ctx = document.getElementById('channel-compare-chart');
  if (!ctx || !CHANNEL_COMPARE) return;
  var cc = CHANNEL_COMPARE;
  var labels = ['Cold Calls', 'Email', 'LinkedIn'];

  // Per-100 normalization for fair cross-channel comparison
  var vol = [cc.calls?.volume||0, cc.email?.volume||0, cc.linkedin?.volume||0];
  var resp = [cc.calls?.responses||0, cc.email?.responses||0, cc.linkedin?.responses||0];
  var interested = [cc.calls?.interested||0, cc.email?.interested||0, cc.linkedin?.interested||0];
  var meetings = [cc.calls?.meetings||0, cc.email?.meetings||0, cc.linkedin?.meetings||0];
  var per100Resp = vol.map(function(v,i) {{ return v ? Math.round(resp[i]/v*100*10)/10 : 0; }});
  var per100Int  = vol.map(function(v,i) {{ return v ? Math.round(interested[i]/v*100*10)/10 : 0; }});
  var per100Mtg  = vol.map(function(v,i) {{ return v ? Math.round(meetings[i]/v*100*10)/10 : 0; }});

  var cfg = chartDefaults();
  new Chart(ctx, {{
    type: 'bar',
    data: {{
      labels: labels,
      datasets: [
        {{
          label: 'Response rate %', data: per100Resp,
          backgroundColor: 'rgba(66,133,244,.55)',
          borderColor: 'rgba(66,133,244,.9)',
          borderWidth: 1, borderRadius: 4,
        }},
        {{
          label: 'Interested %', data: per100Int,
          backgroundColor: 'rgba(251,188,4,.55)',
          borderColor: 'rgba(251,188,4,.9)',
          borderWidth: 1, borderRadius: 4,
        }},
        {{
          label: 'Meetings booked %', data: per100Mtg,
          backgroundColor: 'rgba(52,168,83,.55)',
          borderColor: 'rgba(52,168,83,.9)',
          borderWidth: 1, borderRadius: 4,
        }},
      ]
    }},
    options: Object.assign(cfg, {{
      indexAxis: 'y',
      scales: {{
        x: {{
          min: 0,
          ticks: {{ color: '#9aa0b4', font: {{ size: 10 }}, callback: function(v) {{ return v + '%'; }} }},
          grid: {{ color: '#2d3348' }},
          title: {{ display: true, text: 'Rate per 100 outreach', color: '#5a6078', font: {{ size: 10 }} }}
        }},
        y: {{
          ticks: {{ color: '#e8eaed', font: {{ size: 12 }} }},
          grid: {{ display: false }},
        }}
      }}
    }})
  }});
}}


// ============================================================
// Insights: show/hide overflow cards
// ============================================================
function toggleInsights(btn) {{
  var hidden = document.querySelector('.insights-hidden');
  if (!hidden) return;
  var isHidden = hidden.style.display === 'none';
  hidden.style.display = isHidden ? '' : 'none';
  var total = document.querySelectorAll('.insight-card').length;
  btn.textContent = isHidden ? 'Show fewer \u25b4' : 'Show all ' + total + ' insights \u25be';
}}


// ============================================================
// Call log: filter + pagination
// ============================================================
var callLogRows  = [];
var callLogPage_ = 0;
var callPageSize = 20;

function buildCallLogRows() {{
  var search = (document.getElementById('call-search').value || '').toLowerCase();
  var cat    = (document.getElementById('call-cat-filter').value || '');
  var tbody  = document.getElementById('call-log-body');
  if (!tbody) return;
  var allRows = Array.from(tbody.querySelectorAll('tr:not(.detail-row)'));
  callLogRows = allRows.filter(function(tr) {{
    var text = tr.textContent.toLowerCase();
    var matchSearch = !search || text.indexOf(search) !== -1;
    var matchCat    = !cat    || (tr.dataset.category || '') === cat;
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

function toggleCompanyRow(tr) {{
  var coId = tr.dataset.coId;
  if (!coId) return;
  var det = document.getElementById(coId);
  var expanded = tr.classList.toggle('expanded');
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
// Companies: filter + sort + pagination
// ============================================================
var coRows = [];
var coPage_ = 0;
var coPageSize = 50;

function filterCompanies() {{
  var search  = (document.getElementById('company-search').value || '').toLowerCase();
  var status  = document.getElementById('company-status-filter').value;
  var channel = document.getElementById('company-channel-filter').value;
  var know    = document.getElementById('company-knowledge-filter').value;
  var dateVal = document.getElementById('company-date-filter').value;
  var sortBy  = document.getElementById('company-sort').value;
  var tbody   = document.querySelector('#company-table tbody');
  if (!tbody) return;
  var allRows = Array.from(tbody.querySelectorAll('tr:not(.detail-row)'));
  // Hide all detail rows when re-filtering
  Array.from(tbody.querySelectorAll('tr.detail-row')).forEach(function(d) {{ d.style.display = 'none'; }});
  Array.from(tbody.querySelectorAll('tr.expanded')).forEach(function(r) {{ r.classList.remove('expanded'); }});

  coRows = allRows.filter(function(r) {{
    var name = r.getAttribute('data-name') || '';
    var st   = r.getAttribute('data-status') || '';
    var ch   = r.getAttribute('data-channels') || '';
    var lt   = r.getAttribute('data-lasttouch') || '';
    if (search && name.indexOf(search) < 0) return false;
    if (status && st !== status) return false;
    if (channel && ch.indexOf(channel) < 0) return false;
    if (dateVal && lt !== dateVal) return false;
    if (know === 'has_provider' && r.getAttribute('data-has-provider') !== '1') return false;
    if (know === 'has_commodities' && r.getAttribute('data-has-commodities') !== '1') return false;
    if (know === 'has_contact' && r.getAttribute('data-has-contact') !== '1') return false;
    return true;
  }});

  // Sort
  if (sortBy === 'name') {{
    coRows.sort(function(a, b) {{
      return (a.getAttribute('data-name') || '').localeCompare(b.getAttribute('data-name') || '');
    }});
  }} else {{
    coRows.sort(function(a, b) {{
      return (b.getAttribute('data-lasttouch') || '').localeCompare(a.getAttribute('data-lasttouch') || '');
    }});
  }}

  var countEl = document.getElementById('companies-count');
  if (countEl) countEl.textContent = coRows.length + ' total';
  coPage_ = 0;
  renderCompanyTablePage();
}}

function renderCompanyTablePage() {{
  var total = coRows.length;
  var pages = Math.max(1, Math.ceil(total / coPageSize));
  var start = coPage_ * coPageSize;
  var end   = Math.min(start + coPageSize, total);
  var tbody = document.querySelector('#company-table tbody');
  if (!tbody) return;
  Array.from(tbody.querySelectorAll('tr')).forEach(function(r) {{ r.style.display = 'none'; }});
  coRows.slice(start, end).forEach(function(r) {{
    r.style.display = '';
    // Show detail row if this row is expanded
    var coId = r.dataset.coId;
    if (coId && r.classList.contains('expanded')) {{
      var det = document.getElementById(coId);
      if (det) det.style.display = '';
    }}
  }});
  var info = document.getElementById('company-page-info');
  if (info) info.textContent = total ? ((start+1) + '–' + end + ' of ' + total) : '0 companies';
  var btns = document.getElementById('co-page-btns');
  if (btns) {{
    btns.innerHTML = '';
    for (var i = 0; i < pages && i < 10; i++) {{
      var b = document.createElement('button');
      b.className = 'page-btn' + (i === coPage_ ? ' active' : '');
      b.textContent = i + 1;
      b.onclick = (function(p) {{ return function() {{ coPage_ = p; renderCompanyTablePage(); }}; }})(i);
      btns.appendChild(b);
    }}
  }}
  var prev = document.getElementById('co-prev-btn');
  var next = document.getElementById('co-next-btn');
  if (prev) prev.disabled = coPage_ === 0;
  if (next) next.disabled = coPage_ >= pages - 1;
}}

function companyPage(dir) {{
  var pages = Math.max(1, Math.ceil(coRows.length / coPageSize));
  coPage_ = Math.max(0, Math.min(pages - 1, coPage_ + dir));
  renderCompanyTablePage();
}}


// ============================================================
// Init on load
// ============================================================
window.addEventListener('DOMContentLoaded', function() {{
  // Init call log pagination
  var tbody = document.getElementById('call-log-body');
  if (tbody) {{
    callLogRows = Array.from(tbody.querySelectorAll('tr:not(.detail-row)'));
    renderCallLogPage();
  }}
  // Init company table
  filterCompanies();
  // Start live data polling
  fetchLiveToday();
  setInterval(fetchLiveToday, 120000); // every 2 min
}});

// ============================================================
// Live Today — fetch today's calls from Supabase in real-time
// ============================================================
var SUPA_URL = 'https://giptkpwwhwhtrrrmdfqt.supabase.co/rest/v1';
var SUPA_KEY = 'sb_publishable_QYwzbS_t_lEtO8LqtrW7zg_0St7HQVs';
var HUMAN_CONTACT_CATS = ['Interested','Not Interested','Meeting Booked','Referral Given','No Rail','Wrong Person','Gatekeeper','Call Back','Pitched'];

function fetchLiveToday() {{
  var today = new Date();
  var yyyy = today.getFullYear();
  var mm = String(today.getMonth() + 1).padStart(2, '0');
  var dd = String(today.getDate()).padStart(2, '0');
  var todayStr = yyyy + '-' + mm + '-' + dd;

  var url = SUPA_URL + '/calls?called_at=gte.' + todayStr + 'T00:00:00&select=category,duration_s,called_at,contact_name,companies(name)&order=called_at.desc';

  fetch(url, {{
    headers: {{
      'apikey': SUPA_KEY,
      'Authorization': 'Bearer ' + SUPA_KEY
    }}
  }})
  .then(function(r) {{ return r.json(); }})
  .then(function(calls) {{
    if (!calls || !calls.length) {{
      // No calls yet today — still show the banner with zeros
      var banner = document.getElementById('live-today-banner');
      if (banner) {{
        banner.style.display = 'block';
        document.getElementById('live-dials').textContent = '0';
        document.getElementById('live-contacts').textContent = '0';
        document.getElementById('live-contact-pct').textContent = '—';
        document.getElementById('live-interested').textContent = '0';
        document.getElementById('live-meetings').textContent = '0';
        document.getElementById('live-vms').textContent = '0';
        document.getElementById('live-timestamp').textContent = 'No calls yet · updated ' + new Date().toLocaleTimeString([], {{hour:'2-digit',minute:'2-digit'}});
        document.getElementById('live-recent').innerHTML = '<span style="color:var(--text-muted)">No calls recorded today yet.</span>';
      }}
      return;
    }}

    var dials = calls.length;
    var contacts = 0, interested = 0, meetings = 0, vms = 0;
    calls.forEach(function(c) {{
      var cat = c.category || '';
      if (HUMAN_CONTACT_CATS.indexOf(cat) !== -1) contacts++;
      if (cat === 'Interested') interested++;
      if (cat === 'Meeting Booked') meetings++;
      if (cat === 'Left Voicemail') vms++;
    }});
    var contactPct = dials > 0 ? (contacts / dials * 100).toFixed(1) + '%' : '—';

    document.getElementById('live-today-banner').style.display = 'block';
    document.getElementById('live-dials').textContent = dials;
    document.getElementById('live-contacts').textContent = contacts;
    document.getElementById('live-contact-pct').textContent = contactPct;
    document.getElementById('live-interested').textContent = interested;
    document.getElementById('live-meetings').textContent = meetings;
    document.getElementById('live-vms').textContent = vms;
    document.getElementById('live-timestamp').textContent = 'updated ' + new Date().toLocaleTimeString([], {{hour:'2-digit',minute:'2-digit'}});

    // Show last 5 calls
    var recent = calls.slice(0, 5);
    var recentHtml = '<strong>Recent:</strong> ';
    recent.forEach(function(c, i) {{
      var time = new Date(c.called_at).toLocaleTimeString([], {{hour:'2-digit',minute:'2-digit'}});
      var name = c.contact_name || '?';
      var co = (c.companies && c.companies.name) || '';
      var cat = c.category || '';
      var catColor = cat === 'Interested' ? 'var(--accent-green)' : cat === 'Meeting Booked' ? 'var(--accent-blue)' : 'var(--text-muted)';
      recentHtml += '<span style="margin-right:1rem;">' + time + ' ' + name + (co ? ' @ ' + co : '') + ' <span style="color:' + catColor + '">' + cat + '</span></span>';
    }});
    document.getElementById('live-recent').innerHTML = recentHtml;

    // Also update the Home tab KPI if visible
    var homeDialsEl = document.querySelector('#tab-home [data-live-dials]');
    if (homeDialsEl) homeDialsEl.textContent = dials;
  }})
  .catch(function(err) {{
    console.warn('Live fetch failed:', err);
  }});
}}
</script>"""


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_html(data: dict) -> str:
    from datetime import datetime as _dt, timezone as _tz
    _build_ts = _dt.now(_tz.utc).strftime("%Y%m%d%H%M%S")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="build-ts" content="{_build_ts}">
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
    {_tab_email(data)}
    {_tab_linkedin(data)}
    {_tab_companies(data)}
    {_tab_pipeline(data)}
    {_tab_experiments(data)}
  </main>
  {_footer(data)}
  {_scripts(data)}
  <script>
  // Auto-update: check for new build every 2 min, bypass CDN with cache-busting param
  (function() {{
    var current = document.querySelector('meta[name="build-ts"]');
    if (!current) return;
    var myTs = current.getAttribute('content');
    setInterval(function() {{
      fetch(location.pathname + '?_cb=' + Date.now(), {{cache: 'no-store'}})
        .then(function(r) {{ return r.text(); }})
        .then(function(html) {{
          var m = html.match(/name="build-ts"\\s+content="(\\d+)"/);
          if (m && m[1] !== myTs) location.reload();
        }})
        .catch(function() {{}});
    }}, 120000);
  }})();
  </script>
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
