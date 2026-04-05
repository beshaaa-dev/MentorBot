# Homework Feature

All bot text must be in Russian.

## Reference: Pipeline & Lead Status IDs (pipeline `10726418`)
- `84497006` — homework assigned to student
- `84497010` — student submitted answers
- `84880018` — admin validation passed, homework ready for mentor
- `84880014` — mentor rejected, student must re-edit
- `84880022` — mentor approved

Config constants (`config.py`):
```python
CRM_HOMEWORK_PIPELINE    = 10726418
CRM_HW_ASSIGNED_STATUS   = "84497006"
CRM_HW_SUBMITTED_STATUS  = "84497010"
CRM_HW_REEDIT_STATUS     = "84880014"
CRM_HW_FOR_MENTOR_STATUS = "84880018"
CRM_HW_APPROVED_STATUS   = "84880022"
```

## Reference: Lead Field IDs
| Field | ID |
|---|---|
| Homework questions 1–5 | `560085`, `560087`, `560089`, `560091`, `560093` (only first is required) |
| Homework deadline (date) | `560201` |
| Student text answers 1–5 | `560189`, `560191`, `560193`, `560195`, `560197` |
| DB homework record ID | `560199` |
| Completion date | `560203` |
| Deadline missed ("Да"/"Нет") | `560205` |
| Reedit reason (written by mentor in CRM) | `560207` |
| Mentor tg nickname | `550463` — existing field `mentor_tg_nickname` on `Lead`, `field_id=550463` |

## Reference: DB Models
```python
class HomeworkStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"       # awaiting admin validation
    PENDING_MENTOR = "pending_mentor"
    POSTPONED = "postponed"
    APPROVED = "approved"
    REEDIT = "reedit"             # mentor rejected, student editing again

class Homework(Base):
    __tablename__ = "homeworks"
    id, student_id, mentor_id, lead_id (UNIQUE), status
    first_hw … fifth_hw          # question texts from CRM
    deadline                      # DateTime nullable
    feedback, rating              # mentor evaluation
    created_at, updated_at

class HomeworkAnswer(Base):
    __tablename__ = "homework_answers"
    id, homework_id (FK), question_number (1–5)
    answer_content               # full text OR Telegram file_id string
    is_text                      # bool
    UNIQUE(homework_id, question_number)

class MentorHomeworkInvite(Base):
    __tablename__ = "mentor_homework_invites"
    mentor_id (UNIQUE), message_id, chat_id
```

---

# Implementation Plan

## Shared foundation (implement first, required by all stages)

1. **`database/models.py`** — add all DB models above ✅
2. **`crm/crm_models.py`** — add homework fields to `Lead` with `field_id=` kwarg; `mentor_tg_nickname` updated with `field_id=550463` ✅
3. **`crm/crm_service.py`** — add `get_crm_contact_by_id`, `get_homework_lead(contact, status_id)` ✅
4. **`database/homework_service.py`** *(new)* — CRUD, mirrors `task_service.py` ✅
5. **`repositories/homework_repository.py`** *(new)* — business logic, mirrors `task_repository.py` ✅
6. **`repositories/user_repository.py`** — add `HomeworkLeadDetails` + `get_homework()` ✅
7. **`messages.py` + `keyboards.py`** — all homework Russian strings and keyboards ✅

---

## Stage 1 — Student receives homework ✅

Two triggers deliver homework to the student: the amoCRM webhook and the `/start` command (both are idempotent — they share the same DB creation logic).

### Trigger A: amoCRM webhook

**`POST /homework/assigned`** (`webhooks.py`)

1. Parse form body (`application/x-www-form-urlencoded`), validate `pipeline_id == CRM_HOMEWORK_PIPELINE` and `status_id == CRM_HW_ASSIGNED_STATUS`
2. Call `save_homework_from_webhook(lead_id)` in executor:
   - `get_crm_lead(lead_id)` → safe-iterate `lead.contacts` to find student `telegram_id`
   - Read questions from fields `560085–560093`, deadline from `560201`
   - Look up mentor via `lead.mentor_tg_nickname`
   - Create `Homework` (idempotent — returns existing record if `lead_id` already in DB)
3. Send student `HW_NEW_ASSIGNMENT` + **Приступить** button via `Bot(token).send_message`

### Trigger B: `/start` command

On `/start`, after test → visit card → task checks:

1. `get_crm_contact_by_id(user.crm_id)` — fetches contact without requiring a main-pipeline lead
2. `get_homework_lead(contact, status_id=CRM_HW_ASSIGNED_STATUS)` — finds lead in pipeline `10726418`
3. If found: `save_homework_from_webhook(lead_id)` (idempotent)
4. Send `HW_NEW_ASSIGNMENT` + **Приступить** button → return `ConversationHandler.END`

`/start` flow order: test → visit card → task → **homework** → "no task"

### Student taps Приступить → `ConversationHandler` in `handlers/homework_student.py`

Entry point: `CallbackQueryHandler(pattern="^start_homework_\d+$")`

States:
```
ANSWERING_HW_1=100 → CONFIRMING_HW_1=101
ANSWERING_HW_2=102 → CONFIRMING_HW_2=103   (optional, only if second_hw exists)
ANSWERING_HW_3=104 → CONFIRMING_HW_3=105   (optional)
ANSWERING_HW_4=106 → CONFIRMING_HW_4=107   (optional)
ANSWERING_HW_5=108 → CONFIRMING_HW_5=109   (optional)
REVIEWING=110                               → Confirm all / Edit Nth
```

Accepts: text, audio, video, photo, voice, video_note, document.

Per question: extract `file_id` from the message at receive time and store `{q_num: {"is_text": bool, "text": str|None, "file_id": str|None}}` in `context.user_data["hw_answers"]`. Show inline Да/Нет confirmation; "Нет" loops back to ANSWERING_HW_N.

**On final confirm (`submit_student_answers`):**
1. For non-text answers: `bot.get_file(file_id)` → download bytes → `upload_video()` → get CRM Drive URL
2. Write text answers to CRM fields `560189–560197`; build single CRM note with all answers (text inline, media as URLs)
3. Write `hw_db_record_id` → `560199`, `hw_completion_date` → `560203`, `hw_deadline_missed` → `560205`
4. `lead.save()` (single batched call)
5. `upsert_homework_answers(...)` in DB; `update_homework_status(hw_id, SUBMITTED)`
6. `update_lead_status_in_pipeline(lead, CRM_HOMEWORK_PIPELINE, CRM_HW_SUBMITTED_STATUS)`

Settings: `persistent=True`, `name="homework_student"`, `conversation_timeout=259200` (3 days).

### CRM helpers (`crm/crm_service.py`)

```python
def get_crm_contact_by_id(crm_id: int | str) -> Contact | None:
    """Fetch Contact by CRM id without requiring a valid lead in the main pipeline."""

def get_homework_lead(contact: Contact, status_id: str) -> Lead | None:
    """Return the lead in CRM_HOMEWORK_PIPELINE with the given status, or None."""
```

### `user_repository.py` additions

```python
@dataclass(slots=True)
class HomeworkLeadDetails:
    lead_id: str
    questions: list[str]    # 1–5 non-empty question texts
    deadline: str | None    # formatted Moscow time string

def get_homework(user_crm_id: str) -> HomeworkLeadDetails | None:
    contact = get_crm_contact_by_id(user_crm_id)
    lead = get_homework_lead(contact, status_id=CRM_HW_ASSIGNED_STATUS)
    # reads hw_question_1…5 and hw_deadline from lead
```

### Files touched in Stage 1
- `config.py` — `CRM_HOMEWORK_PIPELINE` + all `CRM_HW_*` status constants ✅
- `crm/crm_models.py` — homework fields on `Lead`; `mentor_tg_nickname` updated with `field_id=550463` ✅
- `crm/crm_service.py` — `get_crm_contact_by_id`, `get_homework_lead(contact, status_id)` ✅
- `database/models.py` — `HomeworkStatus`, `Homework`, `HomeworkAnswer`, `MentorHomeworkInvite` ✅
- `database/homework_service.py` *(new)* ✅
- `repositories/homework_repository.py` *(new)* — `save_homework_from_webhook`, `submit_student_answers` ✅
- `repositories/user_repository.py` — `HomeworkLeadDetails`, `get_homework` ✅
- `messages.py` — homework Russian strings ✅
- `keyboards.py` — `get_start_homework_keyboard`, `get_hw_answer_confirmation_keyboard`, `get_hw_review_keyboard` ✅
- `webhooks.py` — `POST /homework/assigned` ✅
- `handlers/student.py` — homework check after task check in `handle_student` ✅
- `handlers/homework_student.py` *(new)* — `ConversationHandler` ✅
- `handlers/__init__.py` — register `hw_student_conversation_handler` ✅

---

## Stage 2 — Student receives homework for re-editing

**Trigger:** mentor rejects in amoCRM → lead status → `84880014` → `POST /homework/reedit`

**What happens:**
1. Parse form body, validate `pipeline_id == CRM_HOMEWORK_PIPELINE` and `status_id == CRM_HW_REEDIT_STATUS`
2. Fetch lead, read reedit reason from field `560207`
3. Find student in DB by lead's contact `telegram_id`, find their existing `Homework` record by `lead_id`, update status → `REEDIT`
4. Send student: reason text + inline button **Исправить** (`reedit_homework_{hw_id}`)

**Student taps Исправить → same `ConversationHandler` in `handlers/homework_student.py`:**

Entry point: `CallbackQueryHandler(pattern="^reedit_homework_\d+$")`

On entry: pre-populate `context.user_data["hw_answers"]` from existing `HomeworkAnswer` records (using stored `file_id` for media, `answer_content` for text) so student can selectively overwrite.

Submission logic on final confirm is identical to Stage 1, but `upsert_homework_answers` updates existing rows.

**Files touched:**
- `webhooks.py` — add `POST /homework/reedit`
- `handlers/homework_student.py` — add `reedit_homework_` entry point + pre-population logic

---

## Stage 3 — Mentor receives answers

**Trigger:** admin passes validation in amoCRM → lead status → `84880018` → `POST /homework/for-mentor`

**What happens:**
1. Parse form body, validate `pipeline_id == CRM_HOMEWORK_PIPELINE` and `status_id == CRM_HW_FOR_MENTOR_STATUS`
2. Fetch lead, read mentor tg nickname from field `550463` (`lead.mentor_tg_nickname`), find mentor in DB
3. Update `Homework` record status → `PENDING_MENTOR`
4. Look up `MentorHomeworkInvite` for this mentor → if exists, delete old Telegram message
5. Send mentor: "Новое домашнее задание для проверки" + inline button **Проверить** (`check_homework_{hw_id}`)
6. Upsert `MentorHomeworkInvite` with new `message_id`

**Mentor taps Проверить → `handlers/homework_mentor.py`:**

Shows earliest `PENDING_MENTOR` homework: questions + student answers (send media by `file_id` via `bot.send_cached_media`, show text inline). Inline keyboard:

| Button | Callback | Action |
|---|---|---|
| Проверить позже | `hw_postpone_{hw_id}` | status → POSTPONED, show next hw or menu |
| Дать обратную связь | `hw_feedback_{hw_id}` | prompt for text; on receive → save to `Homework.feedback`, back to hw menu |
| Оценить | `hw_rate_{hw_id}` | show inline 0–5; on tap → save to `Homework.rating`, back to hw menu |
| Доработать | `hw_reedit_{hw_id}` | lead → `CRM_HW_REEDIT_STATUS`, db → REEDIT, next hw or menu |
| Одобрить | `hw_approve_{hw_id}` | lead → `CRM_HW_APPROVED_STATUS`, db → APPROVED, next hw or menu |

Feedback in-flight state tracked via `context.user_data["hw_feedback_id"]`.

Postponed homeworks shown after all postponed tasks in `handle_postponed_tasks_button` (extend `handlers/mentor.py`).

**Files touched:**
- `webhooks.py` — add `POST /homework/for-mentor`
- `handlers/homework_mentor.py` *(new)* — all mentor callbacks + feedback state handler
- `handlers/mentor.py` — extend `handle_postponed_tasks_button`
- `handlers/__init__.py` — register mentor homework handlers
