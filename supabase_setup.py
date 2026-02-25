#!/usr/bin/env python3
"""
Supabase schema setup + data migration for Sales Outbound system.

Creates all tables and migrates existing JSON data into Supabase.

Usage:
    python3 supabase_setup.py              # Create schema + migrate data
    python3 supabase_setup.py --schema     # Schema only (no data)
    python3 supabase_setup.py --migrate    # Data migration only
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

# SQL for creating all tables
SCHEMA_SQL = """
-- ============================================
-- SALES OUTBOUND SYSTEM — SUPABASE SCHEMA
-- ============================================

-- Companies: central entity linking all channels
CREATE TABLE IF NOT EXISTS companies (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    hubspot_id TEXT UNIQUE,
    industry TEXT,
    status TEXT DEFAULT 'prospect'
        CHECK (status IN ('prospect', 'contacted', 'interested', 'meeting_booked', 'opportunity', 'closed', 'disqualified')),
    channels_touched TEXT[] DEFAULT '{}',
    total_touches INT DEFAULT 0,
    last_touch_at TIMESTAMPTZ,
    first_touch_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_companies_name ON companies(name);
CREATE INDEX IF NOT EXISTS idx_companies_status ON companies(status);
CREATE INDEX IF NOT EXISTS idx_companies_hubspot_id ON companies(hubspot_id);

-- Contacts: people at companies
CREATE TABLE IF NOT EXISTS contacts (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    company_id BIGINT REFERENCES companies(id),
    hubspot_id TEXT,
    title TEXT,
    email TEXT,
    phone TEXT,
    linkedin_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_contacts_company ON contacts(company_id);

-- Calls: from HubSpot
CREATE TABLE IF NOT EXISTS calls (
    id BIGSERIAL PRIMARY KEY,
    hubspot_call_id TEXT UNIQUE,
    company_id BIGINT REFERENCES companies(id),
    contact_name TEXT,
    category TEXT,
    duration_s INT DEFAULT 0,
    notes TEXT,
    summary TEXT,
    recording_url TEXT,
    has_transcript BOOLEAN DEFAULT FALSE,
    called_at TIMESTAMPTZ,
    week_num INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_calls_company ON calls(company_id);
CREATE INDEX IF NOT EXISTS idx_calls_category ON calls(category);
CREATE INDEX IF NOT EXISTS idx_calls_called_at ON calls(called_at);
CREATE INDEX IF NOT EXISTS idx_calls_week_num ON calls(week_num);

-- Call intelligence: AI-extracted from call summaries
CREATE TABLE IF NOT EXISTS call_intel (
    id BIGSERIAL PRIMARY KEY,
    call_id BIGINT REFERENCES calls(id),
    company_id BIGINT REFERENCES companies(id),
    interest_level TEXT CHECK (interest_level IN ('high', 'medium', 'low', 'none')),
    qualified BOOLEAN,
    next_action TEXT,
    objection TEXT,
    competitor TEXT,
    commodities TEXT,
    referral_name TEXT,
    referral_role TEXT,
    key_quote TEXT,
    extracted_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_call_intel_company ON call_intel(company_id);
CREATE INDEX IF NOT EXISTS idx_call_intel_interest ON call_intel(interest_level);

-- Email sequences: from Apollo
CREATE TABLE IF NOT EXISTS email_sequences (
    id BIGSERIAL PRIMARY KEY,
    sequence_name TEXT NOT NULL,
    apollo_id TEXT,
    status TEXT DEFAULT 'active',
    sent INT DEFAULT 0,
    delivered INT DEFAULT 0,
    opened INT DEFAULT 0,
    replied INT DEFAULT 0,
    clicked INT DEFAULT 0,
    open_rate REAL DEFAULT 0,
    reply_rate REAL DEFAULT 0,
    click_rate REAL DEFAULT 0,
    snapshot_date DATE DEFAULT CURRENT_DATE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- InMails: from Google Sheets
CREATE TABLE IF NOT EXISTS inmails (
    id BIGSERIAL PRIMARY KEY,
    company_id BIGINT REFERENCES companies(id),
    contact_name TEXT,
    contact_title TEXT,
    company_name TEXT,
    sent_date DATE,
    replied BOOLEAN DEFAULT FALSE,
    reply_sentiment TEXT CHECK (reply_sentiment IN ('interested', 'not_interested', 'neutral', 'ooo', NULL)),
    reply_text TEXT,
    week_num INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_inmails_company ON inmails(company_id);
CREATE INDEX IF NOT EXISTS idx_inmails_sentiment ON inmails(reply_sentiment);

-- Weekly snapshots: aggregated metrics per channel per week
CREATE TABLE IF NOT EXISTS weekly_snapshots (
    id BIGSERIAL PRIMARY KEY,
    week_num INT NOT NULL,
    monday DATE NOT NULL,
    channel TEXT NOT NULL CHECK (channel IN ('calls', 'email', 'linkedin')),
    -- Call metrics
    dials INT,
    human_contacts INT,
    human_contact_rate REAL,
    meetings_booked INT,
    categories JSONB,
    -- Email metrics
    emails_sent INT,
    emails_opened INT,
    email_open_rate REAL,
    emails_replied INT,
    email_reply_rate REAL,
    -- LinkedIn metrics
    inmails_sent INT,
    inmails_replied INT,
    inmail_reply_rate REAL,
    interested_count INT,
    --
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(week_num, channel)
);

CREATE INDEX IF NOT EXISTS idx_weekly_channel ON weekly_snapshots(channel);

-- Insights: AI-generated daily advisor
CREATE TABLE IF NOT EXISTS insights (
    id BIGSERIAL PRIMARY KEY,
    insight_date DATE DEFAULT CURRENT_DATE,
    type TEXT NOT NULL
        CHECK (type IN ('action_required', 'alert', 'win', 'experiment', 'coaching', 'strategic')),
    severity TEXT DEFAULT 'medium'
        CHECK (severity IN ('high', 'medium', 'low')),
    title TEXT NOT NULL,
    body TEXT,
    related_company_id BIGINT REFERENCES companies(id),
    related_call_id BIGINT REFERENCES calls(id),
    channel TEXT,
    acknowledged BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_insights_date ON insights(insight_date);
CREATE INDEX IF NOT EXISTS idx_insights_type ON insights(type);
CREATE INDEX IF NOT EXISTS idx_insights_severity ON insights(severity);

-- Experiments: track what we're testing
CREATE TABLE IF NOT EXISTS experiments (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    hypothesis TEXT,
    channel TEXT,
    start_date DATE DEFAULT CURRENT_DATE,
    end_date DATE,
    status TEXT DEFAULT 'active'
        CHECK (status IN ('active', 'paused', 'completed', 'cancelled')),
    metric TEXT,
    result_summary TEXT,
    auto_detected BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Updated_at trigger function
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to companies
DROP TRIGGER IF EXISTS companies_updated_at ON companies;
CREATE TRIGGER companies_updated_at
    BEFORE UPDATE ON companies
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
"""


def create_schema():
    """Create all tables via Supabase SQL editor (RPC)."""
    from supabase import create_client

    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    sb = create_client(url, key)

    # Execute via postgrest SQL — need to use the REST API directly
    import httpx

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }

    # Split SQL into individual statements and execute via pg_net or direct SQL
    # Supabase doesn't have a direct SQL endpoint via client, use the SQL editor API
    sql_url = f"{url}/rest/v1/rpc/exec_sql"

    # Alternative: use the Supabase Management API SQL endpoint
    # For now, use individual table creation via postgrest
    # Actually, use the pg REST query endpoint
    query_url = f"{url}/pg/query"

    # Try the SQL query endpoint (available in newer Supabase)
    resp = httpx.post(
        query_url,
        headers=headers,
        json={"query": SCHEMA_SQL},
        timeout=30,
    )

    if resp.status_code == 200:
        print("Schema created successfully via pg/query")
        return True

    # Fallback: try the old sql endpoint
    sql_endpoint = f"{url}/sql"
    resp = httpx.post(
        sql_endpoint,
        headers=headers,
        json={"query": SCHEMA_SQL},
        timeout=30,
    )

    if resp.status_code == 200:
        print("Schema created successfully via /sql")
        return True

    # If both fail, output the SQL for manual execution
    print(f"Could not execute SQL via API (status {resp.status_code})")
    print("Run this SQL manually in the Supabase SQL Editor:")
    print("=" * 60)
    sql_file = BASE_DIR / "schema.sql"
    sql_file.write_text(SCHEMA_SQL)
    print(f"SQL written to {sql_file}")
    print(f"Go to: {url.replace('.supabase.co', '.supabase.co')}/project/default/sql/new")
    print("Paste the contents of schema.sql and click Run")
    return False


def migrate_calls(sb):
    """Migrate call_data.json into companies + calls tables."""
    call_data_file = BASE_DIR / "call_data.json"
    if not call_data_file.exists():
        print("  No call_data.json found, skipping calls migration")
        return

    data = json.loads(call_data_file.read_text())
    calls = data.get("calls", [])
    print(f"  Migrating {len(calls)} calls...")

    # Build company map
    company_map = {}  # name -> company record
    for call in calls:
        co_name = (call.get("company_name") or "").strip()
        if not co_name:
            continue
        if co_name not in company_map:
            # Use hubspot company ID as hubspot_id (some may be None)
            hs_id = call.get("company_id")
            company_map[co_name] = {
                "name": co_name,
                "hubspot_id": str(hs_id) if hs_id else None,
                "status": "prospect",
                "channels_touched": ["calls"],
                "total_touches": 0,
                "first_touch_at": call.get("timestamp"),
                "last_touch_at": call.get("timestamp"),
            }
        entry = company_map[co_name]
        entry["total_touches"] += 1
        ts = call.get("timestamp", "")
        if ts and (not entry["first_touch_at"] or ts < entry["first_touch_at"]):
            entry["first_touch_at"] = ts
        if ts and (not entry["last_touch_at"] or ts > entry["last_touch_at"]):
            entry["last_touch_at"] = ts

    # Determine company status from call categories
    company_categories = {}
    for call in calls:
        co_name = (call.get("company_name") or "").strip()
        if not co_name:
            continue
        cat = call.get("category", "")
        if co_name not in company_categories:
            company_categories[co_name] = set()
        company_categories[co_name].add(cat)

    for co_name, cats in company_categories.items():
        if co_name in company_map:
            if "Meeting Booked" in cats:
                company_map[co_name]["status"] = "meeting_booked"
            elif "Interested" in cats:
                company_map[co_name]["status"] = "interested"
            elif cats & {"Not Interested", "Referral Given", "No Rail", "Wrong Person", "Gatekeeper"}:
                company_map[co_name]["status"] = "contacted"

    # Insert companies one-by-one (no UNIQUE on name, so can't upsert by name)
    companies_list = list(company_map.values())
    print(f"  Inserting {len(companies_list)} companies...")

    for i in range(0, len(companies_list), 200):
        chunk = companies_list[i:i + 200]
        sb.table("companies").insert(chunk).execute()

    # Fetch company IDs back
    result = sb.table("companies").select("id, name").execute()
    name_to_id = {r["name"]: r["id"] for r in result.data}

    # Insert calls
    call_records = []
    for call in calls:
        co_name = (call.get("company_name") or "").strip()
        ts = call.get("timestamp")
        call_records.append({
            "hubspot_call_id": str(call.get("id", "")),
            "company_id": name_to_id.get(co_name),
            "contact_name": call.get("contact_name", "Unknown"),
            "category": call.get("category", ""),
            "duration_s": call.get("duration_s", 0),
            "notes": call.get("notes", ""),
            "summary": call.get("summary", ""),
            "recording_url": call.get("recording_url") or "",
            "has_transcript": call.get("has_transcript", False),
            "called_at": ts,
            "week_num": call.get("week_num"),
        })

    print(f"  Inserting {len(call_records)} call records...")
    for i in range(0, len(call_records), 200):
        chunk = call_records[i:i + 200]
        sb.table("calls").upsert(
            chunk, on_conflict="hubspot_call_id"
        ).execute()

    print(f"  Done: {len(companies_list)} companies, {len(call_records)} calls")
    return name_to_id


def migrate_intel(sb, name_to_id: dict):
    """Migrate call_intel.json into call_intel table."""
    intel_file = BASE_DIR / "call_intel.json"
    if not intel_file.exists():
        print("  No call_intel.json found, skipping intel migration")
        return

    data = json.loads(intel_file.read_text())
    intel_list = data.get("intel", [])
    print(f"  Migrating {len(intel_list)} intel records...")

    # Fetch call IDs by hubspot_call_id
    result = sb.table("calls").select("id, hubspot_call_id").execute()
    hs_to_call_id = {r["hubspot_call_id"]: r["id"] for r in result.data}

    records = []
    for entry in intel_list:
        call_id = hs_to_call_id.get(str(entry.get("call_id", "")))
        co_name = (entry.get("company_name") or "").strip()
        company_id = name_to_id.get(co_name) if co_name else None

        records.append({
            "call_id": call_id,
            "company_id": company_id,
            "interest_level": entry.get("interest_level"),
            "qualified": entry.get("qualified", False),
            "next_action": entry.get("next_action"),
            "objection": entry.get("objection"),
            "competitor": entry.get("competitor"),
            "commodities": entry.get("commodities"),
            "referral_name": entry.get("referral_name"),
            "referral_role": entry.get("referral_role"),
            "key_quote": entry.get("key_quote"),
        })

    for i in range(0, len(records), 200):
        chunk = records[i:i + 200]
        sb.table("call_intel").insert(chunk).execute()

    print(f"  Done: {len(records)} intel records")


def migrate_weekly(sb, data: dict):
    """Migrate weekly_data into weekly_snapshots."""
    weekly = data.get("weekly_data", [])
    if not weekly:
        print("  No weekly data found")
        return

    print(f"  Migrating {len(weekly)} weekly snapshots...")
    records = []
    for w in weekly:
        records.append({
            "week_num": w["week_num"],
            "monday": w["monday"],
            "channel": "calls",
            "dials": w.get("total_dials", 0),
            "human_contacts": w.get("human_contact", 0),
            "human_contact_rate": w.get("human_contact_rate", 0),
            "meetings_booked": w.get("meetings_booked", 0),
            "categories": json.dumps(w.get("categories", {})),
        })

    sb.table("weekly_snapshots").upsert(
        records, on_conflict="week_num,channel"
    ).execute()
    print(f"  Done: {len(records)} weekly snapshots")


def migrate_inmails(sb, name_to_id: dict):
    """Migrate inmail data from inmail_data.json (or call_data.json fallback)."""
    # Primary source: inmail_data.json
    inmail_file = BASE_DIR / "inmail_data.json"
    if inmail_file.exists():
        data = json.loads(inmail_file.read_text())
    else:
        # Fallback: inmail_stats inside call_data.json
        call_data_file = BASE_DIR / "call_data.json"
        if not call_data_file.exists():
            print("  No inmail data found, skipping")
            return
        full_data = json.loads(call_data_file.read_text())
        data = full_data.get("inmail_stats")
        if not data:
            print("  No inmail data found, skipping")
            return

    # Migrate weekly inmail data to weekly_snapshots
    weekly = data.get("weekly_data", [])
    if weekly:
        print(f"  Migrating {len(weekly)} inmail weekly snapshots...")
        records = []
        for w in weekly:
            records.append({
                "week_num": w.get("week_num", 0),
                "monday": w.get("monday"),
                "channel": "linkedin",
                "inmails_sent": w.get("sent", 0),
                "inmails_replied": w.get("replied", 0),
                "inmail_reply_rate": w.get("reply_rate", 0),
                "interested_count": w.get("interested", 0),
            })
        sb.table("weekly_snapshots").upsert(
            records, on_conflict="week_num,channel"
        ).execute()
        print(f"  Done: {len(records)} inmail weekly snapshots")

    # Migrate individual inmail records
    inmails = data.get("inmails", [])
    if inmails:
        print(f"  Migrating {len(inmails)} individual inmails...")
        records = []
        for im in inmails:
            co_name = (im.get("company") or "").strip()
            sentiment = im.get("sentiment")
            # Map sentiment to valid enum values
            if sentiment and sentiment not in ("interested", "not_interested", "neutral", "ooo"):
                sentiment = None
            records.append({
                "company_id": name_to_id.get(co_name),
                "contact_name": im.get("recipient_name", ""),
                "contact_title": im.get("recipient_title", ""),
                "company_name": co_name,
                "sent_date": im.get("date_sent"),
                "replied": im.get("replied", False),
                "reply_sentiment": sentiment,
                "reply_text": im.get("reply_text", ""),
                "week_num": im.get("week_num"),
            })
        for i in range(0, len(records), 200):
            chunk = records[i:i + 200]
            sb.table("inmails").insert(chunk).execute()
        print(f"  Done: {len(records)} inmails")


def run_migration():
    """Full data migration from JSON files to Supabase."""
    from supabase import create_client

    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    sb = create_client(url, key)

    print("\n=== Phase 1: Migrate Calls + Companies ===")
    name_to_id = migrate_calls(sb)
    if not name_to_id:
        name_to_id = {}

    print("\n=== Phase 2: Migrate Call Intelligence ===")
    migrate_intel(sb, name_to_id)

    print("\n=== Phase 3: Migrate Weekly Snapshots ===")
    call_data_file = BASE_DIR / "call_data.json"
    if call_data_file.exists():
        data = json.loads(call_data_file.read_text())
        migrate_weekly(sb, data)

    print("\n=== Phase 4: Migrate InMail Data ===")
    migrate_inmails(sb, name_to_id)

    # Print summary
    print("\n=== Migration Summary ===")
    for table in ["companies", "calls", "call_intel", "weekly_snapshots", "inmails", "insights", "experiments"]:
        try:
            result = sb.table(table).select("id", count="exact").limit(0).execute()
            print(f"  {table}: {result.count} rows")
        except Exception:
            print(f"  {table}: (table may not exist yet)")

    print("\nMigration complete!")


def main():
    parser = argparse.ArgumentParser(description="Supabase setup + migration")
    parser.add_argument("--schema", action="store_true", help="Create schema only")
    parser.add_argument("--migrate", action="store_true", help="Run data migration only")
    args = parser.parse_args()

    if args.schema or (not args.schema and not args.migrate):
        print("=== Creating Schema ===")
        success = create_schema()
        if not success and not args.migrate:
            print("\nSchema must be created before migration.")
            print("Run the SQL manually, then re-run with --migrate")
            return

    if args.migrate or (not args.schema and not args.migrate):
        run_migration()


if __name__ == "__main__":
    main()
