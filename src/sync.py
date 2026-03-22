"""Core sync logic: Apple Reminders → Google Tasks (one-way)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from .apple_reminders import fetch_reminders
from .google_tasks import GoogleTasksClient, TaskNotFoundError

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

    created = updated = completed_count = 0

    # 4. Upsert: for every reminder currently in Apple, create or update in Google Tasks
    for reminder in reminders:
        if reminder.apple_id in mappings:
            try:
                log.debug("Updating: %r", reminder.title)
                gtasks.update_task(
                    list_id,
                    mappings[reminder.apple_id],
                    reminder.title,
                    reminder.notes,
                    reminder.due,
                )
                updated += 1
            except TaskNotFoundError:
                # Task was deleted in Google Tasks — drop the stale mapping and recreate.
                log.info("Recreating manually deleted task: %r", reminder.title)
                del mappings[reminder.apple_id]
                gtask_id = gtasks.create_task(
                    list_id, reminder.title, reminder.notes, reminder.due
                )
                mappings[reminder.apple_id] = gtask_id
                created += 1
        else:
            log.info("Creating: %r", reminder.title)
            gtask_id = gtasks.create_task(
                list_id, reminder.title, reminder.notes, reminder.due
            )
            mappings[reminder.apple_id] = gtask_id
            created += 1

    # 5. Complete: for every tracked reminder that has disappeared from Apple
    #    (deleted or completed there), mark it as completed in Google Tasks.
    stale = [aid for aid in list(mappings) if aid not in apple_index]
    for apple_id in stale:
        gtask_id = mappings.pop(apple_id)
        log.info("Completing removed reminder — Google Task id: %s", gtask_id)
        gtasks.complete_task(list_id, gtask_id)
        completed_count += 1

    # 6. Persist updated mapping
    state["last_sync"] = datetime.now().isoformat()
    _save_state(state)

    log.info(
        "Sync complete — created: %d  updated: %d  completed: %d",
        created,
        updated,
        completed_count,
    )
