#!/usr/bin/env python3
"""
dash_data.py — Supabase data fetching layer for the sales dashboard.

Queries all tables and returns a structured dict consumed by the dashboard
generator. No presentation logic here — plain Python dicts and lists only.

Usage:
    from dash_data import fetch_all
    data = fetch_all()

    # Or run directly to inspect output:
    python3 dash_data.py
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Supabase client
# ---------------------------------------------------------------------------

def _get_sb():
    from supabase import create_client
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


# ---------------------------------------------------------------------------
# Pagination helper
# ---------------------------------------------------------------------------

def _fetch_all_rows(sb, table: str, select: str = "*", order_col: str | None = None, desc: bool = True) -> list[dict]:
    """Fetch every row from a table, paginating in 1000-row chunks."""
    all_rows = []
    page_size = 1000
    offset = 0
    while True:
        q = sb.table(table).select(select).range(offset, offset + page_size - 1)
        if order_col:
            q = q.order(order_col, desc=desc)
        result = q.execute()
        all_rows.extend(result.data)
        if len(result.data) < page_size:
            break
        offset += page_size
    return all_rows


def _fetch_all_rows_filtered(
    sb,
    table: str,
    select: str = "*",
    filters: list[tuple] | None = None,
    order_col: str | None = None,
    desc: bool = True,
) -> list[dict]:
    """Fetch rows with optional eq filters, paginating as needed.

    filters: list of (column, value) tuples applied as .eq() calls.
    """
    all_rows = []
    page_size = 1000
    offset = 0
    while True:
        q = sb.table(table).select(select).range(offset, offset + page_size - 1)
        for col, val in (filters or []):
            q = q.eq(col, val)
        if order_col:
            q = q.order(order_col, desc=desc)
        result = q.execute()
        all_rows.extend(result.data)
        if len(result.data) < page_size:
            break
        offset += page_size
    return all_rows


# ---------------------------------------------------------------------------
# Individual section builders
# ---------------------------------------------------------------------------

def _build_overview(
    call_snapshots: list[dict],
    linkedin_snapshots: list[dict],
    total_companies: int,
    total_calls: int,
    total_inmails: int,
) -> dict:
    """Compute top-level KPIs including this-week / last-week / WoW deltas."""
    def _snap_to_row(snap: dict | None) -> dict:
        if not snap:
            return {
                "week_num": None,
                "monday": None,
                "dials": 0,
                "human_contacts": 0,
                "contact_rate": 0.0,
                "meetings_booked": 0,
                "inmails_sent": 0,
                "inmails_replied": 0,
                "inmail_reply_rate": 0.0,
            }
        return {
            "week_num": snap.get("week_num"),
            "monday": snap.get("monday"),
            "dials": snap.get("dials") or 0,
            "human_contacts": snap.get("human_contacts") or 0,
            "contact_rate": snap.get("human_contact_rate") or 0.0,
            "meetings_booked": snap.get("meetings_booked") or 0,
            "inmails_sent": 0,
            "inmails_replied": 0,
            "inmail_reply_rate": 0.0,
        }

    # Index call snapshots by week_num
    call_by_week: dict[int, dict] = {s["week_num"]: s for s in call_snapshots}
    linkedin_by_week: dict[int, dict] = {s["week_num"]: s for s in linkedin_snapshots}

    # Determine current campaign-week by finding the highest week_num present
    all_week_nums = sorted(call_by_week.keys(), reverse=True)
    current_week_num = all_week_nums[0] if all_week_nums else None
    last_week_num = all_week_nums[1] if len(all_week_nums) > 1 else None

    this_week = _snap_to_row(call_by_week.get(current_week_num) if current_week_num else None)
    last_week = _snap_to_row(call_by_week.get(last_week_num) if last_week_num else None)

    # Overlay LinkedIn metrics
    for week_row, wnum in [(this_week, current_week_num), (last_week, last_week_num)]:
        if wnum and wnum in linkedin_by_week:
            li = linkedin_by_week[wnum]
            week_row["inmails_sent"] = li.get("inmails_sent") or 0
            week_row["inmails_replied"] = li.get("inmails_replied") or 0
            week_row["inmail_reply_rate"] = li.get("inmail_reply_rate") or 0.0

    active_channels: list[str] = []
    if total_calls > 0:
        active_channels.append("calls")
    if total_inmails > 0:
        active_channels.append("linkedin")

    wow_deltas = {
        "dials": this_week["dials"] - last_week["dials"],
        "contact_rate": round(this_week["contact_rate"] - last_week["contact_rate"], 4),
        "meetings_booked": this_week["meetings_booked"] - last_week["meetings_booked"],
        "inmail_reply_rate": round(
            this_week["inmail_reply_rate"] - last_week["inmail_reply_rate"], 4
        ),
    }

    return {
        "total_companies": total_companies,
        "total_calls": total_calls,
        "total_inmails": total_inmails,
        "active_channels": active_channels,
        "this_week": this_week,
        "last_week": last_week,
        "wow_deltas": wow_deltas,
    }


def _build_insights(raw_insights: list[dict], company_id_to_name: dict[int, str]) -> list[dict]:
    """Return last-7-days insights ordered by date desc, then severity asc within each date."""
    from itertools import groupby

    cutoff = (date.today() - timedelta(days=7)).isoformat()
    severity_order = {"high": 0, "medium": 1, "low": 2}

    filtered = [i for i in raw_insights if (i.get("insight_date") or "") >= cutoff]

    # Group by date (ascending), sort each day's items by severity, then reverse
    # the day groups so newest date comes first.
    keyed = sorted(filtered, key=lambda i: i.get("insight_date") or "")
    by_date: list[dict] = []
    for _, group in groupby(keyed, key=lambda i: i.get("insight_date") or ""):
        day_items = sorted(group, key=lambda i: severity_order.get(i.get("severity", "medium"), 1))
        by_date = day_items + by_date  # prepend so newest date ends up first

    return [
        {
            "id": row["id"],
            "type": row.get("type", ""),
            "severity": row.get("severity", "medium"),
            "title": row.get("title", ""),
            "body": row.get("body", ""),
            "channel": row.get("channel", ""),
            "company_name": company_id_to_name.get(row.get("related_company_id")) if row.get("related_company_id") else None,
            "acknowledged": row.get("acknowledged", False),
            "insight_date": row.get("insight_date", ""),
        }
        for row in by_date
    ]


def _build_call_trends(call_snapshots: list[dict]) -> list[dict]:
    """Weekly call metrics from weekly_snapshots, ordered by week_num asc."""
    rows = sorted(call_snapshots, key=lambda s: s.get("week_num") or 0)
    result = []
    for snap in rows:
        cats = snap.get("categories") or {}
        if isinstance(cats, str):
            try:
                cats = json.loads(cats)
            except (json.JSONDecodeError, TypeError):
                cats = {}
        result.append({
            "week_num": snap.get("week_num"),
            "monday": snap.get("monday"),
            "dials": snap.get("dials") or 0,
            "human_contacts": snap.get("human_contacts") or 0,
            "contact_rate": snap.get("human_contact_rate") or 0.0,
            "meetings_booked": snap.get("meetings_booked") or 0,
            "categories": cats,
        })
    return result


def _build_call_log(
    calls: list[dict],
    company_id_to_name: dict[int, str],
    intel_by_call_id: dict[int, dict],
) -> list[dict]:
    """Individual call records with company name and intel resolved."""
    result = []
    for call in calls:
        call_id = call["id"]
        intel_row = intel_by_call_id.get(call_id)
        intel = None
        if intel_row:
            intel = {
                "interest_level": intel_row.get("interest_level"),
                "next_action": intel_row.get("next_action"),
                "key_quote": intel_row.get("key_quote"),
                "referral_name": intel_row.get("referral_name"),
                "competitor": intel_row.get("competitor"),
                "commodities": intel_row.get("commodities"),
            }
        result.append({
            "id": call_id,
            "called_at": call.get("called_at"),
            "contact_name": call.get("contact_name"),
            "company_name": company_id_to_name.get(call.get("company_id")),
            "category": call.get("category"),
            "duration_s": call.get("duration_s") or 0,
            "summary": call.get("summary"),
            "notes": call.get("notes"),
            "recording_url": call.get("recording_url"),
            "has_transcript": call.get("has_transcript", False),
            "intel": intel,
        })
    return result


def _build_call_categories(calls: list[dict]) -> dict:
    """Aggregate category counts and derived rates from all calls."""
    # Categories that count as a human contact
    human_contact_cats = {
        "Interested", "Not Interested", "Meeting Booked",
        "Referral Given", "No Rail", "Wrong Person", "Gatekeeper",
        "Call Back", "Pitched",
    }
    meeting_cats = {"Meeting Booked"}

    total = len(calls)
    counts: Counter = Counter(c.get("category") or "Unknown" for c in calls)
    human_contacts = sum(v for k, v in counts.items() if k in human_contact_cats)
    meetings = sum(v for k, v in counts.items() if k in meeting_cats)

    return {
        "total": total,
        "categories": dict(counts.most_common()),
        "human_contact_rate": round(human_contacts / total, 4) if total else 0.0,
        "meeting_rate": round(meetings / total, 4) if total else 0.0,
    }


def _build_inmail_trends(linkedin_snapshots: list[dict]) -> list[dict]:
    """Weekly InMail metrics ordered by week_num asc."""
    rows = sorted(linkedin_snapshots, key=lambda s: s.get("week_num") or 0)
    return [
        {
            "week_num": snap.get("week_num"),
            "monday": snap.get("monday"),
            "sent": snap.get("inmails_sent") or 0,
            "replied": snap.get("inmails_replied") or 0,
            "reply_rate": snap.get("inmail_reply_rate") or 0.0,
            "interested": snap.get("interested_count") or 0,
        }
        for snap in rows
    ]


def _build_inmails(raw_inmails: list[dict]) -> list[dict]:
    """Individual InMail records ordered by sent_date DESC."""
    sorted_rows = sorted(
        raw_inmails,
        key=lambda r: r.get("sent_date") or "",
        reverse=True,
    )
    return [
        {
            "id": row["id"],
            "contact_name": row.get("contact_name"),
            "contact_title": row.get("contact_title"),
            "company_name": row.get("company_name"),
            "sent_date": row.get("sent_date"),
            "replied": row.get("replied", False),
            "reply_sentiment": row.get("reply_sentiment"),
            "reply_text": row.get("reply_text"),
            "week_num": row.get("week_num"),
        }
        for row in sorted_rows
    ]


def _build_inmail_stats(raw_inmails: list[dict]) -> dict:
    """Aggregate InMail stats and sentiment breakdown."""
    total_sent = len(raw_inmails)
    total_replied = sum(1 for r in raw_inmails if r.get("replied"))
    sentiment_counts: Counter = Counter(
        r.get("reply_sentiment") for r in raw_inmails if r.get("reply_sentiment")
    )
    return {
        "total_sent": total_sent,
        "total_replied": total_replied,
        "reply_rate": round(total_replied / total_sent, 4) if total_sent else 0.0,
        "sentiment_breakdown": dict(sentiment_counts),
    }


def _build_email_sequences(raw_sequences: list[dict]) -> list[dict]:
    return [
        {
            "sequence_name": row.get("sequence_name"),
            "sent": row.get("sent") or 0,
            "opened": row.get("opened") or 0,
            "open_rate": row.get("open_rate") or 0.0,
            "replied": row.get("replied") or 0,
            "reply_rate": row.get("reply_rate") or 0.0,
            "clicked": row.get("clicked") or 0,
            "click_rate": row.get("click_rate") or 0.0,
            "snapshot_date": row.get("snapshot_date"),
        }
        for row in raw_sequences
    ]


def _build_companies(
    raw_companies: list[dict],
    calls: list[dict],
    raw_inmails: list[dict],
    intel_by_call_id: dict[int, dict],
) -> list[dict]:
    """Company records with per-company call/inmail counts, latest intel, and recent activity."""
    # Index calls and inmails by company_id
    calls_by_company: defaultdict[int, list[dict]] = defaultdict(list)
    for c in calls:
        cid = c.get("company_id")
        if cid:
            calls_by_company[cid].append(c)

    inmails_by_company: defaultdict[int, list[dict]] = defaultdict(list)
    for im in raw_inmails:
        cid = im.get("company_id")
        if cid:
            inmails_by_company[cid].append(im)

    # Sort companies by last_touch_at desc (nulls last)
    sorted_companies = sorted(
        raw_companies,
        key=lambda c: c.get("last_touch_at") or "",
        reverse=True,
    )

    result = []
    for company in sorted_companies:
        cid = company["id"]
        company_calls = sorted(
            calls_by_company.get(cid, []),
            key=lambda c: c.get("called_at") or "",
            reverse=True,
        )
        company_inmails = sorted(
            inmails_by_company.get(cid, []),
            key=lambda im: im.get("sent_date") or "",
            reverse=True,
        )

        # Latest intel: most recent call with intel, by called_at desc
        latest_intel = None
        for call in company_calls:
            intel_row = intel_by_call_id.get(call["id"])
            if intel_row:
                latest_intel = {
                    "interest_level": intel_row.get("interest_level"),
                    "next_action": intel_row.get("next_action"),
                    "key_quote": intel_row.get("key_quote"),
                }
                break

        channels = company.get("channels_touched") or []
        if isinstance(channels, str):
            # Postgres arrays come back as Python lists via the client, but guard anyway
            try:
                channels = json.loads(channels)
            except (json.JSONDecodeError, TypeError):
                channels = [channels] if channels else []

        result.append({
            "id": cid,
            "name": company.get("name"),
            "status": company.get("status"),
            "channels_touched": channels,
            "total_touches": company.get("total_touches") or 0,
            "last_touch_at": company.get("last_touch_at"),
            "first_touch_at": company.get("first_touch_at"),
            "call_count": len(company_calls),
            "inmail_count": len(company_inmails),
            "latest_intel": latest_intel,
            "calls": [
                {
                    "called_at": c.get("called_at"),
                    "category": c.get("category"),
                    "summary": c.get("summary"),
                }
                for c in company_calls[:5]
            ],
            "inmails": [
                {
                    "sent_date": im.get("sent_date"),
                    "replied": im.get("replied", False),
                    "reply_sentiment": im.get("reply_sentiment"),
                }
                for im in company_inmails
            ],
        })
    return result


def _build_experiments(raw_experiments: list[dict]) -> list[dict]:
    return [
        {
            "id": row["id"],
            "name": row.get("name"),
            "hypothesis": row.get("hypothesis"),
            "channel": row.get("channel"),
            "start_date": row.get("start_date"),
            "status": row.get("status"),
            "metric": row.get("metric"),
            "result_summary": row.get("result_summary"),
        }
        for row in raw_experiments
    ]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def fetch_all() -> dict:
    """Fetch all data needed for dashboard. Returns structured dict.

    Prints progress to stderr to keep stdout clean for piping.
    """
    sb = _get_sb()

    def _log(msg: str) -> None:
        print(f"[dash_data] {msg}", file=sys.stderr)

    # ------------------------------------------------------------------
    # 1. Fetch raw rows from all tables
    # ------------------------------------------------------------------
    _log("Fetching companies...")
    raw_companies = _fetch_all_rows(sb, "companies", order_col="last_touch_at", desc=True)
    _log(f"  {len(raw_companies)} companies")

    _log("Fetching calls...")
    calls = _fetch_all_rows(sb, "calls", order_col="called_at", desc=True)
    _log(f"  {len(calls)} calls")

    _log("Fetching call_intel...")
    raw_intel = _fetch_all_rows(sb, "call_intel")
    _log(f"  {len(raw_intel)} intel records")

    _log("Fetching inmails...")
    raw_inmails = _fetch_all_rows(sb, "inmails", order_col="sent_date", desc=True)
    _log(f"  {len(raw_inmails)} inmails")

    _log("Fetching email_sequences...")
    raw_sequences = _fetch_all_rows(sb, "email_sequences", order_col="snapshot_date", desc=True)
    _log(f"  {len(raw_sequences)} email sequences")

    _log("Fetching weekly_snapshots (calls)...")
    call_snapshots = _fetch_all_rows_filtered(
        sb, "weekly_snapshots", filters=[("channel", "calls")], order_col="week_num", desc=False
    )
    _log(f"  {len(call_snapshots)} call weekly snapshots")

    _log("Fetching weekly_snapshots (linkedin)...")
    linkedin_snapshots = _fetch_all_rows_filtered(
        sb, "weekly_snapshots", filters=[("channel", "linkedin")], order_col="week_num", desc=False
    )
    _log(f"  {len(linkedin_snapshots)} linkedin weekly snapshots")

    _log("Fetching insights...")
    raw_insights = _fetch_all_rows(sb, "insights", order_col="insight_date", desc=True)
    _log(f"  {len(raw_insights)} insights")

    _log("Fetching experiments...")
    raw_experiments = _fetch_all_rows(sb, "experiments", order_col="start_date", desc=True)
    _log(f"  {len(raw_experiments)} experiments")

    # ------------------------------------------------------------------
    # 2. Build lookup indexes (do joins in Python)
    # ------------------------------------------------------------------
    company_id_to_name: dict[int, str] = {c["id"]: c["name"] for c in raw_companies}

    # One intel record per call (use the most recent extraction if there are duplicates)
    intel_by_call_id: dict[int, dict] = {}
    for intel_row in raw_intel:
        cid = intel_row.get("call_id")
        if cid is None:
            continue
        existing = intel_by_call_id.get(cid)
        if existing is None or (intel_row.get("extracted_at") or "") > (existing.get("extracted_at") or ""):
            intel_by_call_id[cid] = intel_row

    # ------------------------------------------------------------------
    # 3. Build each dashboard section
    # ------------------------------------------------------------------
    _log("Building dashboard sections...")

    overview = _build_overview(
        call_snapshots=call_snapshots,
        linkedin_snapshots=linkedin_snapshots,
        total_companies=len(raw_companies),
        total_calls=len(calls),
        total_inmails=len(raw_inmails),
    )

    insights = _build_insights(raw_insights, company_id_to_name)
    call_trends = _build_call_trends(call_snapshots)
    call_log = _build_call_log(calls, company_id_to_name, intel_by_call_id)
    call_categories = _build_call_categories(calls)
    inmail_trends = _build_inmail_trends(linkedin_snapshots)
    inmails = _build_inmails(raw_inmails)
    inmail_stats = _build_inmail_stats(raw_inmails)
    email_sequences = _build_email_sequences(raw_sequences)
    companies = _build_companies(raw_companies, calls, raw_inmails, intel_by_call_id)
    experiments = _build_experiments(raw_experiments)

    _log("Done.")

    return {
        "overview": overview,
        "insights": insights,
        "call_trends": call_trends,
        "call_log": call_log,
        "call_categories": call_categories,
        "inmail_trends": inmail_trends,
        "inmails": inmails,
        "inmail_stats": inmail_stats,
        "email_sequences": email_sequences,
        "companies": companies,
        "experiments": experiments,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# CLI: print a summary when run directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json as _json

    data = fetch_all()

    ov = data["overview"]
    print(f"\n=== Dashboard Data Summary ===")
    print(f"  Companies       : {ov['total_companies']}")
    print(f"  Calls           : {ov['total_calls']}")
    print(f"  InMails         : {ov['total_inmails']}")
    print(f"  Active channels : {', '.join(ov['active_channels']) or 'none'}")

    tw = ov["this_week"]
    print(f"\n  This week (#{tw['week_num']}, {tw['monday']}):")
    print(f"    Dials          : {tw['dials']}")
    print(f"    Human contacts : {tw['human_contacts']} ({tw['contact_rate']:.1%})")
    print(f"    Meetings       : {tw['meetings_booked']}")
    print(f"    InMails sent   : {tw['inmails_sent']} / replied: {tw['inmails_replied']}")

    d = ov["wow_deltas"]
    print(f"\n  WoW deltas:")
    print(f"    Dials          : {d['dials']:+d}")
    print(f"    Contact rate   : {d['contact_rate']:+.1%}")
    print(f"    Meetings       : {d['meetings_booked']:+d}")
    print(f"    InMail reply % : {d['inmail_reply_rate']:+.1%}")

    print(f"\n  Call categories : {data['call_categories']['total']} total")
    for cat, cnt in list(data["call_categories"]["categories"].items())[:5]:
        print(f"    {cat:<30} {cnt}")

    print(f"\n  Insights (last 7 days) : {len(data['insights'])}")
    print(f"  Experiments            : {len(data['experiments'])}")
    print(f"  Email sequences        : {len(data['email_sequences'])}")
    print(f"\n  Generated at: {data['generated_at']}")
