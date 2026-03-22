# Apple Reminders → Google Tasks Sync

A lightweight macOS background service that performs a **one-way sync** from Apple Reminders to Google Tasks. Reminders are synced as tasks; when a reminder is completed or deleted in Apple Reminders, the corresponding Google Task is marked as completed.

## Features

- One-way sync: Apple Reminders is the source of truth
- Syncs title, notes, and due date
- Configurable source list(s) in Apple Reminders and target list in Google Tasks
- Configurable polling interval (default: 10 minutes)
- Runs as a native macOS launchd background agent
- Structured logging to `~/Library/Logs/reminders-gtasks-sync.log`

## Requirements

- macOS 12 or later
- Python 3.10+
- A Google account with Google Tasks enabled

---

## Setup

### 1 — Google Cloud credentials

1. Go to the [Google Cloud Console](https://console.cloud.google.com).
2. Create a new project (or select an existing one).
3. Navigate to **APIs & Services → Library** and enable the **Google Tasks API**.
4. Navigate to **APIs & Services → Credentials** and click **Create Credentials → OAuth 2.0 Client ID**.
   - Application type: **Desktop app**
   - Give it any name (e.g. `reminders-gtasks-sync`)
5. Click **Download JSON** and save the file as `credentials.json` in this directory.

> `credentials.json` and `token.json` are listed in `.gitignore` — never commit them.

### 2 — Configure the sync

```bash
cp config.example.json config.json
```

Edit `config.json`:

| Key | Description | Default |
|-----|-------------|---------|
| `apple_lists` | Array of Apple Reminders list names to sync | `["Reminders"]` |
| `google_tasks_list` | Name of the Google Tasks list to sync into | `"WallCal"` |
| `poll_interval_minutes` | How often the sync runs (in minutes) | `10` |
| `log_level` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`) | `"INFO"` |

### 3 — Grant Reminders access

The first time the script runs, macOS will prompt you to grant Reminders access to Terminal (or whichever app runs the script). If the prompt doesn't appear automatically, go to:

**System Settings → Privacy & Security → Reminders → enable Terminal**

### 4 — Run setup

```bash
./setup.sh
```

This will:

1. Create a Python virtual environment at `.venv/`
2. Install all dependencies
3. Open your browser for a one-time Google OAuth2 login (grants access to Google Tasks)
4. Write and register a launchd agent that runs the sync on your configured interval

---

## Usage

### Manual sync

```bash
.venv/bin/python3 main.py
```

### Watch live logs

```bash
tail -f ~/Library/Logs/reminders-gtasks-sync.log
```

### Stop the background agent

```bash
launchctl unload ~/Library/LaunchAgents/com.reminders-gtasks-sync.plist
```

### Restart the background agent

```bash
launchctl unload ~/Library/LaunchAgents/com.reminders-gtasks-sync.plist
launchctl load  ~/Library/LaunchAgents/com.reminders-gtasks-sync.plist
```

### Re-run setup after changing config

If you change `poll_interval_minutes` in `config.json`, re-run `./setup.sh` to regenerate and reload the launchd plist.

---

## How it works

```
Apple Reminders (EventKit)
         │
         │  fetch incomplete reminders
         ▼
      sync.py  ←──  state.json  (apple_id → google_task_id mapping)
         │
         │  create / update / complete
         ▼
   Google Tasks API
```

1. **Fetch** — all incomplete reminders are fetched from the configured Apple Reminders list(s) using the native EventKit framework.
2. **Upsert** — each reminder is created or updated in Google Tasks, matched by a persistent ID stored in `state.json`.
3. **Complete** — any Google Task tracked in `state.json` that is no longer present in Apple Reminders (deleted or completed there) is marked as completed.

Tasks created directly in Google Tasks (not via this sync) are not touched.

---

## Project structure

```
├── main.py                  # Entry point
├── src/
│   ├── apple_reminders.py   # EventKit interface
│   ├── google_tasks.py      # Google Tasks API client
│   └── sync.py              # Sync logic
├── config.example.json      # Configuration template
├── requirements.txt
└── setup.sh                 # One-command install & launchd registration
```

**Runtime files (gitignored):**

| File | Purpose |
|------|---------|
| `config.json` | Your local configuration |
| `credentials.json` | Google OAuth2 client secret |
| `token.json` | Cached Google access/refresh token |
| `state.json` | apple\_id → google\_task\_id mapping |
| `.venv/` | Python virtual environment |

---

## Known limitations

- **Due date clearing**: if a due date is removed from a reminder in Apple, the existing due date in Google Tasks will not be cleared (Google Tasks API limitation with PUT semantics).
- **Subtasks**: Apple Reminders sub-tasks are not synced.
- **Attachments / images**: not supported by the Google Tasks API.
