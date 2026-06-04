# MentorBot

A Telegram bot for managing mentor-student workflows, integrated with AmoCRM. Built with Python, `python-telegram-bot`, FastAPI, and SQLAlchemy.

## Architecture Overview

The project runs as **two independent processes**:

| Process | Entry Point | Purpose |
|---|---|---|
| Telegram bot | `main.py` | Handles all user interactions via long-polling |
| Webhook server | `webhooks.py` | Receives AmoCRM status-change webhooks and sends Telegram notifications |

The two processes share no in-memory state — the webhook server creates a short-lived `Bot` instance to send notifications.

## Project Structure

```
handlers/       — Telegram update handlers (ConversationHandlers, CallbackQueryHandlers)
repositories/   — Business logic orchestrating DB + CRM operations
database/       — SQLAlchemy models, session management, and DB-level service functions
crm/            — AmoCRM API wrappers and custom models
services/       — Background job logic (broadcast scheduling, reminders, export)
messages.py     — All user-facing text strings (Russian)
keyboards.py    — Inline keyboard builders
timezone_utils.py — UTC ↔ Moscow (UTC+3) conversion helpers
```

Handler registration order is defined in `handlers/__init__.py`. More specific handlers must be registered before broader ones (`unknown_message_handler` is always last).

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment variables

Copy `.env.example` to `.env` and fill in the values. 

### 3. Run the bot

```bash
python main.py
```

### 4. Run the webhook server

```bash
python webhooks.py
# or
uvicorn webhooks:app --host 0.0.0.0 --port 8000
```

## Key Design Decisions

- **CRM rate limiting** — all CRM calls must go through `amo_crm_rate_limiter.limit()` (sync) or `async_amo_crm_rate_limiter.limit()` (async) from `rate_limiter.py`.
- **Token safety** — `ThreadSafeTokenManager` wraps the non-thread-safe AmoCRM library. The `_patch_amo_interaction()` workaround retries on 401 during token-refresh races — do not remove it.
- **State persistence** — conversation state is saved to `bot_persistence.pickle` via `ThreadSafePicklePersistence`, flushed every 60 seconds.
- **Broadcast system** — scheduled via `python-telegram-bot`'s `JobQueue`; pending jobs are restored 10–12 seconds after startup. See [docs/broadcast-system.md](docs/broadcast-system.md).
- **Webhook deduplication** — in-memory TTL cache prevents duplicate processing of the same AmoCRM event.

## Documentation

- [docs/broadcast-system.md](docs/broadcast-system.md) — Broadcast and survey flow
- [docs/VISIT_CARD_PROCESS.md](docs/VISIT_CARD_PROCESS.md) — Visit card generation process
