# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Project

This project has **two separate processes** that must run independently:

```bash
# Telegram bot (polling mode)
python main.py

# AmoCRM webhook server (FastAPI)
python webhooks.py
# or
uvicorn webhooks:app --host 0.0.0.0 --port 8000
```

Install dependencies:
```bash
pip install -r requirements.txt
```

## Required Environment Variables

Copy from `.env.example` or configure in `.env`:
- `TELEGRAM_BOT_TOKEN` — Telegram Bot API token from @BotFather
- `DATABASE_URL` — defaults to `sqlite:///./mentor_bot.db` if not set
- `CRM_CLIENT_ID`, `CRM_CLIENT_SECRET`, `CRM_AUTH_CODE`, `CRM_SUBDOMAIN` — AmoCRM OAuth credentials
- `CRM_PIPELINE` and `CRM_*_STATUS` — AmoCRM pipeline and status IDs
- `CRM_CHAT_CHANNEL_ID`, `CRM_CHAT_CHANNEL_SECRET`, `CRM_CHAT_BOT_NAME` — AmoCRM Chat API
- `AMO_CHAT_WEBHOOK_SECRET` — HMAC secret for webhook signature verification

AmoCRM tokens are stored locally in `tokens/` after the first `init_amo_crm_token()` call.

## Architecture Overview

### Two-Process Design

The bot (main.py) runs as a long-polling Telegram bot. The webhook server (webhooks.py) is a FastAPI app that receives CRM status-change webhooks and sends Telegram notifications by constructing a `Bot` object directly (no shared state between processes).

### Layer Structure

```
handlers/       — Telegram update handlers (ConversationHandlers, CallbackQueryHandlers)
repositories/   — Business logic that orchestrates DB + CRM operations
database/       — SQLAlchemy models, session management, and DB-level service functions
crm/            — AmoCRM API wrappers (crm_service.py) and custom models (crm_models.py)
services/       — Background job logic (broadcast scheduling, reminders, export)
```

**Handler registration order matters** — `handlers/__init__.py` defines the exact order. More specific handlers must be registered before broader ones (e.g., `unknown_message_handler` is always last).

### Database

SQLAlchemy 2.0 with synchronous sessions. The `get_db()` context manager in [database/db_helper.py](database/db_helper.py) is the standard way to open a session. All datetimes are stored as **naive UTC**. Moscow timezone (UTC+3) is used for user-facing display and input — convert using [timezone_utils.py](timezone_utils.py).

Models in [database/models.py](database/models.py):
- `User` (mentor/student), `Task`/`TaskMessage`, `TestResult` — main program flow
- `Homework`/`HomeworkAnswer`/`MentorHomeworkNotification` — homework flow
- `Chat`/`ChatMember`/`Broadcast`/`SurveyResponse`/`SurveyAnswer` — broadcast/survey system

### AmoCRM Integration

`crm/crm_service.py` wraps the `amocrm-api` library. All synchronous CRM calls must be wrapped with `amo_crm_rate_limiter.limit()` (from [rate_limiter.py](rate_limiter.py)); async calls use `async_amo_crm_rate_limiter.limit()`.

Token management uses `ThreadSafeTokenManager` ([thread_safe_token_manager.py](thread_safe_token_manager.py)) because the AmoCRM library is not thread-safe. There is a known workaround in `_patch_amo_interaction()` that retries on 401 during token refresh race conditions — do not remove it without verifying the upstream bug is fixed.

### Webhook → Bot Notification Flow

`webhooks.py` receives form-encoded POST requests from AmoCRM when a lead changes status. Each endpoint:
1. Validates pipeline/status IDs from form data
2. Deduplicates using an in-memory TTL cache
3. Spawns a background `asyncio.Task` that calls the relevant `repositories/homework_repository.py` function, then sends a Telegram message via a short-lived `Bot` instance.

### Broadcast System

Admins use `/admin` in a group chat. Flow: chat selection → type (message/survey) → timing → confirmation. Broadcasts and reminders are scheduled via `python-telegram-bot`'s `JobQueue`. On bot restart, `restore_scheduled_jobs` and `restore_reminder_jobs` re-schedule any pending jobs (runs 10 and 12 seconds after startup respectively). See [docs/broadcast-system.md](docs/broadcast-system.md) for full spec.

Survey questions are defined as a list of dicts in [handlers/survey_questions.py](handlers/survey_questions.py). To add questions, add an entry to `SURVEY_QUESTIONS` with a unique `key` used for DB storage.

### State Persistence

Bot conversation state is persisted to `bot_persistence.pickle` via `ThreadSafePicklePersistence` ([thread_safe_persistence.py](thread_safe_persistence.py)), updated every 60 seconds. This file is git-ignored.

### Messages and Keyboards

All user-facing text is in [messages.py](messages.py) (Russian). Inline keyboards are built in [keyboards.py](keyboards.py). Do not hardcode message strings in handlers.

## Documentation Language

Write all code documentation and comments in English (per project convention).
