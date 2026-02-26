#!/usr/bin/env python3
"""Daily call sheet generator.

Reads call history from Supabase, applies cadence rules, and outputs
a prioritized list of contacts Adam can call today.

Usage:
    python3 call_sheet.py              # print today's call sheet
    python3 call_sheet.py --sync       # sync call history → contacts table first
    python3 call_sheet.py --stats      # show roster stats only

Rules:
    - Max 4 call attempts per contact, spaced 3+ business days apart
    - Max 5 contacts worked per company
    - Terminal outcomes retire a contact permanently
    - Blocked companies (do_not_contact / not_interested / exhausted) are excluded
    - No voicemails, no emails — calls only
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, date
from pathlib import Path

import psycopg2
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env.telegraph", override=True)
load_dotenv(ROOT / ".env", override=True)

# ── Config ──────────────────────────────────────────────────────────
MAX_ATTEMPTS = 4
COOLDOWN_DAYS = 3            # business days between calls to same contact
MAX_CONTACTS_PER_COMPANY = 5
DAILY_TARGET = 50            # contacts per day
BLOCKED_COMPANY_STATUSES = {"do_not_contact", "not_interested", "exhausted"}
TERMINAL_CATEGORIES = {"Not Interested", "No Rail", "Wrong Person", "Wrong Number"}
POSITIVE_CATEGORIES = {"Interested", "Meeting Booked", "Referral Given"}

DB_PARAMS = dict(
    host="db.giptkpwwhwhtrrrmdfqt.supabase.co",
    port=5432,
    user="postgres",
    password="NINTOEMF2w2Uwxbn",
    dbname="postgres",
    sslmode="require",
)


def get_conn():
    return psycopg2.connect(**DB_PARAMS)


def get_supabase_headers():
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_ANON_KEY", "") or os.environ.get("SUPABASE_KEY", "")
    return url, {"apikey": key, "Authorization": f"Bearer {key}"}


def add_business_days(start: date, days: int) -> date:
    """Add N business days (Mon-Fri) to a date."""
    current = start
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Mon=0 .. Fri=4
            added += 1
    return current


# ── Sync: call history → contacts table ─────────────────────────────

def sync_contacts():
    """Backfill/update the contacts table from call history in Supabase."""
    conn = get_conn()
    cur = conn.cursor()

    # Fetch all calls via direct Postgres (much faster than REST pagination)
    cur.execute("""
        SELECT c.contact_name, co.name, c.category, c.called_at
        FROM calls c
        LEFT JOIN companies co ON c.company_id = co.id
        ORDER BY c.called_at ASC;
    """)
    all_calls = [
        {"contact_name": r[0], "company_name": r[1], "category": r[2], "called_at": str(r[3]) if r[3] else ""}
        for r in cur.fetchall()
    ]
    print(f"  Fetched {len(all_calls)} calls from Supabase")

    # Fetch blocked companies
    cur.execute("SELECT name FROM companies WHERE status IN %s;", (tuple(BLOCKED_COMPANY_STATUSES),))
    blocked_cos = {r[0] for r in cur.fetchall()}
    print(f"  {len(blocked_cos)} blocked companies")
    cur.close()
    conn.close()

    # Build contact profiles from call history
    contacts = {}  # key: "name|||company" → profile
    for c in all_calls:
        name = (c.get("contact_name") or "").strip()
        company = (c.get("company_name") or "").strip()
        if not name or not company:
            continue

        key = f"{name}|||{company}"
        if key not in contacts:
            contacts[key] = {
                "name": name,
                "company_name": company,
                "attempt_count": 0,
                "last_called_at": None,
                "best_outcome": None,
                "categories": [],
            }

        p = contacts[key]
        cat = c.get("category", "")
        called_at = (c.get("called_at") or "")[:10]

        p["attempt_count"] += 1
        p["categories"].append(cat)
        if called_at:
            p["last_called_at"] = called_at

        # Track best outcome
        if cat in POSITIVE_CATEGORIES:
            p["best_outcome"] = cat
        elif cat in TERMINAL_CATEGORIES and not p["best_outcome"]:
            p["best_outcome"] = cat

    print(f"  {len(contacts)} unique contacts identified")

    # Determine status and next_callable for each contact
    today = date.today()
    conn = get_conn()
    cur = conn.cursor()

    # Clear and rebuild
    cur.execute("DELETE FROM contacts;")

    inserted = 0
    for key, p in contacts.items():
        cats = p["categories"]
        last_called = p["last_called_at"]

        # Determine status
        status = "active"
        retired_reason = None

        # Check if company is blocked
        if p["company_name"] in blocked_cos:
            status = "blocked"
            retired_reason = "Company blocked"

        # Check terminal outcomes
        elif any(c in TERMINAL_CATEGORIES for c in cats):
            terminal = [c for c in cats if c in TERMINAL_CATEGORIES][-1]
            status = "retired"
            retired_reason = f"Outcome: {terminal}"

        # Check if meeting booked (done — in pipeline)
        elif "Meeting Booked" in cats:
            status = "retired"
            retired_reason = "Meeting booked — in pipeline"

        # Check max attempts
        elif p["attempt_count"] >= MAX_ATTEMPTS:
            status = "retired"
            retired_reason = f"Max attempts reached ({p['attempt_count']})"

        # Check cooldown
        elif last_called:
            next_callable = add_business_days(
                datetime.strptime(last_called, "%Y-%m-%d").date(),
                COOLDOWN_DAYS,
            )
            if next_callable > today:
                status = "cooling"

        # Calculate next_callable_at
        next_callable_at = None
        if status == "active" and last_called:
            next_callable_at = add_business_days(
                datetime.strptime(last_called, "%Y-%m-%d").date(),
                COOLDOWN_DAYS,
            )
        elif status == "cooling" and last_called:
            next_callable_at = add_business_days(
                datetime.strptime(last_called, "%Y-%m-%d").date(),
                COOLDOWN_DAYS,
            )

        cur.execute(
            """INSERT INTO contacts
               (name, company_name, attempt_count, last_called_at, next_callable_at,
                best_outcome, status, retired_reason)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                p["name"],
                p["company_name"],
                p["attempt_count"],
                last_called,
                next_callable_at,
                p["best_outcome"],
                status,
                retired_reason,
            ),
        )
        inserted += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f"  Synced {inserted} contacts to Supabase")


# ── Stats ────────────────────────────────────────────────────────────

def show_stats():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT status, count(*) FROM contacts GROUP BY status ORDER BY count DESC;")
    rows = cur.fetchall()
    total = sum(r[1] for r in rows)

    print(f"\n{'=' * 55}")
    print(f"  CONTACT ROSTER — {date.today()}")
    print(f"{'=' * 55}")
    print(f"  Total contacts: {total}")
    print()
    for status, count in rows:
        pct = count / total * 100 if total else 0
        bar = "#" * int(pct / 2)
        print(f"  {status:12s}  {count:4d}  ({pct:4.1f}%)  {bar}")

    # Retired breakdown
    cur.execute("""SELECT retired_reason, count(*) FROM contacts
                   WHERE status = 'retired' GROUP BY retired_reason ORDER BY count DESC;""")
    print(f"\n  Retired breakdown:")
    for reason, count in cur.fetchall():
        print(f"    {count:3d}  {reason}")

    # Company saturation
    cur.execute("""SELECT company_name,
                   count(*) FILTER (WHERE status = 'active') as active,
                   count(*) FILTER (WHERE status = 'retired') as retired,
                   count(*) as total
                   FROM contacts GROUP BY company_name
                   HAVING count(*) >= 5 ORDER BY count(*) DESC LIMIT 15;""")
    print(f"\n  Most-worked companies (5+ contacts):")
    print(f"  {'Company':35s}  Active  Retired  Total")
    for co, active, retired, total in cur.fetchall():
        flag = " ← saturated" if active == 0 else ""
        print(f"  {co:35s}  {active:5d}  {retired:6d}  {total:5d}{flag}")

    cur.close()
    conn.close()


# ── Generate daily call sheet ────────────────────────────────────────

def generate_call_sheet():
    today = date.today()
    conn = get_conn()
    cur = conn.cursor()

    # Get callable contacts: active + next_callable_at <= today (or NULL)
    # Priority order: prior positive signal first, then fewest attempts, then oldest
    cur.execute("""
        SELECT name, company_name, attempt_count, last_called_at, best_outcome
        FROM contacts
        WHERE status = 'active'
          AND (next_callable_at IS NULL OR next_callable_at <= %s)
        ORDER BY
          CASE WHEN best_outcome IN ('Interested', 'Referral Given') THEN 0 ELSE 1 END,
          attempt_count ASC,
          last_called_at ASC NULLS FIRST;
    """, (today,))
    candidates = cur.fetchall()

    # Also get cooling contacts coming off cooldown today
    cur.execute("""
        SELECT name, company_name, attempt_count, last_called_at, best_outcome
        FROM contacts
        WHERE status = 'cooling'
          AND next_callable_at <= %s
        ORDER BY
          CASE WHEN best_outcome IN ('Interested', 'Referral Given') THEN 0 ELSE 1 END,
          attempt_count ASC;
    """, (today,))
    candidates.extend(cur.fetchall())

    # Enforce company-level limits: max 5 contacts per company in today's sheet
    # Also check how many contacts are already worked (active+cooling) per company
    cur.execute("""
        SELECT company_name, count(*)
        FROM contacts
        WHERE status IN ('active', 'cooling')
        GROUP BY company_name;
    """)
    company_active = dict(cur.fetchall())

    # Build the call sheet
    company_slots_today = defaultdict(int)
    call_sheet = []

    for name, company, attempts, last_called, best in candidates:
        # Skip if company already has too many active contacts
        active_at_co = company_active.get(company, 0)
        if active_at_co > MAX_CONTACTS_PER_COMPANY:
            continue

        # Limit contacts per company in today's sheet (max 3 per day)
        if company_slots_today[company] >= 3:
            continue

        company_slots_today[company] += 1
        call_sheet.append({
            "name": name,
            "company": company,
            "attempt": attempts + 1,
            "last_called": str(last_called or "—"),
            "prior_best": best or "—",
        })

        if len(call_sheet) >= DAILY_TARGET:
            break

    cur.close()
    conn.close()

    # Print the call sheet
    print(f"\n{'=' * 80}")
    print(f"  DAILY CALL SHEET — {today.strftime('%A %b %d, %Y')}")
    print(f"  {len(call_sheet)} contacts to call (target: {DAILY_TARGET})")
    print(f"{'=' * 80}")

    if not call_sheet:
        print("\n  No contacts available. Run --sync to refresh, or add new prospects.")
        return

    # Group by priority
    fresh = [c for c in call_sheet if c["attempt"] == 1]
    retry = [c for c in call_sheet if c["attempt"] > 1]

    if fresh:
        print(f"\n  FRESH CONTACTS — first call ({len(fresh)})")
        print(f"  {'#':>3s}  {'Contact':30s}  {'Company':35s}")
        print(f"  {'─' * 3}  {'─' * 30}  {'─' * 35}")
        for i, c in enumerate(fresh, 1):
            print(f"  {i:3d}  {c['name']:30s}  {c['company']:35s}")

    if retry:
        print(f"\n  RETRY CONTACTS — follow-up calls ({len(retry)})")
        print(f"  {'#':>3s}  {'Contact':30s}  {'Company':35s}  {'Att':>3s}  {'Last Called':12s}  Prior Best")
        print(f"  {'─' * 3}  {'─' * 30}  {'─' * 35}  {'─' * 3}  {'─' * 12}  {'─' * 15}")
        for i, c in enumerate(retry, len(fresh) + 1):
            print(f"  {i:3d}  {c['name']:30s}  {c['company']:35s}  {c['attempt']:3d}  {c['last_called']:12s}  {c['prior_best']}")

    # Company distribution
    cos = defaultdict(int)
    for c in call_sheet:
        cos[c["company"]] += 1
    print(f"\n  Across {len(cos)} companies", end="")
    multi = {k: v for k, v in cos.items() if v > 1}
    if multi:
        print(f" ({len(multi)} with 2+ contacts):")
        for co, cnt in sorted(multi.items(), key=lambda x: -x[1])[:10]:
            print(f"    {co}: {cnt}")
    else:
        print()


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Daily call sheet generator")
    parser.add_argument("--sync", action="store_true", help="Sync call history → contacts table")
    parser.add_argument("--stats", action="store_true", help="Show roster stats")
    args = parser.parse_args()

    if args.sync:
        print("Syncing contacts from call history...")
        sync_contacts()
        print()

    if args.stats:
        show_stats()
        return

    # Default: generate call sheet (auto-sync if contacts table is empty)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM contacts;")
    count = cur.fetchone()[0]
    cur.close()
    conn.close()

    if count == 0:
        print("Contacts table empty — syncing from call history first...")
        sync_contacts()
        print()

    generate_call_sheet()


if __name__ == "__main__":
    main()
