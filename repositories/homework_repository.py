import asyncio

from telegram import Bot

from config import CRM_HOMEWORK_PIPELINE, CRM_HW_SUBMITTED_STATUS
from crm.crm_service import get_crm_lead, save_entity, update_lead_status_in_pipeline
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
from database.user_service import find_by_tg_id, find_by_tg_nickname
from logger import setup_logger
from rate_limiter import amo_crm_rate_limiter
from repositories.crm_answers import (
    append_lead_tag,
    create_lead_note,
    extract_student_and_mentor,
    fetch_lead_contacts,
    get_contact_info,
    is_deadline_missed,
    prepare_answers,
    push_answers_to_crm,
    read_deadline,
    sync_contact_from_user,
    sync_users_from_lead,
)
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

    student_tg_id, _ = extract_student_and_mentor(lead)

    edit_reason = getattr(lead, "hw_edit_reason", None) or "не указана"

    homework = _get_homework_by_lead_id(lead_id)
    if not homework:
        raise ValueError(f"No homework record for lead_id={lead_id}")

    questions = read_questions(lead)
    deadline = read_deadline(lead.hw_deadline)

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

    student_tg_id, _ = extract_student_and_mentor(lead)

    edit_reason = getattr(lead, "hw_edit_reason_mentor", None) or ""

    homework = _get_homework_by_lead_id(lead_id)
    if not homework:
        raise ValueError(f"No homework record for lead_id={lead_id}")

    questions = read_questions(lead)
    deadline = read_deadline(lead.hw_deadline)

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
    logger.info(
        f"Updated homework id={homework.id} for edit_from_mentor, lead_id={lead_id}"
    )
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

    student = None
    student_tg_id = None
    mentor_tg_nickname = None

    try:
        student_tg_id, mentor_tg_nickname = extract_student_and_mentor(lead)
        student = find_by_tg_id(student_tg_id)
    except ValueError:
        logger.warning(
            "save_homework_from_webhook: tg_id lookup failed for lead_id=%s, trying tg_nickname",
            lead_id,
        )

    if not student:
        # Фоллбэк: поиск по telegram_nickname (поле 536049)
        for contact in fetch_lead_contacts(lead):
            nickname = getattr(contact, "telegram_nickname", None)
            if nickname:
                nickname = nickname.lstrip("@")
                student = find_by_tg_nickname(nickname)
                if student and student.tg_id:
                    student_tg_id = student.tg_id
                    mentor_tg_nickname = getattr(lead, "mentor_tg_nickname", None)
                    sync_contact_from_user(contact, student)
                    logger.info(
                        "save_homework_from_webhook: resolved student by tg_nickname=@%s for lead_id=%s",
                        nickname,
                        lead_id,
                    )
                    break
                student = None

    if not student:
        append_lead_tag(lead, "Ошибка бот")
        with amo_crm_rate_limiter.limit():
            save_entity(lead)
        create_lead_note(
            lead, "Не получилось отправить домашку из-за отсутствующих тг айди и ника"
        )
        raise ValueError(
            f"Student not found by tg_id or tg_nickname for lead {lead_id}"
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

    deadline = read_deadline(lead.hw_deadline)

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
    sync_users_from_lead(lead)

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

    student_tg_id, _ = extract_student_and_mentor(lead)

    homework = _get_homework_by_lead_id(lead_id)
    if not homework:
        raise ValueError(f"No homework record for lead_id={lead_id}")

    return homework, student_tg_id


def get_earliest_pending_homework_for_mentor(mentor_id: int) -> Homework | None:
    """Возвращает самое раннее ДЗ в статусе PENDING_MENTOR для данного ментора."""
    return _get_earliest_pending_mentor_homework(mentor_id)


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


async def submit_student_answers(
    hw_id: int,
    answers: dict[int, dict],
    bot: Bot,
) -> None:
    """
    Upload media answers, write all CRM fields in one save, persist HomeworkAnswer rows,
    update homework status → SUBMITTED, move the lead to CRM_HW_SUBMITTED_STATUS.

    `answers` format: {question_number: {"text": str|None, "file_id": str|None, "media_type": str}}
    """
    loop = asyncio.get_running_loop()

    homework = await loop.run_in_executor(None, _get_homework_by_id, hw_id)
    if not homework:
        raise ValueError(f"Homework {hw_id} not found")

    lead = await loop.run_in_executor(None, get_crm_lead, homework.lead_id)
    if not lead:
        raise ValueError(f"CRM lead {homework.lead_id} not found")

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

    for q_num, field_name in text_field_map.items():
        if q_num > questions_total:
            setattr(lead, field_name, "")
        else:
            data = answers.get(q_num, {})
            if data.get("media_type") == "text" and data.get("text"):
                setattr(lead, field_name, data["text"])
            else:
                setattr(lead, field_name, "Ответ в примечании")

    answer_rows, answer_info = await prepare_answers(bot, answers, file_prefix="hw")

    lead.hw_db_record_id = str(hw_id)
    lead.hw_completion_date = int(now_moscow().timestamp())
    lead.hw_deadline_missed = "Да" if is_deadline_missed(homework.deadline) else "Нет"

    contact_id, contact_name = await loop.run_in_executor(None, get_contact_info, lead)

    def _save_lead():
        with amo_crm_rate_limiter.limit():
            save_entity(lead)

    await loop.run_in_executor(None, _save_lead)

    await push_answers_to_crm(
        lead=lead,
        lead_id=homework.lead_id,
        answer_info=answer_info,
        label="Д/З",
        contact_id=contact_id,
        contact_name=contact_name,
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
