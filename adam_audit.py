"""
Adam Jackson Cold Calling Performance Audit
Reads call_data.json + call_intel.json and prints a thorough analysis.
No file output — stdout only.
"""

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any

BASE = Path("/Users/nicoamoretti/nico_repo/sales-dashboard")


# ── helpers ─────────────────────────────────────────────────────────────────

def load() -> tuple[list[dict], list[dict]]:
    with open(BASE / "call_data.json") as f:
        data = json.load(f)
    with open(BASE / "call_intel.json") as f:
        intel = json.load(f)
    return data["calls"], intel["intel"]


def ts(call: dict) -> datetime:
    raw = call["timestamp"]
    # strip tz offset so fromisoformat works on 3.10-
    return datetime.fromisoformat(raw[:19])


def divider(title: str = "", width: int = 70) -> None:
    if title:
        pad = (width - len(title) - 2) // 2
        print(f"\n{'=' * pad} {title} {'=' * (width - pad - len(title) - 2)}")
    else:
        print("=" * width)


def section(title: str) -> None:
    print(f"\n--- {title} ---")


def pct(part: int, total: int) -> str:
    if total == 0:
        return "0.0%"
    return f"{100 * part / total:.1f}%"


def fmt_dur(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    return f"{int(seconds // 60)}m {int(seconds % 60)}s"


# ── category constants ───────────────────────────────────────────────────────

LIVE_CATEGORIES = {
    "Interested",
    "Not Interested",
    "Referral Given",
    "Meeting Booked",
    "Gatekeeper",
    "Wrong Person",
    "No Rail",
}

POSITIVE_CATEGORIES = {"Interested", "Meeting Booked", "Referral Given"}


# ── 1. Overall stats ─────────────────────────────────────────────────────────

def section_overall(calls: list[dict]) -> None:
    divider("1. OVERALL STATS")

    dates = [ts(c) for c in calls]
    min_date = min(dates)
    max_date = max(dates)
    date_range_days = (max_date - min_date).days + 1
    weeks = date_range_days / 7

    print(f"  Total calls       : {len(calls):,}")
    print(f"  Date range        : {min_date.date()} → {max_date.date()}  ({date_range_days} days)")
    print(f"  Approximate weeks : {weeks:.1f}")
    print(f"  Avg calls / day   : {len(calls) / date_range_days:.1f}")
    print(f"  Avg calls / week  : {len(calls) / weeks:.1f}")

    # daily call counts → weekly buckets
    by_week: dict[int, int] = Counter(c["week_num"] for c in calls)
    week_nums = sorted(by_week)
    print(f"\n  Weekly call volume (week # : count):")
    for w in week_nums:
        bar = "#" * min(by_week[w], 60)
        print(f"    Week {w:>2}: {by_week[w]:>3}  {bar}")


# ── 2. Category breakdown ─────────────────────────────────────────────────────

def section_categories(calls: list[dict]) -> dict[str, int]:
    divider("2. CATEGORY BREAKDOWN")

    cat_counts: Counter = Counter(c["category"] for c in calls)
    total = len(calls)

    # canonical order
    ORDER = [
        "No Answer",
        "Left Voicemail",
        "Gatekeeper",
        "Wrong Person",
        "Wrong Number",
        "No Rail",
        "Interested",
        "Not Interested",
        "Referral Given",
        "Meeting Booked",
    ]
    # any unlisted categories
    all_cats = ORDER + [k for k in cat_counts if k not in ORDER]

    print(f"  {'Category':<22}  {'Count':>6}  {'%':>6}")
    print(f"  {'-'*22}  {'------':>6}  {'------':>6}")
    for cat in all_cats:
        if cat in cat_counts:
            print(f"  {cat:<22}  {cat_counts[cat]:>6}  {pct(cat_counts[cat], total):>6}")
    print(f"  {'TOTAL':<22}  {total:>6}")
    return dict(cat_counts)


# ── 3. Contact rate ──────────────────────────────────────────────────────────

def section_contact_rate(calls: list[dict], cat_counts: dict[str, int]) -> None:
    divider("3. CONTACT RATE")

    total = len(calls)
    live = sum(cat_counts.get(c, 0) for c in LIVE_CATEGORIES)
    no_answer = cat_counts.get("No Answer", 0)
    voicemail = cat_counts.get("Left Voicemail", 0)
    no_contact = no_answer + voicemail

    print(f"  Total calls              : {total:>5}")
    print(f"  No Answer                : {no_answer:>5}  ({pct(no_answer, total)})")
    print(f"  Left Voicemail           : {voicemail:>5}  ({pct(voicemail, total)})")
    print(f"  No-contact subtotal      : {no_contact:>5}  ({pct(no_contact, total)})")
    print(f"  Live conversations       : {live:>5}  ({pct(live, total)})  <- Contact Rate")
    print()
    print(f"  Breakdown of live conversations:")
    for cat in sorted(LIVE_CATEGORIES, key=lambda x: cat_counts.get(x, 0), reverse=True):
        n = cat_counts.get(cat, 0)
        if n:
            print(f"    {cat:<22}: {n:>4}  ({pct(n, total)} of all calls, "
                  f"{pct(n, live)} of live)")


# ── 4. Conversion analysis ───────────────────────────────────────────────────

def section_conversion(calls: list[dict], cat_counts: dict[str, int]) -> None:
    divider("4. CONVERSION ANALYSIS  (of live conversations)")

    live = sum(cat_counts.get(c, 0) for c in LIVE_CATEGORIES)
    positive = sum(cat_counts.get(c, 0) for c in POSITIVE_CATEGORIES)
    meetings = cat_counts.get("Meeting Booked", 0)
    interested = cat_counts.get("Interested", 0)
    referrals = cat_counts.get("Referral Given", 0)
    not_interested = cat_counts.get("Not Interested", 0)
    gatekeeper = cat_counts.get("Gatekeeper", 0)
    wrong_person = cat_counts.get("Wrong Person", 0)
    no_rail = cat_counts.get("No Rail", 0)

    print(f"  Live conversations       : {live}")
    print()
    print(f"  Positive outcomes (Interested + Meeting Booked + Referral Given):")
    print(f"    Total positive         : {positive:>4}  ({pct(positive, live)} of live)")
    print(f"    Meeting Booked         : {meetings:>4}  ({pct(meetings, live)} of live)")
    print(f"    Interested             : {interested:>4}  ({pct(interested, live)} of live)")
    print(f"    Referral Given         : {referrals:>4}  ({pct(referrals, live)} of live)")
    print()
    print(f"  Negative / neutral outcomes:")
    print(f"    Not Interested         : {not_interested:>4}  ({pct(not_interested, live)} of live)")
    print(f"    Gatekeeper             : {gatekeeper:>4}  ({pct(gatekeeper, live)} of live)")
    print(f"    Wrong Person           : {wrong_person:>4}  ({pct(wrong_person, live)} of live)")
    print(f"    No Rail                : {no_rail:>4}  ({pct(no_rail, live)} of live)")
    print()
    print(f"  Meeting rate (meetings / total calls): {pct(meetings, len(calls))}")
    print(f"  Meeting rate (meetings / live convos): {pct(meetings, live)}")


# ── 5. Duration analysis ──────────────────────────────────────────────────────

def section_duration(calls: list[dict]) -> None:
    divider("5. DURATION ANALYSIS")

    # by category
    by_cat: dict[str, list[int]] = defaultdict(list)
    for c in calls:
        by_cat[c["category"]].append(c["duration_s"])

    print(f"  {'Category':<22}  {'Count':>5}  {'Avg':>7}  {'Median':>7}  {'Max':>7}")
    print(f"  {'-'*22}  {'-----':>5}  {'-------':>7}  {'-------':>7}  {'-------':>7}")
    for cat, durs in sorted(by_cat.items(), key=lambda x: mean(x[1]), reverse=True):
        if durs:
            print(
                f"  {cat:<22}  {len(durs):>5}  "
                f"{fmt_dur(mean(durs)):>7}  "
                f"{fmt_dur(median(durs)):>7}  "
                f"{fmt_dur(max(durs)):>7}"
            )

    # top 10 longest calls
    section("Top 10 Longest Calls")
    longest = sorted(calls, key=lambda c: c["duration_s"], reverse=True)[:10]
    for i, c in enumerate(longest, 1):
        summary_snippet = (c.get("summary") or "")[:120].replace("\n", " ")
        if len(summary_snippet) == 120:
            summary_snippet += "..."
        print(f"  {i:>2}. {fmt_dur(c['duration_s']):>7}  [{c['category']:<18}]  "
              f"{c['contact_name']} @ {c['company_name']}")
        if summary_snippet:
            print(f"       \"{summary_snippet}\"")
        notes = (c.get("notes") or "").strip()
        if notes:
            print(f"       Notes: {notes[:100]}")


# ── 6. Call intel analysis ────────────────────────────────────────────────────

def section_intel(intel: list[dict]) -> None:
    divider("6. CALL INTELLIGENCE ANALYSIS  (114 calls with structured intel)")

    # interest levels
    section("Interest Level Distribution")
    interest_counts: Counter = Counter(r.get("interest_level") or "none" for r in intel)
    total_intel = len(intel)
    for level in ["high", "medium", "low", "none"]:
        n = interest_counts.get(level, 0)
        bar = "#" * int(30 * n / total_intel)
        print(f"  {level:<8}: {n:>3}  ({pct(n, total_intel)})  {bar}")

    # next action quality
    section("Next Action Quality")
    has_next_action = [r for r in intel if r.get("next_action")]
    actionable_keywords = [
        "call", "email", "schedule", "follow", "meet", "send", "reach out",
        "contact", "attend", "book",
    ]
    vague_keywords = [
        "check with nico", "consult with nico", "nicolas amoretti",
        "confirm with nico", "get guidance from nico", "nico to",
        "wait for", "no further action",
    ]

    specific = []
    escalated_to_nico = []
    vague = []
    for r in intel:
        na = (r.get("next_action") or "").lower()
        if not na:
            continue
        if any(v in na for v in vague_keywords):
            escalated_to_nico.append(r)
        elif any(k in na for k in actionable_keywords):
            specific.append(r)
        else:
            vague.append(r)

    print(f"  Calls with next action   : {len(has_next_action)} / {total_intel} ({pct(len(has_next_action), total_intel)})")
    print(f"  Specific & actionable    : {len(specific):>3}  (clear follow-up step)")
    print(f"  Escalated to Nico        : {len(escalated_to_nico):>3}  (needs manager input)")
    print(f"  Vague / unclear          : {len(vague):>3}  (lacking specificity)")
    print()
    print(f"  Sample 'escalated to Nico' next actions:")
    for r in escalated_to_nico[:6]:
        print(f"    - [{r['company_name']:<30}] {r['next_action']}")

    # referrals
    section("Referrals Obtained")
    with_referral = [r for r in intel if r.get("referral_name")]
    print(f"  Calls with referral      : {len(with_referral)} / {total_intel} ({pct(len(with_referral), total_intel)})")
    print(f"\n  Referral quality breakdown:")
    has_contact_info = [r for r in with_referral
                        if r.get("next_action") and
                        any(ch.isdigit() for ch in (r.get("next_action") or ""))]
    print(f"    With phone # in action : {len(has_contact_info)}  (immediately callable)")
    print(f"    Without phone #        : {len(with_referral) - len(has_contact_info)}  (needs research)")
    print(f"\n  Sample referrals:")
    for r in with_referral[:8]:
        role = r.get("referral_role") or "role unknown"
        na = (r.get("next_action") or "no next action")[:80]
        print(f"    - {r['referral_name']:<22} ({role:<30}) @ {r['company_name']}")
        print(f"      Action: {na}")

    # objections
    section("Objections Heard")
    with_objection = [r for r in intel if r.get("objection")]
    print(f"  Calls with logged objection: {len(with_objection)} / {total_intel} ({pct(len(with_objection), total_intel)})")

    # cluster objection themes
    obj_themes: Counter = Counter()
    for r in with_objection:
        obj = (r.get("objection") or "").lower()
        if "happy" in obj or "satisfied" in obj or "works well" in obj or "no issues" in obj:
            obj_themes["Satisfied with current solution"] += 1
        elif "contract" in obj or "locked" in obj or "2-year" in obj or "rollout" in obj:
            obj_themes["Locked in contract"] += 1
        elif "in-house" in obj or "built" in obj or "internal" in obj or "own system" in obj:
            obj_themes["In-house solution"] += 1
        elif "wrong person" in obj or "doesn't handle" in obj or "does not handle" in obj:
            obj_themes["Wrong person / no decision authority"] += 1
        elif "no rail" in obj or "not use rail" in obj or "don't use rail" in obj or "doesn't use rail" in obj or "no rail" in obj or "only truck" in obj or "uses truck" in obj or "truck" in obj:
            obj_themes["Does not ship via rail"] += 1
        elif "budget" in obj:
            obj_themes["Budget constraints"] += 1
        elif "wrong" in obj or "no longer" in obj or "retired" in obj:
            obj_themes["Stale / bad contact"] += 1
        else:
            obj_themes["Other"] += 1

    print(f"\n  Objection themes:")
    for theme, count in obj_themes.most_common():
        print(f"    {theme:<40}: {count}")

    print(f"\n  Sample objections and how they were handled:")
    samples = [r for r in with_objection if r.get("key_quote") and r.get("next_action")][:8]
    for r in samples:
        print(f"    Company: {r['company_name']} ({r['category']})")
        print(f"    Objection: {r['objection']}")
        print(f"    Quote: \"{r.get('key_quote', '')}\"")
        print(f"    Next action: {r.get('next_action', '')[:80]}")
        print()

    # competitors
    section("Competitors Mentioned")
    with_competitor = [r for r in intel if r.get("competitor")]
    print(f"  Calls with competitor mentioned: {len(with_competitor)} / {total_intel} ({pct(len(with_competitor), total_intel)})")
    all_competitors: list[str] = []
    for r in with_competitor:
        comps = [c.strip() for c in (r.get("competitor") or "").split(",")]
        all_competitors.extend(comps)
    comp_counts = Counter(all_competitors)
    print(f"\n  Competitor frequency:")
    for comp, count in comp_counts.most_common():
        print(f"    {comp:<30}: {count}")

    # key quotes
    section("Key Quotes (Good Selling Moments)")
    with_quote = [r for r in intel if r.get("key_quote")]
    good_selling = [
        r for r in with_quote
        if r.get("category") in POSITIVE_CATEGORIES
        or (r.get("interest_level") or "none") in ("high", "medium")
    ]
    bad_handling = [
        r for r in with_quote
        if (r.get("interest_level") or "none") == "none"
        and r.get("category") == "Not Interested"
    ]

    print(f"  Total calls with key quotes : {len(with_quote)}")
    print(f"  Positive context quotes     : {len(good_selling)}")
    print(f"  Negative/flat outcomes      : {len(bad_handling)}")
    print()
    print(f"  Standout positive quotes:")
    for r in good_selling[:6]:
        print(f"    [{r['company_name']:<30}] \"{r['key_quote']}\"")
    print()
    print(f"  Telling quotes from rejections:")
    for r in bad_handling[:5]:
        print(f"    [{r['company_name']:<30}] \"{r['key_quote']}\"")

    # qualified rate
    section("Qualified Prospects")
    qualified = [r for r in intel if r.get("qualified") is True]
    not_qualified = [r for r in intel if r.get("qualified") is False]
    print(f"  Qualified     : {len(qualified)} / {total_intel} ({pct(len(qualified), total_intel)})")
    print(f"  Not qualified : {len(not_qualified)} / {total_intel} ({pct(len(not_qualified), total_intel)})")


# ── 7. Voicemail quality ──────────────────────────────────────────────────────

def section_voicemail_quality(calls: list[dict]) -> None:
    divider("7. VOICEMAIL QUALITY")

    vms = [c for c in calls if c["category"] == "Left Voicemail" and c.get("summary")]

    generic_phrases = [
        "unreliable portals",
        "unreliable ETAs",
        "demurrage charges",
        "damage charges",
        "unchallengeable",
        "too many portals",
        "visibility issues",
        "chemical shippers",
        "eta wage charges",
    ]

    generic_vm: list[dict] = []
    personalized_vm: list[dict] = []

    for c in vms:
        summary_lower = c["summary"].lower()
        hits = sum(1 for phrase in generic_phrases if phrase in summary_lower)
        if hits >= 2:
            generic_vm.append(c)
        else:
            personalized_vm.append(c)

    total_vms = [c for c in calls if c["category"] == "Left Voicemail"]
    print(f"  Total voicemails logged    : {len(total_vms)}")
    print(f"  VMs with transcribed summary: {len(vms)}")
    print(f"  Appears generic (templated): {len(generic_vm)}  ({pct(len(generic_vm), len(vms))} of summarized)")
    print(f"  Appears personalized       : {len(personalized_vm)}  ({pct(len(personalized_vm), len(vms))} of summarized)")

    section("Sample Voicemail Summaries")
    print("  [GENERIC TEMPLATE EXAMPLES]")
    for c in generic_vm[:3]:
        lines = [ln.strip() for ln in c["summary"].split("\n") if ln.strip() and not ln.startswith("#")]
        first_line = lines[0] if lines else ""
        print(f"    {c['company_name']} ({c['contact_name']}): {first_line[:120]}")

    print()
    print("  [MORE PERSONALIZED EXAMPLES]")
    for c in personalized_vm[:3]:
        lines = [ln.strip() for ln in c["summary"].split("\n") if ln.strip() and not ln.startswith("#")]
        first_line = lines[0] if lines else ""
        print(f"    {c['company_name']} ({c['contact_name']}): {first_line[:120]}")


# ── 8. Weekly trends ──────────────────────────────────────────────────────────

def section_weekly_trends(calls: list[dict], intel: list[dict]) -> None:
    divider("8. WEEKLY TRENDS")

    # group by week_num
    weeks: dict[int, list[dict]] = defaultdict(list)
    for c in calls:
        weeks[c["week_num"]].append(c)

    intel_by_call_id: dict[str, dict] = {r["call_id"]: r for r in intel}

    print(f"  {'Wk':>3}  {'Date Range':<22}  {'Calls':>5}  {'Contact%':>8}  "
          f"{'Positive%':>9}  {'Meetings':>8}  {'Referrals':>9}  {'Avg Interest':<12}")
    print(f"  {'--':>3}  {'-'*22}  {'-----':>5}  {'--------':>8}  "
          f"{'--------':>9}  {'--------':>8}  {'---------':>9}  {'------------':<12}")

    for w in sorted(weeks):
        wk_calls = weeks[w]
        wk_dates = sorted(ts(c) for c in wk_calls)
        date_range = f"{wk_dates[0].date()} - {wk_dates[-1].date()}" if wk_dates else ""
        total = len(wk_calls)
        live = sum(1 for c in wk_calls if c["category"] in LIVE_CATEGORIES)
        positive = sum(1 for c in wk_calls if c["category"] in POSITIVE_CATEGORIES)
        meetings = sum(1 for c in wk_calls if c["category"] == "Meeting Booked")
        referrals = sum(1 for c in wk_calls if c["category"] == "Referral Given")

        # interest from intel for this week
        interest_vals = {"high": 3, "medium": 2, "low": 1, "none": 0}
        wk_intel = [intel_by_call_id[c["id"]] for c in wk_calls if c["id"] in intel_by_call_id]
        if wk_intel:
            avg_interest = mean(interest_vals.get(r.get("interest_level") or "none", 0) for r in wk_intel)
            interest_str = f"{avg_interest:.2f}/3.00"
        else:
            interest_str = "no intel"

        contact_pct = f"{100 * live / total:.0f}%" if total else "—"
        pos_pct = f"{100 * positive / live:.0f}%" if live else "—"

        print(f"  {w:>3}  {date_range:<22}  {total:>5}  {contact_pct:>8}  "
              f"{pos_pct:>9}  {meetings:>8}  {referrals:>9}  {interest_str:<12}")

    # trend commentary
    section("Trend Interpretation")
    wk_list = sorted(weeks.keys())
    first_half = wk_list[:len(wk_list) // 2]
    second_half = wk_list[len(wk_list) // 2:]

    def contact_rate(wk_keys: list[int]) -> float:
        total = sum(len(weeks[w]) for w in wk_keys)
        live = sum(
            1 for w in wk_keys for c in weeks[w]
            if c["category"] in LIVE_CATEGORIES
        )
        return live / total if total else 0

    def meeting_rate(wk_keys: list[int]) -> float:
        total = sum(len(weeks[w]) for w in wk_keys)
        mtg = sum(
            1 for w in wk_keys for c in weeks[w]
            if c["category"] == "Meeting Booked"
        )
        return mtg / total if total else 0

    cr_first = contact_rate(first_half)
    cr_second = contact_rate(second_half)
    mr_first = meeting_rate(first_half)
    mr_second = meeting_rate(second_half)

    cr_trend = "IMPROVING" if cr_second > cr_first else "DECLINING"
    mr_trend = "IMPROVING" if mr_second > mr_first else "DECLINING"

    print(f"  Contact rate first half    : {100 * cr_first:.1f}%")
    print(f"  Contact rate second half   : {100 * cr_second:.1f}%  -> {cr_trend}")
    print(f"  Meeting rate first half    : {100 * mr_first:.2f}%")
    print(f"  Meeting rate second half   : {100 * mr_second:.2f}%  -> {mr_trend}")


# ── 9. Top companies by engagement ───────────────────────────────────────────

def section_top_companies(calls: list[dict], intel: list[dict]) -> None:
    divider("9. TOP COMPANIES BY ENGAGEMENT")

    intel_by_call_id = {r["call_id"]: r for r in intel}

    company_data: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "total": 0,
        "live": 0,
        "meetings": 0,
        "referrals": 0,
        "interested": 0,
        "max_interest": "none",
        "key_quotes": [],
        "contacts_reached": set(),
    })

    interest_rank = {"high": 3, "medium": 2, "low": 1, "none": 0}

    for c in calls:
        co = c["company_name"]
        d = company_data[co]
        d["total"] += 1
        if c["category"] in LIVE_CATEGORIES:
            d["live"] += 1
            d["contacts_reached"].add(c["contact_name"])
        if c["category"] == "Meeting Booked":
            d["meetings"] += 1
        if c["category"] == "Referral Given":
            d["referrals"] += 1
        if c["category"] == "Interested":
            d["interested"] += 1
        # pull intel
        r = intel_by_call_id.get(c["id"])
        if r:
            lvl = r.get("interest_level") or "none"
            if interest_rank.get(lvl, 0) > interest_rank.get(d["max_interest"], 0):
                d["max_interest"] = lvl
            if r.get("key_quote"):
                d["key_quotes"].append(r["key_quote"])

    # score companies: weighted sum
    def score(d: dict) -> float:
        return (
            d["meetings"] * 10
            + d["interested"] * 4
            + d["referrals"] * 3
            + d["live"] * 1
            + interest_rank.get(d["max_interest"], 0) * 2
        )

    ranked = sorted(company_data.items(), key=lambda x: score(x[1]), reverse=True)[:15]

    print(f"  (scoring: Meeting=10pts, Interested=4pts, Referral=3pts, Live=1pt, Interest level=2pts)")
    print()
    print(f"  {'Company':<35}  {'Score':>5}  {'Calls':>5}  {'Live':>5}  "
          f"{'Mtg':>4}  {'Int':>4}  {'Ref':>4}  {'MaxInterest':<12}")
    print(f"  {'-'*35}  {'-----':>5}  {'-----':>5}  {'-----':>5}  "
          f"{'---':>4}  {'---':>4}  {'---':>4}  {'------------':<12}")

    for co, d in ranked:
        s = score(d)
        print(
            f"  {co:<35}  {s:>5.0f}  {d['total']:>5}  {d['live']:>5}  "
            f"{d['meetings']:>4}  {d['interested']:>4}  {d['referrals']:>4}  {d['max_interest']:<12}"
        )
        if d["key_quotes"]:
            print(f"       Quote: \"{d['key_quotes'][0][:80]}\"")

    section("Companies With Meetings Booked")
    mtg_companies = [(co, d) for co, d in company_data.items() if d["meetings"] > 0]
    for co, d in sorted(mtg_companies, key=lambda x: x[1]["meetings"], reverse=True):
        contacts = ", ".join(d["contacts_reached"])
        print(f"  {co:<35} ({d['meetings']} meeting(s)) — contacts: {contacts}")


# ── 10. Critique ──────────────────────────────────────────────────────────────

def section_critique(calls: list[dict], intel: list[dict], cat_counts: dict[str, int]) -> None:
    divider("10. HONEST PERFORMANCE CRITIQUE")

    total = len(calls)
    live = sum(cat_counts.get(c, 0) for c in LIVE_CATEGORIES)
    meetings = cat_counts.get("Meeting Booked", 0)
    referrals = cat_counts.get("Referral Given", 0)
    voicemails = cat_counts.get("Left Voicemail", 0)

    # escalations to Nico
    escalated_count = sum(
        1 for r in intel
        if any(v in (r.get("next_action") or "").lower()
               for v in ["check with nico", "consult with nico", "nicolas amoretti",
                         "confirm with nico", "get guidance from nico", "nico to"])
    )

    interest_counts: Counter = Counter(r.get("interest_level") or "none" for r in intel)
    high_interest = interest_counts.get("high", 0)
    medium_interest = interest_counts.get("medium", 0)

    print("""
STRENGTHS
---------""")
    print(f"""
  1. VOLUME & CONSISTENCY
     Adam is logging {total:,} calls over ~{(max(ts(c) for c in calls) - min(ts(c) for c in calls)).days} days — that is strong output.
     Averaging {total / ((max(ts(c) for c in calls) - min(ts(c) for c in calls)).days / 7):.0f} calls per week shows he is dialing consistently
     and not cherry-picking easy days.

  2. REFERRAL EXTRACTION
     {referrals} calls resulted in referrals ({pct(referrals, live)} of live conversations).
     He is asking the right question — "who should I talk to?" — and getting
     actionable names with phone numbers in many cases. This is a real skill.

  3. MEETINGS BOOKED
     {meetings} meetings booked from {total:,} dials = {pct(meetings, total)} overall meeting rate.
     In outbound cold calling, anything above 0.5% is considered good.
     He is hitting {pct(meetings, live)} of live conversations — solid.

  4. INTEL CAPTURE
     {len(intel)} calls have structured intel extracted. He is writing notes that are
     substantive enough to produce qualified competitor, objection, and commodity data.
     Key quotes suggest he is listening and paraphrasing prospects accurately.

  5. NAVIGATING GATEKEEPERS
     He converts gatekeeper conversations into referral chains rather than hanging up.
     Examples like GROWMARK, Advansix, Sherwin-Williams show persistence in working
     through the org.
""")

    print("""
WEAKNESSES & AREAS FOR IMPROVEMENT
------------------------------------""")
    print(f"""
  1. CONTACT RATE IS LOW
     Only {pct(live, total)} of calls reach a live person. The remaining
     {pct(cat_counts.get('No Answer',0) + voicemails, total)} are dead ends (no answer or voicemail).
     Benchmark for skilled SDRs is 15-25% contact rate. Adam is at ~{100*live/total:.0f}%.
     This may partly reflect list quality, but call timing and strategy can improve it.
     RECOMMENDATION: Test different call windows (early morning / after 4 PM).
     Analyze which hour_pt values convert best and concentrate dials there.

  2. VOICEMAIL STRATEGY IS GENERIC
     Analysis of VM summaries shows a highly templated script: "unreliable portals,"
     "unchallengeable damage charges," "chemical shippers" repeated across nearly all
     voicemails regardless of industry vertical or company context.
     Generic voicemails rarely get callbacks — they signal mass-dialing, not research.
     RECOMMENDATION: Develop 3-4 industry-specific VM scripts (chemicals, grain/ag,
     industrial materials, automotive). Reference the company's actual rail footprint
     or a known pain from their industry when possible.

  3. HIGH ESCALATION TO MANAGER
     {escalated_count} of {len(intel)} intel records ({pct(escalated_count, len(intel))}) have next actions like
     "check with Nico" or "get guidance from Nico." This means Adam is repeatedly
     hitting situations he cannot navigate independently. While escalation is
     appropriate for complex deals, doing it on 1 in 4-5 calls signals gaps in:
       - Knowing when a prospect is qualified vs. not
       - Knowing what to do with edge cases (inbound-only rail, brokerage scenarios)
       - Deal qualification confidence
     RECOMMENDATION: Build a simple decision tree with Nico: "If X, do Y."
     Adam should be able to self-classify 80% of scenarios without escalation.

  4. INTEREST LEVEL IS MOSTLY LOW
     Of {len(intel)} calls with intel:
       High interest    : {high_interest}  ({pct(high_interest, len(intel))})
       Medium interest  : {medium_interest}  ({pct(medium_interest, len(intel))})
       Low/none         : {interest_counts.get('low',0) + interest_counts.get('none',0)}  ({pct(interest_counts.get('low',0) + interest_counts.get('none',0), len(intel))})
     Only {high_interest} "high interest" conversations in the entire dataset is a red flag.
     It could mean:
       a) His pitch is not creating genuine urgency
       b) He is categorizing conservatively (unlikely to distort a call)
       c) The list has too many unqualified targets (no-rail companies appear frequently)
     RECOMMENDATION: Audit list quality. {pct(cat_counts.get('No Rail',0), total)} of all calls
     hit "No Rail" companies — these should be filtered before dialing.

  5. OBJECTION HANDLING IS PASSIVE
     On calls where prospects say "we're happy with our current system" (most common
     objection), the notes and intel show Adam accepts the objection and moves on
     rather than probing underneath it.
     Key example — Colonial Group: "Right now just no interest or need. She says
     budget, but there's something deeper." Adam noticed the gap but did not dig in.
     RECOMMENDATION: Train a single objection-handling framework:
       "That's great to hear — can I ask, what does your team do when [specific pain
       — e.g., a car goes missing in transit] happens?" Force them to articulate
       their workaround, which surfaces latent pain.

  6. WRONG PERSON / STALE DATA RATE IS HIGH
     {cat_counts.get('Wrong Person',0)} calls ({pct(cat_counts.get('Wrong Person',0), total)}) hit the wrong person,
     and many of these are contacts who have left the company ("no longer works there,"
     "retired," "chapter 11"). This is a list hygiene problem.
     RECOMMENDATION: Before dialing, spend 30 seconds on LinkedIn to verify the
     contact is still at the company. A pre-dial scrub of 5-10 calls in the morning
     would cut bad-data calls significantly.

  7. DUPLICATE OUTREACH TO SAME COMPANIES
     GROWMARK, Evonik, AmSty, Oil-Dri, Sherwin-Williams, MKC, Chemtrade, Advansix,
     and others appear multiple times across weeks without clear progression.
     The call on GROWMARK FS is flagged with: "We just talked about 10 minutes ago."
     This is a CRM data hygiene issue that wastes dials and risks burning relationships.
     RECOMMENDATION: Before dialing any company, check if another contact at
     the same company was dialed in the past 48 hours.

  8. MEETING FOLLOW-THROUGH UNKNOWN
     4 meetings were booked — AmSty (Feb 10), MKC (Feb 11), Richardson International
     (March), West Central Cooperative (Feb 18). There is no call-back data in this
     dataset showing what happened after these meetings. Are they being worked?
     Are they stalling? RECOMMENDATION: Create a "post-meeting" tracking category.
""")

    section("SUMMARY SCORECARD")
    print(f"""
  Volume             : {'STRONG':>10}  {total} total calls, ~{total/((max(ts(c) for c in calls)-min(ts(c) for c in calls)).days/7):.0f}/week
  Contact Rate       : {'BELOW PAR':>10}  {pct(live, total)} vs. 15-25% benchmark
  Meeting Conversion : {'ON TRACK':>10}  {meetings} meetings from {total} dials ({pct(meetings, total)})
  Referral Skill     : {'STRENGTH':>10}  {referrals} referrals, many with phone numbers
  Voicemail Quality  : {'WEAK':>10}  Templated script, minimal personalization
  Objection Handling : {'DEVELOPING':>10}  Notices gaps but does not probe
  List Quality       : {'NEEDS WORK':>10}  Too many wrong-person / no-rail calls
  Intel / Notes      : {'SOLID':>10}  Substantive enough for AI extraction
  Manager Dependency : {'TOO HIGH':>10}  {pct(escalated_count, len(intel))} of calls escalated to Nico
  Trend Direction    : {'WATCH':>10}  Analyze second-half contact rate vs. first
""")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    calls, intel = load()

    divider("ADAM JACKSON — COLD CALLING PERFORMANCE AUDIT", 70)
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Data through: {max(ts(c) for c in calls).date()}")
    print(f"  Call dataset: {len(calls)} calls | Intel dataset: {len(intel)} structured records")
    divider()

    section_overall(calls)
    cat_counts = section_categories(calls)
    section_contact_rate(calls, cat_counts)
    section_conversion(calls, cat_counts)
    section_duration(calls)
    section_intel(intel)
    section_voicemail_quality(calls)
    section_weekly_trends(calls, intel)
    section_top_companies(calls, intel)
    section_critique(calls, intel, cat_counts)

    divider()
    print("  END OF AUDIT")
    divider()


if __name__ == "__main__":
    main()
