"""Google Tasks API client with OAuth2 authentication."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/tasks"]


class TaskNotFoundError(Exception):
    """Raised when a Google Task ID no longer exists (e.g. deleted manually)."""


class GoogleTasksClient:
    def __init__(self, credentials_path: Path, token_path: Path) -> None:
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service = self._authenticate()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _authenticate(self):
        creds: Optional[Credentials] = None

        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                log.debug("Refreshing expired Google OAuth2 token")
                creds.refresh(Request())
            else:
                if not self.credentials_path.exists():
                    raise FileNotFoundError(
                        f"credentials.json not found at {self.credentials_path}. "
                        "Download it from the Google Cloud Console "
                        "(APIs & Services → Credentials → OAuth 2.0 Client)."
                    )
                log.info("Opening browser for Google OAuth2 authorization…")
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_path), SCOPES
                )
                creds = flow.run_local_server(port=0)

            self.token_path.touch(mode=0o600)
            self.token_path.write_text(creds.to_json())
            log.info("Google credentials saved to %s", self.token_path)

        return build("tasks", "v1", credentials=creds)

    # ------------------------------------------------------------------
    # Task lists
    # ------------------------------------------------------------------

    def find_list_id(self, list_name: str) -> str:
        """Return the ID of the task list matching *list_name* (exact match)."""
        response = self.service.tasklists().list(maxResults=100).execute()
        for tl in response.get("items", []):
            if tl["title"] == list_name:
                return tl["id"]
        available = [tl["title"] for tl in response.get("items", [])]
        raise ValueError(
            f"Google Tasks list '{list_name}' not found. "
            f"Available lists: {available}"
        )

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    def create_task(
        self,
        list_id: str,
        title: str,
        notes: Optional[str],
        due: Optional[datetime],
    ) -> str:
        """Create a task and return its ID."""
        body: dict = {
            "title": title,
            "status": "needsAction",
            "notes": notes or "",
        }
        if due is not None:
            body["due"] = _format_due(due)

        task = self.service.tasks().insert(tasklist=list_id, body=body).execute()
        log.debug("Created Google Task id=%s title=%r", task["id"], title)
        return task["id"]

    def update_task(
        self,
        list_id: str,
        task_id: str,
        title: str,
        notes: Optional[str],
        due: Optional[datetime],
    ) -> None:
        """Overwrite an existing task's fields (PUT semantics)."""
        body: dict = {
            "id": task_id,
            "title": title,
            "status": "needsAction",
            "notes": notes or "",
        }
        if due is not None:
            body["due"] = _format_due(due)

        try:
            self.service.tasks().update(
                tasklist=list_id, task=task_id, body=body
            ).execute()
        except HttpError as exc:
            if exc.resp.status == 404:
                log.warning(
                    "Task %s not found in Google Tasks (deleted manually) — will recreate on next sync",
                    task_id,
                )
                raise TaskNotFoundError(task_id)
            raise

    def complete_task(self, list_id: str, task_id: str) -> None:
        """Mark a task as completed."""
        try:
            self.service.tasks().update(
                tasklist=list_id,
                task=task_id,
                body={"id": task_id, "status": "completed"},
            ).execute()
            log.debug("Completed Google Task id=%s", task_id)
        except HttpError as exc:
            if exc.resp.status == 404:
                log.warning(
                    "Task %s not found in Google Tasks (may have been deleted manually), skipping complete",
                    task_id,
                )
            else:
                raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_due(dt: datetime) -> str:
    """Format a datetime as the RFC 3339 string expected by the Google Tasks API."""
    return dt.strftime("%Y-%m-%dT00:00:00.000Z")
