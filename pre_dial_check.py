#!/usr/bin/env python3
"""Pre-dial check: generates a DO NOT CALL list for the day.

Run before each calling session:
    python3 pre_dial_check.py

Reads call_data.json + Supabase companies table and prints:
  1. Blocked companies (DNC / not_interested / exhausted)
  2. Blocked contacts (said no, wrong person, 3+ VMs with no reply, 5+ no-answers)
  3. Cooling-off contacts (called in the last 5 business days)
"""

import json, os, sys
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env.telegraph", override=True)
load_dotenv(ROOT / ".env", override=True)


# ── Config ──────────────────────────────────────────────────────────
COOLDOWN_DAYS = 7          # Don't call same contact within N calendar days
MAX_VM_NO_REPLY = 3        # After N voicemails with no pickup → stop
MAX_NO_ANSWER = 5          # After N no-answers → stop
BLOCKED_STATUSES = {"do_not_contact", "not_interested", "exhausted"}
TERMINAL_CATEGORIES = {"Not Interested", "No Rail", "Wrong Person", "Wrong Number", "Meeting Booked"}


def load_calls():
    with open(ROOT / "call_data.json") as f:
        return json.load(f)["calls"]


def load_blocked_companies():
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_ANON_KEY", "") or os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        print("⚠  Supabase creds not found, skipping company-level blocks")
        return {}
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    r = requests.get(
        f"{url}/rest/v1/companies?select=name,status,status_reason"
        f"&status=in.({','.join(BLOCKED_STATUSES)})",
        headers=headers,
    )
    if not r.ok:
        print(f"⚠  Supabase error {r.status_code}")
        return {}
    return {c["name"]: (c["status"], c.get("status_reason", "")) for c in r.json()}


def analyze(calls, blocked_companies):
    today = datetime.now()
    cooldown_cutoff = (today - timedelta(days=COOLDOWN_DAYS)).strftime("%Y-%m-%d")

    # ── Contact-level analysis ──
    contact_history = defaultdict(lambda: {"cats": [], "dates": [], "company": ""})
    for c in calls:
        name = (c.get("contact_name") or "").strip()
        company = (c.get("company_name") or "").strip()
        if not name:
            continue
        key = f"{name}|||{company}"
        contact_history[key]["cats"].append(c.get("category", ""))
        contact_history[key]["dates"].append(c.get("timestamp", "")[:10])
        contact_history[key]["company"] = company

    blocked_contacts = []  # (name, company, reason)
    cooling_contacts = []  # (name, company, last_call, days_ago)

    for key, hist in contact_history.items():
        name, company = key.split("|||")
        cats = hist["cats"]
        dates = sorted(hist["dates"])

        # Rule 1: terminal outcome → permanently blocked
        for cat in TERMINAL_CATEGORIES:
            if cat in cats:
                blocked_contacts.append((name, company, f"Outcome: {cat}"))
                break
        else:
            # Rule 2: too many voicemails with no pickup
            vm_count = cats.count("Left Voicemail")
            ever_answered = any(c not in ("Left Voicemail", "No Answer") for c in cats)
            if vm_count >= MAX_VM_NO_REPLY and not ever_answered:
                blocked_contacts.append((name, company, f"{vm_count} voicemails, never answered"))
            # Rule 3: too many no-answers
            elif cats.count("No Answer") >= MAX_NO_ANSWER:
                blocked_contacts.append((name, company, f"{cats.count('No Answer')} no-answers"))
            # Rule 4: cooldown period
            elif dates and dates[-1] >= cooldown_cutoff:
                days_ago = (today - datetime.strptime(dates[-1], "%Y-%m-%d")).days
                cooling_contacts.append((name, company, dates[-1], days_ago))

    return blocked_contacts, cooling_contacts


def main():
    calls = load_calls()
    blocked_companies = load_blocked_companies()

    blocked_contacts, cooling_contacts = analyze(calls, blocked_companies)

    # ── Print report ──
    print("=" * 70)
    print(f"  PRE-DIAL CHECK — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)

    # 1. Blocked companies
    print(f"\n{'─' * 70}")
    print(f"  BLOCKED COMPANIES ({len(blocked_companies)})")
    print(f"{'─' * 70}")
    if blocked_companies:
        for name, (status, reason) in sorted(blocked_companies.items()):
            print(f"  ✗ {name:35s}  [{status}]  {reason[:60]}")
    else:
        print("  None")

    # 2. Blocked contacts
    print(f"\n{'─' * 70}")
    print(f"  BLOCKED CONTACTS ({len(blocked_contacts)}) — do not call")
    print(f"{'─' * 70}")
    # Group by reason type
    by_reason = defaultdict(list)
    for name, company, reason in blocked_contacts:
        by_reason[reason.split(":")[0] if ":" in reason else reason].append((name, company, reason))

    for reason_key in ["Outcome: Not Interested", "Outcome: No Rail", "Outcome: Wrong Person",
                        "Outcome: Wrong Number", "Outcome: Meeting Booked"]:
        items = by_reason.get(reason_key, [])
        if items:
            print(f"\n  {reason_key} ({len(items)}):")
            for name, company, _ in sorted(items, key=lambda x: x[1]):
                print(f"    • {name:30s}  @ {company}")

    # VM/no-answer exhausted
    other_blocked = [(n, c, r) for n, c, r in blocked_contacts
                     if not any(r.startswith(f"Outcome: {t}") for t in TERMINAL_CATEGORIES)]
    if other_blocked:
        print(f"\n  Exhausted contacts ({len(other_blocked)}):")
        for name, company, reason in sorted(other_blocked, key=lambda x: x[1]):
            print(f"    • {name:30s}  @ {company:30s}  ({reason})")

    # 3. Cooling off
    print(f"\n{'─' * 70}")
    print(f"  COOLING OFF ({len(cooling_contacts)}) — called in last {COOLDOWN_DAYS} days")
    print(f"{'─' * 70}")
    for name, company, last_call, days_ago in sorted(cooling_contacts, key=lambda x: x[3]):
        print(f"  ⏸ {name:30s}  @ {company:30s}  last call: {last_call} ({days_ago}d ago)")

    # Summary
    blocked_co_names = set(blocked_companies.keys())
    blocked_contact_set = set((n, c) for n, c, _ in blocked_contacts)
    cooling_set = set((n, c) for n, c, _, _ in cooling_contacts)

    print(f"\n{'=' * 70}")
    print(f"  SUMMARY")
    print(f"{'=' * 70}")
    print(f"  Companies blocked     : {len(blocked_companies)}")
    print(f"  Contacts blocked      : {len(blocked_contacts)}")
    print(f"  Contacts cooling off  : {len(cooling_contacts)}")
    total_excluded = len(blocked_contacts) + len(cooling_contacts)
    print(f"  Total exclusions      : {total_excluded} contacts")
    print()


if __name__ == "__main__":
    main()
