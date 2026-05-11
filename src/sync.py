"""Core sync logic: Apple Reminders → Google Tasks (one-way)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from .apple_reminders import fetch_reminders
from .google_tasks import GoogleTasksClient, QuotaExceededError, TaskNotFoundError

log = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).parent.parent
STATE_PATH = _BASE_DIR / "state.json"
CREDENTIALS_PATH = _BASE_DIR / "credentials.json"
TOKEN_PATH = _BASE_DIR / "token.json"


# ---------------------------------------------------------------------------
# State helpers  (apple_id → google_task_id mapping)
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"mappings": {}}


def _save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, default=str))


# ---------------------------------------------------------------------------
# Main sync entry point
# ---------------------------------------------------------------------------

def run_sync(config: dict) -> None:
    apple_lists: list[str] = config["apple_lists"]
    gtasks_list: str = config["google_tasks_list"]

    # 1. Fetch incomplete reminders from Apple
    log.info("Fetching incomplete reminders from Apple list(s): %s", apple_lists)
    reminders = fetch_reminders(apple_lists)
    log.info("Found %d incomplete reminder(s) in Apple Reminders", len(reminders))
    apple_index = {r.apple_id: r for r in reminders}

    # 2. Load persisted ID mapping
    state = _load_state()
    mappings: dict[str, str] = state.setdefault("mappings", {})  # apple_id → gtask_id

    # 3. Connect to Google Tasks
    gtasks = GoogleTasksClient(CREDENTIALS_PATH, TOKEN_PATH)
    list_id = gtasks.find_list_id(gtasks_list)
    log.info("Target Google Tasks list: '%s' (%s)", gtasks_list, list_id)

    created = updated = skipped = completed_count = 0

    # Cache maps apple_id → {"title": ..., "notes": ..., "due": ...} of last pushed state.
    cache: dict[str, dict] = state.setdefault("cache", {})

    def _reminder_cache_entry(r) -> dict:
        return {"title": r.title, "notes": r.notes, "due": str(r.due)}

    quota_hit = False

    # 4. Upsert: for every reminder currently in Apple, create or update in Google Tasks
    for reminder in reminders:
        if reminder.apple_id in mappings:
            current = _reminder_cache_entry(reminder)
            cached = cache.get(reminder.apple_id)
            if cached is None:
                # No cache entry means this is the first run after the cache was introduced
                # (or state.json was reset). Assume Google Tasks is already in sync and seed
                # the cache, so we don't push all reminders at once and exhaust the quota.
                log.debug("Seeding cache (no prior entry): %r", reminder.title)
                cache[reminder.apple_id] = current
                skipped += 1
                continue
            if cached == current:
                log.debug("Skipping unchanged: %r", reminder.title)
                skipped += 1
                continue
            try:
                log.debug("Updating: %r", reminder.title)
                gtasks.update_task(
                    list_id,
                    mappings[reminder.apple_id],
                    reminder.title,
                    reminder.notes,
                    reminder.due,
                )
                cache[reminder.apple_id] = current
                updated += 1
            except TaskNotFoundError:
                # Task was deleted in Google Tasks — drop the stale mapping and recreate.
                log.info("Recreating manually deleted task: %r", reminder.title)
                del mappings[reminder.apple_id]
                try:
                    gtask_id = gtasks.create_task(
                        list_id, reminder.title, reminder.notes, reminder.due
                    )
                except QuotaExceededError:
                    quota_hit = True
                    break
                mappings[reminder.apple_id] = gtask_id
                cache[reminder.apple_id] = current
                created += 1
            except QuotaExceededError:
                quota_hit = True
                break
        else:
            log.info("Creating: %r", reminder.title)
            try:
                gtask_id = gtasks.create_task(
                    list_id, reminder.title, reminder.notes, reminder.due
                )
            except QuotaExceededError:
                quota_hit = True
                break
            mappings[reminder.apple_id] = gtask_id
            cache[reminder.apple_id] = _reminder_cache_entry(reminder)
            created += 1

    if quota_hit:
        log.warning(
            "Google Tasks API daily quota exhausted — sync partially complete "
            "(created: %d  updated: %d). Remaining reminders will sync tomorrow "
            "when the quota resets, or increase your quota in the Google Cloud Console.",
            created,
            updated,
        )

    # 5. Complete: for every tracked reminder that has disappeared from Apple
    #    (deleted or completed there), mark it as completed in Google Tasks.
    stale = [aid for aid in list(mappings) if aid not in apple_index]
    for apple_id in stale:
        gtask_id = mappings.pop(apple_id)
        cache.pop(apple_id, None)
        log.info("Completing removed reminder — Google Task id: %s", gtask_id)
        gtasks.complete_task(list_id, gtask_id)
        completed_count += 1

    # 6. Persist updated mapping
    state["last_sync"] = datetime.now().isoformat()
    _save_state(state)

    log.info(
        "Sync complete — created: %d  updated: %d  skipped: %d  completed: %d",
        created,
        updated,
        skipped,
        completed_count,
    )
