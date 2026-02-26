#!/usr/bin/env python3
"""
advisor.py — AI Sales Advisor for Telegraph Outbound.

Queries Supabase for recent multi-channel sales data, builds a rich context
prompt, and asks Gemini Flash to generate categorized, actionable insights.
Writes results to the `insights` table.

Usage:
    python3 advisor.py                  # generate today's insights
    python3 advisor.py --dry-run        # show prompt + insights without writing to DB
    python3 advisor.py --clear-today    # clear today's insights before regenerating
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GEMINI_MODEL = "gemini-2.0-flash"
MAX_INSIGHTS = 10
INSIGHT_TYPES = frozenset(
    {"action_required", "alert", "win", "experiment", "coaching", "strategic"}
)
SEVERITY_VALUES = frozenset({"high", "medium", "low"})

# Calls are interesting when they fall in these categories
SUBSTANTIVE_CATEGORIES = {
    "Interested", "Meeting Booked", "Referral Given",
    "Not Interested", "No Rail", "Wrong Person", "Gatekeeper",
}


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class WeekSnapshot:
    week_num: int
    monday: Optional[str]
    channel: str
    # calls
    dials: int = 0
    human_contacts: int = 0
    human_contact_rate: float = 0.0
    meetings_booked: int = 0
    categories: dict = field(default_factory=dict)
    # email
    emails_sent: int = 0
    email_open_rate: float = 0.0
    email_reply_rate: float = 0.0
    # linkedin
    inmails_sent: int = 0
    inmail_reply_rate: float = 0.0
    interested_count: int = 0


@dataclass
class SalesContext:
    today: date
    current_week: int
    # Weekly call trends (last 3 weeks)
    call_weeks: list[WeekSnapshot]
    # Weekly inmail trends (last 3 weeks)
    inmail_weeks: list[WeekSnapshot]
    # Email sequences (most recent snapshot)
    email_sequences: list[dict]
    # High-interest call intel (this week + last week)
    high_interest_calls: list[dict]
    # Unacted referrals (referral recorded, no follow-up call since)
    unacted_referrals: list[dict]
    # Common objections (last 2 weeks)
    objections: list[dict]
    # Recent meetings booked
    recent_meetings: list[dict]
    # Interested InMails with no follow-up
    interested_inmails: list[dict]
    # Company name → ID map for linking insights
    company_id_map: dict[str, int] = field(default_factory=dict)
    # call_id map: hubspot_call_id → db id
    call_id_map: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Supabase queries
# ---------------------------------------------------------------------------

def _sb():
    """Create and return a Supabase client."""
    from supabase import create_client
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)


def _current_week_num(sb) -> int:
    """Return the highest week_num present in weekly_snapshots for calls."""
    result = (
        sb.table("weekly_snapshots")
        .select("week_num")
        .eq("channel", "calls")
        .order("week_num", desc=True)
        .limit(1)
        .execute()
    )
    if result.data:
        return result.data[0]["week_num"]
    # Fallback: derive from today
    campaign_start = date(2026, 1, 19)
    delta = (date.today() - campaign_start).days
    return max(1, delta // 7 + 1)


def _fetch_weekly_snapshots(sb, channel: str, last_n: int = 3) -> list[WeekSnapshot]:
    result = (
        sb.table("weekly_snapshots")
        .select("*")
        .eq("channel", channel)
        .order("week_num", desc=True)
        .limit(last_n)
        .execute()
    )
    snapshots = []
    for row in reversed(result.data):  # oldest first
        s = WeekSnapshot(
            week_num=row["week_num"],
            monday=row.get("monday"),
            channel=channel,
            dials=row.get("dials") or 0,
            human_contacts=row.get("human_contacts") or 0,
            human_contact_rate=row.get("human_contact_rate") or 0.0,
            meetings_booked=row.get("meetings_booked") or 0,
            categories=row.get("categories") or {},
            emails_sent=row.get("emails_sent") or 0,
            email_open_rate=row.get("email_open_rate") or 0.0,
            email_reply_rate=row.get("email_reply_rate") or 0.0,
            inmails_sent=row.get("inmails_sent") or 0,
            inmail_reply_rate=row.get("inmail_reply_rate") or 0.0,
            interested_count=row.get("interested_count") or 0,
        )
        snapshots.append(s)
    return snapshots


def _fetch_email_sequences(sb) -> list[dict]:
    """Get the most recent snapshot for each active sequence."""
    result = (
        sb.table("email_sequences")
        .select("sequence_name, sent, opened, replied, open_rate, reply_rate, snapshot_date")
        .eq("status", "active")
        .order("snapshot_date", desc=True)
        .limit(20)
        .execute()
    )
    # Deduplicate: keep latest snapshot per sequence name
    seen: set[str] = set()
    sequences = []
    for row in result.data:
        name = row["sequence_name"]
        if name not in seen:
            seen.add(name)
            sequences.append(row)
    return sequences


def _fetch_high_interest_calls(sb, current_week: int) -> list[dict]:
    """
    Return call_intel rows with high/medium interest from the last 2 weeks,
    joined with call + company data.
    """
    min_week = current_week - 1
    result = (
        sb.table("call_intel")
        .select(
            "id, interest_level, next_action, referral_name, referral_role, "
            "objection, commodities, key_quote, qualified, "
            "calls(id, contact_name, category, called_at, hubspot_call_id, week_num, company_id), "
            "companies(id, name, status)"
        )
        .in_("interest_level", ["high", "medium"])
        .execute()
    )

    # Filter to last 2 weeks via the call's week_num
    filtered = []
    for row in result.data:
        call = row.get("calls") or {}
        week = call.get("week_num") or 0
        if week >= min_week:
            filtered.append(row)
    return filtered


def _fetch_unacted_referrals(sb, current_week: int) -> list[dict]:
    """
    Return call_intel rows where a referral was recorded (referral_name is set)
    but no subsequent call has been logged to the same company after the referral date.
    """
    result = (
        sb.table("call_intel")
        .select(
            "referral_name, referral_role, next_action, "
            "calls(id, contact_name, called_at, hubspot_call_id, company_id, week_num), "
            "companies(id, name)"
        )
        .not_.is_("referral_name", "null")
        .execute()
    )

    # For each referral, check if there's a later call to the same company
    unacted = []
    for row in result.data:
        call = row.get("calls") or {}
        company_id = call.get("company_id")
        called_at = call.get("called_at") or ""
        week_num = call.get("week_num") or 0

        # Only flag referrals from the last 2 weeks
        if week_num < current_week - 1:
            continue

        if not company_id:
            unacted.append(row)
            continue

        # Check for any subsequent call to the same company
        follow_up = (
            sb.table("calls")
            .select("id, called_at")
            .eq("company_id", company_id)
            .gt("called_at", called_at)
            .limit(1)
            .execute()
        )
        if not follow_up.data:
            unacted.append(row)

    return unacted


def _fetch_recent_objections(sb, current_week: int) -> list[dict]:
    """Return top objections from the last 2 weeks with frequency counts."""
    min_week = current_week - 1
    result = (
        sb.table("call_intel")
        .select("objection, calls(week_num)")
        .not_.is_("objection", "null")
        .execute()
    )

    counts: dict[str, int] = {}
    for row in result.data:
        call = row.get("calls") or {}
        week = call.get("week_num") or 0
        if week < min_week:
            continue
        obj = (row.get("objection") or "").strip()
        if obj:
            counts[obj] = counts.get(obj, 0) + 1

    return [
        {"objection": obj, "count": cnt}
        for obj, cnt in sorted(counts.items(), key=lambda x: -x[1])
    ][:8]


def _fetch_recent_meetings(sb, current_week: int) -> list[dict]:
    """Return calls categorized as Meeting Booked in the last 2 weeks."""
    min_week = current_week - 1
    result = (
        sb.table("calls")
        .select("id, contact_name, called_at, week_num, company_id, hubspot_call_id, "
                "companies(id, name, status)")
        .eq("category", "Meeting Booked")
        .gte("week_num", min_week)
        .order("called_at", desc=True)
        .execute()
    )
    return result.data


def _fetch_interested_inmails(sb, current_week: int) -> list[dict]:
    """Return InMails with 'interested' sentiment from the last 2 weeks."""
    min_week = current_week - 1
    result = (
        sb.table("inmails")
        .select("id, contact_name, contact_title, company_name, sent_date, "
                "reply_text, week_num, company_id")
        .eq("reply_sentiment", "interested")
        .gte("week_num", min_week)
        .order("sent_date", desc=True)
        .execute()
    )
    return result.data


def _fetch_company_id_map(sb) -> dict[str, int]:
    """Return a name → id map for all companies."""
    result = sb.table("companies").select("id, name").execute()
    return {row["name"]: row["id"] for row in result.data}


def _fetch_call_id_map(sb) -> dict[str, int]:
    """Return hubspot_call_id → db id map."""
    result = sb.table("calls").select("id, hubspot_call_id").execute()
    return {row["hubspot_call_id"]: row["id"] for row in result.data if row.get("hubspot_call_id")}


def gather_context(sb) -> SalesContext:
    """Pull all required data from Supabase into a SalesContext."""
    today = date.today()
    current_week = _current_week_num(sb)
    print(f"  Current week: {current_week} | Today: {today}")

    print("  Fetching weekly call snapshots...")
    call_weeks = _fetch_weekly_snapshots(sb, "calls", last_n=4)

    print("  Fetching weekly InMail snapshots...")
    inmail_weeks = _fetch_weekly_snapshots(sb, "linkedin", last_n=4)

    print("  Fetching email sequences...")
    email_sequences = _fetch_email_sequences(sb)

    print("  Fetching high-interest call intel...")
    high_interest_calls = _fetch_high_interest_calls(sb, current_week)

    print("  Fetching unacted referrals...")
    unacted_referrals = _fetch_unacted_referrals(sb, current_week)

    print("  Fetching recent objections...")
    objections = _fetch_recent_objections(sb, current_week)

    print("  Fetching recent meetings booked...")
    recent_meetings = _fetch_recent_meetings(sb, current_week)

    print("  Fetching interested InMails...")
    interested_inmails = _fetch_interested_inmails(sb, current_week)

    print("  Fetching company ID map...")
    company_id_map = _fetch_company_id_map(sb)

    print("  Fetching call ID map...")
    call_id_map = _fetch_call_id_map(sb)

    return SalesContext(
        today=today,
        current_week=current_week,
        call_weeks=call_weeks,
        inmail_weeks=inmail_weeks,
        email_sequences=email_sequences,
        high_interest_calls=high_interest_calls,
        unacted_referrals=unacted_referrals,
        objections=objections,
        recent_meetings=recent_meetings,
        interested_inmails=interested_inmails,
        company_id_map=company_id_map,
        call_id_map=call_id_map,
    )


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _fmt_week(w: WeekSnapshot) -> str:
    label = f"Week {w.week_num}" + (f" ({w.monday})" if w.monday else "")
    if w.channel == "calls":
        hcr = f"{w.human_contact_rate:.1%}" if w.human_contact_rate else "n/a"
        return (
            f"  {label}: {w.dials} dials, {w.human_contacts} contacts "
            f"({hcr} rate), {w.meetings_booked} meetings"
        )
    elif w.channel == "linkedin":
        rr = f"{w.inmail_reply_rate:.1%}" if w.inmail_reply_rate else "n/a"
        return (
            f"  {label}: {w.inmails_sent} sent, {w.inmail_reply_rate:.0%} reply rate, "
            f"{w.interested_count} interested"
        )
    elif w.channel == "email":
        return (
            f"  {label}: {w.emails_sent} sent, "
            f"open={w.email_open_rate:.1%}, reply={w.email_reply_rate:.1%}"
        )
    return f"  {label}"


def _fmt_call_intel(row: dict) -> str:
    call = row.get("calls") or {}
    company = row.get("companies") or {}
    company_name = company.get("name") or "Unknown Company"
    contact = call.get("contact_name") or "Unknown"
    called_at = (call.get("called_at") or "")[:10]
    interest = row.get("interest_level") or "?"
    next_action = row.get("next_action") or ""
    referral = row.get("referral_name") or ""
    objection = row.get("objection") or ""
    commodities = row.get("commodities") or ""
    key_quote = row.get("key_quote") or ""

    parts = [f"  - {contact} @ {company_name} [{interest}] called {called_at}"]
    if next_action:
        parts.append(f"    Next: {next_action}")
    if referral:
        role = row.get("referral_role") or ""
        parts.append(f"    Referred to: {referral}" + (f" ({role})" if role else ""))
    if objection:
        parts.append(f"    Objection: {objection}")
    if commodities:
        parts.append(f"    Ships: {commodities}")
    if key_quote:
        parts.append(f"    Quote: \"{key_quote}\"")
    return "\n".join(parts)


def _fmt_referral(row: dict) -> str:
    call = row.get("calls") or {}
    company = row.get("companies") or {}
    company_name = company.get("name") or "Unknown"
    contact = call.get("contact_name") or "Unknown"
    called_at = (call.get("called_at") or "")[:10]
    ref_name = row.get("referral_name") or "?"
    ref_role = row.get("referral_role") or ""
    next_action = row.get("next_action") or ""
    line = f"  - From {contact} @ {company_name} on {called_at} → {ref_name}"
    if ref_role:
        line += f" ({ref_role})"
    if next_action:
        line += f" | Suggested action: {next_action}"
    return line


def _fmt_inmail(row: dict) -> str:
    contact = row.get("contact_name") or "Unknown"
    title = row.get("contact_title") or ""
    company = row.get("company_name") or "Unknown"
    sent_date = row.get("sent_date") or ""
    reply = (row.get("reply_text") or "")[:200]
    line = f"  - {contact}"
    if title:
        line += f" ({title})"
    line += f" @ {company} — sent {sent_date}"
    if reply:
        line += f"\n    Reply: \"{reply}\""
    return line


def build_prompt(ctx: SalesContext) -> str:
    """Build the full Gemini prompt from the SalesContext."""

    # --- Call trend section ---
    call_trend_lines = ["### Call Performance (last 3-4 weeks)"]
    if ctx.call_weeks:
        for w in ctx.call_weeks:
            call_trend_lines.append(_fmt_week(w))
        # Compute week-over-week delta for latest vs previous
        if len(ctx.call_weeks) >= 2:
            curr = ctx.call_weeks[-1]
            prev = ctx.call_weeks[-2]
            dial_delta = curr.dials - prev.dials
            hcr_delta = curr.human_contact_rate - prev.human_contact_rate
            meeting_delta = curr.meetings_booked - prev.meetings_booked
            sign = lambda n: "+" if n >= 0 else ""
            call_trend_lines.append(
                f"  WoW change (Week {prev.week_num} → Week {curr.week_num}): "
                f"dials {sign(dial_delta)}{dial_delta}, "
                f"contact rate {sign(hcr_delta)}{hcr_delta:.1%}, "
                f"meetings {sign(meeting_delta)}{meeting_delta}"
            )
    else:
        call_trend_lines.append("  (no call data available)")

    # --- InMail trend section ---
    inmail_trend_lines = ["### LinkedIn InMail Performance (last 3-4 weeks)"]
    if ctx.inmail_weeks:
        for w in ctx.inmail_weeks:
            inmail_trend_lines.append(_fmt_week(w))
    else:
        inmail_trend_lines.append("  (no InMail data available)")

    # --- Email sequences section ---
    email_lines = ["### Apollo Email Sequences (latest snapshot)"]
    if ctx.email_sequences:
        for seq in ctx.email_sequences[:6]:
            name = seq.get("sequence_name") or "Unnamed"
            sent = seq.get("sent") or 0
            open_rate = seq.get("open_rate") or 0
            reply_rate = seq.get("reply_rate") or 0
            replied = seq.get("replied") or 0
            email_lines.append(
                f"  - \"{name}\": {sent} sent, {open_rate:.0%} open, "
                f"{reply_rate:.0%} reply ({replied} replies)"
            )
    else:
        email_lines.append("  (no email sequence data available)")

    # --- High-interest calls section ---
    interest_lines = ["### High-Interest Calls (last 2 weeks)"]
    if ctx.high_interest_calls:
        for row in ctx.high_interest_calls[:10]:
            interest_lines.append(_fmt_call_intel(row))
    else:
        interest_lines.append("  (none found)")

    # --- Unacted referrals section ---
    referral_lines = ["### Unacted Referrals (last 2 weeks — no follow-up call logged)"]
    if ctx.unacted_referrals:
        for row in ctx.unacted_referrals[:8]:
            referral_lines.append(_fmt_referral(row))
    else:
        referral_lines.append("  (none — all referrals have been followed up)")

    # --- Objections section ---
    objection_lines = ["### Top Objections (last 2 weeks)"]
    if ctx.objections:
        for obj in ctx.objections:
            objection_lines.append(f"  - \"{obj['objection']}\" (x{obj['count']})")
    else:
        objection_lines.append("  (no objection data)")

    # --- Recent meetings section ---
    meeting_lines = ["### Meetings Booked (last 2 weeks)"]
    if ctx.recent_meetings:
        for m in ctx.recent_meetings:
            contact = m.get("contact_name") or "Unknown"
            called_at = (m.get("called_at") or "")[:10]
            company = (m.get("companies") or {}).get("name") or "Unknown"
            meeting_lines.append(f"  - {contact} @ {company} on {called_at}")
    else:
        meeting_lines.append("  (no meetings booked recently)")

    # --- Interested InMails section ---
    inmail_interest_lines = ["### Interested InMail Replies (last 2 weeks)"]
    if ctx.interested_inmails:
        for row in ctx.interested_inmails[:8]:
            inmail_interest_lines.append(_fmt_inmail(row))
    else:
        inmail_interest_lines.append("  (none)")

    # --- Compile company name list for cross-referencing ---
    company_names_sample = sorted(ctx.company_id_map.keys())[:80]
    company_list_str = ", ".join(company_names_sample)
    if len(ctx.company_id_map) > 80:
        company_list_str += f" ... (+{len(ctx.company_id_map) - 80} more)"

    data_block = "\n\n".join([
        "\n".join(call_trend_lines),
        "\n".join(inmail_trend_lines),
        "\n".join(email_lines),
        "\n".join(interest_lines),
        "\n".join(referral_lines),
        "\n".join(objection_lines),
        "\n".join(meeting_lines),
        "\n".join(inmail_interest_lines),
    ])

    prompt = f"""\
You are a senior sales coach and strategist advising a cold outbound sales team \
at Telegraph, a freight railroad brokerage startup. The team runs three outbound \
channels: cold calling (via HubSpot, worked by Adam), Apollo email sequences, and \
LinkedIn InMails. Their goal is to book discovery calls with logistics and shipping \
managers at companies that move freight by rail.

Today is {ctx.today} (Campaign Week {ctx.current_week}).

Key stakeholders:
- Nico (daily user): manages outbound execution, wants tactical guidance
- Shachar (co-founder/growth, weekly): wants to know "is cold outbound working?"
- Harris (CEO, weekly): wants pipeline results and trend direction

Key benchmarks to compare against:
- Cold calling: good contact rate is >12%, great is >18%
- Meeting booking rate (meetings / human contacts): good is >5%, great is >10%
- InMail reply rate: good is >15%, great is >25%
- Email reply rate: good is >3%, great is >6%

---
SALES DATA ({ctx.today}):

{data_block}

---
KNOWN COMPANIES (for related_company_name field — pick exact match from this list):
{company_list_str}

---
INSTRUCTIONS:

Generate between 5 and {MAX_INSIGHTS} insights. Be selective — only surface \
insights that are genuinely actionable or surprising. Do not pad with generic advice.

TONE: Be constructive and matter-of-fact. Avoid alarmist language (no "dangerously", \
"plummeted", "crashed", "critical"). State facts and recommend actions neutrally. \
This dashboard is read by leadership — present data with confidence, not panic.

Each insight must fall into exactly one of these types:
- action_required: something that must happen TODAY or this week (follow-up, outreach)
- alert: a trend or metric worth monitoring
- win: a success to acknowledge and reinforce
- experiment: a specific, concrete test to run (with clear hypothesis)
- coaching: a technique improvement grounded in the call data
- strategic: big-picture observation about channel performance or targeting

Severity rules:
- high: time-sensitive (referral aging past 48h, meeting follow-up needed, notable trend change)
- medium: worth addressing this week
- low: improvement opportunity, nice-to-know

Output ONLY a JSON array. No markdown, no preamble, no commentary outside the JSON.
Each element must match this exact schema:

{{
  "type": "action_required" | "alert" | "win" | "experiment" | "coaching" | "strategic",
  "severity": "high" | "medium" | "low",
  "title": "Short title (max 80 chars)",
  "body": "Detailed explanation (2-5 sentences). Be specific: use names, companies, numbers, dates. Make it self-contained — the reader should know exactly what to do or think.",
  "channel": "calls" | "email" | "linkedin" | "multi" | null,
  "related_company_name": "exact company name from the KNOWN COMPANIES list, or null"
}}

Critical rules:
- Titles must be specific, not generic ("Follow up with Sarah at Acme Corp" not "Follow up on referral")
- Body must cite actual data from the context above (names, numbers, dates)
- Do not invent data not present in the context
- For action_required: specify who should do what, by when
- For experiment: include hypothesis + metric to watch
- For coaching: ground the advice in a specific pattern observed in the data
- Do not generate more than 2 insights of the same type
- Prioritize action_required and alert over other types if the data warrants it
"""
    return prompt


# ---------------------------------------------------------------------------
# Gemini call
# ---------------------------------------------------------------------------

def call_gemini(prompt: str) -> str:
    """Send prompt to Gemini Flash and return raw text response."""
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set in environment or .env")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config={"temperature": 0.3, "max_output_tokens": 3000},
    )
    return response.text


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _strip_code_fence(text: str) -> str:
    """Remove markdown code fences (```json ... ```) from a string."""
    text = text.strip()
    # Remove opening fence with optional language tag
    text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.IGNORECASE)
    # Remove closing fence
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def parse_insights(raw: str) -> list[dict]:
    """
    Parse Gemini's response into a list of insight dicts.
    Handles markdown code fences and single-object responses.
    Validates and normalises each insight.
    """
    cleaned = _strip_code_fence(raw)

    # Try direct parse
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try extracting the first JSON array from the response
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                print(f"WARNING: Could not parse JSON from response:\n{cleaned[:300]}")
                return []
        else:
            print(f"WARNING: No JSON array found in response:\n{cleaned[:300]}")
            return []

    if isinstance(parsed, dict):
        parsed = [parsed]

    if not isinstance(parsed, list):
        print(f"WARNING: Expected list, got {type(parsed)}")
        return []

    valid = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        # Validate required fields
        if not item.get("type") or not item.get("title"):
            continue
        if item["type"] not in INSIGHT_TYPES:
            print(f"  WARNING: Unknown type '{item['type']}', skipping")
            continue
        # Normalise severity
        severity = item.get("severity", "medium")
        if severity not in SEVERITY_VALUES:
            severity = "medium"
        valid.append({
            "type": item["type"],
            "severity": severity,
            "title": str(item.get("title", ""))[:200],
            "body": str(item.get("body", "")),
            "channel": item.get("channel") or None,
            "related_company_name": item.get("related_company_name") or None,
        })

    return valid[:MAX_INSIGHTS]


# ---------------------------------------------------------------------------
# Company / call ID resolution
# ---------------------------------------------------------------------------

def resolve_ids(insights: list[dict], ctx: SalesContext) -> list[dict]:
    """
    Replace related_company_name with related_company_id by looking up
    the company_id_map. Also strips the name key.
    """
    resolved = []
    for ins in insights:
        company_name = ins.pop("related_company_name", None)
        company_id: Optional[int] = None

        if company_name:
            # Exact match first
            company_id = ctx.company_id_map.get(company_name)
            if not company_id:
                # Case-insensitive fallback
                lower_name = company_name.lower()
                for name, cid in ctx.company_id_map.items():
                    if name.lower() == lower_name:
                        company_id = cid
                        break

        ins["related_company_id"] = company_id
        ins["related_call_id"] = None  # not resolved at this level
        resolved.append(ins)
    return resolved


# ---------------------------------------------------------------------------
# Database write
# ---------------------------------------------------------------------------

def write_insights(sb, insights: list[dict], today: date) -> int:
    """Insert insights into the DB. Returns count written."""
    records = []
    for ins in insights:
        records.append({
            "insight_date": today.isoformat(),
            "type": ins["type"],
            "severity": ins["severity"],
            "title": ins["title"],
            "body": ins["body"],
            "channel": ins.get("channel"),
            "related_company_id": ins.get("related_company_id"),
            "related_call_id": ins.get("related_call_id"),
            "acknowledged": False,
        })

    if records:
        sb.table("insights").insert(records).execute()

    return len(records)


def clear_today_insights(sb, today: date) -> int:
    """Delete all insights for today. Returns count deleted."""
    result = (
        sb.table("insights")
        .delete()
        .eq("insight_date", today.isoformat())
        .execute()
    )
    return len(result.data) if result.data else 0


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

TYPE_ICONS = {
    "action_required": "[ACTION]",
    "alert":           "[ALERT] ",
    "win":             "[WIN]   ",
    "experiment":      "[EXPT]  ",
    "coaching":        "[COACH] ",
    "strategic":       "[STRAT] ",
}

SEVERITY_LABELS = {
    "high":   "HIGH  ",
    "medium": "MED   ",
    "low":    "LOW   ",
}


def print_insights(insights: list[dict]) -> None:
    print()
    print("=" * 72)
    print(f"  TELEGRAPH SALES ADVISOR — {len(insights)} insight(s) generated")
    print("=" * 72)

    # Sort: action_required first, then by severity
    severity_order = {"high": 0, "medium": 1, "low": 2}
    type_order = {
        "action_required": 0, "alert": 1, "win": 2,
        "experiment": 3, "coaching": 4, "strategic": 5,
    }
    sorted_insights = sorted(
        insights,
        key=lambda x: (type_order.get(x["type"], 99), severity_order.get(x["severity"], 9)),
    )

    for i, ins in enumerate(sorted_insights, 1):
        icon = TYPE_ICONS.get(ins["type"], "[?]    ")
        sev = SEVERITY_LABELS.get(ins["severity"], "      ")
        channel = ins.get("channel") or ""
        company_id = ins.get("related_company_id")
        meta = []
        if channel:
            meta.append(channel)
        if company_id:
            meta.append(f"company_id={company_id}")
        meta_str = f"  ({', '.join(meta)})" if meta else ""

        print()
        print(f"  {i}. {icon} {sev}  {ins['title']}{meta_str}")
        # Word-wrap body at 68 chars
        body = ins.get("body") or ""
        for line in body.split("\n"):
            # Simple wrap
            words = line.split()
            current = "     "
            for word in words:
                if len(current) + len(word) + 1 > 72:
                    print(current)
                    current = "     " + word
                else:
                    current += (" " if current != "     " else "") + word
            if current.strip():
                print(current)

    print()
    print("=" * 72)


def print_data_summary(ctx: SalesContext) -> None:
    """Print a compact summary of what was pulled from Supabase."""
    print()
    print("--- Data pulled from Supabase ---")
    print(f"  Call weeks loaded:        {len(ctx.call_weeks)}")
    print(f"  InMail weeks loaded:      {len(ctx.inmail_weeks)}")
    print(f"  Email sequences:          {len(ctx.email_sequences)}")
    print(f"  High-interest calls:      {len(ctx.high_interest_calls)}")
    print(f"  Unacted referrals:        {len(ctx.unacted_referrals)}")
    print(f"  Recent objections:        {len(ctx.objections)}")
    print(f"  Recent meetings:          {len(ctx.recent_meetings)}")
    print(f"  Interested InMails:       {len(ctx.interested_inmails)}")
    print(f"  Companies in map:         {len(ctx.company_id_map)}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Telegraph AI Sales Advisor — generates daily insights from Supabase data"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show prompt + insights without writing to DB",
    )
    parser.add_argument(
        "--clear-today",
        action="store_true",
        help="Delete today's existing insights before regenerating",
    )
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="Print the full prompt sent to Gemini (implies --dry-run if used alone)",
    )
    args = parser.parse_args()

    # Validate env
    missing = [k for k in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "GEMINI_API_KEY") if not os.environ.get(k)]
    if missing:
        print(f"ERROR: Missing environment variables: {', '.join(missing)}")
        print("Make sure your .env file is populated or these are exported in your shell.")
        return 1

    sb = _sb()
    today = date.today()

    # Optionally clear today's insights first
    if args.clear_today and not args.dry_run:
        deleted = clear_today_insights(sb, today)
        print(f"Cleared {deleted} existing insights for {today}")

    # Gather data
    print(f"\nGathering sales data from Supabase...")
    ctx = gather_context(sb)
    print_data_summary(ctx)

    # Build prompt
    prompt = build_prompt(ctx)

    if args.show_prompt:
        print("\n--- GEMINI PROMPT ---")
        print(prompt)
        print("--- END PROMPT ---\n")

    # Call Gemini
    print(f"Calling Gemini ({GEMINI_MODEL})...")
    try:
        raw_response = call_gemini(prompt)
    except Exception as e:
        print(f"ERROR calling Gemini: {e}")
        return 1

    # Parse
    insights = parse_insights(raw_response)

    if not insights:
        print("No valid insights parsed from Gemini response.")
        if not args.show_prompt:
            print("Run with --show-prompt to debug the prompt, or check the raw response:")
            print(raw_response[:500])
        return 1

    # Resolve company IDs
    insights = resolve_ids(insights, ctx)

    # Print
    print_insights(insights)

    # Write to DB (unless dry-run)
    if args.dry_run:
        print("(dry-run — not writing to database)")
    else:
        count = write_insights(sb, insights, today)
        print(f"Wrote {count} insights to Supabase insights table for {today}.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
