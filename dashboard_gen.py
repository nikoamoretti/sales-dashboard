#!/usr/bin/env python3
"""
dashboard_gen.py — Outbound Central: multi-channel dashboard generator for GitHub Pages.

Generates:
  - call_data.json  (daily JSON snapshot of all calls)
  - index.html      (5-tab management dashboard)

Data sources (all optional except HubSpot calls):
  - HubSpot Calls   — cold calling stats (required)
  - HubSpot Tasks   — Adam's open task queue
  - Apollo           — email sequence stats
  - Google Sheets    — LinkedIn outreach stats

Usage:
    HUBSPOT_TOKEN=xxx python3 dashboard_gen.py
    HUBSPOT_TOKEN=xxx APOLLO_API_KEY=yyy python3 dashboard_gen.py
"""

import html as _html
import json
import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from hubspot import (
    fetch_calls, fetch_meeting_details_for_categorized, filter_calls_in_range,
    group_calls_by_week, load_historical_categories,
    calculate_category_stats, categorize_call, parse_hs_timestamp,
    safe_int, strip_html, enrich_calls_with_associations,
    ADAM_OWNER_ID, PACIFIC, PITCHED_CATS,
    HUMAN_CONTACT_CATS, ALL_CATEGORIES,
)
from hubspot_tasks import fetch_open_tasks
from apollo_stats import fetch_apollo_stats
from sheets_reader import fetch_linkedin_stats

HERE = Path(__file__).parent
CAMPAIGN_START = date(2026, 1, 19)


def _h(s) -> str:
    """HTML-escape a string for safe embedding in HTML."""
    return _html.escape(str(s or ""), quote=True)


def validate_env() -> str:
    token = os.getenv("HUBSPOT_TOKEN")
    if not token:
        print("ERROR: HUBSPOT_TOKEN environment variable not set")
        sys.exit(1)
    return token


def compute_week_number(monday: date) -> int:
    delta = (monday - CAMPAIGN_START).days
    return max(1, delta // 7 + 1)


def build_call_data(token: str) -> dict:
    """Fetch all data from HubSpot and build the call_data structure."""
    now = datetime.now(PACIFIC)
    today_start = datetime.combine(now.date(), time.min, tzinfo=PACIFIC)
    tomorrow_start = today_start + timedelta(days=1)
    start_ms = int(today_start.timestamp() * 1000)
    end_ms = int(tomorrow_start.timestamp() * 1000)

    historical = load_historical_categories()
    print(f"Loaded {len(historical)} historical categorizations")

    print("Fetching all of Adam's outbound calls...")
    all_calls = fetch_calls(token, 0, end_ms, owner_id=ADAM_OWNER_ID)
    print(f"Total calls: {len(all_calls)}")

    # Enrich with contact/company/note associations
    print("Enriching calls with associations...")
    enrichment = enrich_calls_with_associations(token, all_calls)

    # Build individual call records
    calls_list = []
    for call in all_calls:
        props = call.get("properties", {})
        ts = parse_hs_timestamp(props.get("hs_timestamp"))
        if not ts:
            continue
        ts_pt = ts.astimezone(PACIFIC)
        dt_utc = ts.astimezone(ZoneInfo("UTC"))
        monday = dt_utc.date() - timedelta(days=dt_utc.weekday())

        cat = categorize_call(call, historical)
        duration_ms = safe_int(props.get("hs_call_duration"))
        call_id = call.get("id", "")
        enr = enrichment.get(call_id, {})

        # Use enriched contact name if available, fall back to call title
        contact = enr.get("contact_name") or (props.get("hs_call_title") or "Unknown").strip()

        calls_list.append({
            "id": call_id,
            "timestamp": ts_pt.isoformat(),
            "contact_name": contact,
            "company_name": enr.get("company_name", ""),
            "company_id": enr.get("company_id", ""),
            "category": cat,
            "duration_s": duration_ms // 1000,
            "notes": (props.get("hs_body_preview") or strip_html(props.get("hs_call_body") or "")).strip(),
            "engagement_notes": enr.get("engagement_notes", []),
            "has_transcript": str(props.get("hs_call_has_transcript") or "").lower() == "true",
            "week_num": compute_week_number(monday),
            "hour_pt": ts_pt.hour,
        })

    # All-time stats
    all_time_stats = calculate_category_stats(all_calls, historical)

    # Today's stats
    today_calls = filter_calls_in_range(all_calls, start_ms, end_ms)
    today_data = None
    if today_calls:
        t = calculate_category_stats(today_calls, historical)
        today_data = {
            "dials": t["total_dials"],
            "hc": t["human_contact"],
            "rate": t["human_contact_rate"],
            "categories": t["categories"],
        }

    # Meeting details — resolve contact/company for ALL "Meeting Booked" calls
    print("Fetching meeting details...")
    meeting_details = fetch_meeting_details_for_categorized(token, all_calls, historical)
    print(f"Meeting details: {len(meeting_details)}")

    # Weekly breakdown
    weeks = group_calls_by_week(all_calls)
    current_monday = now.date() - timedelta(days=now.weekday())
    weekly_data = []
    total_meetings = 0

    for i, (monday, week_calls) in enumerate(weeks, 1):
        friday = monday + timedelta(days=4)
        ws = calculate_category_stats(week_calls, historical)
        total_meetings += ws["meetings_booked"]

        weekly_data.append({
            "week_num": i,
            "monday": monday.isoformat(),
            "dates": f"{monday.strftime('%b %d')}\u2013{friday.strftime('%d')}",
            "total_dials": ws["total_dials"],
            "categories": ws["categories"],
            "human_contact": ws["human_contact"],
            "human_contact_rate": ws["human_contact_rate"],
            "pitch_rate": ws["pitch_rate"],
            "meetings_booked": ws["meetings_booked"],
            "is_current": monday == current_monday,
        })

    return {
        "generated_at": now.isoformat(),
        "calls": calls_list,
        "weekly_data": weekly_data,
        "meeting_details": meeting_details,
        "totals": {
            "dials": all_time_stats["total_dials"],
            "hc": all_time_stats["human_contact"],
            "hc_rate": all_time_stats["human_contact_rate"],
            "meetings": total_meetings,
            "categories": {cat: all_time_stats["categories"].get(cat, 0) for cat in ALL_CATEGORIES},
        },
        "today": today_data,
    }


def _tab_bar() -> str:
    """Generate the tab bar HTML."""
    tabs = [
        ("overview", "Overview"),
        ("trends", "Weekly Trends"),
        ("calllog", "Call Log"),
        ("analysis", "Analysis"),
        ("companies", "Companies"),
    ]
    btns = []
    for tid, label in tabs:
        cls = ' active' if tid == "overview" else ""
        btns.append(f'<button class="tab-btn{cls}" data-tab="{tid}">{label}</button>')
    return '<div class="tab-bar">' + "".join(btns) + "</div>"


def _build_task_queue_banner(data: dict) -> str:
    """Build task queue alert banner HTML. Returns empty string if no data."""
    tq = data.get("task_queue")
    if not tq:
        return ""

    alert = tq["alert_level"]
    total = tq["total_open"]
    high = tq["by_priority"].get("HIGH", 0)
    oldest = tq["oldest_task_days"]

    icon_map = {"ok": "&#x2705;", "warning": "&#x26A0;&#xFE0F;", "critical": "&#x1F6A8;"}
    icon = icon_map.get(alert, "")

    priority_parts = []
    for p in ["HIGH", "MEDIUM", "LOW"]:
        count = tq["by_priority"].get(p, 0)
        if count > 0:
            priority_parts.append(f'<div class="tb-stat"><span class="tb-num">{count}</span><span class="tb-label">{p}</span></div>')

    return f"""
  <div class="task-banner alert-{alert}" id="task-banner" onclick="document.getElementById('task-list').classList.toggle('open');this.classList.toggle('open');">
    <span class="tb-icon">{icon}</span>
    <div class="tb-stats">
      <div class="tb-stat"><span class="tb-num">{total}</span><span class="tb-label">Open Tasks</span></div>
      {"".join(priority_parts)}
      <div class="tb-stat"><span class="tb-num">{oldest}d</span><span class="tb-label">Oldest</span></div>
    </div>
    <span class="tb-chevron">&#x25B6;</span>
  </div>
  <div class="task-list" id="task-list">
    <div class="task-list-inner" id="task-list-inner"></div>
  </div>"""


def _build_channels_grid(data: dict) -> str:
    """Build outbound channels 3-column grid."""
    t = data["totals"]
    apollo = data.get("apollo_stats")
    linkedin = data.get("linkedin_stats")

    # Cold Calling column
    calls_html = f"""
    <div class="channel-card ch-calls">
      <div class="channel-title">Cold Calling</div>
      <div class="channel-stats">
        <div class="channel-stat"><span class="channel-stat-label">Dials</span><span class="channel-stat-val highlight">{t['dials']:,}</span></div>
        <div class="channel-stat"><span class="channel-stat-label">HC Rate</span><span class="channel-stat-val">{t['hc_rate']}%</span></div>
        <div class="channel-stat"><span class="channel-stat-label">Meetings</span><span class="channel-stat-val">{t['meetings']}</span></div>
      </div>
    </div>"""

    # Email Sequences column
    if apollo:
        at = apollo["totals"]
        email_html = f"""
    <div class="channel-card ch-email">
      <div class="channel-title">Email Sequences</div>
      <div class="channel-stats">
        <div class="channel-stat"><span class="channel-stat-label">Sent</span><span class="channel-stat-val highlight">{at['emails_sent']:,}</span></div>
        <div class="channel-stat"><span class="channel-stat-label">Open Rate</span><span class="channel-stat-val">{at['open_rate']}%</span></div>
        <div class="channel-stat"><span class="channel-stat-label">Reply Rate</span><span class="channel-stat-val">{at['reply_rate']}%</span></div>
      </div>
    </div>"""
    else:
        email_html = """
    <div class="channel-card ch-email">
      <div class="channel-title">Email Sequences</div>
      <div class="channel-not-configured">Not configured &mdash; set APOLLO_API_KEY</div>
    </div>"""

    # LinkedIn column
    if linkedin:
        li_html = f"""
    <div class="channel-card ch-linkedin">
      <div class="channel-title">LinkedIn Outreach</div>
      <div class="channel-stats">
        <div class="channel-stat"><span class="channel-stat-label">Requests</span><span class="channel-stat-val highlight">{linkedin['requests_sent']}</span></div>
        <div class="channel-stat"><span class="channel-stat-label">Connected</span><span class="channel-stat-val">{linkedin['connected']}</span></div>
        <div class="channel-stat"><span class="channel-stat-label">Accept Rate</span><span class="channel-stat-val">{linkedin['accept_rate']}%</span></div>
      </div>
    </div>"""
    else:
        li_html = """
    <div class="channel-card ch-linkedin">
      <div class="channel-title">LinkedIn Outreach</div>
      <div class="channel-not-configured">Not configured &mdash; set GOOGLE_SHEET_ID</div>
    </div>"""

    return f"""
  <div class="section-header" style="border-left-color:var(--cyan);"><h2>Outbound Channels</h2><p>All active outreach channels at a glance</p></div>
  <div class="channels-grid">
    {calls_html}
    {email_html}
    {li_html}
  </div>"""


def _build_overview_tab(data: dict) -> str:
    """Tab 1: Task queue + Hero KPIs + outbound channels + today snapshot + meetings."""
    t = data["totals"]
    today = data["today"]
    meetings = data["meeting_details"]
    apollo = data.get("apollo_stats")

    # Hero cards — 4 cards (add Emails Sent if available)
    emails_sent_card = ""
    if apollo:
        at = apollo["totals"]
        emails_sent_card = f"""
    <div class="hero-card accent-cyan">
      <span class="num">{at['emails_sent']:,}</span>
      <div class="label">Emails Sent</div>
      <div class="sub">{at['open_rate']}% open rate</div>
    </div>"""

    hero = f"""
  <div class="hero" style="grid-template-columns: repeat({4 if apollo else 3}, 1fr);">
    <div class="hero-card accent-green">
      <span class="num">{t['meetings']}</span>
      <div class="label">Meetings Booked</div>
    </div>
    <div class="hero-card accent-blue">
      <span class="num">{t['dials']:,}</span>
      <div class="label">Total Dials</div>
    </div>
    <div class="hero-card accent-orange">
      <span class="num">{t['hc_rate']}%</span>
      <div class="label">Human Contact Rate</div>
      <div class="sub">{t['hc']:,} conversations</div>
    </div>
    {emails_sent_card}
  </div>"""

    # Task queue banner
    task_html = _build_task_queue_banner(data)

    # Outbound channels grid
    channels_html = _build_channels_grid(data)

    # Today snapshot
    today_html = ""
    if today and today["dials"] > 0:
        cat_pills = ""
        for cat in ALL_CATEGORIES:
            val = today["categories"].get(cat, 0)
            if val > 0:
                cat_pills += f'<div class="today-cat-item"><span class="today-cat-count">{val}</span><span class="today-cat-label">{_h(cat)}</span></div>'

        today_html = f"""
  <div class="today-snapshot">
    <div class="section-header" style="border-left-color:var(--green);"><h2>Today's Snapshot</h2></div>
    <div class="today-grid">
      <div class="today-stat"><span class="today-num" style="color:var(--blue);">{today['dials']}</span><span class="today-label">Dials</span></div>
      <div class="today-stat"><span class="today-num" style="color:var(--green);">{today['hc']}</span><span class="today-label">Contacts</span></div>
      <div class="today-stat"><span class="today-num" style="color:var(--orange);">{today['rate']}%</span><span class="today-label">Contact Rate</span></div>
    </div>
    <div class="today-categories">{cat_pills}</div>
  </div>"""

    # Meeting details
    mtg_html = ""
    if meetings:
        items = ""
        for m in meetings:
            items += f'<div class="mtg-item"><span class="meeting-dot"></span><div><strong>{_h(m["name"])}</strong><span class="mtg-company">{_h(m["company"])}</span><span class="mtg-date">{_h(m["date"])}</span></div></div>'
        mtg_html = f"""
  <div class="meetings-detail">
    <div class="section-header" style="border-left-color:var(--green);"><h2>Meetings Booked</h2><p>{t['meetings']} total from cold calling</p></div>
    <div class="meetings-card">{items}</div>
  </div>"""

    return f"""<div id="tab-overview" class="tab-panel active">
{task_html}
{hero}
{channels_html}
{today_html}
{mtg_html}
</div>"""


def _build_trends_tab(data: dict) -> str:
    """Tab 2: Weekly table + combo chart + stacked outcomes."""
    weekly = data["weekly_data"]
    t = data["totals"]

    # Category short names for table header
    cat_short = {
        "Interested": "Int", "Meeting Booked": "Mtg", "Referral Given": "Ref",
        "Not Interested": "NI", "No Rail": "NoRl", "Wrong Person": "WrPr",
        "Wrong Number": "Wr#", "Gatekeeper": "GK", "Left Voicemail": "VM",
        "No Answer": "NoAns",
    }
    cat_headers = "".join(f"<th>{cat_short.get(c, c)}</th>" for c in ALL_CATEGORIES)

    # Table rows
    rows = ""
    total_dials = 0
    total_hc = 0
    cat_totals = {c: 0 for c in ALL_CATEGORIES}

    for idx, w in enumerate(weekly):
        rc = ' style="background:rgba(59,130,246,0.08);"' if w["is_current"] else ""
        marker = " *" if w["is_current"] else ""
        cats = w["categories"]
        total_dials += w["total_dials"]
        total_hc += w["human_contact"]

        cat_cells = ""
        for c in ALL_CATEGORIES:
            v = cats.get(c, 0)
            cat_totals[c] += v
            if v > 0:
                cat_cells += f'<td class="num-col">{v}</td>'
            else:
                cat_cells += '<td class="num-col muted-num">&mdash;</td>'

        mtg_count = cats.get("Meeting Booked", 0)
        if mtg_count > 0:
            mtg_cell = f'<td class="green"><span class="meeting-dot"></span>{mtg_count}</td>'
        else:
            mtg_cell = '<td class="num-col muted-num">&mdash;</td>'

        # Week-over-week delta
        delta_html = ""
        if idx > 0:
            prev_rate = weekly[idx - 1]["human_contact_rate"]
            curr_rate = w["human_contact_rate"]
            diff = round(curr_rate - prev_rate, 1)
            if diff > 0:
                delta_html = f' <span class="delta-up">+{diff}</span>'
            elif diff < 0:
                delta_html = f' <span class="delta-down">{diff}</span>'

        rows += f"""<tr{rc}>
            <td class="muted">Wk {w['week_num']}{marker}</td>
            <td class="muted">{w['dates']}</td>
            <td class="num-col">{w['total_dials']}</td>
            {cat_cells}
            <td class="pct-col">{w['human_contact_rate']}%{delta_html}</td>
            {mtg_cell}
          </tr>"""

    # Footer
    total_rate = round(total_hc / total_dials * 100, 1) if total_dials else 0
    total_cat_cells = "".join(f'<td class="num-col">{cat_totals[c]}</td>' for c in ALL_CATEGORIES)
    total_mtg = cat_totals.get("Meeting Booked", 0)
    mtg_foot = f'<td class="total-meet"><span class="meeting-dot"></span>{total_mtg}</td>' if total_mtg else '<td class="total-meet">&mdash;</td>'

    return f"""<div id="tab-trends" class="tab-panel">
  <section style="margin-bottom:48px;">
    <div class="section-header"><h2>Weekly Performance</h2><p>Full breakdown with all 10 categories</p></div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th style="text-align:left;">Week</th><th style="text-align:left;">Dates</th><th>Dials</th>
          {cat_headers}
          <th>HC %</th><th>Mtgs</th>
        </tr></thead>
        <tbody>{rows}</tbody>
        <tfoot><tr>
          <td colspan="2" style="color:var(--muted);font-weight:600;font-size:11px;letter-spacing:0.08em;text-transform:uppercase;">Total</td>
          <td class="num-col">{total_dials}</td>
          {total_cat_cells}
          <td class="pct-col">{total_rate}%</td>
          {mtg_foot}
        </tr></tfoot>
      </table>
    </div>
  </section>
  <div class="charts-row">
    <div class="chart-wrap"><h3>Weekly Dials + Human Contact Rate</h3><canvas id="weeklyDialsChart" height="200"></canvas></div>
    <div class="chart-wrap accent-green"><h3>Conversation Outcomes by Week</h3><canvas id="stackedChart" height="200"></canvas></div>
  </div>
</div>"""


def _build_calllog_tab() -> str:
    """Tab 3: Call log — rendered client-side from embedded JSON."""
    return """<div id="tab-calllog" class="tab-panel">
  <div class="section-header"><h2>Call Log</h2><p>Every call, newest first &mdash; click a row to see full details</p></div>
  <div class="calllog-controls">
    <input type="text" id="calllog-search" placeholder="Search by name, company, category, or notes..." />
    <select id="calllog-filter">
      <option value="">All Categories</option>
    </select>
  </div>
  <div class="calllog-stats" id="calllog-stats"></div>
  <div class="table-wrap">
    <table id="calllog-table">
      <thead><tr>
        <th style="text-align:left;">Date/Time</th>
        <th style="text-align:left;">Contact</th>
        <th style="text-align:left;">Company</th>
        <th>Category</th>
        <th>Duration</th>
        <th style="text-align:left;">Notes</th>
      </tr></thead>
      <tbody id="calllog-body"></tbody>
    </table>
  </div>
  <div class="calllog-pagination" id="calllog-pagination"></div>
</div>"""


def _build_analysis_tab() -> str:
    """Tab 4: Forensic analysis — preserved from forensic_report.py content."""
    # Load forensic data if available
    forensic_path = HERE / "forensic_data.json"
    if not forensic_path.exists():
        return """<div id="tab-analysis" class="tab-panel">
  <div class="section-header"><h2>Analysis</h2><p>Forensic data not available. Run forensic_audit.py first.</p></div>
</div>"""

    with open(forensic_path) as f:
        fd = json.load(f)

    old_weekly = fd["old_system_weekly"]
    new_raw = fd.get("new_raw_weekly", fd["new_system_weekly"])

    if not old_weekly or not new_raw:
        return """<div id="tab-analysis" class="tab-panel">
  <div class="section-header"><h2>Analysis</h2><p>Insufficient data to render analysis.</p></div>
</div>"""

    old_start = old_weekly[0]["rate"]
    old_end = old_weekly[-1]["rate"]
    new_wk2_5 = [w["rate"] for w in new_raw if 2 <= w["week_num"] <= 5]
    if not new_wk2_5:
        new_wk2_5 = [w["rate"] for w in new_raw]
    new_low = min(new_wk2_5)
    new_high = max(new_wk2_5)

    weeks_labels = json.dumps([f"Wk {w['week_num']}" for w in old_weekly])
    old_rates = json.dumps([w["rate"] for w in old_weekly])
    new_rates = json.dumps([w["rate"] for w in new_raw])

    # Store analysis data as globals for lazy init in main script
    analysis_data = {
        "weeks_labels": json.loads(weeks_labels),
        "old_rates": json.loads(old_rates),
        "new_rates": json.loads(new_rates),
    }
    # Attach to the function so build_html can access it
    _build_analysis_tab._data = analysis_data

    return f"""<div id="tab-analysis" class="tab-panel">
  <div class="bottom-line">
    <h2>The contact rate decline was a dashboard bug, not a sales problem.</h2>
    <p>The old dashboard showed a cliff from {old_start}% to {old_end}%.
    After fixing the measurement, the real rate has been steady at {new_low:.0f}&ndash;{new_high:.0f}% since Week 2.</p>
  </div>

  <div class="section">
    <div class="section-label problem">The Problem</div>
    <h3>What the old dashboard showed</h3>
    <div class="chart-card"><div class="chart-wrap-sm"><canvas id="oldChart"></canvas></div></div>
    <div class="explain">
      <p>The old dashboard reported human contact rate falling from
      <strong>{old_start}%</strong> to <strong>{old_end}%</strong> &mdash;
      a dramatic collapse that suggested a serious performance problem.</p>
      <p style="margin-top:10px;"><strong>Why it was wrong:</strong>
      On <em>Feb 9</em>, Adam started using 4 new call outcome labels.
      The old dashboard didn't map them &mdash; <strong>27 real human contacts became invisible</strong>.
      At the same time, 9 calls were over-counted due to duration-based fallback.</p>
    </div>
  </div>

  <div class="section">
    <div class="section-label correction">The Correction</div>
    <h3>What the real numbers look like</h3>
    <div class="chart-card"><div class="chart-wrap-sm"><canvas id="newChart"></canvas></div></div>
    <div class="explain">
      <p>After updating to the 10-category system, the contact rate has been
      <strong>stable at {new_low:.0f}&ndash;{new_high:.0f}% from Week 2 through Week 5</strong>.</p>
    </div>
  </div>
</div>"""


def _build_companies_tab() -> str:
    """Tab 5: Companies — aggregated company view, rendered client-side."""
    return """<div id="tab-companies" class="tab-panel">
  <div class="section-header"><h2>Companies</h2><p>Every company contacted &mdash; click to expand call history</p></div>
  <div class="calllog-controls">
    <input type="text" id="company-search" placeholder="Search by company name..." />
    <select id="company-sort">
      <option value="calls">Most Calls</option>
      <option value="recent">Most Recent</option>
      <option value="name">Alphabetical</option>
      <option value="meetings">Meetings First</option>
    </select>
  </div>
  <div class="calllog-stats" id="company-stats"></div>
  <div id="company-list"></div>
</div>"""


def build_html(data: dict) -> str:
    """Build the complete self-contained HTML dashboard."""
    now = datetime.fromisoformat(data["generated_at"])
    date_str = now.strftime("%B %d, %Y")
    current_monday = now.date() - timedelta(days=now.weekday())
    campaign_week = compute_week_number(current_monday)
    gen_time = now.strftime("%B %d, %Y at %I:%M %p") + " PT"

    # Escape </ to prevent </script> breaking the HTML parser
    weekly_json = json.dumps(data["weekly_data"], default=str).replace("</", "<\\/")
    calls_json = json.dumps(data["calls"], default=str).replace("</", "<\\/")
    totals_json = json.dumps(data["totals"], default=str).replace("</", "<\\/")
    task_queue_json = json.dumps(data.get("task_queue"), default=str).replace("</", "<\\/")

    tab_bar = _tab_bar()
    overview = _build_overview_tab(data)
    trends = _build_trends_tab(data)
    calllog = _build_calllog_tab()
    analysis = _build_analysis_tab()
    companies = _build_companies_tab()

    # Analysis chart data for lazy init (set by _build_analysis_tab if forensic data exists)
    analysis_chart_data = getattr(_build_analysis_tab, "_data", None)
    analysis_json = json.dumps(analysis_chart_data).replace("</", "<\\/") if analysis_chart_data else "null"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Outbound Central &mdash; {date_str}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet" />
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    :root {{
      --bg:        #0F1B2D;
      --card:      #1B2A4A;
      --border:    rgba(59,130,246,0.18);
      --border-hover: rgba(59,130,246,0.40);
      --text:      #F0F6FF;
      --muted:     #8BA3C7;
      --blue:      #3B82F6;
      --green:     #10B981;
      --green-dim: rgba(16,185,129,0.10);
      --orange:    #F59E0B;
      --red:       #EF4444;
      --cyan:      #06B6D4;
      --purple:    #8B5CF6;
      --shadow:    0 2px 12px rgba(0,0,0,0.30);
      --shadow-hover: 0 6px 24px rgba(0,0,0,0.40);
      --r:         10px;
    }}

    html {{ scroll-behavior: smooth; }}

    body {{
      background: var(--bg);
      background-image: radial-gradient(ellipse 80% 60% at 50% -10%, rgba(59,130,246,0.10) 0%, transparent 70%);
      color: var(--text);
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
      -webkit-font-smoothing: antialiased;
      line-height: 1.5;
      min-height: 100vh;
    }}

    .page {{ max-width: 1080px; margin: 0 auto; padding: 0 28px 80px; }}

    /* HEADER */
    header {{
      text-align: center;
      padding: 48px 0 32px;
      border-bottom: 1px solid var(--border);
      margin-bottom: 0;
    }}
    header .label {{
      font-size: 11px; font-weight: 700; letter-spacing: 0.18em;
      text-transform: uppercase; color: var(--blue); margin-bottom: 10px;
    }}
    header h1 {{
      font-size: clamp(24px, 4vw, 34px); font-weight: 800;
      letter-spacing: -0.02em; line-height: 1.1; margin-bottom: 8px;
    }}
    header .subtitle {{ font-size: 15px; color: var(--muted); }}

    /* TAB BAR */
    .tab-bar {{
      display: flex; gap: 0; border-bottom: 1px solid var(--border);
      margin-bottom: 36px; overflow-x: auto;
    }}
    .tab-btn {{
      background: none; border: none; color: var(--muted);
      font-family: 'Inter', system-ui, sans-serif; font-size: 14px; font-weight: 600;
      padding: 14px 22px; cursor: pointer;
      border-bottom: 2px solid transparent; transition: color 0.15s, border-color 0.15s;
      white-space: nowrap;
    }}
    .tab-btn:hover {{ color: var(--text); }}
    .tab-btn.active {{ color: var(--text); border-bottom-color: var(--blue); }}

    /* TAB PANELS */
    .tab-panel {{ visibility: hidden; height: 0; overflow: hidden; }}
    .tab-panel.active {{ visibility: visible; height: auto; overflow: visible; }}

    /* HERO CARDS */
    .hero {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 48px; }}
    .hero-card {{
      background: var(--card); border: 1px solid var(--border); border-radius: var(--r);
      padding: 36px 24px 32px; text-align: center; position: relative; overflow: hidden;
      box-shadow: var(--shadow); transition: border-color 0.2s, box-shadow 0.2s, transform 0.2s;
    }}
    .hero-card::before {{ content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; }}
    .hero-card.accent-green::before {{ background: var(--green); }}
    .hero-card.accent-blue::before {{ background: var(--blue); }}
    .hero-card.accent-orange::before {{ background: var(--orange); }}
    .hero-card:hover {{ border-color: var(--border-hover); box-shadow: var(--shadow-hover); transform: translateY(-1px); }}
    .hero-card .num {{
      font-size: clamp(48px, 7vw, 68px); font-weight: 900;
      letter-spacing: -0.04em; line-height: 1; display: block; margin-bottom: 10px;
    }}
    .hero-card.accent-green .num {{ color: var(--green); text-shadow: 0 0 28px rgba(16,185,129,0.35); }}
    .hero-card.accent-blue .num {{ color: var(--blue); text-shadow: 0 0 28px rgba(59,130,246,0.35); }}
    .hero-card.accent-orange .num {{ color: var(--orange); text-shadow: 0 0 28px rgba(245,158,11,0.35); }}
    .hero-card .label {{
      font-size: 11px; font-weight: 700; letter-spacing: 0.10em;
      text-transform: uppercase; color: var(--muted);
    }}
    .hero-card .sub {{ font-size: 13px; color: var(--muted); margin-top: 6px; }}

    /* TODAY SNAPSHOT */
    .today-snapshot {{ margin-bottom: 48px; }}
    .today-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-bottom: 16px; }}
    .today-stat {{
      background: var(--card); border: 1px solid var(--border); border-radius: var(--r);
      padding: 22px 18px; text-align: center; position: relative; overflow: hidden;
      box-shadow: var(--shadow); transition: border-color 0.2s, box-shadow 0.2s, transform 0.2s;
    }}
    .today-stat::before {{ content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; background: var(--green); }}
    .today-stat:hover {{ border-color: var(--border-hover); box-shadow: var(--shadow-hover); transform: translateY(-1px); }}
    .today-num {{ font-size: clamp(30px, 5vw, 42px); font-weight: 900; letter-spacing: -0.03em; line-height: 1; display: block; margin-bottom: 4px; }}
    .today-label {{ font-size: 11px; font-weight: 700; letter-spacing: 0.10em; text-transform: uppercase; color: var(--muted); }}
    .today-categories {{ display: flex; flex-wrap: wrap; gap: 10px; }}
    .today-cat-item {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 8px 14px; display: flex; align-items: center; gap: 8px; }}
    .today-cat-count {{ font-size: 18px; font-weight: 800; color: var(--text); }}
    .today-cat-label {{ font-size: 12px; color: var(--muted); font-weight: 600; }}

    /* SECTION HEADERS */
    .section-header {{ margin-bottom: 24px; padding-left: 14px; border-left: 3px solid var(--blue); }}
    .section-header h2 {{ font-size: 20px; font-weight: 800; letter-spacing: -0.02em; line-height: 1.2; margin-bottom: 3px; }}
    .section-header p {{ font-size: 13px; color: var(--muted); }}

    /* TABLE */
    .table-wrap {{
      background: var(--card); border: 1px solid var(--border); border-radius: var(--r);
      overflow-x: auto; margin-bottom: 32px; box-shadow: var(--shadow);
    }}
    table {{ width: 100%; border-collapse: collapse; min-width: 900px; }}
    thead tr {{ border-left: 3px solid var(--blue); }}
    thead th {{
      background: rgba(59,130,246,0.10); font-size: 10px; font-weight: 700;
      letter-spacing: 0.10em; text-transform: uppercase; color: var(--muted);
      padding: 13px 10px; text-align: right; white-space: nowrap;
    }}
    thead th:nth-child(1), thead th:nth-child(2) {{ text-align: left; }}
    tbody tr {{ border-top: 1px solid var(--border); transition: background 0.15s; }}
    tbody tr:hover {{ background: rgba(59,130,246,0.05); }}
    tbody td {{ padding: 12px 10px; font-size: 13px; color: var(--text); }}
    tbody td.num-col {{ font-weight: 700; font-variant-numeric: tabular-nums; text-align: right; }}
    tbody td.muted-num {{ color: rgba(139,163,199,0.35); font-weight: 400; }}
    tbody td.pct-col {{ text-align: right; color: var(--muted); font-weight: 600; font-variant-numeric: tabular-nums; }}
    tbody td.green {{ color: var(--green); font-weight: 700; text-align: right; }}
    tbody td.muted {{ color: var(--muted); }}
    tfoot tr {{ border-top: 2px solid rgba(59,130,246,0.35); background: rgba(59,130,246,0.06); }}
    tfoot td {{ padding: 13px 10px; font-size: 13px; font-weight: 700; }}
    tfoot td.num-col {{ font-variant-numeric: tabular-nums; text-align: right; }}
    tfoot td.pct-col {{ text-align: right; color: var(--muted); font-weight: 600; }}
    tfoot td.total-meet {{ text-align: right; color: var(--green); }}
    .meeting-dot {{ display: inline-block; width: 7px; height: 7px; background: var(--green); border-radius: 50%; margin-right: 5px; vertical-align: middle; }}

    /* DELTA INDICATORS */
    .delta-up {{ color: var(--green); font-size: 11px; font-weight: 700; }}
    .delta-down {{ color: var(--red); font-size: 11px; font-weight: 700; }}

    /* CHARTS */
    .charts-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 48px; }}
    .chart-wrap {{
      background: var(--card); border: 1px solid var(--border); border-radius: var(--r);
      padding: 24px 22px 18px; position: relative; overflow: hidden;
      box-shadow: var(--shadow); transition: border-color 0.2s, box-shadow 0.2s, transform 0.2s;
    }}
    .chart-wrap::before {{ content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; background: var(--blue); }}
    .chart-wrap.accent-green::before {{ background: var(--green); }}
    .chart-wrap:hover {{ border-color: var(--border-hover); box-shadow: var(--shadow-hover); transform: translateY(-1px); }}
    .chart-wrap h3 {{ font-size: 11px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; color: var(--muted); margin-bottom: 18px; }}

    /* MEETINGS DETAIL */
    .meetings-detail {{ margin-bottom: 48px; }}
    .meetings-card {{
      background: var(--green-dim); border: 1px solid rgba(16,185,129,0.25);
      border-left: 3px solid var(--green); border-radius: var(--r);
      padding: 24px 28px; box-shadow: var(--shadow);
    }}
    .mtg-item {{ display: flex; align-items: center; gap: 14px; padding: 12px 0; border-bottom: 1px solid rgba(16,185,129,0.15); }}
    .mtg-item:last-child {{ border-bottom: none; padding-bottom: 0; }}
    .mtg-item:first-child {{ padding-top: 0; }}
    .mtg-item .meeting-dot {{ width: 10px; height: 10px; flex-shrink: 0; }}
    .mtg-item strong {{ color: var(--text); font-size: 15px; margin-right: 8px; }}
    .mtg-company {{ color: var(--muted); font-size: 14px; margin-right: 8px; }}
    .mtg-date {{ color: rgba(139,163,199,0.6); font-size: 13px; }}

    /* CALL LOG */
    .calllog-controls {{
      display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap;
    }}
    .calllog-controls input {{
      flex: 1; min-width: 200px; padding: 10px 16px;
      background: var(--card); border: 1px solid var(--border); border-radius: 8px;
      color: var(--text); font-family: 'Inter', sans-serif; font-size: 14px;
      outline: none; transition: border-color 0.2s;
    }}
    .calllog-controls input:focus {{ border-color: var(--blue); }}
    .calllog-controls input::placeholder {{ color: var(--muted); }}
    .calllog-controls select {{
      padding: 10px 16px; background: var(--card); border: 1px solid var(--border);
      border-radius: 8px; color: var(--text); font-family: 'Inter', sans-serif;
      font-size: 14px; cursor: pointer; outline: none;
    }}
    .calllog-stats {{
      font-size: 13px; color: var(--muted); margin-bottom: 12px;
    }}
    .calllog-pagination {{
      display: flex; gap: 8px; justify-content: center; margin-top: 16px;
    }}
    .calllog-pagination button {{
      background: var(--card); border: 1px solid var(--border); border-radius: 6px;
      color: var(--muted); padding: 8px 14px; cursor: pointer; font-family: 'Inter', sans-serif;
      font-size: 13px; transition: border-color 0.15s, color 0.15s;
    }}
    .calllog-pagination button:hover {{ border-color: var(--blue); color: var(--text); }}
    .calllog-pagination button.active {{ border-color: var(--blue); color: var(--text); background: rgba(59,130,246,0.15); }}

    /* Expandable notes row */
    .notes-row td {{
      padding: 0 10px 16px 10px !important;
      border-top: none !important;
    }}
    .notes-row {{ display: none; }}
    .notes-row.open {{ display: table-row; }}
    .notes-content {{
      background: rgba(59,130,246,0.05); border-radius: 8px;
      padding: 14px 18px; font-size: 13px; color: var(--muted);
      line-height: 1.6; white-space: pre-wrap; word-break: break-word;
    }}
    tbody tr.expandable {{ cursor: pointer; }}
    tbody tr.expandable:hover {{ background: rgba(59,130,246,0.08); }}

    /* ANALYSIS TAB */
    .bottom-line {{
      background: var(--card); border: 1px solid rgba(16,185,129,0.30);
      border-radius: 10px; padding: 28px 32px; margin-bottom: 48px; text-align: center;
    }}
    .bottom-line h2 {{ font-size: 20px; font-weight: 800; color: var(--green); margin-bottom: 8px; }}
    .bottom-line p {{ color: var(--muted); font-size: 14px; max-width: 560px; margin: 0 auto; }}
    .section {{ margin-bottom: 48px; }}
    .section-label {{ font-size: 11px; font-weight: 700; letter-spacing: 0.15em; text-transform: uppercase; margin-bottom: 6px; }}
    .section-label.problem {{ color: var(--red); }}
    .section-label.correction {{ color: var(--green); }}
    .section h3 {{ font-size: 18px; font-weight: 700; margin-bottom: 16px; }}
    .chart-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 24px 28px; margin-bottom: 16px; }}
    .chart-wrap-sm {{ position: relative; height: 260px; }}
    .explain {{ font-size: 14px; color: var(--muted); line-height: 1.7; }}
    .explain strong {{ color: var(--text); }}
    .explain em {{ color: var(--orange); font-style: normal; font-weight: 600; }}

    /* TRANSCRIPT + ENGAGEMENT NOTES */
    .transcript-badge {{
      display: inline-block; font-size: 10px; font-weight: 700; letter-spacing: 0.05em;
      background: rgba(139,92,246,0.15); color: var(--purple); border-radius: 4px;
      padding: 2px 6px; margin-left: 6px; vertical-align: middle;
    }}
    .eng-notes {{ margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border); }}
    .eng-notes-label {{
      font-size: 10px; font-weight: 700; letter-spacing: 0.10em; text-transform: uppercase;
      color: var(--orange); margin-bottom: 6px;
    }}
    .eng-note-item {{
      font-size: 13px; color: var(--muted); line-height: 1.6;
      padding: 6px 0; white-space: pre-wrap; word-break: break-word;
    }}
    .eng-note-item + .eng-note-item {{ border-top: 1px dashed rgba(59,130,246,0.12); }}

    /* COMPANIES TAB */
    .company-card {{
      background: var(--card); border: 1px solid var(--border); border-radius: var(--r);
      margin-bottom: 12px; overflow: hidden; box-shadow: var(--shadow);
      transition: border-color 0.2s, box-shadow 0.2s;
    }}
    .company-card:hover {{ border-color: var(--border-hover); box-shadow: var(--shadow-hover); }}
    .company-header {{
      display: flex; align-items: center; justify-content: space-between;
      padding: 18px 22px; cursor: pointer; gap: 16px;
    }}
    .company-header:hover {{ background: rgba(59,130,246,0.04); }}
    .company-name {{ font-size: 16px; font-weight: 700; color: var(--text); flex: 1; }}
    .company-meta {{ display: flex; gap: 16px; align-items: center; flex-shrink: 0; }}
    .company-stat {{
      font-size: 12px; color: var(--muted); text-align: center; min-width: 50px;
    }}
    .company-stat .cs-num {{ font-size: 18px; font-weight: 800; display: block; line-height: 1.2; }}
    .company-stat .cs-num.green {{ color: var(--green); }}
    .company-stat .cs-num.blue {{ color: var(--blue); }}
    .company-stat .cs-num.orange {{ color: var(--orange); }}
    .company-stat .cs-label {{ font-size: 10px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; }}
    .company-chevron {{ color: var(--muted); font-size: 14px; transition: transform 0.2s; }}
    .company-card.open .company-chevron {{ transform: rotate(90deg); }}
    .company-detail {{ display: none; padding: 0 22px 18px; }}
    .company-card.open .company-detail {{ display: block; }}
    .company-cats {{
      display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px;
    }}
    .company-cat-pill {{
      font-size: 11px; font-weight: 600; padding: 4px 10px;
      border-radius: 6px; background: rgba(59,130,246,0.08);
      color: var(--muted); border: 1px solid var(--border);
    }}
    .company-timeline {{ border-left: 2px solid var(--border); margin-left: 8px; padding-left: 18px; }}
    .company-call {{
      position: relative; padding: 10px 0; font-size: 13px;
      border-bottom: 1px solid rgba(59,130,246,0.06);
    }}
    .company-call:last-child {{ border-bottom: none; }}
    .company-call::before {{
      content: ''; position: absolute; left: -23px; top: 16px;
      width: 8px; height: 8px; border-radius: 50%; background: var(--border);
    }}
    .company-call-header {{ display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }}
    .company-call-date {{ color: var(--muted); font-size: 12px; min-width: 120px; }}
    .company-call-contact {{ color: var(--text); font-weight: 600; }}
    .company-call-cat {{ font-size: 11px; font-weight: 600; }}
    .company-call-dur {{ color: var(--muted); font-size: 12px; }}
    .company-call-notes {{ color: rgba(139,163,199,0.7); font-size: 12px; margin-top: 4px; line-height: 1.5; }}

    /* FOOTER */
    footer {{ border-top: 1px solid var(--border); padding-top: 28px; text-align: center; font-size: 13px; color: var(--muted); line-height: 1.8; }}
    footer strong {{ color: var(--text); }}

    /* HERO CARD — CYAN ACCENT */
    .hero-card.accent-cyan::before {{ background: var(--cyan); }}
    .hero-card.accent-cyan .num {{ color: var(--cyan); text-shadow: 0 0 28px rgba(6,182,212,0.35); }}

    /* TASK QUEUE BANNER */
    .task-banner {{
      border-radius: var(--r); padding: 20px 28px; margin-bottom: 32px;
      display: flex; align-items: center; justify-content: space-between;
      gap: 16px; box-shadow: var(--shadow); cursor: pointer;
      transition: box-shadow 0.2s;
    }}
    .task-banner:hover {{ box-shadow: var(--shadow-hover); }}
    .task-banner.alert-ok {{
      background: rgba(16,185,129,0.08); border: 1px solid rgba(16,185,129,0.30);
      border-left: 4px solid var(--green);
    }}
    .task-banner.alert-warning {{
      background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.30);
      border-left: 4px solid var(--orange);
    }}
    .task-banner.alert-critical {{
      background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.30);
      border-left: 4px solid var(--red);
    }}
    .task-banner .tb-icon {{ font-size: 24px; flex-shrink: 0; }}
    .task-banner .tb-stats {{
      display: flex; gap: 24px; flex-wrap: wrap; flex: 1;
    }}
    .task-banner .tb-stat {{ text-align: center; }}
    .task-banner .tb-num {{
      font-size: 28px; font-weight: 900; display: block; line-height: 1;
    }}
    .task-banner.alert-ok .tb-num {{ color: var(--green); }}
    .task-banner.alert-warning .tb-num {{ color: var(--orange); }}
    .task-banner.alert-critical .tb-num {{ color: var(--red); }}
    .task-banner .tb-label {{
      font-size: 10px; font-weight: 700; letter-spacing: 0.08em;
      text-transform: uppercase; color: var(--muted);
    }}
    .task-banner .tb-chevron {{
      color: var(--muted); font-size: 14px; transition: transform 0.2s; flex-shrink: 0;
    }}
    .task-banner.open .tb-chevron {{ transform: rotate(90deg); }}
    .task-list {{ display: none; margin-bottom: 32px; }}
    .task-list.open {{ display: block; }}
    .task-list-inner {{
      background: var(--card); border: 1px solid var(--border); border-radius: var(--r);
      padding: 16px 22px; max-height: 300px; overflow-y: auto;
    }}
    .task-item {{
      display: flex; align-items: center; gap: 12px; padding: 8px 0;
      border-bottom: 1px solid var(--border); font-size: 13px;
    }}
    .task-item:last-child {{ border-bottom: none; }}
    .task-priority {{
      font-size: 10px; font-weight: 700; letter-spacing: 0.06em; padding: 2px 8px;
      border-radius: 4px; text-transform: uppercase; flex-shrink: 0;
    }}
    .task-priority.high {{ background: rgba(239,68,68,0.15); color: var(--red); }}
    .task-priority.medium {{ background: rgba(245,158,11,0.15); color: var(--orange); }}
    .task-priority.low {{ background: rgba(59,130,246,0.15); color: var(--blue); }}
    .task-priority.none {{ background: rgba(139,163,199,0.10); color: var(--muted); }}

    /* OUTBOUND CHANNELS GRID */
    .channels-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 48px; }}
    .channel-card {{
      background: var(--card); border: 1px solid var(--border); border-radius: var(--r);
      padding: 24px 22px; position: relative; overflow: hidden;
      box-shadow: var(--shadow); transition: border-color 0.2s, box-shadow 0.2s, transform 0.2s;
    }}
    .channel-card::before {{ content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; }}
    .channel-card.ch-calls::before {{ background: var(--blue); }}
    .channel-card.ch-email::before {{ background: var(--cyan); }}
    .channel-card.ch-linkedin::before {{ background: var(--purple); }}
    .channel-card:hover {{ border-color: var(--border-hover); box-shadow: var(--shadow-hover); transform: translateY(-1px); }}
    .channel-title {{
      font-size: 11px; font-weight: 700; letter-spacing: 0.10em;
      text-transform: uppercase; margin-bottom: 16px;
    }}
    .ch-calls .channel-title {{ color: var(--blue); }}
    .ch-email .channel-title {{ color: var(--cyan); }}
    .ch-linkedin .channel-title {{ color: var(--purple); }}
    .channel-stats {{ display: flex; flex-direction: column; gap: 12px; }}
    .channel-stat {{
      display: flex; justify-content: space-between; align-items: baseline;
    }}
    .channel-stat-label {{ font-size: 13px; color: var(--muted); }}
    .channel-stat-val {{ font-size: 20px; font-weight: 800; color: var(--text); }}
    .channel-stat-val.highlight {{ font-size: 24px; }}
    .channel-not-configured {{
      color: var(--muted); font-size: 13px; font-style: italic;
      text-align: center; padding: 20px 0;
    }}

    /* RESPONSIVE */
    @media (max-width: 860px) {{ .charts-row {{ grid-template-columns: 1fr; }} .channels-grid {{ grid-template-columns: 1fr; }} }}
    @media (max-width: 640px) {{
      .hero {{ grid-template-columns: 1fr; }}
      .today-grid {{ grid-template-columns: 1fr; }}
      .today-categories {{ flex-direction: column; }}
      thead th, tbody td, tfoot td {{ padding: 10px 8px; font-size: 12px; }}
      .calllog-controls {{ flex-direction: column; }}
      .task-banner .tb-stats {{ gap: 14px; }}
    }}
  </style>
</head>
<body>
<div class="page">

  <header>
    <div class="label">Outbound Central</div>
    <h1>Outbound Central</h1>
    <div class="subtitle">{date_str} &nbsp;&middot;&nbsp; Week {campaign_week} of campaign</div>
  </header>

  {tab_bar}

  {overview}
  {trends}
  {calllog}
  {analysis}
  {companies}

  <footer>
    <strong>Outbound Central</strong><br>
    Generated {gen_time}
  </footer>

</div>

<script>
  // ═══════════════ DATA ═══════════════
  const weeklyData = {weekly_json};
  const allCalls = {calls_json};
  const totals = {totals_json};
  const taskQueue = {task_queue_json};

  // ═══════════════ TASK LIST RENDER ═══════════════
  (function() {{
    if (!taskQueue || !taskQueue.tasks) return;
    const el = document.getElementById('task-list-inner');
    if (!el) return;
    let html = '';
    taskQueue.tasks.forEach(t => {{
      const pClass = t.priority.toLowerCase();
      html += '<div class="task-item">'
        + '<span class="task-priority ' + pClass + '">' + t.priority + '</span>'
        + '<span>' + t.subject.replace(/</g, '&lt;') + '</span>'
        + '</div>';
    }});
    el.innerHTML = html || '<div style="color:var(--muted);padding:8px;">No open tasks.</div>';
  }})();

  // ═══════════════ CHART DEFAULTS ═══════════════
  Chart.defaults.color = '#8BA3C7';
  Chart.defaults.font.family = "'Inter', sans-serif";

  const tooltipStyle = {{
    backgroundColor: '#1B2A4A', borderColor: 'rgba(59,130,246,0.30)',
    borderWidth: 1, titleColor: '#F0F6FF', bodyColor: '#8BA3C7',
    padding: 12, cornerRadius: 8,
  }};
  const gridStyle = {{ color: 'rgba(59,130,246,0.07)' }};

  const catColors = {{
    'Interested': '#10B981', 'Meeting Booked': '#06B6D4', 'Referral Given': '#8B5CF6',
    'Not Interested': '#F59E0B', 'No Rail': '#6B7280', 'Wrong Person': '#EF4444',
    'Wrong Number': '#F87171', 'Gatekeeper': '#FBBF24', 'Left Voicemail': '#3B82F6',
    'No Answer': '#94A3B8',
  }};

  // ═══════════════ ANALYSIS DATA (lazy init) ═══════════════
  const analysisData = {analysis_json};
  let analysisChartsRendered = false;

  function renderAnalysisCharts() {{
    if (analysisChartsRendered || !analysisData) return;
    analysisChartsRendered = true;
    const weeks = analysisData.weeks_labels;
    const oldRates = analysisData.old_rates;
    const newRates = analysisData.new_rates;
    const lineOpts = () => ({{
      responsive: true, maintainAspectRatio: false,
      scales: {{
        x: {{ grid: {{ color: 'rgba(59,130,246,0.06)' }}, ticks: {{ color: '#8BA3C7', font: {{ family: 'Inter', size: 12 }} }} }},
        y: {{ min: 0, max: 18, grid: {{ color: 'rgba(59,130,246,0.06)' }}, ticks: {{ color: '#8BA3C7', callback: v => v + '%' }} }},
      }},
      plugins: {{ legend: {{ display: false }}, tooltip: {{ backgroundColor: '#1B2A4A', borderColor: 'rgba(59,130,246,0.30)', borderWidth: 1, titleColor: '#F0F6FF', bodyColor: '#8BA3C7', padding: 12, callbacks: {{ label: i => ' Rate: ' + i.parsed.y + '%' }} }} }},
    }});
    new Chart(document.getElementById('oldChart'), {{
      type: 'line',
      data: {{ labels: weeks, datasets: [{{ data: oldRates, borderColor: 'rgba(239,68,68,0.85)', backgroundColor: 'rgba(239,68,68,0.08)', borderWidth: 2.5, pointBackgroundColor: 'rgba(239,68,68,0.85)', pointRadius: 5, tension: 0.3, fill: true }}] }},
      options: lineOpts(),
    }});
    new Chart(document.getElementById('newChart'), {{
      type: 'line',
      data: {{ labels: weeks, datasets: [{{ data: newRates, borderColor: 'rgba(16,185,129,0.90)', backgroundColor: 'rgba(16,185,129,0.08)', borderWidth: 2.5, pointBackgroundColor: 'rgba(16,185,129,0.90)', pointRadius: 5, tension: 0.3, fill: true }}] }},
      options: lineOpts(),
    }});
  }}

  // ═══════════════ TAB SWITCHING ═══════════════
  document.querySelectorAll('.tab-btn').forEach(btn => {{
    btn.addEventListener('click', () => {{
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
      if (btn.dataset.tab === 'analysis') renderAnalysisCharts();
    }});
  }});

  // ═══════════════ TAB 2: WEEKLY CHARTS ═══════════════
  const wkLabels = weeklyData.map(w => 'Wk ' + w.week_num);
  const wkDials = weeklyData.map(w => w.total_dials);
  const wkHCRate = weeklyData.map(w => w.human_contact_rate);

  new Chart(document.getElementById('weeklyDialsChart'), {{
    type: 'bar',
    data: {{
      labels: wkLabels,
      datasets: [
        {{
          label: 'Dials', data: wkDials,
          backgroundColor: 'rgba(59,130,246,0.28)', borderColor: 'rgba(59,130,246,0.70)',
          borderWidth: 1.5, borderRadius: 5, yAxisID: 'y', order: 2,
        }},
        {{
          label: 'Human Contact %', data: wkHCRate, type: 'line',
          borderColor: '#10B981', backgroundColor: 'rgba(16,185,129,0.07)',
          borderWidth: 2.5, pointBackgroundColor: '#10B981', pointRadius: 5,
          pointHoverRadius: 7, fill: true, tension: 0.35, yAxisID: 'y1', order: 0,
        }}
      ]
    }},
    options: {{
      responsive: true,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ labels: {{ color: '#8BA3C7', font: {{ size: 11, family: 'Inter', weight: '600' }}, padding: 16, boxWidth: 12, boxHeight: 12 }} }},
        tooltip: {{ ...tooltipStyle, callbacks: {{ label: ctx => ctx.dataset.yAxisID === 'y1' ? ' HC Rate: ' + ctx.raw + '%' : ' Dials: ' + ctx.raw }} }},
      }},
      scales: {{
        x: {{ ticks: {{ color: '#8BA3C7', font: {{ size: 11, family: 'Inter' }} }}, grid: gridStyle }},
        y: {{ beginAtZero: true, title: {{ display: true, text: 'Dials', color: '#8BA3C7', font: {{ size: 11 }} }}, ticks: {{ color: '#8BA3C7' }}, grid: gridStyle }},
        y1: {{ beginAtZero: true, position: 'right', max: 25, title: {{ display: true, text: 'HC Rate %', color: '#8BA3C7', font: {{ size: 11 }} }}, ticks: {{ color: '#8BA3C7', callback: v => v + '%' }}, grid: {{ drawOnChartArea: false }} }},
      }}
    }}
  }});

  // Stacked conversation outcomes
  const convCats = ['Interested', 'Meeting Booked', 'Referral Given', 'Not Interested', 'No Rail', 'Wrong Person', 'Gatekeeper'];
  const stackDatasets = convCats.map(cat => ({{
    label: cat,
    data: weeklyData.map(w => (w.categories && w.categories[cat]) || 0),
    backgroundColor: catColors[cat] + 'CC', borderColor: catColors[cat],
    borderWidth: 1, borderRadius: 2,
  }}));

  new Chart(document.getElementById('stackedChart'), {{
    type: 'bar',
    data: {{ labels: wkLabels, datasets: stackDatasets }},
    options: {{
      responsive: true,
      plugins: {{
        legend: {{ labels: {{ color: '#8BA3C7', font: {{ size: 10, family: 'Inter', weight: '600' }}, padding: 10, boxWidth: 10, boxHeight: 10 }} }},
        tooltip: tooltipStyle,
      }},
      scales: {{
        x: {{ stacked: true, ticks: {{ color: '#8BA3C7', font: {{ size: 11, family: 'Inter' }} }}, grid: gridStyle }},
        y: {{ stacked: true, beginAtZero: true, title: {{ display: true, text: 'Conversations', color: '#8BA3C7', font: {{ size: 11 }} }}, ticks: {{ color: '#8BA3C7' }}, grid: gridStyle }},
      }}
    }}
  }});

  // ═══════════════ SHARED UTILS ═══════════════
  function formatDuration(s) {{
    if (s < 60) return s + 's';
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return sec > 0 ? m + 'm ' + sec + 's' : m + 'm';
  }}

  function formatTimestamp(iso) {{
    const d = new Date(iso);
    const mon = d.toLocaleString('en-US', {{ month: 'short' }});
    const day = d.getDate();
    const h = d.getHours();
    const m = String(d.getMinutes()).padStart(2, '0');
    const ampm = h >= 12 ? 'PM' : 'AM';
    const h12 = h % 12 || 12;
    return mon + ' ' + day + ', ' + h12 + ':' + m + ' ' + ampm;
  }}

  function truncate(s, len) {{
    if (!s) return '<span style="color:var(--muted);">&mdash;</span>';
    if (s.length <= len) return escapeHtml(s);
    return escapeHtml(s.slice(0, len)) + '&hellip;';
  }}

  function escapeHtml(s) {{
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }}

  // ═══════════════ TAB 3: CALL LOG ═══════════════
  (function() {{
    const PAGE_SIZE = 50;
    let filtered = [];
    let currentPage = 0;

    const searchInput = document.getElementById('calllog-search');
    const filterSelect = document.getElementById('calllog-filter');
    const tbody = document.getElementById('calllog-body');
    const statsEl = document.getElementById('calllog-stats');
    const pagEl = document.getElementById('calllog-pagination');

    // Populate category filter
    const cats = [...new Set(allCalls.map(c => c.category))].sort();
    cats.forEach(c => {{
      const opt = document.createElement('option');
      opt.value = c; opt.textContent = c;
      filterSelect.appendChild(opt);
    }});

    function applyFilters() {{
      const q = searchInput.value.toLowerCase().trim();
      const cat = filterSelect.value;
      filtered = allCalls.filter(c => {{
        if (cat && c.category !== cat) return false;
        if (q) {{
          const haystack = (c.contact_name + ' ' + (c.company_name||'') + ' ' + c.category + ' ' + c.notes + ' ' + (c.engagement_notes||[]).join(' ')).toLowerCase();
          return haystack.includes(q);
        }}
        return true;
      }});
      // Sort newest first
      filtered.sort((a, b) => b.timestamp.localeCompare(a.timestamp));
      currentPage = 0;
      render();
    }}

    function render() {{
      const start = currentPage * PAGE_SIZE;
      const page = filtered.slice(start, start + PAGE_SIZE);
      const totalPages = Math.ceil(filtered.length / PAGE_SIZE);

      if (filtered.length === 0) {{
        statsEl.textContent = 'No calls match your filter.';
      }} else {{
        statsEl.textContent = 'Showing ' + (start + 1) + '\u2013' + Math.min(start + PAGE_SIZE, filtered.length) + ' of ' + filtered.length + ' calls';
      }}

      let html = '';
      page.forEach((c, i) => {{
        const rowId = 'row-' + start + '-' + i;
        const catColor = catColors[c.category] || '#8BA3C7';
        const hasNotes = c.notes && c.notes.trim().length > 0;
        const hasEngNotes = c.engagement_notes && c.engagement_notes.length > 0;
        const hasDetail = hasNotes || hasEngNotes;
        const expandClass = hasDetail ? ' expandable' : '';
        const arrow = hasDetail ? ' &#x25B6;' : '';
        const txBadge = c.has_transcript ? '<span class="transcript-badge">TRANSCRIPT</span>' : '';

        html += '<tr class="' + expandClass + '" onclick="toggleNotes(\\'' + rowId + '\\')">';
        html += '<td class="muted" style="white-space:nowrap;">' + formatTimestamp(c.timestamp) + '</td>';
        html += '<td>' + escapeHtml(c.contact_name) + txBadge + '</td>';
        html += '<td style="color:var(--muted);font-size:12px;">' + escapeHtml(c.company_name || '') + '</td>';
        html += '<td style="text-align:center;"><span style="color:' + catColor + ';font-weight:600;">' + escapeHtml(c.category) + '</span></td>';
        html += '<td class="num-col">' + formatDuration(c.duration_s) + '</td>';
        html += '<td style="max-width:280px;">' + truncate(c.notes, 50) + arrow + '</td>';
        html += '</tr>';

        if (hasDetail) {{
          let detailHtml = '';
          if (hasNotes) detailHtml += '<div class="notes-content">' + escapeHtml(c.notes) + '</div>';
          if (hasEngNotes) {{
            detailHtml += '<div class="eng-notes"><div class="eng-notes-label">Engagement Notes</div>';
            c.engagement_notes.forEach(n => {{ detailHtml += '<div class="eng-note-item">' + escapeHtml(n) + '</div>'; }});
            detailHtml += '</div>';
          }}
          html += '<tr class="notes-row" id="' + rowId + '"><td colspan="6"><div style="padding:4px;">' + detailHtml + '</div></td></tr>';
        }}
      }});

      tbody.innerHTML = html;

      // Pagination
      let pagHtml = '';
      if (totalPages > 1) {{
        if (currentPage > 0) pagHtml += '<button onclick="calllogPage(' + (currentPage - 1) + ')">&laquo; Prev</button>';
        const maxBtns = 7;
        let startP = Math.max(0, currentPage - 3);
        let endP = Math.min(totalPages, startP + maxBtns);
        if (endP - startP < maxBtns) startP = Math.max(0, endP - maxBtns);
        for (let p = startP; p < endP; p++) {{
          const cls = p === currentPage ? ' class="active"' : '';
          pagHtml += '<button' + cls + ' onclick="calllogPage(' + p + ')">' + (p + 1) + '</button>';
        }}
        if (currentPage < totalPages - 1) pagHtml += '<button onclick="calllogPage(' + (currentPage + 1) + ')">Next &raquo;</button>';
      }}
      pagEl.innerHTML = pagHtml;
    }}

    window.calllogPage = function(p) {{ currentPage = p; render(); window.scrollTo(0, document.getElementById('calllog-table').offsetTop - 80); }};
    window.toggleNotes = function(id) {{
      const row = document.getElementById(id);
      if (row) row.classList.toggle('open');
    }};

    searchInput.addEventListener('input', applyFilters);
    filterSelect.addEventListener('change', applyFilters);

    applyFilters();
  }})();

  // ═══════════════ TAB 5: COMPANIES ═══════════════
  (function() {{
    const searchInput = document.getElementById('company-search');
    const sortSelect = document.getElementById('company-sort');
    const statsEl = document.getElementById('company-stats');
    const listEl = document.getElementById('company-list');

    // Build company map from allCalls
    const companyMap = {{}};
    let unknownCount = 0;
    allCalls.forEach(c => {{
      const co = (c.company_name || '').trim();
      if (!co) {{ unknownCount++; return; }}
      if (!companyMap[co]) {{
        companyMap[co] = {{ name: co, calls: [], categories: {{}}, contactSet: {{}}, meetings: 0 }};
      }}
      const entry = companyMap[co];
      entry.calls.push(c);
      entry.categories[c.category] = (entry.categories[c.category] || 0) + 1;
      if (c.contact_name) entry.contactSet[c.contact_name] = 1;
      if (c.category === 'Meeting Booked') entry.meetings++;
    }});

    let companies = Object.values(companyMap);
    companies.forEach(co => {{
      co.contacts = Object.keys(co.contactSet);
      co.totalCalls = co.calls.length;
      co.humanContacts = co.calls.filter(c => ['Interested','Meeting Booked','Referral Given','Not Interested','No Rail','Wrong Person','Gatekeeper'].includes(c.category)).length;
      co.calls.sort((a, b) => b.timestamp.localeCompare(a.timestamp));
      co.lastCall = co.calls[0].timestamp;
      co.firstCall = co.calls[co.calls.length - 1].timestamp;
    }});

    function sortList(arr, key) {{
      const cmp = {{
        calls: (a, b) => b.totalCalls - a.totalCalls,
        recent: (a, b) => b.lastCall.localeCompare(a.lastCall),
        name: (a, b) => a.name.localeCompare(b.name),
        meetings: (a, b) => b.meetings - a.meetings || b.totalCalls - a.totalCalls,
      }};
      return arr.slice().sort(cmp[key] || cmp.calls);
    }}

    function renderCompanies() {{
      const q = searchInput.value.toLowerCase().trim();
      let visible = companies;
      if (q) visible = companies.filter(co => co.name.toLowerCase().includes(q) || co.contacts.some(ct => ct.toLowerCase().includes(q)));

      visible = sortList(visible, sortSelect.value);

      const total = visible.length;
      statsEl.textContent = total + ' companies contacted' + (unknownCount > 0 ? ' (' + unknownCount + ' calls without company)' : '');

      let html = '';
      visible.forEach((co, idx) => {{
        const coId = 'co-' + idx;
        // Category pills
        let catPills = '';
        Object.entries(co.categories).sort((a,b) => b[1] - a[1]).forEach(([cat, count]) => {{
          const color = catColors[cat] || '#8BA3C7';
          catPills += '<span class="company-cat-pill" style="color:' + color + ';border-color:' + color + '33;">' + count + ' ' + escapeHtml(cat) + '</span>';
        }});

        // Timeline
        let timeline = '';
        co.calls.forEach(c => {{
          const catColor = catColors[c.category] || '#8BA3C7';
          const notePreview = c.notes ? '<div class="company-call-notes">' + escapeHtml(c.notes.slice(0, 120)) + (c.notes.length > 120 ? '...' : '') + '</div>' : '';
          const engNotes = (c.engagement_notes || []).map(n => '<div class="company-call-notes" style="color:var(--orange);opacity:0.8;">Note: ' + escapeHtml(n.slice(0, 100)) + (n.length > 100 ? '...' : '') + '</div>').join('');
          const txBadge = c.has_transcript ? ' <span class="transcript-badge">TX</span>' : '';
          timeline += '<div class="company-call">'
            + '<div class="company-call-header">'
            + '<span class="company-call-date">' + formatTimestamp(c.timestamp) + '</span>'
            + '<span class="company-call-contact">' + escapeHtml(c.contact_name) + txBadge + '</span>'
            + '<span class="company-call-cat" style="color:' + catColor + ';">' + escapeHtml(c.category) + '</span>'
            + '<span class="company-call-dur">' + formatDuration(c.duration_s) + '</span>'
            + '</div>'
            + notePreview + engNotes
            + '</div>';
        }});

        html += '<div class="company-card" id="' + coId + '">'
          + '<div class="company-header" onclick="toggleCompany(\\'' + coId + '\\')">'
          + '<div class="company-name">' + escapeHtml(co.name) + '</div>'
          + '<div class="company-meta">'
          + '<div class="company-stat"><span class="cs-num blue">' + co.totalCalls + '</span><span class="cs-label">Calls</span></div>'
          + '<div class="company-stat"><span class="cs-num orange">' + co.humanContacts + '</span><span class="cs-label">HC</span></div>'
          + (co.meetings > 0 ? '<div class="company-stat"><span class="cs-num green">' + co.meetings + '</span><span class="cs-label">Mtgs</span></div>' : '')
          + '<div class="company-stat"><span class="cs-label">' + co.contacts.length + ' contact' + (co.contacts.length !== 1 ? 's' : '') + '</span></div>'
          + '</div>'
          + '<span class="company-chevron">&#x25B6;</span>'
          + '</div>'
          + '<div class="company-detail">'
          + '<div class="company-cats">' + catPills + '</div>'
          + '<div class="company-timeline">' + timeline + '</div>'
          + '</div>'
          + '</div>';
      }});

      listEl.innerHTML = html || '<div style="text-align:center;color:var(--muted);padding:40px;">No companies match your search.</div>';
    }}

    window.toggleCompany = function(id) {{
      const el = document.getElementById(id);
      if (el) el.classList.toggle('open');
    }};

    searchInput.addEventListener('input', renderCompanies);
    sortSelect.addEventListener('change', renderCompanies);
    renderCompanies();
  }})();
</script>
</body>
</html>"""

    return html


def _fetch_task_queue(token: str) -> Optional[dict]:
    """Fetch HubSpot task queue. Returns None on failure."""
    try:
        print("Fetching task queue...")
        result = fetch_open_tasks(token)
        print(f"  Task queue: {result['total_open']} open tasks ({result['alert_level']})")
        return result
    except Exception as e:
        print(f"  Warning: task queue fetch failed: {e}")
        return None


def _fetch_apollo(api_key: str) -> Optional[dict]:
    """Fetch Apollo email stats. Returns None on failure."""
    try:
        print("Fetching Apollo email stats...")
        result = fetch_apollo_stats(api_key)
        t = result["totals"]
        print(f"  Apollo: {t['emails_sent']} sent, {t['open_rate']}% open, {t['reply_rate']}% reply")
        return result
    except Exception as e:
        print(f"  Warning: Apollo fetch failed: {e}")
        return None


def _fetch_linkedin(sheet_id: str, creds_json: str) -> Optional[dict]:
    """Fetch LinkedIn stats from Google Sheet. Returns None on failure."""
    try:
        print("Fetching LinkedIn stats from Google Sheet...")
        result = fetch_linkedin_stats(sheet_id, creds_json)
        print(f"  LinkedIn: {result['requests_sent']} sent, {result['connected']} connected ({result['accept_rate']}%)")
        return result
    except Exception as e:
        print(f"  Warning: LinkedIn stats fetch failed: {e}")
        return None


def main():
    print("Outbound Central — Dashboard Generator")
    print("=" * 45)

    token = validate_env()

    # 1. Build core call data
    data = build_call_data(token)

    # 2. Fetch optional data sources
    data["task_queue"] = _fetch_task_queue(token)

    apollo_key = os.getenv("APOLLO_API_KEY")
    data["apollo_stats"] = _fetch_apollo(apollo_key) if apollo_key else None
    if not apollo_key:
        print("  Apollo: APOLLO_API_KEY not set, skipping")

    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if sheet_id and creds_json:
        data["linkedin_stats"] = _fetch_linkedin(sheet_id, creds_json)
    else:
        data["linkedin_stats"] = None
        print("  LinkedIn: GOOGLE_SHEET_ID/GOOGLE_CREDENTIALS_JSON not set, skipping")

    # 3. Write call_data.json
    json_path = HERE / "call_data.json"
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"Written {json_path} ({json_path.stat().st_size:,} bytes)")

    # 4. Generate HTML
    print("Generating dashboard HTML...")
    html = build_html(data)

    html_path = HERE / "index.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"Written {html_path} ({len(html):,} bytes)")

    print("Done. Open index.html in a browser to view.")


if __name__ == "__main__":
    main()
