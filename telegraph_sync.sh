#!/bin/bash
# telegraph_sync.sh — Single orchestrator for all Telegraph sales automation.
#
# Runs via com.telegraph-sync.plist every 10 minutes. Script self-guards to
# Mon-Fri 5 AM – 5 PM PT. Outside that window it exits silently.
#
# Every run:   sync_hubspot → sync_apollo → sync_linkedin → sync_deals → dashboard_v2 → git push
# 5 AM only:   + call_sheet (Adam has 50 HubSpot tasks by 8 AM EST)
# 5 PM only:   + inmail scrape/sync + enrich + advisor + daily Slack + digest DM + health check

set -u

cd "$(dirname "$0")"

# ── Business-hours guard (Mon-Fri 5 AM – 5 PM PT) ─────────────────────────
DOW=$(date +%u)   # 1=Mon … 7=Sun
NOW_H=$(date +%H) # 00-23
# Allow override for testing: FORCE=1 ./telegraph_sync.sh
if [ "${FORCE:-0}" != "1" ]; then
    if [ "$DOW" -gt 5 ]; then exit 0; fi        # weekend
    if [ "$NOW_H" -lt 5 ] || [ "$NOW_H" -gt 17 ]; then exit 0; fi  # outside 5AM-5PM
fi

# Load all credentials from .env (symlink to ~/.env.telegraph)
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# Override: HOUR=05 ./telegraph_sync.sh (must be zero-padded)
HOUR=${HOUR:-$(date +%H)}
LOG="logs/telegraph_sync.log"
mkdir -p logs

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

log "=== Telegraph Sync (hour=$HOUR) ==="

# ── Always: sync + dashboard ──────────────────────────────────────────────

log "Syncing HubSpot..."
python3 sync_hubspot.py --skip-intel >> "$LOG" 2>&1 || log "WARN: sync_hubspot failed"

log "Syncing Apollo..."
python3 sync_apollo.py >> "$LOG" 2>&1 || log "WARN: sync_apollo failed"

log "Syncing LinkedIn..."
python3 sync_linkedin.py >> "$LOG" 2>&1 || log "WARN: sync_linkedin failed"

log "Syncing deals..."
python3 sync_deals.py >> "$LOG" 2>&1 || log "WARN: sync_deals failed"

log "Generating dashboard..."
python3 dashboard_v2.py >> "$LOG" 2>&1 || log "WARN: dashboard_v2 failed"

# Push if index.html changed
if ! git diff --quiet index.html 2>/dev/null; then
    git add index.html
    git commit -m "chore: update dashboard $(date +%Y-%m-%d-%H%M)" >> "$LOG" 2>&1
    git push >> "$LOG" 2>&1 || log "WARN: git push failed"
    log "Dashboard pushed"
fi

# ── 5 AM: Morning call sheet ─────────────────────────────────────────────

if [ "$HOUR" = "05" ]; then
    log "Creating call sheet for Adam..."
    python3 call_sheet.py >> "$LOG" 2>&1 || log "ERROR: call_sheet failed"
fi

# ── 5 PM: Evening extras ─────────────────────────────────────────────────

if [ "$HOUR" = "17" ]; then
    log "Running InMail scrape + Supabase sync..."
    python3 inmail_pipeline.py --scrape >> "$LOG" 2>&1 || log "WARN: inmail scrape failed (session expired?)"

    log "Enriching companies..."
    python3 enrich_companies.py >> "$LOG" 2>&1 || log "WARN: enrich_companies failed"

    log "Running AI advisor..."
    python3 advisor.py --clear-today >> "$LOG" 2>&1 || log "WARN: advisor failed"

    # Final dashboard regen with enriched data + advisor insights
    log "Regenerating dashboard with enriched data..."
    python3 dashboard_v2.py >> "$LOG" 2>&1 || log "WARN: dashboard regen failed"
    git add index.html
    git diff --staged --quiet || git commit -m "chore: update dashboard $(date +%Y-%m-%d-%H%M)" >> "$LOG" 2>&1
    git push >> "$LOG" 2>&1 || true

    log "Posting daily Slack report..."
    python3 daily_slack_report.py >> "$LOG" 2>&1 || log "WARN: daily_slack_report failed"

    log "Sending daily digest DM..."
    python3 "$HOME/nico_repo/automation/daily-digest/main.py" >> "$LOG" 2>&1 || log "WARN: daily-digest failed"

    log "Running pipeline health check..."
    python3 pipeline_health.py >> "$LOG" 2>&1 || log "WARN: pipeline_health failed"
fi

log "=== Done ==="
