# Broadcast System Documentation

## Table of Contents
1. [Overview](#overview)
2. [Requirements Specification](#requirements-specification)
3. [Implementation Review](#implementation-review)
4. [Architecture](#architecture)
5. [Timezone Handling](#timezone-handling)
6. [Survey Questions](#survey-questions)
7. [Testing Guide](#testing-guide)
8. [Deployment](#deployment)

---

## Overview

The Broadcast System is a Telegram bot feature that allows administrators (curators) to send surveys to chat members via direct messages. The system supports immediate and scheduled sending, automatic reminders, and comprehensive data export.

### Key Features
- **Multi-chat support**: Send surveys to one or multiple chats
- **Scheduled sending**: Schedule surveys for future dates/times
- **Automatic reminders**: Remind users after 3 days, notify curators after 3 days 2 hours
- **Data export**: Export all survey data to XLSX format
- **Admin verification**: Only chat administrators can send surveys
- **Passive registration**: Users are registered when they send messages in chat

---

## Requirements Specification

### User Registration System

**Behavior:**
- Bot tracks when added to chats (no welcome messages)
- Passive registration: users registered when they send messages
- Tracks user departures from chats
- Preserves registrations if bot is re-added
- No welcome messages sent

**Implementation:**
- `handlers/chat_events.py` - Event handlers for bot lifecycle
- `database/chat_service.py` - Database operations for chats and members

### Admin Rights Management

**Requirements:**
1. `/admin` command checks rights across all chats
2. Dynamic admin status checking via Telegram API
3. Cached `is_admin` field in ChatMember table
4. Admin status refreshed before survey sending
5. Admin status updated passively on user messages

**Admin Menu Options:**
- **"Отправить опрос"** - Create new broadcast
- **"Запланированные рассылки"** - View/cancel scheduled broadcasts
- **"Выгрузить данные (XLSX)"** - Export all data
- **"Помощь"** - Help information

### Broadcast Creation Flow

**Steps:**
1. **Chat Selection**: Multi-select with checkmarks
2. **Broadcast Type**: Choose between "Сообщение" (message) or "Опрос" (survey)
3. **Message Content** (if message type): Enter text message
4. **Timing**: Choose "Send Now" or "Scheduled"
5. **DateTime Input** (if scheduled): Format `DD.MM.YYYY HH:MM` in Moscow timezone
6. **Confirmation**: Review and confirm before sending

**Validation:**
- DateTime format must be `DD.MM.YYYY HH:MM`
- Date must be in the future
- All times in Moscow timezone (UTC+3)

### Broadcast Sending

**Process:**
1. Refresh admin status for all chat members
2. Filter: send only to active non-admin members
3. Create SurveyResponse records (for surveys)
4. Send DMs with "Start Survey" button (for surveys) or direct message (for messages)
5. Handle blocked users gracefully
6. Return send statistics

**Behavior:**
- Admins excluded from broadcasts
- Only registered users receive broadcasts
- Blocked users are skipped without errors

### Survey Questions Framework

**Question Types:**
- Buttons/multiple choice
- Scale/rating (1-10)
- Free text input
- Skip/"Don't know" option

**Conditional Logic:**
- Follow-up questions based on rating:
  - 1-5: "Что не понравилось?" (What didn't you like?)
  - 6-7: "Что хотелось бы улучшить?" (What would you improve?)
  - 8-10: "Что понравилось?" (What did you like?)

**Survey Questions:**

#### 1. Оценка вовлеченности наставника (Required)
- **Question**: Оцени насколько наставник был вовлечен на встрече?
- **Format**: Scale 1-10
- **Follow-ups**:
  - 1-5: "Расскажи, чего не хватило"
  - 6-7: "Чего не хватило до 10 баллов?"
  - 8-10: "Что больше всего понравилось"

#### 2. Оценка комфорта на встрече (Required)
- **Question**: Оцени на сколько было комфортно на встрече (место, организация, атмосфера)
- **Format**: Scale 1-10
- **Follow-ups**:
  - 1-5: "Что не понравилось?"
  - 6-7: "Что хотелось бы улучшить?"
  - 8-10: "Что понравилось"

#### 3. Оценка содержания встречи (Required)
- **Question**: Оцени, содержание встречи (темы, обсуждения, знания и т. д.)
- **Format**: Scale 1-10
- **Follow-ups**:
  - 1-5: "Что не понравилось, чего не хватило или что было лишним?"
  - 6-7: "Чего не хватило?"
  - 8-10: "Что понравилось?"

#### 4. Дополнительные комментарии (Optional)
- **Question**: Здесь можно ещё что-то добавить, если хочется
- **Format**: Free text
- **Can skip**: Yes

### Reminder System

**User Reminders:**
- Sent 3 days after broadcast
- Only to users who haven't completed survey
- Includes "Продолжить опрос" button to resume

**Curator Notifications:**
- Sent 3 days 2 hours after broadcast
- Lists users who haven't completed survey
- Shows username/ID for each incomplete user
- Limited to first 20 users if more

**Restoration:**
- Reminder jobs restored after bot restart
- Only future reminders are rescheduled

### Data Export (XLSX)

**Access:**
- ANY curator can export ALL data from ALL chats
- No filtering by curator or admin status
- Accessible via admin menu

**Export Structure:**
- One row per user response
- Columns:
  - Broadcast ID
  - Send Date (Moscow time)
  - Curator Username
  - Chat Title
  - User Telegram ID
  - User Username
  - User First Name
  - User Last Name
  - Started At
  - Completed At
  - Status (Completed/Incomplete)
  - Dynamic question columns (Ответ 1, Фолоу-ап к ответу 1, etc.)

**Format:**
- XLSX file with auto-width columns
- Headers in Russian
- Dates formatted as DD.MM.YYYY HH:MM

---

## Implementation Review

### ✅ Completed Features

All requirements from specification have been successfully implemented:

1. ✅ User Registration System
2. ✅ Admin Rights Management
3. ✅ Admin Menu
4. ✅ Broadcast Creation Flow
5. ✅ Broadcast Sending (both message and survey types)
6. ✅ Survey Questions Framework
7. ✅ Scheduled Broadcasts
8. ✅ Reminder System (with restoration after restart)
9. ✅ XLSX Data Export
10. ✅ Database Schema
11. ✅ Bot Lifecycle Management


### Job Scheduling

**Telegram JobQueue:**
- Accepts naive datetime (interpreted as UTC)
- `schedule_broadcast()` receives UTC time directly
- No double conversion needed

**Reminder Scheduling:**
```python
# sent_at is UTC
user_reminder_time = sent_at + timedelta(days=3)  # Still UTC
job_queue.run_once(when=user_reminder_time, ...)  # UTC time
```

### Restoration After Restart

**Scheduled Broadcasts:**
```python
# scheduled_time from DB is naive UTC
now_utc = datetime.utcnow()
if broadcast.scheduled_time > now_utc:
    schedule_broadcast(broadcast.id, broadcast.scheduled_time, job_queue)
```

**Reminders:**
```python
# sent_at from DB is naive UTC
now_utc = datetime.utcnow()
user_reminder_time = broadcast.sent_at + timedelta(days=3)
if user_reminder_time > now_utc:
    # Reschedule reminder
```

---

## Survey Questions

### Current Implementation

Questions are defined in `handlers/survey_questions.py` in the `SURVEY_QUESTIONS` list.

### Question Structure

```python
{
    "key": "q1",  # Unique identifier
    "text": "Question text",
    "type": "scale",  # or "buttons", "text"
    "options": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],  # For scale/buttons
    "required": True,  # Whether question can be skipped
    "followup": {  # Conditional follow-up questions
        "low": {"range": [1, 5], "question": {...}},
        "mid": {"range": [6, 7], "question": {...}},
        "high": {"range": [8, 10], "question": {...}}
    }
}
```

### Adding New Questions

1. Add question to `SURVEY_QUESTIONS` list
2. Set unique `key` for database storage
3. Define `type`, `text`, and `options`
4. Add `followup` if conditional logic needed
5. Test question flow

---

## Testing Guide

### Manual Testing Checklist

**Setup:**
- [ ] Add bot to group chat
- [ ] Send message as regular user (passive registration)
- [ ] Verify user appears in ChatMember table

**Admin Flow:**
- [ ] Run `/admin` command as admin
- [ ] Verify admin menu appears
- [ ] Check all menu buttons work

**Broadcast Creation:**
- [ ] Create immediate message broadcast
- [ ] Create immediate survey broadcast
- [ ] Create scheduled broadcast
- [ ] Verify datetime validation (format and future date)
- [ ] Cancel scheduled broadcast

**Survey Flow:**
- [ ] Receive survey in DM
- [ ] Complete survey with all question types
- [ ] Test conditional follow-up questions
- [ ] Verify answers saved to database

**Reminders:**
- [ ] Wait 3 days after broadcast (or adjust timedelta for testing)
- [ ] Verify user reminder received
- [ ] Verify "Продолжить опрос" button works
- [ ] Wait 3 days 2 hours
- [ ] Verify curator notification received with incomplete users list

**Data Export:**
- [ ] Export data as XLSX
- [ ] Verify all columns present
- [ ] Verify Russian headers
- [ ] Verify dates in Moscow timezone
- [ ] Verify question columns dynamic

**Bot Lifecycle:**
- [ ] Remove bot from chat
- [ ] Verify chat marked inactive
- [ ] Re-add bot to chat
- [ ] Verify chat reactivated
- [ ] Verify old registrations preserved

**Restart Resilience:**
- [ ] Schedule broadcast for future
- [ ] Restart bot
- [ ] Verify scheduled broadcast still executes
- [ ] Send survey
- [ ] Restart bot before 3 days
- [ ] Verify reminders still sent

### Unit Tests Needed

1. **timezone_utils.py**:
   - Moscow to UTC conversion
   - UTC to Moscow conversion
   - Naive datetime handling

2. **broadcast_creation.py**:
   - DateTime validation
   - Format checking
   - Future date validation

3. **broadcast_export.py**:
   - XLSX generation
   - Column mapping
   - Data formatting

---

## Deployment

### Environment Variables

```bash
TELEGRAM_BOT_TOKEN=your_bot_token
DATABASE_URL=postgresql://user:pass@host:port/dbname
```

### Dependencies

```txt
python-telegram-bot>=20.0
sqlalchemy>=2.0
openpyxl>=3.0
pytz>=2023.3
```

### Database Migration

Run migrations to create tables:
```bash
# Using Alembic or similar
alembic upgrade head
```

### Bot Startup

```bash
python main.py
```

**Startup Sequence:**
1. Initialize database connection
2. Initialize AmoCRM integration
3. Create bot application with persistence
4. Register handlers
5. Schedule job restoration (10 seconds after startup)
6. Schedule reminder restoration (12 seconds after startup)
7. Start polling

### Production Considerations

**Performance:**
- Admin status refresh can be slow for large chats (100+ members)
- XLSX export loads all data into memory (consider pagination for 10,000+ responses)
- Monitor job queue size (2 jobs per survey)

**Security:**
- Admin rights verified before all operations
- SQL injection protection via SQLAlchemy
- No sensitive data in logs
- Consider rate limiting on `/admin` command

**Monitoring:**
- Log all broadcast sends
- Log reminder sends
- Monitor failed DM sends
- Track job queue health

---

## Known Limitations

1. **Survey Resumption**: Users who start but don't complete can't resume from where they left off
2. **Scheduled Broadcast Editing**: Can only cancel, not edit. Must cancel and create new.
3. **Large Chat Performance**: Admin status refresh slow for 100+ member chats
4. **Export Size**: Memory-intensive for very large datasets (10,000+ responses)

---

## Future Enhancements

1. **Survey Analytics Dashboard**: Built-in analytics view in bot
2. **Survey Templates**: Save and reuse survey configurations
3. **Resume Survey**: Allow users to continue from last answered question
4. **Edit Scheduled Broadcasts**: Modify time/chats without recreating
5. **Pagination for Export**: Handle very large datasets efficiently
6. **Multiple Survey Templates**: Support different survey types
7. **Survey Results Preview**: View results in bot without downloading XLSX

---

## Support

For issues or questions, contact the development team or refer to:
- Code repository
- Database schema documentation
- Telegram Bot API documentation

---

**Last Updated**: February 3, 2026  
**Version**: 1.0  
**Status**: Production Ready
