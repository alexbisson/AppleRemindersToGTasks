"""Fetch incomplete reminders from Apple Reminders via the EventKit framework."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import EventKit
import Foundation

log = logging.getLogger(__name__)

# EKAuthorizationStatus values
_AUTH_AUTHORIZED = 3   # macOS ≤ 12
_AUTH_FULL_ACCESS = 4  # macOS 13+  (EKAuthorizationStatusFullAccess)


@dataclass
class Reminder:
    apple_id: str
    title: str
    notes: Optional[str]
    due: Optional[datetime]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _spin_until(event: threading.Event, timeout: float = 30.0) -> None:
    """Wait for *event* with a run-loop spin so EventKit callbacks can fire."""
    deadline = Foundation.NSDate.dateWithTimeIntervalSinceNow_(timeout)
    while not event.is_set():
        # Give the current run loop a short slice so callbacks can be delivered.
        Foundation.NSRunLoop.currentRunLoop().runMode_beforeDate_(
            Foundation.NSDefaultRunLoopMode,
            Foundation.NSDate.dateWithTimeIntervalSinceNow_(0.1),
        )
        if Foundation.NSDate.date().compare_(deadline) == 1:  # NSOrderedDescending
            raise TimeoutError(f"Timed out after {timeout}s waiting for EventKit")


def _ensure_access(store: EventKit.EKEventStore) -> None:
    """Request Reminders access if not already granted; raise on denial."""
    status = EventKit.EKEventStore.authorizationStatusForEntityType_(
        EventKit.EKEntityTypeReminder
    )
    if status in (_AUTH_AUTHORIZED, _AUTH_FULL_ACCESS):
        return

    log.info("Requesting Reminders access (current status=%d)", status)
    done = threading.Event()
    result: dict = {}

    def _callback(granted: bool, error) -> None:
        result["granted"] = bool(granted)
        if error:
            result["error"] = str(error)
        done.set()

    if hasattr(store, "requestFullAccessToRemindersWithCompletion_"):
        store.requestFullAccessToRemindersWithCompletion_(_callback)
    else:
        store.requestAccessToEntityType_completion_(
            EventKit.EKEntityTypeReminder, _callback
        )

    _spin_until(done)

    if not result.get("granted"):
        raise PermissionError(
            "Reminders access denied. "
            "Go to System Settings → Privacy & Security → Reminders "
            "and grant access to Terminal (or your Python binary)."
        )


def _components_to_datetime(components) -> Optional[datetime]:
    """Convert an NSDateComponents object to a Python datetime (UTC)."""
    if components is None:
        return None
    cal = Foundation.NSCalendar.currentCalendar()
    nsdate = cal.dateFromComponents_(components)
    if nsdate is None:
        return None
    return datetime.utcfromtimestamp(nsdate.timeIntervalSince1970())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_reminders(list_names: list[str]) -> list[Reminder]:
    """Return all *incomplete* reminders from the given Apple Reminders list(s)."""
    store = EventKit.EKEventStore.alloc().init()
    _ensure_access(store)

    all_calendars = store.calendarsForEntityType_(EventKit.EKEntityTypeReminder)
    target_calendars = [c for c in all_calendars if c.title() in list_names]

    if not target_calendars:
        available = sorted(c.title() for c in all_calendars)
        raise ValueError(
            f"No Apple Reminders list matching {list_names!r}. "
            f"Available lists: {available}"
        )

    log.debug(
        "Matched %d calendar(s): %s",
        len(target_calendars),
        [c.title() for c in target_calendars],
    )

    predicate = store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(
        None, None, target_calendars
    )

    done = threading.Event()
    raw: list = []

    def _completion(reminders, error) -> None:
        if reminders:
            raw.extend(reminders)
        if error:
            log.error("EventKit fetch error: %s", error)
        done.set()

    store.fetchRemindersMatchingPredicate_completion_(predicate, _completion)
    _spin_until(done)

    results: list[Reminder] = []
    for r in raw:
        title = r.title()
        if not title:
            continue
        results.append(
            Reminder(
                apple_id=str(r.calendarItemIdentifier()),
                title=str(title),
                notes=str(r.notes()) if r.notes() else None,
                due=_components_to_datetime(r.dueDateComponents()),
            )
        )

    return results
