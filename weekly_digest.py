#!/usr/bin/env python3
"""
weekly_digest.py — Weekly Slack digest for Telegraph outbound sales.

Pulls data from Supabase, generates an AI executive summary via Gemini Flash,
and posts a formatted mrkdwn message to a Slack webhook.

Usage:
    python3 weekly_digest.py                 # generate + send to Slack
    python3 weekly_digest.py --dry-run       # print message, don't send
    python3 weekly_digest.py --no-ai         # skip Gemini summary
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CAMPAIGN_START = date(2026, 1, 19)
GEMINI_MODEL = "gemini-2.0-flash"
DASHBOARD_URL = "https://nikoamoretti.github.io/sales-dashboard/"

INSIGHT_EMOJI: dict[str, str] = {
    "action_required": ":red_circle:",
    "alert": ":warning:",
    "win": ":trophy:",
    "experiment": ":bulb:",
    "coaching": ":book:",
    "strategic": ":compass:",
}

# Priority order for selecting the representative insight per type
INSIGHT_TYPE_PRIORITY = ["action_required", "alert", "win", "experiment"]

DIVIDER = "━━━━━━━━━━━━━━━━━━━━━━━━━"


# ---------------------------------------------------------------------------
# Campaign week helpers
# ---------------------------------------------------------------------------

def campaign_week_num(d: date) -> int:
    monday = d - timedelta(days=d.weekday())
    return ((monday - CAMPAIGN_START).days // 7) + 1


def week_date_range(week_num: int) -> tuple[date, date]:
    """Return the Monday and Friday for a given campaign week number."""
    monday = CAMPAIGN_START + timedelta(weeks=week_num - 1)
    friday = monday + timedelta(days=4)
    return monday, friday


def fmt_date_range(week_num: int) -> str:
    monday, friday = week_date_range(week_num)
    if monday.month == friday.month:
        return f"{monday.strftime('%b %-d')}–{friday.strftime('%-d, %Y')}"
    return f"{monday.strftime('%b %-d')} – {friday.strftime('%b %-d, %Y')}"


# ---------------------------------------------------------------------------
# Supabase client
# ---------------------------------------------------------------------------

def _sb():
    from supabase import create_client
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_KEY"],
    )


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_call_snapshots(sb) -> list[dict]:
    """All call weekly_snapshots ordered by week_num ascending."""
    result = (
        sb.table("weekly_snapshots")
        .select("*")
        .eq("channel", "calls")
        .order("week_num", desc=False)
        .execute()
    )
    return result.data or []


def fetch_linkedin_snapshots(sb) -> list[dict]:
    """All linkedin weekly_snapshots ordered by week_num ascending."""
    result = (
        sb.table("weekly_snapshots")
        .select("*")
        .eq("channel", "linkedin")
        .order("week_num", desc=False)
        .execute()
    )
    return result.data or []


def fetch_email_sequences(sb) -> list[dict]:
    """Latest snapshot per active sequence (deduplicated)."""
    result = (
        sb.table("email_sequences")
        .select("sequence_name, sent, opened, replied, open_rate, reply_rate, snapshot_date")
        .eq("status", "active")
        .order("snapshot_date", desc=True)
        .limit(30)
        .execute()
    )
    seen: set[str] = set()
    sequences = []
    for row in result.data or []:
        name = row.get("sequence_name") or ""
        if name not in seen:
            seen.add(name)
            sequences.append(row)
    return sequences


def fetch_meetings_this_week(sb, week_num: int) -> list[dict]:
    """Calls categorised as Meeting Booked in the given campaign week."""
    result = (
        sb.table("calls")
        .select("id, contact_name, called_at, company_id, companies(id, name)")
        .eq("category", "Meeting Booked")
        .eq("week_num", week_num)
        .order("called_at", desc=False)
        .execute()
    )
    return result.data or []


def fetch_recent_insights(sb) -> list[dict]:
    """Insights from today or most recent date — used for AI Advisor section."""
    # Try today first, then fall back to the most recent date available
    today_str = date.today().isoformat()
    result = (
        sb.table("insights")
        .select("type, severity, title, body, channel")
        .eq("insight_date", today_str)
        .order("created_at", desc=False)
        .execute()
    )
    if not result.data:
        # Fetch the most recent date's insights
        latest = (
            sb.table("insights")
            .select("insight_date")
            .order("insight_date", desc=True)
            .limit(1)
            .execute()
        )
        if latest.data:
            latest_date = latest.data[0]["insight_date"]
            result = (
                sb.table("insights")
                .select("type, severity, title, body, channel")
                .eq("insight_date", latest_date)
                .order("created_at", desc=False)
                .execute()
            )
    return result.data or []


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def _pct(value: float | None) -> str:
    """Format a float as a percentage string (e.g. 5.5 → '5.5%'). Values already in percent."""
    if value is None:
        return "n/a"
    return f"{value:.1f}%"


def _delta_arrow(current: float | int | None, previous: float | int | None) -> str:
    """Return '↑', '↓', or '→' based on delta direction."""
    if current is None or previous is None:
        return ""
    if current > previous:
        return "↑"
    if current < previous:
        return "↓"
    return "→"


def _snap(snapshots: list[dict], week_num: int) -> dict:
    """Return the snapshot for a specific week, or empty dict."""
    for s in snapshots:
        if s.get("week_num") == week_num:
            return s
    return {}


# ---------------------------------------------------------------------------
# Gemini executive summary
# ---------------------------------------------------------------------------

def build_summary_prompt(
    current_week: int,
    call_snap: dict,
    prev_call_snap: dict,
    li_snap: dict,
    meetings: list[dict],
    email_sequences: list[dict],
) -> str:
    dials = call_snap.get("dials") or 0
    prev_dials = prev_call_snap.get("dials") or 0
    cr = call_snap.get("human_contact_rate") or 0.0
    prev_cr = prev_call_snap.get("human_contact_rate") or 0.0
    mtgs = call_snap.get("meetings_booked") or 0

    li_sent = li_snap.get("inmails_sent") or 0
    li_rr = li_snap.get("inmail_reply_rate") or 0.0
    li_interested = li_snap.get("interested_count") or 0

    email_summary = ""
    if email_sequences:
        total_sent = sum(s.get("sent") or 0 for s in email_sequences)
        avg_reply = (
            sum(s.get("reply_rate") or 0.0 for s in email_sequences) / len(email_sequences)
            if email_sequences else 0.0
        )
        email_summary = f"Email: {total_sent} sent across {len(email_sequences)} sequences, avg {avg_reply * 100:.1f}% reply rate."
    else:
        email_summary = "Email: no data connected yet."

    meeting_names = ", ".join(
        f"{m.get('contact_name') or 'Unknown'} @ {(m.get('companies') or {}).get('name') or 'Unknown'}"
        for m in meetings
    ) or "none"

    return f"""\
Telegraph is a freight railroad brokerage running cold outbound. Week {current_week} data:

Cold calling: {dials} dials (prev: {prev_dials}), {_pct(cr)} contact rate (prev: {_pct(prev_cr)}), {mtgs} meeting(s) booked.
LinkedIn InMails: {li_sent} sent, {_pct(li_rr)} reply rate, {li_interested} interested.
{email_summary}
Meetings booked this week: {meeting_names}.

Write a 2-3 sentence executive summary of this week's outbound performance. Be direct and specific. Highlight what went well, what needs attention, and one forward-looking note. No bullet points — prose only. Max 60 words."""


def call_gemini_summary(prompt: str) -> str:
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config={"temperature": 0.3, "max_output_tokens": 200},
    )
    return (response.text or "").strip()


# ---------------------------------------------------------------------------
# Insight selection
# ---------------------------------------------------------------------------

def select_top_insights(insights: list[dict]) -> list[dict]:
    """
    Pick the top insight from each of the priority types.
    Severity ordering: high > medium > low.
    Returns at most 4 insights, one per type.
    """
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    by_type: dict[str, list[dict]] = {}
    for ins in insights:
        t = ins.get("type") or "unknown"
        by_type.setdefault(t, []).append(ins)

    # Sort each type's list by severity
    for t in by_type:
        by_type[t].sort(key=lambda x: severity_rank.get(x.get("severity", "medium"), 1))

    selected = []
    for t in INSIGHT_TYPE_PRIORITY:
        if t in by_type and by_type[t]:
            selected.append(by_type[t][0])
    return selected


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------

def _first_sentence(text: str) -> str:
    """Return the first sentence of a body string."""
    text = (text or "").strip()
    for sep in (". ", ".\n", "! ", "? "):
        idx = text.find(sep)
        if idx != -1:
            return text[: idx + 1].strip()
    return text[:180].strip()


def build_message(
    current_week: int,
    call_snapshots: list[dict],
    linkedin_snapshots: list[dict],
    email_sequences: list[dict],
    meetings: list[dict],
    insights: list[dict],
    exec_summary: Optional[str],
) -> str:
    today = date.today()
    call_snap = _snap(call_snapshots, current_week)
    prev_call_snap = _snap(call_snapshots, current_week - 1)
    li_snap = _snap(linkedin_snapshots, current_week)
    prev_li_snap = _snap(linkedin_snapshots, current_week - 1)

    lines: list[str] = []

    # ── Header ──────────────────────────────────────────────────────────────
    lines.append(f":building_construction: *Telegraph Outbound — Weekly Digest*")
    lines.append(f":calendar: Week {current_week} ({fmt_date_range(current_week)})")
    lines.append("")
    lines.append(DIVIDER)

    # ── Executive Summary ───────────────────────────────────────────────────
    lines.append("")
    lines.append(":bar_chart: *Executive Summary*")
    if exec_summary:
        lines.append(exec_summary)
    else:
        lines.append("_(AI summary skipped)_")
    lines.append("")
    lines.append(DIVIDER)

    # ── Cold Calling ────────────────────────────────────────────────────────
    lines.append("")
    dials = call_snap.get("dials") or 0
    prev_dials = prev_call_snap.get("dials") or 0
    cr = call_snap.get("human_contact_rate") or 0.0
    prev_cr = prev_call_snap.get("human_contact_rate") or 0.0
    mtgs = call_snap.get("meetings_booked") or 0
    prev_mtgs = prev_call_snap.get("meetings_booked") or 0

    dials_arrow = _delta_arrow(dials, prev_dials)
    cr_arrow = _delta_arrow(cr, prev_cr)

    lines.append(":telephone_receiver: *Cold Calling*")

    if call_snap:
        lines.append(
            f"• Dials: {dials} "
            f"({dials_arrow} from {prev_dials} last week)"
        )
        lines.append(
            f"• Contact Rate: {_pct(cr)} "
            f"({cr_arrow} from {_pct(prev_cr)})"
        )
        lines.append(f"• Meetings Booked: {mtgs}")

        # Top call categories
        cats: dict = call_snap.get("categories") or {}
        if isinstance(cats, str):
            import json
            try:
                cats = json.loads(cats)
            except (ValueError, TypeError):
                cats = {}
        if cats:
            top_cats = sorted(cats.items(), key=lambda x: -(x[1] or 0))[:3]
            cat_str = ", ".join(f"{name} ({count})" for name, count in top_cats)
            lines.append(f"• Top categories: {cat_str}")
    else:
        lines.append("• No call data for this week")

    # ── LinkedIn InMails ─────────────────────────────────────────────────────
    lines.append("")
    li_sent = li_snap.get("inmails_sent") or 0
    li_replied = li_snap.get("inmails_replied") or 0
    li_rr = li_snap.get("inmail_reply_rate") or 0.0
    prev_li_rr = prev_li_snap.get("inmail_reply_rate") or 0.0
    li_interested = li_snap.get("interested_count") or 0

    lines.append(":incoming_envelope: *LinkedIn InMails*")

    if li_snap:
        rr_arrow = _delta_arrow(li_rr, prev_li_rr)
        lines.append(
            f"• Sent: {li_sent} | Replied: {li_replied} "
            f"({_pct(li_rr)} reply rate {rr_arrow} from {_pct(prev_li_rr)})"
        )
        # Sentiment breakdown from this week's snapshot — interested_count is the only
        # pre-aggregated sentiment field on the snapshot; detailed breakdown requires
        # querying the inmails table directly. Keep it light for the digest.
        lines.append(f"• Interested: {li_interested}")
    else:
        lines.append("• No LinkedIn data for this week")

    # ── Email Sequences ──────────────────────────────────────────────────────
    lines.append("")
    lines.append(":e-mail: *Email Sequences*")

    if email_sequences:
        total_sent = sum(s.get("sent") or 0 for s in email_sequences)
        total_replied = sum(s.get("replied") or 0 for s in email_sequences)
        avg_rr = (
            sum(s.get("reply_rate") or 0.0 for s in email_sequences) / len(email_sequences)
        )
        lines.append(
            f"• {len(email_sequences)} active sequence(s) | "
            f"{total_sent} total sent | {total_replied} replies ({_pct(avg_rr)} avg reply rate)"
        )
        # Top sequence by sent volume
        top_seq = max(email_sequences, key=lambda s: s.get("sent") or 0)
        lines.append(
            f"• Top sequence: \"{top_seq.get('sequence_name') or 'Unknown'}\" — "
            f"{top_seq.get('sent') or 0} sent, {_pct(top_seq.get('reply_rate') or 0.0)} reply rate"
        )
    else:
        lines.append("• Not connected yet")

    lines.append("")
    lines.append(DIVIDER)

    # ── Meetings Booked ──────────────────────────────────────────────────────
    lines.append("")
    lines.append(":dart: *Meetings Booked This Week*")

    if meetings:
        for m in meetings:
            contact = m.get("contact_name") or "Unknown"
            company = (m.get("companies") or {}).get("name") or "Unknown Company"
            called_at = m.get("called_at") or ""
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(called_at.replace("Z", "+00:00"))
                date_str = dt.strftime("%b %-d")
            except (ValueError, AttributeError):
                date_str = called_at[:10] if called_at else "Unknown date"
            lines.append(f"• {date_str} — {contact}, {company}")
    else:
        lines.append("• No meetings booked this week")

    lines.append("")
    lines.append(DIVIDER)

    # ── AI Advisor Highlights ────────────────────────────────────────────────
    lines.append("")
    lines.append(":brain: *AI Advisor Highlights*")

    top_insights = select_top_insights(insights)
    if top_insights:
        for ins in top_insights:
            itype = ins.get("type") or "unknown"
            emoji = INSIGHT_EMOJI.get(itype, ":white_circle:")
            title = ins.get("title") or ""
            body = _first_sentence(ins.get("body") or "")
            lines.append(f"{emoji} {title}")
            if body:
                lines.append(f"   → {body}")
    else:
        lines.append("• No insights generated yet — run `advisor.py` first")

    lines.append("")
    lines.append(DIVIDER)

    # ── 6-Week Trend ─────────────────────────────────────────────────────────
    lines.append("")
    lines.append(":chart_with_upwards_trend: *6-Week Trend*")

    # Show up to 6 weeks (or all available), current week highlighted
    start_week = max(1, current_week - 5)
    for wn in range(start_week, current_week + 1):
        snap = _snap(call_snapshots, wn)
        if not snap and wn != current_week:
            continue

        wk_dials = snap.get("dials") or 0
        wk_cr = snap.get("human_contact_rate") or 0.0
        wk_mtgs = snap.get("meetings_booked") or 0

        mtg_str = ""
        if wk_mtgs == 1:
            mtg_str = ", 1 mtg :white_check_mark:"
        elif wk_mtgs > 1:
            mtg_str = f", {wk_mtgs} mtg " + ":white_check_mark:" * wk_mtgs

        row = f"Wk {wn}: {wk_dials} dials, {_pct(wk_cr)} CR{mtg_str}"

        if wn == current_week:
            lines.append(f"*{row}* ◀")
        else:
            lines.append(row)

    # ── Footer ───────────────────────────────────────────────────────────────
    lines.append("")
    lines.append(f":link: *Full dashboard*: {DASHBOARD_URL}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Slack posting
# ---------------------------------------------------------------------------

def post_to_slack(webhook_url: str, message: str) -> None:
    resp = requests.post(
        webhook_url,
        json={"text": message},
        timeout=10,
    )
    resp.raise_for_status()
    print(f"Slack: {resp.status_code} {resp.text}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Telegraph weekly Slack digest — outbound sales performance summary"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print message to stdout without posting to Slack",
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Skip Gemini executive summary generation",
    )
    args = parser.parse_args()

    # Validate required env vars
    required_env = ["SUPABASE_URL", "SUPABASE_SERVICE_KEY"]
    if not args.no_ai:
        required_env.append("GEMINI_API_KEY")
    if not args.dry_run:
        required_env.append("SLACK_WEBHOOK_URL")

    missing = [k for k in required_env if not os.environ.get(k)]
    if missing:
        print(f"ERROR: Missing environment variables: {', '.join(missing)}", file=sys.stderr)
        return 1

    today = date.today()
    current_week = campaign_week_num(today)
    print(f"Generating digest for Week {current_week} ({fmt_date_range(current_week)})")

    # ── Fetch data ────────────────────────────────────────────────────────────
    sb = _sb()

    print("  Fetching call snapshots...")
    call_snapshots = fetch_call_snapshots(sb)

    print("  Fetching LinkedIn snapshots...")
    linkedin_snapshots = fetch_linkedin_snapshots(sb)

    print("  Fetching email sequences...")
    email_sequences = fetch_email_sequences(sb)

    print("  Fetching meetings this week...")
    meetings = fetch_meetings_this_week(sb, current_week)

    print("  Fetching insights...")
    insights = fetch_recent_insights(sb)

    print(
        f"  Data: {len(call_snapshots)} call weeks, {len(linkedin_snapshots)} LI weeks, "
        f"{len(email_sequences)} email seqs, {len(meetings)} meetings, {len(insights)} insights"
    )

    # ── AI executive summary ─────────────────────────────────────────────────
    exec_summary: Optional[str] = None
    if not args.no_ai:
        print("  Generating Gemini executive summary...")
        call_snap = _snap(call_snapshots, current_week)
        prev_call_snap = _snap(call_snapshots, current_week - 1)
        li_snap = _snap(linkedin_snapshots, current_week)
        prompt = build_summary_prompt(
            current_week=current_week,
            call_snap=call_snap,
            prev_call_snap=prev_call_snap,
            li_snap=li_snap,
            meetings=meetings,
            email_sequences=email_sequences,
        )
        try:
            exec_summary = call_gemini_summary(prompt)
            print(f"  Summary: {exec_summary[:80]}...")
        except Exception as e:
            print(f"  WARNING: Gemini failed — {e}", file=sys.stderr)
            exec_summary = None

    # ── Build message ─────────────────────────────────────────────────────────
    message = build_message(
        current_week=current_week,
        call_snapshots=call_snapshots,
        linkedin_snapshots=linkedin_snapshots,
        email_sequences=email_sequences,
        meetings=meetings,
        insights=insights,
        exec_summary=exec_summary,
    )

    # ── Output ────────────────────────────────────────────────────────────────
    if args.dry_run:
        print("\n" + "=" * 72)
        print(message)
        print("=" * 72)
        print("\n(dry-run — not posted to Slack)")
    else:
        webhook_url = os.environ["SLACK_WEBHOOK_URL"]
        print("  Posting to Slack...")
        try:
            post_to_slack(webhook_url, message)
        except requests.HTTPError as e:
            print(f"ERROR: Slack post failed — {e}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
