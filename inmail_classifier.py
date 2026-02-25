#!/usr/bin/env python3
"""
LinkedIn InMail Reply Classifier.

Reads inmail_raw.json, classifies each reply sentiment via Claude Haiku,
computes weekly and cumulative stats, and writes inmail_data.json.

Usage:
    python3 inmail_classifier.py                            # classify + output
    python3 inmail_classifier.py --campaign-start 2026-01-19
    python3 inmail_classifier.py --force                    # re-classify all
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
RAW_INPUT = BASE_DIR / "inmail_raw.json"
OUTPUT_FILE = BASE_DIR / "inmail_data.json"

DEFAULT_CAMPAIGN_START = "2026-01-19"
HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Ordered longest-first so "Not Interested" matches before "Interested"
VALID_SENTIMENTS = ["Not Interested", "Interested", "Neutral", "OOO"]

CLASSIFY_PROMPT = (
    "You are classifying replies to cold sales InMails. "
    "Classify this reply into EXACTLY one category:\n\n"
    "- Interested: wants to learn more, asks questions, shares contact info, agrees to a meeting\n"
    "- Not Interested: explicitly declines, says no, says they don't use the product/service, "
    "says 'no me interesa', 'not interested', 'no thanks', 'we don't use rail', left the company\n"
    "- Neutral: generic auto-reply ('thanks for reaching out'), acknowledges but no clear intent\n"
    "- OOO: out of office, vacation, away message\n\n"
    "Reply with ONLY the category name, nothing else.\n\n"
    "Reply to classify: {reply_text}"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_id(name: str, company: str, date_sent: str) -> str:
    # Don't include company — it gets enriched later and would break cache
    raw = f"{name}|{date_sent}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


import re

# Words before "en"/"at" that signal education, not company
_EDU_PREFIXES = re.compile(
    r'(?:licenciado|licenciada|lic|maestr[ií]a|mba|doctorado|ingeniero|ingeniera|'
    r'ing\.?|b\.?a\.?|m\.?a\.?|m\.?s\.?|phd|especialista|diplomado|'
    r't[eé]cnico|t[eé]cnica|certificad[oa]|expert|experta|l[ií]der|finance)\s*$',
    re.IGNORECASE,
)

# Words/phrases in the extracted company that indicate it's not actually a company
_NOT_COMPANY = re.compile(
    r'^(?:yacimientos|planeaci[oó]n|estrateg|cadena de|log[ií]stica con)',
    re.IGNORECASE,
)

# Known schools (not companies)
_SCHOOLS = {'tecnológico de monterrey', 'tecnologico de monterrey', 'itesm', 'unam', 'ipn'}

# Normalize company name variants to a canonical form
_COMPANY_ALIASES = {
    "gruma": "GRUMA",
    "molinos azteca pta. rio bravo": "GRUMA",
    "alpek": "Alpek",
    "alpek polyester": "Alpek",
    "j.b. hunt transport": "JB Hunt",
    "j.b. hunt transport services": "JB Hunt",
    "jb hunt mexico": "JB Hunt",
    "jb hunt transport services": "JB Hunt",
    "j.b. hunt transport, inc.": "JB Hunt",
    "samsung": "Samsung SDS",
    "samsung sds": "Samsung SDS",
    "samsung sds (north america)": "Samsung SDS",
    "marathon petroleum corporation": "Marathon Petroleum",
    "valero méxico": "Valero",
    "grupo calmart": "Minergycorp",
    "empresa de alimentos": "Empresa de Alimentos",
    "grupo trimex": "Grupo Trimex",
    "grupo cuprum": "Grupo Cuprum",
    "grupo méxico": "Grupo México",
    "grupo la moderna": "Grupo La Moderna",
}

# Manual overrides: (recipient_name) -> company
# For people whose title doesn't contain their company
_MANUAL_COMPANY = {
    "Arturo Hernández": "Valero",
    "Andrea García Quintero": "Valero",
}


def normalize_company(company: str) -> str:
    """Normalize company name to canonical form."""
    if not company:
        return ""
    return _COMPANY_ALIASES.get(company.lower().strip(), company)


def extract_company(title: str) -> str:
    """Extract company name from a LinkedIn title string.

    Looks for patterns like "... en CompanyName" or "... at CompanyName".
    Skips education contexts and known schools.
    """
    if not title:
        return ""
    for m in re.finditer(r'\b(en|at)\s+([^|/\n]+?)(?:\s*[|/]|\s*,\s*[A-Z]|$)', title, re.IGNORECASE):
        # Check text before the match for edu keywords
        prefix = title[:m.start()].strip()
        # Look at the segment after the last delimiter
        segment = prefix.split('|')[-1].strip()
        if _EDU_PREFIXES.search(segment):
            continue
        company = m.group(2).strip().rstrip('.')
        if len(company) < 3:
            continue
        if _NOT_COMPANY.search(company):
            continue
        if company.lower() in _SCHOOLS:
            continue
        return company
    return ""


def parse_date(value: str) -> Optional[date]:
    """Try to parse various date string formats into a date object."""
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%d %b %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    # ISO datetime (e.g., from a datetime attribute)
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None


def week_number(d: date, campaign_start: date) -> int:
    """Week 1 starts on campaign_start Monday; returns 1-based week number."""
    delta = (d - campaign_start).days
    return max(delta // 7 + 1, 1)


def monday_of_week(week_num: int, campaign_start: date) -> str:
    """Return ISO date string of the Monday that begins the given week."""
    return (campaign_start + timedelta(weeks=week_num - 1)).isoformat()


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_reply(client: anthropic.Anthropic, reply_text: str) -> str:
    """Call Claude Haiku to classify the reply. Returns one of VALID_SENTIMENTS."""
    # Only use the first reply paragraph to avoid contamination from follow-ups
    first_reply = reply_text.split("\n\n")[0].strip()[:500]
    prompt = CLASSIFY_PROMPT.format(reply_text=first_reply)
    message = client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=16,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()

    # Normalize to exact category name
    for category in VALID_SENTIMENTS:
        if category.lower() in raw.lower():
            return category
    return "Neutral"  # safe fallback


# ---------------------------------------------------------------------------
# Weekly aggregation
# ---------------------------------------------------------------------------

def build_weekly_data(inmails: list, campaign_start: date) -> list:
    """Group classified InMails by week and compute per-week stats."""
    from collections import defaultdict

    weeks: dict = defaultdict(lambda: {
        "sent": 0, "replied": 0,
        "interested": 0, "not_interested": 0, "neutral": 0, "ooo": 0,
    })

    for item in inmails:
        wk = item["week_num"]
        weeks[wk]["sent"] += 1
        if item["replied"]:
            weeks[wk]["replied"] += 1
            s = item.get("sentiment", "")
            if s == "Interested":
                weeks[wk]["interested"] += 1
            elif s == "Not Interested":
                weeks[wk]["not_interested"] += 1
            elif s == "OOO":
                weeks[wk]["ooo"] += 1
            else:
                weeks[wk]["neutral"] += 1

    result = []
    for wk in sorted(weeks):
        d = weeks[wk]
        sent = d["sent"]
        replied = d["replied"]
        interested = d["interested"]
        reply_rate = round(replied / sent * 100, 1) if sent else 0.0
        interest_rate = round(interested / replied * 100, 1) if replied else 0.0

        result.append({
            "week_num": wk,
            "monday": monday_of_week(wk, campaign_start),
            "sent": sent,
            "replied": replied,
            "reply_rate": reply_rate,
            "interested": interested,
            "interest_rate": interest_rate,
            "not_interested": d["not_interested"],
            "neutral": d["neutral"],
            "ooo": d["ooo"],
        })

    return result


def build_totals(inmails: list) -> dict:
    sent = len(inmails)
    replied_items = [i for i in inmails if i["replied"]]
    replied = len(replied_items)
    interested = sum(1 for i in replied_items if i.get("sentiment") == "Interested")
    not_interested = sum(1 for i in replied_items if i.get("sentiment") == "Not Interested")
    neutral = sum(1 for i in replied_items if i.get("sentiment") == "Neutral")
    ooo = sum(1 for i in replied_items if i.get("sentiment") == "OOO")

    companies = sorted(set(i["company"] for i in inmails if i.get("company")))

    return {
        "sent": sent,
        "replied": replied,
        "reply_rate": round(replied / sent * 100, 1) if sent else 0.0,
        "interested": interested,
        "interest_rate": round(interested / replied * 100, 1) if replied else 0.0,
        "not_interested": not_interested,
        "neutral": neutral,
        "ooo": ooo,
        "companies_contacted": companies,
    }


# ---------------------------------------------------------------------------
# Main classify flow
# ---------------------------------------------------------------------------

def classify(campaign_start_str: str = DEFAULT_CAMPAIGN_START, force: bool = False) -> None:
    if not RAW_INPUT.exists():
        print(f"ERROR: {RAW_INPUT} not found. Run inmail_scraper.py first.")
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set in environment or .env")
        sys.exit(1)

    campaign_start = date.fromisoformat(campaign_start_str)
    raw_records: list = json.loads(RAW_INPUT.read_text())
    print(f"Loaded {len(raw_records)} raw InMails from {RAW_INPUT}")

    # Load existing output to skip already-classified records (unless --force)
    existing: dict[str, str] = {}  # id -> sentiment
    if not force and OUTPUT_FILE.exists():
        prev = json.loads(OUTPUT_FILE.read_text())
        for item in prev.get("inmails", []):
            if item.get("sentiment"):
                existing[item["id"]] = item["sentiment"]
        print(f"  Skipping {len(existing)} already-classified records (use --force to redo)")

    client = anthropic.Anthropic(api_key=api_key)
    inmails = []

    for rec in raw_records:
        name = rec.get("recipient_name", "")
        company = rec.get("company", "")
        title = rec.get("recipient_title", "")
        if not company and title:
            company = extract_company(title)
        if not company and name in _MANUAL_COMPANY:
            company = _MANUAL_COMPANY[name]
        company = normalize_company(company)
        date_sent_raw = rec.get("date_sent", "")
        replied = bool(rec.get("replied"))
        reply_text = rec.get("reply_text", "")

        item_date = parse_date(date_sent_raw) or campaign_start
        record_id = make_id(name, company, date_sent_raw)

        # Classify if there's a reply and we haven't done it yet (or --force)
        sentiment: Optional[str] = None
        if replied and reply_text:
            if record_id in existing and not force:
                sentiment = existing[record_id]
            else:
                print(f"  Classifying: {name} ({company})...")
                try:
                    sentiment = classify_reply(client, reply_text)
                    print(f"    -> {sentiment}")
                except Exception as e:
                    print(f"    ERROR classifying: {e}")
                    sentiment = "Neutral"
                time.sleep(0.5)  # small delay between API calls

        inmails.append({
            "id": record_id,
            "recipient_name": name,
            "recipient_title": rec.get("recipient_title", ""),
            "company": company,
            "date_sent": item_date.isoformat(),
            "replied": replied,
            "reply_text": reply_text,
            "sentiment": sentiment,
            "week_num": week_number(item_date, campaign_start),
        })

    # Sort by date
    inmails.sort(key=lambda x: x["date_sent"])

    weekly_data = build_weekly_data(inmails, campaign_start)
    totals = build_totals(inmails)

    output = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "campaign_start": campaign_start_str,
        "inmails": inmails,
        "weekly_data": weekly_data,
        "totals": totals,
    }

    OUTPUT_FILE.write_text(json.dumps(output, indent=2, default=str))
    print(f"\nOutput written to {OUTPUT_FILE}")
    print(f"  Total InMails: {totals['sent']}")
    print(f"  Replied:       {totals['replied']} ({totals['reply_rate']}%)")
    print(f"  Interested:    {totals['interested']} ({totals['interest_rate']}% of replies)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="LinkedIn InMail Reply Classifier")
    parser.add_argument(
        "--campaign-start",
        default=DEFAULT_CAMPAIGN_START,
        help=f"Campaign start date (default: {DEFAULT_CAMPAIGN_START})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-classify all replies, even if already classified",
    )
    args = parser.parse_args()

    classify(campaign_start_str=args.campaign_start, force=args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
