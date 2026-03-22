#!/usr/bin/env python3
"""Apple Reminders → Google Tasks one-way sync — entry point."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from src.sync import run_sync

_BASE_DIR = Path(__file__).parent
CONFIG_PATH = _BASE_DIR / "config.json"
LOG_PATH = Path.home() / "Library" / "Logs" / "reminders-gtasks-sync.log"


def _setup_logging(level: str) -> None:
    fmt = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
        ],
    )


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"ERROR: Config file not found at {CONFIG_PATH}")
        print("       Copy config.example.json → config.json and fill in your settings.")
        sys.exit(1)
    return json.loads(CONFIG_PATH.read_text())


def main() -> None:
    config = _load_config()
    _setup_logging(config.get("log_level", "INFO"))
    log = logging.getLogger(__name__)
    log.info("── Apple Reminders → Google Tasks sync ──────────────────────────")
    try:
        run_sync(config)
    except Exception:
        log.exception("Sync failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
