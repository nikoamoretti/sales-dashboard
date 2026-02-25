#!/usr/bin/env python3
"""
LinkedIn Sales Navigator InMail Scraper.

Navigates the Sales Nav inbox, opens each InMail conversation, and extracts
recipient info, sent date, and reply text. Saves raw data to inmail_raw.json.

Usage:
    python3 inmail_scraper.py           # scrape headless
    python3 inmail_scraper.py --visible # scrape with visible browser
    python3 inmail_scraper.py --login   # interactive login to save session
    python3 inmail_scraper.py --status  # show count of InMails in raw data
    python3 inmail_scraper.py --debug   # print JS result for first 3 convos
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, Page, BrowserContext

BASE_DIR = Path(__file__).parent
BROWSER_PROFILE_DIR = BASE_DIR / "browser_profile"
RAW_OUTPUT = BASE_DIR / "inmail_raw.json"

SALES_NAV_INBOX = "https://www.linkedin.com/sales/inbox?viewFilter=INMAILS_ONLY"
LOGIN_URL = "https://www.linkedin.com/login"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# JS that extracts the full thread from the detail pane in a single round-trip.
# Returns { title, messages } where each message has datetime, sender, subject,
# body, and fullText fields.
_JS_EXTRACT_THREAD = """
() => {
    const container = document.querySelector('.thread-container');
    if (!container) return null;

    // Profile lockup: title from first li in the thread
    const titleEl = container.querySelector(
        'div._subhead_1mz7um span, [class*="_subhead_"] span'
    );
    const title = titleEl ? titleEl.innerText.trim() : '';

    // Message list: find the ul inside the message-container section
    const section = container.querySelector(
        'section.message-container-align, section[class*="message-container"]'
    );
    const messageUl = section
        ? section.querySelector('ul')
        : container.querySelector('ul');
    if (!messageUl) return { title, messages: [] };

    const lis = messageUl.querySelectorAll(':scope > li');
    const messages = [];

    for (const li of lis) {
        const timeEl   = li.querySelector('time[datetime]');
        const senderEl = li.querySelector('address span[data-anonymize="person-name"]');
        const bodyEl   = li.querySelector(
            'div.message-content p, div[data-x-message-content="message"] p'
        );
        const subjectEl = li.querySelector(
            'div.message-content h3, div[data-x-message-content="message"] h3'
        );

        // Skip lockup li and any structural items that have no sender/body
        if (!senderEl && !bodyEl) continue;

        messages.push({
            datetime:  timeEl     ? timeEl.getAttribute('datetime')  : '',
            sender:    senderEl   ? senderEl.innerText.trim()        : '',
            subject:   subjectEl  ? subjectEl.innerText.trim()       : '',
            body:      bodyEl     ? bodyEl.innerText.trim()          : '',
            fullText:  li.innerText.trim().substring(0, 500),
        });
    }

    return { title, messages };
}
"""


# ---------------------------------------------------------------------------
# Browser setup
# ---------------------------------------------------------------------------

def launch_browser(headless: bool = True) -> tuple:
    """Launch persistent browser context. Returns (playwright, context)."""
    BROWSER_PROFILE_DIR.mkdir(exist_ok=True)
    pw = sync_playwright().start()
    context: BrowserContext = pw.chromium.launch_persistent_context(
        str(BROWSER_PROFILE_DIR),
        headless=headless,
        viewport={"width": 1280, "height": 900},
        user_agent=USER_AGENT,
        args=["--disable-blink-features=AutomationControlled"],
    )
    return pw, context


def is_logged_out(page: Page) -> bool:
    return any(s in page.url for s in ["/login", "/authwall", "/uas/login"])


# ---------------------------------------------------------------------------
# Conversation list scrolling
# ---------------------------------------------------------------------------

def scroll_conversation_list(page: Page) -> list:
    """
    Scroll through the entire inbox list and collect conversation elements.
    Returns a list of element handles for each conversation item.
    """
    print("  Scrolling through conversation list...")

    scroll_js = """
        const el = document.querySelector('.overflow-y-auto.overflow-hidden.flex-grow-1')
            || document.querySelector('[class*="conversations-list"]')
            || document.querySelector('ul[role="list"]');
        if (el) el.scrollTop = el.scrollHeight;
        else window.scrollTo(0, document.body.scrollHeight);
    """

    prev_count = 0
    stall_rounds = 0
    for _ in range(60):  # cap at ~60 scroll attempts
        page.evaluate(scroll_js)
        time.sleep(1.2)

        items = page.query_selector_all("li.conversation-list-item")
        if not items:
            items = page.query_selector_all(
                "li[class*='conversation'], "
                "li[class*='thread-item'], "
                "li[class*='msg-conversation']"
            )

        current_count = len(items)
        if current_count == prev_count:
            stall_rounds += 1
            if stall_rounds >= 4:
                break
        else:
            stall_rounds = 0
        prev_count = current_count

    print(f"  Found {prev_count} conversations in inbox")
    return page.query_selector_all(
        "li.conversation-list-item, "
        "li[class*='conversation'], "
        "li[class*='thread-item']"
    )


# ---------------------------------------------------------------------------
# List-item parsing helpers
# ---------------------------------------------------------------------------

def _parse_list_item(item) -> dict:
    """
    Extract name, preview, and timestamp from a conversation list item using
    the actual Sales Nav selectors.

    Selectors:
      - Name:      .t-16.t-black.t-normal
      - Preview:   .t-14.t-black--light
      - Timestamp: time.conversation-list-item__timestamp
    """
    result = {"name": "", "preview": "", "date_hint": ""}

    try:
        name_el = item.query_selector(".t-16.t-black.t-normal")
        if name_el:
            result["name"] = name_el.inner_text().strip()
    except Exception:
        pass

    try:
        preview_el = item.query_selector(".t-14.t-black--light")
        if preview_el:
            result["preview"] = preview_el.inner_text().strip()
    except Exception:
        pass

    try:
        time_el = item.query_selector("time.conversation-list-item__timestamp")
        if time_el:
            # Prefer the datetime attribute; fall back to visible text
            result["date_hint"] = (
                time_el.get_attribute("datetime")
                or time_el.inner_text().strip()
            )
    except Exception:
        pass

    # Fallback name from raw text first line
    if not result["name"]:
        try:
            raw = item.inner_text().strip()
            lines = [l.strip() for l in raw.splitlines() if l.strip()]
            if lines:
                result["name"] = lines[0]
        except Exception:
            pass

    return result


# ---------------------------------------------------------------------------
# Conversation detail extraction
# ---------------------------------------------------------------------------

def extract_conversation(
    page: Page, item, debug: bool = False, debug_idx: int = 0
) -> Optional[dict]:
    """
    Click a conversation list item and extract InMail details from the thread.

    Direction detection algorithm:
      1. Run _JS_EXTRACT_THREAD via page.evaluate() for a single round-trip.
      2. Treat the first message's sender as my_name (the logged-in user).
      3. Any subsequent message where sender != my_name is an inbound reply.
      4. date_sent = datetime of the first outbound message.
      5. reply_text = concatenation of all inbound message bodies.

    Returns a dict or None on hard failure.
    """
    # --- Get current thread heading so we can detect when it changes ---
    old_heading = ""
    try:
        h2 = page.query_selector(".thread-container h2")
        if h2:
            old_heading = h2.inner_text().strip()
    except Exception:
        pass

    # --- Click to open the conversation ---
    try:
        item.scroll_into_view_if_needed()
        item.click()
    except Exception as e:
        print(f"    WARN: Could not click item: {e}")
        return None

    # Wait for the thread content to change (heading updates to new recipient)
    for _ in range(15):
        try:
            h2 = page.query_selector(".thread-container h2")
            if h2:
                new_heading = h2.inner_text().strip()
                if new_heading and new_heading != old_heading:
                    time.sleep(0.5)  # let messages render
                    break
        except Exception:
            pass
        time.sleep(0.3)
    else:
        # Fallback: just wait
        page.wait_for_timeout(2500)

    # --- Parse list item for fallback name / date ---
    li_parsed = _parse_list_item(item)

    # --- Extract thread via JS (single round-trip) ---
    try:
        thread = page.evaluate(_JS_EXTRACT_THREAD)
    except Exception as e:
        print(f"    WARN: JS thread extraction failed: {e}")
        thread = None

    # --- Debug output (first 3 conversations only) ---
    if debug and debug_idx < 3:
        print(f"\n  === DEBUG: conversation #{debug_idx + 1} ===")
        print(f"  [LIST ITEM PARSED] {li_parsed}")
        print(f"  [JS THREAD RESULT] {json.dumps(thread, indent=2)}")
        print()

    # --- Build the output record ---
    recipient_name = li_parsed["name"]
    recipient_title = ""
    company = ""  # not available in inbox view
    date_sent = ""
    replied = False
    reply_texts: list[str] = []
    my_name = ""

    if thread:
        # Title from the profile lockup in the thread pane
        if thread.get("title"):
            recipient_title = thread["title"]

        messages: list[dict] = thread.get("messages") or []

        # Determine my_name from the first message (always outbound)
        if messages and messages[0].get("sender"):
            my_name = messages[0]["sender"]

        for idx, msg in enumerate(messages):
            sender = msg.get("sender", "").strip()
            body = msg.get("body", "").strip()
            dt = msg.get("datetime", "").strip()

            # Determine direction: first message or sender matches me = outbound
            is_outbound = (idx == 0) or (bool(my_name) and sender == my_name)

            if is_outbound:
                # Capture date_sent from the first outbound message
                if not date_sent and dt:
                    date_sent = dt
            else:
                # Inbound reply
                if body:
                    replied = True
                    reply_texts.append(body)

    # Fallback date from the list item timestamp
    if not date_sent and li_parsed["date_hint"]:
        date_sent = li_parsed["date_hint"]

    return {
        "recipient_name": recipient_name,
        "recipient_title": recipient_title,
        "company": company,
        "date_sent": date_sent,
        "replied": replied,
        "reply_text": "\n\n".join(reply_texts),
    }


# ---------------------------------------------------------------------------
# Main scrape flow
# ---------------------------------------------------------------------------

def scrape(headless: bool = True, debug: bool = False) -> list:
    """Scrape all InMail conversations and return list of raw records."""
    pw, context = launch_browser(headless)
    page = context.new_page()

    try:
        print(f"\nNavigating to Sales Navigator inbox...")
        page.goto(SALES_NAV_INBOX, wait_until="domcontentloaded")
        time.sleep(3)

        if is_logged_out(page):
            print("ERROR: Not logged in. Run with --login to set up your session.")
            context.close()
            pw.stop()
            return []

        print(f"  Loaded: {page.url}")

        # Scroll to load all conversations
        items = scroll_conversation_list(page)
        total = len(items)
        print(f"\nProcessing {total} conversations...")

        results = []
        for idx in range(total):
            # Re-query each iteration: DOM may mutate after clicks
            current_items = page.query_selector_all(
                "li.conversation-list-item, "
                "li[class*='conversation'], "
                "li[class*='thread-item']"
            )
            if idx >= len(current_items):
                print(
                    f"  [{idx + 1}/{total}] WARN: item index out of range "
                    "after re-query; stopping"
                )
                break

            item = current_items[idx]
            try:
                record = extract_conversation(
                    page, item, debug=debug, debug_idx=idx
                )
                if record:
                    results.append(record)
                    status = "replied" if record["replied"] else "no reply"
                    name = record["recipient_name"] or f"#{idx + 1}"
                    print(f"  [{idx + 1}/{total}] {name} — {status}")
            except Exception as e:
                print(f"  [{idx + 1}/{total}] ERROR: {e}")

            # Small delay between conversations to avoid rate-limiting
            time.sleep(1.0)

    finally:
        context.close()
        pw.stop()

    # Save raw output
    with open(RAW_OUTPUT, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nSaved {len(results)} records to {RAW_OUTPUT}")

    return results


# ---------------------------------------------------------------------------
# Login mode
# ---------------------------------------------------------------------------

def login_interactive(timeout_seconds: int = 300) -> None:
    """Open a visible browser so the user can log in manually. Session is saved."""
    print("Opening browser for manual login...")
    print(f"Log in to LinkedIn Sales Navigator. You have {timeout_seconds} seconds.")
    print("The browser will stay open until you're logged in or time runs out.\n")
    pw, context = launch_browser(headless=False)
    page = context.new_page()
    page.goto(LOGIN_URL)

    deadline = time.time() + timeout_seconds
    logged_in = False
    while time.time() < deadline:
        try:
            url = page.url
            if "/login" not in url and "/authwall" not in url and "linkedin.com" in url:
                logged_in = True
                print("Login detected! Saving session...")
                time.sleep(3)  # let cookies settle
                break
        except Exception:
            pass
        time.sleep(2)

    context.close()
    pw.stop()
    if logged_in:
        print(f"Session saved to {BROWSER_PROFILE_DIR}")
    else:
        print("Timed out waiting for login. Try again with --login")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="LinkedIn Sales Navigator InMail Scraper")
    parser.add_argument("--visible", action="store_true", help="Run browser visibly")
    parser.add_argument("--login",   action="store_true", help="Interactive login mode")
    parser.add_argument("--status",  action="store_true", help="Show raw data counts")
    parser.add_argument(
        "--debug",
        action="store_true",
        help=(
            "Print the JS thread extraction result for the first 3 conversations "
            "to diagnose selector issues"
        ),
    )
    args = parser.parse_args()

    if args.status:
        if RAW_OUTPUT.exists():
            data = json.loads(RAW_OUTPUT.read_text())
            replied = sum(1 for r in data if r.get("replied"))
            print(f"inmail_raw.json: {len(data)} InMails, {replied} with replies")
        else:
            print("inmail_raw.json does not exist. Run a scrape first.")
        return 0

    if args.login:
        login_interactive()
        return 0

    scrape(headless=not args.visible, debug=args.debug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
