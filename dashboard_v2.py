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
        ("calling",    "Cold Calling"),
        ("outreach",   "Email & LinkedIn"),
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
    wow = ov.get("wow_deltas", {})
    insights = data.get("insights", [])
    companies = data.get("companies", [])
    pipeline_counts = ov.get("pipeline", {})

    # Week label
    wk_num = tw.get("week_num")
    wk_label = f"Week {wk_num}" if wk_num else "This Week"

    # Keep kpi() helper for potential reuse elsewhere
    def kpi(value, label, delta_key, prev_value=None, suffix="", no_delta=False):
        display = str(value) if value is not None else "\u2014"
        is_none = value is None
        muted_class = " kpi-card-muted" if is_none else ""

        delta_html = ""
        if not no_delta and delta_key:
            raw_delta = wow.get(delta_key, 0)
            try:
                dv = float(str(raw_delta).replace("+", ""))
            except (ValueError, TypeError):
                dv = 0
            if dv != 0:
                cls = "delta-up" if dv > 0 else "delta-down"
                sign = "+" if dv > 0 else ""
                delta_html = f'<span class="{cls}">{sign}{dv:g}{suffix}</span>'

        context_html = ""
        if prev_value is not None and not is_none:
            context_html = f'<span class="delta-context"> (was {_h(str(prev_value))} last wk)</span>'
        elif is_none:
            context_html = '<span class="delta-context">No data this week</span>'

        return f"""
    <div class="kpi-card{muted_class}" role="article" aria-label="{_h(label)}: {_h(display)}">
      <div class="kpi-value">{_h(display)}</div>
      <div class="kpi-label">{_h(label)}</div>
      <div class="kpi-delta">{delta_html}{context_html}</div>
    </div>"""

    # ------------------------------------------------------------------
    # 1. Pipeline bar
    # ------------------------------------------------------------------
    p_prospect = pipeline_counts.get("prospect", 0)
    p_contacted = pipeline_counts.get("contacted", 0)
    p_interested = pipeline_counts.get("interested", 0)
    p_meeting = pipeline_counts.get("meeting_booked", 0)

    pipeline_html = f"""
  <section aria-labelledby="home-pipeline-heading">
    <div class="pipeline-bar" role="img" aria-label="Sales pipeline: {p_prospect} prospect, {p_contacted} contacted, {p_interested} interested, {p_meeting} meetings booked">
      <div class="pipeline-segment ps-prospect">
        <span class="pipe-count">{p_prospect}</span>
        <span class="pipe-label">Prospect</span>
        <span class="pipe-arrow" aria-hidden="true">&rsaquo;</span>
      </div>
      <div class="pipeline-segment ps-contacted">
        <span class="pipe-count">{p_contacted}</span>
        <span class="pipe-label">Contacted</span>
        <span class="pipe-arrow" aria-hidden="true">&rsaquo;</span>
      </div>
      <div class="pipeline-segment ps-interested">
        <span class="pipe-count">{p_interested}</span>
        <span class="pipe-label">Interested</span>
        <span class="pipe-arrow" aria-hidden="true">&rsaquo;</span>
      </div>
      <div class="pipeline-segment ps-meeting">
        <span class="pipe-count">{p_meeting}</span>
        <span class="pipe-label">Meetings</span>
      </div>
    </div>
  </section>"""

    # ------------------------------------------------------------------
    # 2. Action queue — companies needing attention
    # ------------------------------------------------------------------
    action_candidates = []
    for co in companies:
        status = (co.get("status") or "").lower()
        if status not in ("interested", "meeting_booked"):
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

    # Sort: meeting_booked first, then interested, then by most recent touch
    status_priority = {"meeting_booked": 0, "interested": 1}
    action_candidates.sort(key=lambda a: (
        status_priority.get(a["status"], 9),
        "" if not a.get("last_touch") else a["last_touch"],
    ), reverse=False)
    # Secondary sort: most recent touch first within same priority
    action_candidates.sort(key=lambda a: a.get("last_touch") or "", reverse=True)
    action_candidates.sort(key=lambda a: status_priority.get(a["status"], 9))

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
      <span class="sh-icon" aria-hidden="true">🎯</span> Action Queue
    </h2>
    <div class="action-queue">
      {action_items_html}
    </div>
  </section>"""
    else:
        action_queue_html = ""

    # ------------------------------------------------------------------
    # 3. Week summary — compact single line
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

    # Build compact metric spans
    parts = []
    if dials or lw_dials:
        parts.append(f'<strong class="ws-metric">{dials}</strong> dials <span class="ws-prev">(was {lw_dials})</span>')
        parts.append(f'<strong class="ws-metric">{cr:.1f}%</strong> contact rate <span class="ws-prev">(was {lw_cr:.1f}%)</span>')
        parts.append(f'<strong class="ws-metric">{meetings}</strong> {"meeting" if meetings == 1 else "meetings"} <span class="ws-prev">(was {lw_meetings})</span>')
    if inmails_sent or lw_inmails:
        parts.append(f'<strong class="ws-metric">{inmails_sent}</strong> inmails <span class="ws-prev">(was {lw_inmails})</span>')

    week_summary_inner = " &middot; ".join(parts)
    week_summary_html = f"""
  <section aria-labelledby="home-week-heading">
    <h2 class="section-heading" id="home-week-heading">
      <span class="sh-icon" aria-hidden="true">📊</span> {_h(wk_label)}
    </h2>
    <div class="week-summary" role="status">{week_summary_inner if week_summary_inner else "No activity data this week."}</div>
  </section>"""

    # ------------------------------------------------------------------
    # 4. Advisor Insights — keep as-is
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
    # 5. Channels This Week — keep as-is
    # ------------------------------------------------------------------
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
    ch_email_metric = f"{total_email_sent} sent" if total_email_sent else "\u2014"
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
  {pipeline_html}
  {action_queue_html}
  {week_summary_html}
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
    for call in call_log:
        dur = _fmt_dur(call.get("duration_s", 0))
        _raw_summary = (call.get("summary") or "").strip()
        _raw_summary = _re.sub(r'^(#+\s+\S.*?\n)+', '', _raw_summary).strip()
        summary = _raw_summary.replace("\n", " ")[:200]
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
          <td style="color:var(--text-secondary);font-size:.75rem;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="{_h(im.get("contact_title",""))}">{_h((im.get("contact_title","") or "")[:50] + ("…" if len(im.get("contact_title","") or "") > 50 else ""))}</td>
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

    # Knowledge-filter: has intel
    knowledge_options = '<option value="">All companies</option><option value="has_provider">Has provider</option><option value="has_commodities">Has commodities</option><option value="has_contact">Has contact</option>'

    from datetime import date as _date
    today_str = _date.today().isoformat()

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

        # CRM fields
        industry = co.get("industry") or ""
        provider = co.get("current_provider") or ""
        commodities = co.get("commodities") or ""
        renewal_date = str(co.get("contract_renewal_date") or "")[:10]
        next_action = co.get("next_action") or ""
        next_action_date = str(co.get("next_action_date") or "")[:10]
        contact_name = co.get("contact_name") or ""
        contact_role = co.get("contact_role") or ""
        notes = co.get("notes") or ""

        # Card accent class based on urgency
        card_class = "company-card"
        if renewal_date and renewal_date <= today_str:
            card_class += " has-renewal"
        elif next_action:
            card_class += " has-action"

        # Data attributes for sorting and filtering
        sort_renewal = renewal_date or "9999-12-31"
        sort_action = next_action_date or "9999-12-31"
        ch_list_str = " ".join(channels)

        # Data attributes for knowledge filter
        has_provider = "1" if provider else "0"
        has_commodities = "1" if commodities else "0"
        has_contact = "1" if contact_name else "0"

        # ----------------------------------------------------------
        # Card layout: Header -> Knowledge -> Next Action -> Meta line -> Expandable detail
        # ----------------------------------------------------------

        # 1. Header: name + status badge
        header_html = f"""
        <div class="company-card-header">
          <span class="company-name">{_h(name)}</span>
          <span class="badge badge-{_h(status)}">{_h(status.replace('_',' ').title())}</span>
        </div>"""

        # 2. Knowledge section
        knowledge_rows = []
        if industry:
            knowledge_rows.append(f'<div class="ck-row"><span class="ck-label">Industry</span><span class="ck-value">{_h(industry)}</span></div>')
        if provider:
            knowledge_rows.append(f'<div class="ck-row"><span class="ck-label">Provider</span><span class="ck-value">&rarr; {_h(provider)}</span></div>')
        if commodities:
            knowledge_rows.append(f'<div class="ck-row"><span class="ck-label">Ships</span><span class="ck-value">{_h(commodities[:100])}</span></div>')
        if contact_name:
            role_part = f" ({_h(contact_role)})" if contact_role else ""
            knowledge_rows.append(f'<div class="ck-row"><span class="ck-label">Contact</span><span class="ck-value">{_h(contact_name)}{role_part}</span></div>')

        knowledge_html = ""
        if knowledge_rows:
            knowledge_html = f'<div class="company-knowledge">{"".join(knowledge_rows)}</div>'

        # 3. Next action (blue box)
        action_html = ""
        if next_action:
            date_part = f'<span class="action-date">{_h(next_action_date)}</span>' if next_action_date else ""
            action_html = f'<div class="company-next-action">{_h(next_action[:100])}{date_part}</div>'
        elif intel and intel.get("next_action"):
            na = intel["next_action"]
            action_html = f'<div class="company-next-action">{_h(na[:100])}</div>'

        # Contract renewal badge (inline in meta)
        renewal_part = ""
        if renewal_date and renewal_date != "":
            overdue = renewal_date <= today_str
            if overdue:
                renewal_part = f' &middot; <span style="color:var(--accent-red);">Renewal overdue: {_h(renewal_date)}</span>'
            else:
                renewal_part = f' &middot; <span style="color:var(--accent-orange);">Renewal: {_h(renewal_date)}</span>'

        # 4. Meta line (compact, demoted)
        meta_parts = []
        if last_touch:
            meta_parts.append(f"Last call: {_h(last_touch)}")
        if call_count:
            meta_parts.append(f"{call_count} call{'s' if call_count != 1 else ''}")
        if inmail_count:
            meta_parts.append(f"{inmail_count} inmail{'s' if inmail_count != 1 else ''}")
        meta_text = " &middot; ".join(meta_parts) if meta_parts else ""
        meta_html = f'<div class="company-meta-line">{meta_text}{renewal_part}</div>' if (meta_text or renewal_part) else ""

        # 5. Expandable detail: notes + activity history
        activity_html = ""
        for call in (co.get("calls") or [])[:3]:
            cat = call.get("category", "")
            dt = str(call.get("called_at") or "")[:10]
            activity_html += f'<div class="company-activity-item"><span class="company-activity-date">{_h(dt)}</span><span>Call: {_h(cat)}</span></div>'
        for im in (co.get("inmails") or [])[:2]:
            dt = str(im.get("sent_date") or "")[:10]
            sent_label = im.get("reply_sentiment") or ("Replied" if im.get("replied") else "Sent")
            activity_html += f'<div class="company-activity-item"><span class="company-activity-date">{_h(dt)}</span><span>InMail: {_h(str(sent_label))}</span></div>'

        notes_html = ""
        if notes:
            notes_html = f'<div class="company-detail-section"><div class="company-detail-section-title">Notes</div><div class="company-notes">{_h(notes[:300])}</div></div>'

        safe_id = _h(co_id.replace(" ", "_"))

        cards += f"""
      <article class="{card_class}"
               role="button"
               tabindex="0"
               aria-expanded="false"
               data-status="{_h(status)}"
               data-channels="{_h(ch_list_str)}"
               data-name="{_h(name.lower())}"
               data-renewal="{_h(sort_renewal)}"
               data-actiondate="{_h(sort_action)}"
               data-touches="{touches}"
               data-lasttouch="{_h(last_touch)}"
               data-has-provider="{has_provider}"
               data-has-commodities="{has_commodities}"
               data-has-contact="{has_contact}"
               onclick="toggleCompanyCard(this)"
               onkeydown="if(event.key==='Enter'||event.key===' '){{event.preventDefault();toggleCompanyCard(this);}}">
        {header_html}
        {knowledge_html}
        {action_html}
        {meta_html}
        <div class="company-detail" id="co-detail-{safe_id}">
          {notes_html}
          <div class="company-detail-section">
            <div class="company-detail-section-title">Recent Activity</div>
            {activity_html if activity_html else '<div style="color:var(--text-muted);font-size:.75rem;">No activity recorded yet.</div>'}
          </div>
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
      <select id="company-knowledge-filter" aria-label="Filter by knowledge" onchange="filterCompanies()">
        {knowledge_options}
      </select>
      <select id="company-sort" aria-label="Sort companies" onchange="filterCompanies()">
        <option value="recent" selected>Most recent</option>
        <option value="touches">Most touches</option>
        <option value="renewal">Renewal date</option>
        <option value="action">Next action date</option>
        <option value="name">Name A-Z</option>
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
    }
    stage_bg = {
        "Demo": "rgba(66,133,244,.12)",
        "Introductory Call": "rgba(0,196,204,.12)",
        "Qualified": "rgba(168,85,247,.12)",
        "Pilot": "rgba(52,168,83,.12)",
        "Proposal": "rgba(249,115,22,.12)",
        "Nurture": "rgba(251,188,4,.12)",
        "Backlog": "rgba(90,96,120,.12)",
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

    return f"""
<section id="tab-pipeline"
         class="tab-panel app-wrapper"
         role="tabpanel"
         aria-labelledby="tab-btn-pipeline"
         aria-hidden="true">
  {kpi_html}
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
let outreachChartsRendered = false;
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
  if (tabId === 'calling'  && !callingChartsRendered)  initCallingCharts();
  if (tabId === 'outreach' && !outreachChartsRendered) initOutreachCharts();
  if (tabId === 'pipeline' && !pipelineChartRendered) initPipelineChart();
  if (tabId === 'experiments' && !channelChartRendered) initChannelChart();

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
  var knowledge = (document.getElementById('company-knowledge-filter') || {{}}).value || '';
  var sortBy  = (document.getElementById('company-sort') || {{}}).value || 'recent';
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
    var mKnow    = true;
    if (knowledge === 'has_provider')    mKnow = card.dataset.hasProvider === '1';
    if (knowledge === 'has_commodities') mKnow = card.dataset.hasCommodities === '1';
    if (knowledge === 'has_contact')     mKnow = card.dataset.hasContact === '1';
    return mSearch && mStatus && mChannel && mKnow;
  }});

  // Sort
  coVisible.sort(function(a, b) {{
    if (sortBy === 'renewal') {{
      return (a.dataset.renewal || '9999') < (b.dataset.renewal || '9999') ? -1 : 1;
    }} else if (sortBy === 'action') {{
      return (a.dataset.actiondate || '9999') < (b.dataset.actiondate || '9999') ? -1 : 1;
    }} else if (sortBy === 'name') {{
      return (a.dataset.name || '') < (b.dataset.name || '') ? -1 : 1;
    }} else if (sortBy === 'recent') {{
      // Sort by last touch date descending
      var aTouch = a.dataset.lasttouch || '';
      var bTouch = b.dataset.lasttouch || '';
      if (bTouch > aTouch) return 1;
      if (bTouch < aTouch) return -1;
      return 0;
    }} else {{
      // touches desc
      return (parseInt(b.dataset.touches)||0) - (parseInt(a.dataset.touches)||0);
    }}
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
    {_tab_pipeline(data)}
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
