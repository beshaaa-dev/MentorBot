---
name: amocrm-api
description: >-
  Uses the Python amocrm-api (amocrm.v2 / Krukov) SDK correctly with pipelines,
  leads, contacts, links, tags, and notes. Respects AmoCRM 7 RPS. Use when
  integrating AmoCRM/Kommo, fixing CRM sync bugs, or editing
  repositories/crm_service that call Contact, Lead, or Pipeline.
---

# amocrm-api (Python `amocrm.v2`)

## Official API reference

Treat **[AmoCRM CRM Platform API Reference](https://www.amocrm.ru/developers/content/crm_platform/api-reference)** as the source of truth for REST paths, payloads, and behavior (v4: `/api/v4/...`). When unsure about fields, methods, or limits, align with that documentation.

Kommo accounts generally follow the same v4 API shape for core entities.

## Rate limiting: 7 RPS

AmoCRM allows **at most 7 requests per second** per integration. **Every** call that hits their CRM API must be throttled accordingly.

- **This repo:** wrap SDK / direct HTTP calls with `amo_crm_rate_limiter.limit()` from [`rate_limiter.py`](rate_limiter.py) (`RateLimiter(max_requests=7, time_window=1.0)` sliding window).
- **New code:** acquire before each request; do not batch-unlimited parallel calls without a shared limiter.
- Bursts: the limiter blocks until a slot is free; keep sequential CRM work predictable.

Package: **`amocrm-api`** on PyPI → `from amocrm.v2 import Pipeline, tokens` and entity models.

## Pipelines: never use `filter(query=id)` for numeric id

List endpoints pass `query` to the API as a **text search** (e.g. pipeline **name**), not as pipeline id.

- **Wrong:** `Pipeline.objects.filter(query=str(pipeline_id))` then match `p.id`
- **Right:** `Pipeline.objects.get(object_id=pipeline_id)` → `GET /api/v4/leads/pipelines/{id}`

Same idea anywhere a numeric entity id is required.

## Embedded link lists: `contact.leads` / truthiness

For `_EmbeddedLinkListField` (e.g. `Contact.leads`, `Lead.contacts`), when there are **no** linked items the descriptor returns `_ListData(data=None)`.

- That wrapper is **truthy**, so `if not contact.leads` does **not** guard iteration.
- Iterating runs `for item in None` → **`TypeError: 'NoneType' object is not iterable`**.

**Safe pattern before iterating:**

```python
lead_refs = (contact._data.get("_embedded") or {}).get("leads")
if not lead_refs:
    return None
for lead in contact.leads:
    ...
```

Adjust key (`"leads"`, `"contacts"`, etc.) for the field.

## New `Lead` + linked `Contact`: no `contacts=[...]` in constructor

`Lead.contacts` is `_EmbeddedLinkListField`; **`on_set` raises `TypeError`** — you cannot pass `contacts=[contact]` into `Lead(...)`.

**Pattern:**

```python
lead = Lead(pipeline=pipeline, status=status)
lead.save()
lead.contacts.append(contact, main=True)
```

`append` uses the links API (`POST .../leads/{id}/link`). Both sides must have **`id`** after `save()`.

## Tags

`entity.tags` is a wrapper over `_embedded.tags`. To dedupe, compare `getattr(t, "name", None)` to the string; then `entity.tags.append("tag_name")` and `entity.save()`.

## Notes

```python
from amocrm.v2.entity.note import COMMON_TYPE
entity.notes.objects.create(text="...", note_type=COMMON_TYPE)
entity.save()
```

Works on **Lead** and **Contact** (same `NotesField` pattern).

## Custom fields (this project)

[`crm/crm_models.py`](crm/crm_models.py) subclasses `Contact` / `Lead` with `custom_field.*` — use those models for fields like `telegram_id`, not the base library classes.

## Async / blocking

SDK uses **synchronous** `requests`. In async handlers (e.g. python-telegram-bot), run CRM entrypoints in **`asyncio.get_running_loop().run_in_executor`** or a small thread pool so the event loop is not blocked.

## This repo

- Global CRM helpers: [`crm/crm_service.py`](crm/crm_service.py) (`update_lead_status_in_pipeline`, tokens, etc.).
