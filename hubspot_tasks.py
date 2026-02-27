"""
hubspot_tasks.py — HubSpot task management for call sheet + queue monitor.

Functions:
  - fetch_open_tasks()         — dashboard monitor (existing)
  - search_call_sheet_tasks()  — find stale [Call Sheet ...] tasks
  - complete_tasks()           — batch-mark tasks as COMPLETED
  - create_call_tasks()        — batch-create today's call sheet tasks
"""

import os
import time
from datetime import datetime, date, timezone
from typing import Dict, List, Optional

import requests

HUBSPOT_API_BASE = "https://api.hubapi.com"
ADAM_OWNER_ID = "87407439"
CALL_SHEET_PREFIX = "[Call Sheet"


def fetch_open_tasks(token: str, owner_id: str = ADAM_OWNER_ID) -> Dict:
    """Fetch all open tasks assigned to owner_id and return summary stats."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    all_tasks: List[Dict] = []
    after = None

    while True:
        payload = {
            "filterGroups": [{
                "filters": [
                    {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": owner_id},
                    {"propertyName": "hs_task_status", "operator": "NEQ", "value": "COMPLETED"},
                ]
            }],
            "properties": [
                "hs_task_subject", "hs_task_status", "hs_timestamp",
                "hs_task_priority", "hs_task_type",
            ],
            "limit": 100,
        }
        if after:
            payload["after"] = after

        resp = requests.post(
            f"{HUBSPOT_API_BASE}/crm/v3/objects/tasks/search",
            json=payload, headers=headers, timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        all_tasks.extend(results)

        paging = data.get("paging")
        if not paging or "next" not in paging:
            break
        after = paging["next"]["after"]

    return _summarize_tasks(all_tasks)


def _summarize_tasks(tasks: List[Dict]) -> Dict:
    """Build summary from raw task list, excluding auto-generated follow-ups."""
    # Filter out HubSpot auto-generated follow-up tasks
    tasks = [t for t in tasks
             if "follow up" not in (t.get("properties", {}).get("hs_task_subject") or "").lower()]

    by_priority = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "NONE": 0}
    oldest_ts: Optional[datetime] = None
    task_list = []

    for task in tasks:
        props = task.get("properties", {})
        priority = (props.get("hs_task_priority") or "NONE").upper()
        if priority not in by_priority:
            priority = "NONE"
        by_priority[priority] += 1

        # Track oldest task
        ts_str = props.get("hs_timestamp")
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if oldest_ts is None or ts < oldest_ts:
                    oldest_ts = ts
            except (ValueError, TypeError):
                pass

        task_list.append({
            "subject": props.get("hs_task_subject", "Untitled"),
            "priority": priority,
            "status": props.get("hs_task_status", ""),
        })

    total = len(tasks)
    oldest_days = 0
    if oldest_ts:
        oldest_days = max(0, (datetime.now(timezone.utc) - oldest_ts).days)

    # Alert: green >50, yellow 20-50, red <20
    if total > 50:
        alert_level = "ok"
    elif total >= 20:
        alert_level = "warning"
    else:
        alert_level = "critical"

    display_priority = {k: v for k, v in by_priority.items() if v > 0}

    return {
        "total_open": total,
        "by_priority": display_priority,
        "alert_level": alert_level,
        "oldest_task_days": oldest_days,
        "tasks": sorted(task_list, key=lambda t: {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "NONE": 3}.get(t["priority"], 3)),
    }


# ---------------------------------------------------------------------------
# Call sheet task management
# ---------------------------------------------------------------------------

def search_call_sheet_tasks(
    token: str, owner_id: str = ADAM_OWNER_ID,
) -> Dict[str, List[Dict]]:
    """Find NOT_STARTED [Call Sheet ...] tasks, split into stale vs today.

    Returns {"stale": [...], "today": [...]}.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    today_prefix = f"{CALL_SHEET_PREFIX} {date.today().isoformat()}]"
    stale: List[Dict] = []
    today: List[Dict] = []
    after = None

    while True:
        payload = {
            "filterGroups": [{
                "filters": [
                    {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": owner_id},
                    {"propertyName": "hs_task_status", "operator": "EQ", "value": "NOT_STARTED"},
                    {"propertyName": "hs_task_type", "operator": "EQ", "value": "CALL"},
                ]
            }],
            "properties": ["hs_task_subject", "hs_task_status"],
            "limit": 100,
        }
        if after:
            payload["after"] = after

        resp = requests.post(
            f"{HUBSPOT_API_BASE}/crm/v3/objects/tasks/search",
            json=payload, headers=headers, timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])

        for t in results:
            subject = t.get("properties", {}).get("hs_task_subject", "")
            if not subject.startswith(CALL_SHEET_PREFIX):
                continue
            if subject.startswith(today_prefix):
                today.append(t)
            else:
                stale.append(t)

        paging = data.get("paging")
        if not paging or "next" not in paging:
            break
        after = paging["next"]["after"]

    return {"stale": stale, "today": today}


def complete_tasks(token: str, task_ids: List[str]) -> int:
    """Batch-mark tasks as COMPLETED. Returns count of successfully completed."""
    if not task_ids:
        return 0

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    completed = 0
    # HubSpot batch update: max 100 per request
    for i in range(0, len(task_ids), 100):
        batch = task_ids[i:i + 100]
        payload = {
            "inputs": [
                {"id": tid, "properties": {"hs_task_status": "COMPLETED"}}
                for tid in batch
            ]
        }
        try:
            resp = requests.post(
                f"{HUBSPOT_API_BASE}/crm/v3/objects/tasks/batch/update",
                json=payload, headers=headers, timeout=30,
            )
            resp.raise_for_status()
            completed += len(batch)
        except requests.RequestException as e:
            print(f"  Warning: batch complete failed (batch {i//100}): {e}")

    return completed


def create_call_tasks(
    token: str,
    tasks: List[Dict],
    owner_id: str = ADAM_OWNER_ID,
) -> int:
    """Batch-create HubSpot tasks for today's call sheet.

    Each task dict should have:
        name, company, attempt, priority, hubspot_contact_id, hubspot_company_id

    Returns count of tasks created.
    """
    if not tasks:
        return 0

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    today_str = date.today().isoformat()
    created = 0

    # HubSpot batch create: max 100 per request
    for i in range(0, len(tasks), 100):
        batch = tasks[i:i + 100]
        inputs = []

        for t in batch:
            attempt = t.get("attempt", 1)
            suffix = f" (Attempt {attempt})" if attempt > 1 else ""
            subject = f"[Call Sheet {today_str}] Call {t['name']} @ {t['company']}{suffix}"

            # Map priority string to HubSpot enum
            priority = t.get("priority", "LOW")

            inputs.append({
                "properties": {
                    "hs_task_subject": subject,
                    "hubspot_owner_id": owner_id,
                    "hs_task_status": "NOT_STARTED",
                    "hs_task_priority": priority,
                    "hs_task_type": "CALL",
                    "hs_timestamp": datetime.now(timezone.utc).isoformat(),
                },
            })

        payload = {"inputs": inputs}
        try:
            resp = requests.post(
                f"{HUBSPOT_API_BASE}/crm/v3/objects/tasks/batch/create",
                json=payload, headers=headers, timeout=30,
            )
            resp.raise_for_status()
            result_ids = [r["id"] for r in resp.json().get("results", [])]
            if len(result_ids) != len(batch):
                print(f"  Warning: created {len(result_ids)}/{len(batch)} tasks in batch {i//100}")
            created += len(result_ids)

            # Associate tasks with contacts + companies
            _associate_tasks(token, batch[:len(result_ids)], result_ids)

        except requests.RequestException as e:
            print(f"  Warning: batch create failed (batch {i//100}): {e}")

    return created


def _associate_tasks(
    token: str,
    task_defs: List[Dict],
    task_ids: List[str],
) -> None:
    """Associate newly created tasks with HubSpot contacts and companies."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    contact_assocs = []
    company_assocs = []

    for task_def, task_id in zip(task_defs, task_ids):
        cid = task_def.get("hubspot_contact_id")
        if cid:
            contact_assocs.append({
                "from": {"id": task_id},
                "to": {"id": str(cid)},
                "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 204}],
            })
        comp_id = task_def.get("hubspot_company_id")
        if comp_id:
            company_assocs.append({
                "from": {"id": task_id},
                "to": {"id": str(comp_id)},
                "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 192}],
            })

    # Batch associate with contacts
    for i in range(0, len(contact_assocs), 100):
        batch = contact_assocs[i:i + 100]
        try:
            requests.post(
                f"{HUBSPOT_API_BASE}/crm/v4/associations/task/contact/batch/create",
                json={"inputs": batch}, headers=headers, timeout=30,
            ).raise_for_status()
        except requests.RequestException as e:
            print(f"  Warning: task->contact association failed: {e}")

    # Batch associate with companies
    for i in range(0, len(company_assocs), 100):
        batch = company_assocs[i:i + 100]
        try:
            requests.post(
                f"{HUBSPOT_API_BASE}/crm/v4/associations/task/company/batch/create",
                json={"inputs": batch}, headers=headers, timeout=30,
            ).raise_for_status()
        except requests.RequestException as e:
            print(f"  Warning: task->company association failed: {e}")
