import asyncio
from datetime import date, datetime, timezone

from amocrm.v2.entity.note import COMMON_TYPE
from telegram import Bot

from config import CRM_HOMEWORK_PIPELINE, CRM_HW_SUBMITTED_STATUS
from crm.crm_chat_service import send_media_to_chat, send_video_to_chat
from crm.crm_service import (
    get_crm_lead,
    update_lead_status_in_pipeline,
    upload_file,
    upload_video,
)
from crm.crm_models import Lead
from database.homework_service import (
    create_homework as _create_homework,
    get_homework_by_id as _get_homework_by_id,
    get_homework_by_lead_id as _get_homework_by_lead_id,
    update_homework as _update_homework,
    update_homework_status as _update_homework_status,
    upsert_homework_answers as _upsert_homework_answers,
    get_earliest_pending_mentor_homework as _get_earliest_pending_mentor_homework,
)
from database.models import Homework, HomeworkStatus
from database.user_service import find_by_tg_id, find_by_tg_nickname, get_by_id, update_user
from logger import setup_logger
from rate_limiter import amo_crm_rate_limiter
from timezone_utils import now_moscow

logger = setup_logger(__name__)


def process_homework_edit(lead_id: str) -> tuple[Homework, int, str]:
    """
    Получает лид из CRM, обновляет вопросы/дедлайн и статус → EDIT.

    Returns:
        (homework, student_tg_id, edit_reason)

    Raises:
        ValueError: если лид, студент или домашнее задание не найдены.
    """
    lead = get_crm_lead(lead_id)
    if not lead:
        raise ValueError(f"CRM lead {lead_id} not found")

    student_tg_id, _ = _extract_student_and_mentor(lead)

    edit_reason = getattr(lead, "hw_edit_reason", None) or "не указана"

    homework = _get_homework_by_lead_id(lead_id)
    if not homework:
        raise ValueError(f"No homework record for lead_id={lead_id}")

    questions = read_questions(lead)
    deadline = read_deadline(lead)

    homework = _update_homework(
        hw_id=homework.id,
        first_hw=questions[0] if questions else homework.first_hw,
        status=HomeworkStatus.EDIT,
        second_hw=questions[1] if len(questions) > 1 else None,
        third_hw=questions[2] if len(questions) > 2 else None,
        fourth_hw=questions[3] if len(questions) > 3 else None,
        fifth_hw=questions[4] if len(questions) > 4 else None,
        deadline=deadline,
    )
    logger.info(f"Updated homework id={homework.id} for edit, lead_id={lead_id}")
    return homework, student_tg_id, edit_reason


def process_homework_edit_from_mentor(lead_id: str) -> tuple[Homework, int, str]:
    """
    Получает лид из CRM, обновляет вопросы/дедлайн и статус → EDIT_FROM_MENTOR.

    Returns:
        (homework, student_tg_id, edit_reason)

    Raises:
        ValueError: если лид, студент или домашнее задание не найдены.
    """
    lead = get_crm_lead(lead_id)
    if not lead:
        raise ValueError(f"CRM lead {lead_id} not found")

    student_tg_id, _ = _extract_student_and_mentor(lead)

    edit_reason = getattr(lead, "hw_edit_reason_mentor", None) or ""

    homework = _get_homework_by_lead_id(lead_id)
    if not homework:
        raise ValueError(f"No homework record for lead_id={lead_id}")

    questions = read_questions(lead)
    deadline = read_deadline(lead)

    homework = _update_homework(
        hw_id=homework.id,
        first_hw=questions[0] if questions else homework.first_hw,
        status=HomeworkStatus.EDIT_FROM_MENTOR,
        second_hw=questions[1] if len(questions) > 1 else None,
        third_hw=questions[2] if len(questions) > 2 else None,
        fourth_hw=questions[3] if len(questions) > 3 else None,
        fifth_hw=questions[4] if len(questions) > 4 else None,
        deadline=deadline,
    )
    logger.info(f"Updated homework id={homework.id} for edit_from_mentor, lead_id={lead_id}")
    return homework, student_tg_id, edit_reason


def save_homework_from_webhook(lead_id: str) -> tuple[Homework, int]:
    """
    Fetch the CRM lead, resolve student + mentor, and persist a Homework record.
    Idempotent: returns the existing record if one already exists for this lead_id.

    Returns:
        (homework, student_tg_id)

    Raises:
        ValueError: if the lead, student or required fields are missing.
    """
    lead = get_crm_lead(lead_id)
    if not lead:
        raise ValueError(f"CRM lead {lead_id} not found")

    student_tg_id, mentor_tg_nickname = _extract_student_and_mentor(lead)

    student = find_by_tg_id(student_tg_id)
    if not student:
        raise ValueError(
            f"Student with tg_id={student_tg_id} not found in DB for lead {lead_id}"
        )

    mentor_id: int | None = None
    if mentor_tg_nickname:
        nickname = mentor_tg_nickname.lstrip("@")
        mentor = find_by_tg_nickname(nickname)
        if mentor:
            mentor_id = mentor.id
        else:
            logger.warning(f"Mentor @{nickname} not found in DB for lead {lead_id}")

    questions = read_questions(lead)
    if not questions:
        raise ValueError(f"No questions found on lead {lead_id}")

    deadline = read_deadline(lead)

    existing = _get_homework_by_lead_id(lead_id)
    if existing:
        homework = _update_homework(
            hw_id=existing.id,
            first_hw=questions[0],
            status=HomeworkStatus.PENDING,
            second_hw=questions[1] if len(questions) > 1 else None,
            third_hw=questions[2] if len(questions) > 2 else None,
            fourth_hw=questions[3] if len(questions) > 3 else None,
            fifth_hw=questions[4] if len(questions) > 4 else None,
            deadline=deadline,
            mentor_id=mentor_id,
        )
        logger.info(f"Updated homework id={existing.id} for lead_id={lead_id}")
        return homework, student_tg_id

    homework = _create_homework(
        student_id=student.id,
        lead_id=lead_id,
        status=HomeworkStatus.PENDING,
        first_hw=questions[0],
        second_hw=questions[1] if len(questions) > 1 else None,
        third_hw=questions[2] if len(questions) > 2 else None,
        fourth_hw=questions[3] if len(questions) > 3 else None,
        fifth_hw=questions[4] if len(questions) > 4 else None,
        deadline=deadline,
        mentor_id=mentor_id,
    )
    logger.info(
        f"Created homework id={homework.id} for student_id={student.id}, lead_id={lead_id}"
    )
    return homework, student_tg_id


def process_homework_for_mentor(lead_id: str) -> tuple[Homework, int, int]:
    """
    Получает лид из CRM, находит ментора и обновляет статус ДЗ → PENDING_MENTOR.

    Returns:
        (homework, mentor_tg_id, mentor_db_id)

    Raises:
        ValueError: если лид, ментор или запись ДЗ не найдены.
    """
    lead = get_crm_lead(lead_id)
    if not lead:
        raise ValueError(f"CRM lead {lead_id} not found")

    mentor_tg_nickname = getattr(lead, "mentor_tg_nickname", None)
    if not mentor_tg_nickname:
        raise ValueError(f"Lead {lead_id} has no mentor_tg_nickname")

    nickname = mentor_tg_nickname.lstrip("@")
    mentor = find_by_tg_nickname(nickname)
    if not mentor:
        raise ValueError(f"Mentor @{nickname} not found in DB for lead {lead_id}")

    if not mentor.tg_id:
        raise ValueError(f"Mentor @{nickname} has no tg_id")

    # Обновляем данные пользователей из CRM-контактов
    _sync_users_from_lead(lead)

    homework = _get_homework_by_lead_id(lead_id)
    if not homework:
        raise ValueError(f"No homework record for lead_id={lead_id}")

    homework = _update_homework_status(homework.id, HomeworkStatus.PENDING_MENTOR)
    logger.info(
        f"Homework id={homework.id} set to PENDING_MENTOR for mentor @{nickname}"
    )
    return homework, mentor.tg_id, mentor.id


def process_homework_accepted(lead_id: str) -> tuple[Homework, int]:
    """
    Получает лид из CRM, находит студента и домашнее задание.

    Returns:
        (homework, student_tg_id)

    Raises:
        ValueError: если лид, студент или запись ДЗ не найдены.
    """
    lead = get_crm_lead(lead_id)
    if not lead:
        raise ValueError(f"CRM lead {lead_id} not found")

    student_tg_id, _ = _extract_student_and_mentor(lead)

    homework = _get_homework_by_lead_id(lead_id)
    if not homework:
        raise ValueError(f"No homework record for lead_id={lead_id}")

    return homework, student_tg_id


def get_earliest_pending_homework_for_mentor(mentor_id: int) -> Homework | None:
    """Возвращает самое раннее ДЗ в статусе PENDING_MENTOR для данного ментора."""
    return _get_earliest_pending_mentor_homework(mentor_id)


def _extract_student_and_mentor(lead: Lead) -> tuple[int, str | None]:
    """Return (student_tg_id, mentor_tg_nickname) from lead's contact."""
    contact_refs = (lead._data.get("_embedded") or {}).get("contacts")
    if not contact_refs:
        raise ValueError(f"Lead {lead.id} has no embedded contacts")

    for contact in lead.contacts:
        raw_tg_id = contact.telegram_id
        if raw_tg_id:
            try:
                tg_id = int(str(raw_tg_id).strip())
            except ValueError:
                continue
            mentor_nickname = getattr(lead, "mentor_tg_nickname", None)
            _sync_user_from_contact(tg_id, contact)
            return tg_id, mentor_nickname

    raise ValueError(f"No contact with telegram_id found on lead {lead.id}")


def _sync_users_from_lead(lead: Lead) -> None:
    """Обновляет данные всех пользователей из CRM-контактов лида."""
    for contact in lead.contacts:
        raw_tg_id = contact.telegram_id
        if raw_tg_id:
            try:
                tg_id = int(str(raw_tg_id).strip())
                _sync_user_from_contact(tg_id, contact)
            except (ValueError, TypeError):
                pass


def _sync_user_from_contact(tg_id: int, contact) -> None:
    """Обновляет имя и tg_nickname пользователя в БД из данных CRM-контакта."""
    try:
        user = find_by_tg_id(tg_id)
        if not user:
            return

        contact_name = getattr(contact, "name", None) or ""
        tg_nickname = getattr(contact, "telegram_nickname", None)

        parts = contact_name.strip().split(maxsplit=1)
        first_name = parts[0] if parts else None
        last_name = parts[1] if len(parts) > 1 else None

        update_kwargs = {}
        if first_name:
            update_kwargs["first_name"] = first_name
        if last_name:
            update_kwargs["last_name"] = last_name
        if tg_nickname:
            update_kwargs["tg_nickname"] = tg_nickname.lstrip("@")

        if update_kwargs:
            update_user(user.id, **update_kwargs)
            logger.info(f"Synced user tg_id={tg_id} from CRM contact: {update_kwargs}")
    except Exception as e:
        logger.warning(f"Failed to sync user tg_id={tg_id} from CRM contact: {e}")


def read_questions(lead: Lead) -> list[str]:
    return [
        q
        for q in [
            lead.hw_question_1,
            lead.hw_question_2,
            lead.hw_question_3,
            lead.hw_question_4,
            lead.hw_question_5,
        ]
        if q
    ]


def read_deadline(lead: Lead) -> datetime | None:
    raw = lead.hw_deadline
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None)
    if isinstance(raw, date):
        return datetime(raw.year, raw.month, raw.day)
    try:
        ts = int(raw)
        return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


async def submit_student_answers(
    hw_id: int,
    answers: dict[int, dict],
    bot: Bot,
) -> None:
    """
    Upload video answers, write all CRM fields in one save, persist HomeworkAnswer rows,
    update homework status → SUBMITTED, update lead status → 84497010.

    `answers` format: {question_number: {"text": str|None, "file_id": str|None, "media_type": str}}
    media_type: "text" | "video" | "video_note" | "audio" | "voice" | "photo" | "document".
    "video"/"video_note" → Drive + chat; "audio"/"voice" → Drive + lead Files; "photo" → Drive + lead Files; "document" → Drive + chat (file).
    """
    loop = asyncio.get_running_loop()

    homework = await loop.run_in_executor(None, _get_homework_by_id, hw_id)
    if not homework:
        raise ValueError(f"Homework {hw_id} not found")

    lead = await loop.run_in_executor(None, get_crm_lead, homework.lead_id)
    if not lead:
        raise ValueError(f"CRM lead {homework.lead_id} not found")

    answer_rows: list[dict] = []
    answer_info: list[dict] = []
    text_field_map = {
        1: "hw_answer_1",
        2: "hw_answer_2",
        3: "hw_answer_3",
        4: "hw_answer_4",
        5: "hw_answer_5",
    }

    questions_total = sum(
        1
        for q in [
            homework.first_hw,
            homework.second_hw,
            homework.third_hw,
            homework.fourth_hw,
            homework.fifth_hw,
        ]
        if q
    )

    for q_num in range(1, 6):
        field_name = text_field_map[q_num]
        if q_num > questions_total:
            setattr(lead, field_name, "")
        else:
            data = answers.get(q_num, {})
            if data.get("media_type") == "text" and data.get("text"):
                setattr(lead, field_name, data["text"])
            else:
                setattr(lead, field_name, "Ответ в примечании")

    for q_num in sorted(answers.keys()):
        data = answers[q_num]
        text: str | None = data.get("text")
        file_id: str | None = data.get("file_id")
        media_type: str = data.get("media_type", "text")

        if media_type == "text" and text:
            content = text
            answer_info.append({"q_num": q_num, "type": "text", "text": text})
        elif media_type in ("video", "video_note"):
            download_url, file_size, filename = await _upload_answer_media(
                bot, file_id, q_num
            )
            content = file_id or ""
            answer_info.append(
                {
                    "q_num": q_num,
                    "type": "video",
                    "url": download_url,
                    "filename": filename,
                    "file_size": file_size,
                }
            )
        elif media_type in ("audio", "voice"):
            file_uuid, version_uuid, file_size, filename, download_url = await _upload_answer_audio(
                bot, file_id, q_num, media_type
            )
            content = file_id or ""
            answer_info.append(
                {
                    "q_num": q_num,
                    "type": "audio",
                    "uuid": file_uuid,
                    "version_uuid": version_uuid,
                    "filename": filename,
                    "file_size": file_size,
                    "download_url": download_url,
                }
            )
        elif media_type == "photo":
            file_uuid, version_uuid, file_size, filename, download_url = await _upload_answer_image(
                bot, file_id, q_num
            )
            content = file_id or ""
            answer_info.append(
                {
                    "q_num": q_num,
                    "type": "image",
                    "uuid": file_uuid,
                    "version_uuid": version_uuid,
                    "filename": filename,
                    "file_size": file_size,
                    "download_url": download_url,
                }
            )
        elif media_type == "document":
            file_uuid, version_uuid, file_size, filename, download_url = await _upload_answer_document(
                bot, file_id, q_num,
                original_filename=data.get("file_name"),
                mime_type=data.get("mime_type"),
            )
            content = file_id or ""
            answer_info.append(
                {
                    "q_num": q_num,
                    "type": "document",
                    "uuid": file_uuid,
                    "version_uuid": version_uuid,
                    "filename": filename,
                    "file_size": file_size,
                    "download_url": download_url,
                }
            )
        else:
            content = file_id or ""
            answer_info.append({"q_num": q_num, "type": "other"})

        answer_rows.append(
            {"question_number": q_num, "answer_content": content, "media_type": media_type}
        )

    now = now_moscow()
    completion_ts = int(now.timestamp())

    homework_deadline = homework.deadline
    missed_deadline = False
    if homework_deadline and now_moscow().replace(tzinfo=None) > homework_deadline:
        missed_deadline = True

    lead.hw_db_record_id = str(hw_id)
    lead.hw_completion_date = completion_ts
    lead.hw_deadline_missed = "Да" if missed_deadline else "Нет"

    contact_id, contact_name = await loop.run_in_executor(None, _get_contact_info, lead)

    def _save_lead():
        with amo_crm_rate_limiter.limit():
            lead.save()

    def _create_note(text: str) -> None:
        with amo_crm_rate_limiter.limit():
            lead.notes.objects.create(text=text, note_type=COMMON_TYPE)

    await loop.run_in_executor(None, _save_lead)

    for info in answer_info:
        q_num = info["q_num"]
        if info["type"] == "text":
            await loop.run_in_executor(
                None, _create_note, f"Ответ на Д/З № {q_num}: {info['text']}"
            )
        elif info["type"] == "video":
            video_url = info["url"]
            if video_url and contact_id:
                sent = await send_video_to_chat(
                    video_url=video_url,
                    contact_id=contact_id,
                    filename=info["filename"],
                    lead_id=int(homework.lead_id),
                    contact_name=contact_name,
                    file_size=info["file_size"],
                    text=f"Ответ на Д/З № {q_num}",
                )
                if not sent:
                    await loop.run_in_executor(
                        None,
                        _create_note,
                        f"Ответ на Д/З № {q_num} (видео): {video_url}",
                    )
            else:
                await loop.run_in_executor(
                    None,
                    _create_note,
                    f"Ответ на Д/З № {q_num} (видео): {video_url or 'не удалось загрузить'}",
                )
        elif info["type"] == "audio":
            dl_url = info.get("download_url")
            if dl_url and contact_id:
                sent = await send_media_to_chat(
                    media_url=dl_url,
                    contact_id=contact_id,
                    filename=info["filename"],
                    media_type="voice",
                    lead_id=int(homework.lead_id),
                    contact_name=contact_name,
                    file_size=info.get("file_size", 0),
                    text=f"Ответ на Д/З № {q_num} (аудио)",
                )
                if not sent:
                    await loop.run_in_executor(
                        None,
                        _create_note,
                        f"Ответ на Д/З № {q_num} (аудио): {dl_url}",
                    )
            else:
                await loop.run_in_executor(
                    None,
                    _create_note,
                    f"Ответ на Д/З № {q_num} (аудио): не удалось загрузить",
                )
        elif info["type"] == "image":
            dl_url = info.get("download_url")
            if dl_url and contact_id:
                sent = await send_media_to_chat(
                    media_url=dl_url,
                    contact_id=contact_id,
                    filename=info["filename"],
                    media_type="picture",
                    lead_id=int(homework.lead_id),
                    contact_name=contact_name,
                    file_size=info.get("file_size", 0),
                    text=f"Ответ на Д/З № {q_num} (фото)",
                )
                if not sent:
                    await loop.run_in_executor(
                        None,
                        _create_note,
                        f"Ответ на Д/З № {q_num} (фото): {dl_url}",
                    )
            else:
                await loop.run_in_executor(
                    None,
                    _create_note,
                    f"Ответ на Д/З № {q_num} (фото): не удалось загрузить",
                )
        elif info["type"] == "document":
            dl_url = info.get("download_url")
            if dl_url and contact_id:
                sent = await send_media_to_chat(
                    media_url=dl_url,
                    contact_id=contact_id,
                    filename=info["filename"],
                    media_type="file",
                    lead_id=int(homework.lead_id),
                    contact_name=contact_name,
                    file_size=info.get("file_size", 0),
                    text=f"Ответ на Д/З № {q_num} (файл)",
                )
                if not sent:
                    await loop.run_in_executor(
                        None,
                        _create_note,
                        f"Ответ на Д/З № {q_num} (файл): {dl_url}",
                    )
            else:
                await loop.run_in_executor(
                    None,
                    _create_note,
                    f"Ответ на Д/З № {q_num} (файл): не удалось загрузить",
                )
        else:
            await loop.run_in_executor(
                None,
                _create_note,
                f"Ответ на Д/З № {q_num} (медиафайл): передан в Telegram",
            )
    await loop.run_in_executor(None, _upsert_homework_answers, hw_id, answer_rows)
    await loop.run_in_executor(
        None, _update_homework_status, hw_id, HomeworkStatus.SUBMITTED
    )
    await loop.run_in_executor(
        None,
        update_lead_status_in_pipeline,
        lead,
        CRM_HOMEWORK_PIPELINE,
        CRM_HW_SUBMITTED_STATUS,
    )

    logger.info(f"Homework {hw_id} submitted successfully")


def _get_contact_info(lead) -> tuple[int | None, str]:
    for contact in lead.contacts:
        if contact.telegram_id:
            return contact.id, getattr(contact, "name", "") or ""
    return None, ""


async def _upload_answer_media(
    bot: Bot,
    file_id: str | None,
    q_num: int,
) -> tuple[str | None, int, str]:
    filename = f"hw_{q_num}_{(file_id or 'unknown')[:8]}.mp4"
    if not file_id:
        return None, 0, filename
    try:
        tg_file = await bot.get_file(file_id)
        file_bytes = await tg_file.download_as_bytearray()
        download_url, _ = await upload_video(bytes(file_bytes), filename)
        return download_url, len(file_bytes), filename
    except Exception as e:
        logger.error(f"Failed to upload media for question {q_num}: {e}", exc_info=True)
        return None, 0, filename


async def _upload_answer_audio(
    bot: Bot,
    file_id: str | None,
    q_num: int,
    media_type: str | None,
) -> tuple[str | None, str | None, int, str, str | None]:
    """Returns (file_uuid, version_uuid, file_size, filename, download_url). UUIDs are None on failure."""
    ext = "ogg" if media_type == "voice" else "mp3"
    content_type = "audio/ogg" if media_type == "voice" else "audio/mpeg"
    filename = f"hw_{q_num}_{(file_id or 'unknown')[:8]}.{ext}"
    if not file_id:
        return None, None, 0, filename, None
    try:
        tg_file = await bot.get_file(file_id)
        file_bytes = await tg_file.download_as_bytearray()
        file_uuid, version_uuid, _, download_url = await upload_file(
            bytes(file_bytes), filename, content_type
        )
        return file_uuid, version_uuid, len(file_bytes), filename, download_url
    except Exception as e:
        logger.error(f"Failed to upload audio for question {q_num}: {e}", exc_info=True)
        return None, None, 0, filename, None


async def _upload_answer_document(
    bot: Bot,
    file_id: str | None,
    q_num: int,
    original_filename: str | None = None,
    mime_type: str | None = None,
) -> tuple[str | None, str | None, int, str, str | None]:
    """Возвращает (file_uuid, version_uuid, file_size, filename, download_url)."""
    filename = original_filename or f"hw_{q_num}_{(file_id or 'unknown')[:8]}.bin"
    content_type = mime_type or "application/octet-stream"
    if not file_id:
        return None, None, 0, filename, None
    try:
        tg_file = await bot.get_file(file_id)
        file_bytes = await tg_file.download_as_bytearray()
        file_uuid, version_uuid, _, download_url = await upload_file(
            bytes(file_bytes), filename, content_type
        )
        return file_uuid, version_uuid, len(file_bytes), filename, download_url
    except Exception as e:
        logger.error(f"Failed to upload document for question {q_num}: {e}", exc_info=True)
        return None, None, 0, filename, None


async def _upload_answer_image(
    bot: Bot,
    file_id: str | None,
    q_num: int,
) -> tuple[str | None, str | None, int, str, str | None]:
    """Returns (file_uuid, version_uuid, file_size, filename, download_url). UUIDs are None on failure."""
    filename = f"hw_{q_num}_{(file_id or 'unknown')[:8]}.jpg"
    if not file_id:
        return None, None, 0, filename, None
    try:
        tg_file = await bot.get_file(file_id)
        file_bytes = await tg_file.download_as_bytearray()
        file_uuid, version_uuid, _, download_url = await upload_file(
            bytes(file_bytes), filename, "image/jpeg"
        )
        return file_uuid, version_uuid, len(file_bytes), filename, download_url
    except Exception as e:
        logger.error(f"Failed to upload image for question {q_num}: {e}", exc_info=True)
        return None, None, 0, filename, None
