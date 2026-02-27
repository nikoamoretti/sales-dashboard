#!/usr/bin/env python3
"""
Call Intelligence Extractor.

Reads call_data.json, runs Gemini Flash (free) over summaries + notes to
extract structured intelligence per call, writes call_intel.json.

Usage:
    python3 call_intel.py                # extract new calls only (Gemini)
    python3 call_intel.py --force        # re-extract all
    python3 call_intel.py --dry-run      # show what would be processed
    python3 call_intel.py --model haiku  # use Claude Haiku instead
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
CALL_DATA = BASE_DIR / "call_data.json"
OUTPUT_FILE = BASE_DIR / "call_intel.json"

GEMINI_MODEL = "gemini-2.0-flash"
HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Categories where intel extraction is worthwhile
EXTRACTABLE_CATEGORIES = {
    "Interested", "Meeting Booked", "Referral Given",
    "Not Interested", "No Rail", "Wrong Person", "Gatekeeper",
}

EXTRACT_PROMPT = """\
You are analyzing a cold call from a freight railroad brokerage (Telegraph) \
to a potential shipping customer. Extract structured intelligence from the \
call summary and notes below.

Return ONLY valid JSON with these fields (use null for unknown/not applicable):

{{
  "interest_level": "high" | "medium" | "low" | "none",
  "next_action": "short CRM task, max 50 chars (e.g. 'Email rate comparison to Ben Grimm')",
  "referral_name": "name of person referred to, or null",
  "referral_role": "role/title of referred person, or null",
  "objection": "main objection raised, or null",
  "competitor": "any competitor mentioned, or null",
  "commodities": "what they ship (chemicals, plastics, food, etc.), or null",
  "key_quote": "most important thing the prospect said, or null",
  "qualified": true | false
}}

Guidelines:
- interest_level: "high" = wants meeting/demo, "medium" = open but noncommittal, \
"low" = reluctant/pushing back, "none" = hard no or wrong person
- next_action: short CRM task, MAX 50 chars. Start with a verb. \
Examples: "Email rate comparison to Ben Grimm", "Call back Thu 2pm", \
"Ask Nico re: corporate contact", "Remove — no rail". NOT paragraphs.
- qualified: true if they ship via rail or could, false if wrong number/person, \
no rail, or clearly not a fit
- competitor: names like "CSX", "UP", "BNSF", "NS", "XPO", etc.
- referral_name: do NOT include "Adam", "Adam Jackson", "Nico", or "Nicolas Amoretti" \
as referrals — only include names of people at the prospect company
- If the call is just a voicemail with no real conversation, still extract what you can

CALL DATA:
Contact: {contact_name}
Company: {company_name}
Category: {category}
Duration: {duration}s

{text_block}
"""


def build_text_block(call: dict) -> str:
    """Combine summary + notes into the text block for the prompt."""
    parts = []
    summary = call.get("summary", "")
    notes = call.get("notes", "")
    engagement = call.get("engagement_notes", [])

    if summary:
        parts.append(f"AI SUMMARY:\n{summary}")
    if notes:
        parts.append(f"ADAM'S NOTES:\n{notes}")
    if engagement:
        for i, note in enumerate(engagement, 1):
            parts.append(f"ENGAGEMENT NOTE {i}:\n{note}")

    return "\n\n".join(parts)


def _build_prompt(call: dict) -> str:
    return EXTRACT_PROMPT.format(
        contact_name=call.get("contact_name", "Unknown"),
        company_name=call.get("company_name", "Unknown"),
        category=call.get("category", "Unknown"),
        duration=call.get("duration_s", 0),
        text_block=build_text_block(call),
    )


def _parse_json_response(raw: str) -> Optional[dict]:
    """Parse JSON from model response, handling code fences."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print(f"    WARNING: Failed to parse JSON: {raw[:120]}")
        return None


# ---------------------------------------------------------------------------
# Model backends
# ---------------------------------------------------------------------------

class GeminiBackend:
    def __init__(self):
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set in environment or .env")
        self.client = genai.Client(api_key=api_key)
        self.name = f"Gemini ({GEMINI_MODEL})"

    def extract(self, call: dict) -> Optional[dict]:
        prompt = _build_prompt(call)
        response = self.client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config={"temperature": 0, "max_output_tokens": 400},
        )
        return _parse_json_response(response.text)


class HaikuBackend:
    def __init__(self):
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set in environment or .env")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.name = f"Haiku ({HAIKU_MODEL})"

    def extract(self, call: dict) -> Optional[dict]:
        prompt = _build_prompt(call)
        message = self.client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=300,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        return _parse_json_response(message.content[0].text)


def get_backend(model_name: str):
    if model_name == "gemini":
        return GeminiBackend()
    elif model_name == "haiku":
        return HaikuBackend()
    else:
        raise ValueError(f"Unknown model: {model_name}. Use 'gemini' or 'haiku'.")


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def run(force: bool = False, dry_run: bool = False, model: str = "gemini") -> None:
    if not CALL_DATA.exists():
        print(f"ERROR: {CALL_DATA} not found. Run dashboard_gen.py first.")
        sys.exit(1)

    data = json.loads(CALL_DATA.read_text())
    calls = data.get("calls", [])
    print(f"Loaded {len(calls)} calls from {CALL_DATA}")

    # Load existing cache
    cache: dict[str, dict] = {}
    if not force and OUTPUT_FILE.exists():
        prev = json.loads(OUTPUT_FILE.read_text())
        for entry in prev.get("intel", []):
            cache[str(entry["call_id"])] = entry
        print(f"  Cached: {len(cache)} already extracted (use --force to redo)")

    # Filter to extractable calls with text content
    to_process = []
    for call in calls:
        call_id = str(call.get("id", ""))
        if not call_id:
            continue
        if call_id in cache:
            continue
        if call.get("category") not in EXTRACTABLE_CATEGORIES:
            continue
        text = build_text_block(call)
        if not text.strip():
            continue
        to_process.append(call)

    print(f"  To process: {len(to_process)} calls")

    if dry_run:
        for call in to_process[:10]:
            print(f"    {call['contact_name']:30s} {call.get('company_name',''):20s} [{call['category']}]")
        if len(to_process) > 10:
            print(f"    ... and {len(to_process) - 10} more")
        return

    if not to_process:
        _write_output(cache)
        return

    backend = get_backend(model)
    print(f"  Using: {backend.name}")

    extracted = 0
    errors = 0

    for i, call in enumerate(to_process, 1):
        call_id = str(call["id"])
        name = call.get("contact_name", "Unknown")
        company = call.get("company_name", "")
        print(f"  [{i}/{len(to_process)}] {name} ({company})...", end=" ", flush=True)

        try:
            intel = backend.extract(call)
            if intel:
                cache[call_id] = {
                    "call_id": call_id,
                    "contact_name": name,
                    "company_name": company,
                    "category": call.get("category", ""),
                    "timestamp": call.get("timestamp", ""),
                    **intel,
                }
                extracted += 1
                level = intel.get("interest_level", "?")
                action = (intel.get("next_action") or "")[:60]
                print(f"[{level}] {action}")
            else:
                print("SKIP (no parseable result)")
        except Exception as e:
            print(f"ERROR: {e}")
            errors += 1
            if errors > 5:
                print("Too many errors, stopping.")
                break
            time.sleep(2)

        # Gemini free tier: 15 RPM = 1 req per 4s to be safe
        delay = 0.3 if model == "haiku" else 4.2
        time.sleep(delay)

    _write_output(cache, extracted)


def _write_output(cache: dict, new_count: int = 0) -> None:
    intel_list = sorted(cache.values(), key=lambda x: x.get("timestamp", ""))

    qualified = sum(1 for x in intel_list if x.get("qualified"))
    with_referral = sum(1 for x in intel_list if x.get("referral_name"))
    with_action = sum(1 for x in intel_list if x.get("next_action"))
    with_competitor = sum(1 for x in intel_list if x.get("competitor"))
    with_commodity = sum(1 for x in intel_list if x.get("commodities"))

    interest_counts = {}
    for entry in intel_list:
        level = entry.get("interest_level", "unknown")
        interest_counts[level] = interest_counts.get(level, 0) + 1

    output = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "total_extracted": len(intel_list),
        "summary": {
            "qualified": qualified,
            "with_referral": with_referral,
            "with_next_action": with_action,
            "with_competitor": with_competitor,
            "with_commodities": with_commodity,
            "interest_levels": interest_counts,
        },
        "intel": intel_list,
    }

    OUTPUT_FILE.write_text(json.dumps(output, indent=2, default=str))
    print(f"\nOutput: {OUTPUT_FILE}")
    print(f"  Total extracted: {len(intel_list)}")
    print(f"  New this run:    {new_count}")
    print(f"  Qualified:       {qualified}")
    print(f"  With referrals:  {with_referral}")
    print(f"  With competitors:{with_competitor}")
    print(f"  Interest levels: {interest_counts}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Call Intelligence Extractor")
    parser.add_argument("--force", action="store_true", help="Re-extract all calls")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be processed")
    parser.add_argument("--model", default="gemini", choices=["gemini", "haiku"],
                        help="Model backend (default: gemini = free)")
    args = parser.parse_args()
    run(force=args.force, dry_run=args.dry_run, model=args.model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
