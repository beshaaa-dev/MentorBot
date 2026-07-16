import asyncio
from dataclasses import dataclass

from telegram import Bot

from database.task_service import (
    create_task_from_lead as _create_task_from_lead,
    get_active_task_by_lead_id as _get_active_task_by_lead_id,
    get_latest_task_by_lead_id as _get_latest_task_by_lead_id,
    update_task as _update_task,
    update_task_status as _update_task_status,
    upsert_task_answers as _upsert_task_answers,
    find_earliest_task as _find_earliest_task,
    get_task_by_id as _get_task_by_id,
    get_decided_tasks,
    get_tasks_by_status as _get_tasks_by_status,
    get_postponed_tasks as _get_postponed_tasks,
)
from database.user_service import find_by_tg_id, find_by_tg_nickname
from database.models import Task, TaskStatus
from logger import setup_logger
from crm.crm_models import Lead
from crm.crm_service import (
    get_crm_lead,
    save_entity,
    update_lead_status_by_lead,
    update_lead_status_in_pipeline,
)
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
import config

logger = setup_logger(__name__)


class TaskStatusChangeNotAllowedError(Exception):
    pass


@dataclass
class DecidedTaskContext:
    task: Task
    index: int
    total: int
    older_task_id: int | None
    newer_task_id: int | None
    cached_task_ids: list[int]


@dataclass
class PostponedTaskContext:
    task: Task
    index: int
    total: int
    older_task_id: int | None
    newer_task_id: int | None
    cached_task_ids: list[int]


def read_questions(lead: Lead) -> list[str]:
    return [q for q in [lead.first_task, lead.second_task, lead.third_task] if q]


def _resolve_mentor_id(lead: Lead, lead_id: str) -> int | None:
    """
    Отсутствие ментора не блокирует выдачу задания студенту — наставник может
    появиться в CRM позже, к моменту проверки.
    """
    from repositories.user_repository import create_mentor_if_needed

    mentor_tg_nickname = getattr(lead, "mentor_tg_nickname", None)
    if not mentor_tg_nickname:
        logger.warning(f"Lead {lead_id} has no mentor_tg_nickname")
        return None

    nickname = mentor_tg_nickname.lstrip("@")
    create_mentor_if_needed(nickname)

    mentor = find_by_tg_nickname(nickname)
    if not mentor:
        logger.warning(f"Mentor @{nickname} not found in DB for lead {lead_id}")
        return None
    return mentor.id


def save_task_from_webhook(lead_id: str) -> tuple[Task, int]:
    """  
    Returns:
        (task, student_tg_id)

    Raises:
        ValueError: if the lead, student or required fields are missing.
    """
    lead = get_crm_lead(lead_id)
    if not lead:
        raise ValueError(f"CRM lead {lead_id} not found")

    student = None
    student_tg_id = None

    try:
        student_tg_id, _ = extract_student_and_mentor(lead)
        student = find_by_tg_id(student_tg_id)
    except ValueError:
        logger.warning(
            "save_task_from_webhook: tg_id lookup failed for lead_id=%s, trying tg_nickname",
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
                    sync_contact_from_user(contact, student)
                    logger.info(
                        "save_task_from_webhook: resolved student by tg_nickname=@%s for lead_id=%s",
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
            lead, "Не получилось отправить тестовое из-за отсутствующих тг айди и ника"
        )
        raise ValueError(f"Student not found by tg_id or tg_nickname for lead {lead_id}")

    questions = read_questions(lead)
    if not questions:
        raise ValueError(f"No tasks found on lead {lead_id}")

    deadline = read_deadline(lead.task_deadline)
    mentor_id = _resolve_mentor_id(lead, lead_id)

    existing = _get_active_task_by_lead_id(lead_id)
    if existing:
        task = _update_task(
            task_id=existing.id,
            first_task=questions[0],
            status=TaskStatus.PENDING,
            second_task=questions[1] if len(questions) > 1 else None,
            third_task=questions[2] if len(questions) > 2 else None,
            deadline=deadline,
            mentor_id=mentor_id,
        )
        logger.info(f"Updated task id={existing.id} for lead_id={lead_id}")
        return task, student_tg_id

    task = _create_task_from_lead(
        student_id=student.id,
        lead_id=lead_id,
        status=TaskStatus.PENDING,
        first_task=questions[0],
        second_task=questions[1] if len(questions) > 1 else None,
        third_task=questions[2] if len(questions) > 2 else None,
        deadline=deadline,
        mentor_id=mentor_id,
    )
    logger.info(
        f"Created task id={task.id} for student_id={student.id}, lead_id={lead_id}"
    )
    return task, student_tg_id


def process_task_edit(lead_id: str) -> tuple[Task, int, str]:
    """
    Returns:
        (task, student_tg_id, edit_reason)

    Raises:
        ValueError: если лид, студент или задание не найдены.
    """
    lead = get_crm_lead(lead_id)
    if not lead:
        raise ValueError(f"CRM lead {lead_id} not found")

    student_tg_id, _ = extract_student_and_mentor(lead)

    edit_reason = getattr(lead, "task_edit_reason", None) or "не указана"

    task = _get_latest_task_by_lead_id(lead_id)
    if not task:
        raise ValueError(f"No task record for lead_id={lead_id}")

    questions = read_questions(lead)
    deadline = read_deadline(lead.task_deadline)

    task = _update_task(
        task_id=task.id,
        first_task=questions[0] if questions else task.first_task,
        status=TaskStatus.EDIT,
        second_task=questions[1] if len(questions) > 1 else None,
        third_task=questions[2] if len(questions) > 2 else None,
        deadline=deadline,
        edit_reason=edit_reason,
    )
    logger.info(f"Updated task id={task.id} for edit, lead_id={lead_id}")
    return task, student_tg_id, edit_reason


def process_task_for_mentor(lead_id: str) -> tuple[Task, int, int]:
    """
    Returns:
        (task, mentor_tg_id, mentor_db_id)

    Raises:
        ValueError: если лид, ментор или задание не найдены.
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

    sync_users_from_lead(lead)

    # Берём самое свежее задание в любом статусе: куратор может вернуть лид в этот
    # статус повторно — наставника нужно уведомить снова
    task = _get_latest_task_by_lead_id(lead_id)
    if not task:
        raise ValueError(f"No task record for lead_id={lead_id}")

    task = _update_task_status(task.id, TaskStatus.UNCHECKED)
    if task.mentor_id != mentor.id:
        task = _update_task(
            task_id=task.id,
            first_task=task.first_task,
            second_task=task.second_task,
            third_task=task.third_task,
            deadline=task.deadline,
            mentor_id=mentor.id,
        )

    logger.info(f"Task id={task.id} set to UNCHECKED for mentor @{nickname}")
    return task, mentor.tg_id, mentor.id


async def submit_student_task_answers(
    task_id: int,
    answers: dict[int, dict],
    bot: Bot,
) -> None:
    """
    `answers` format: {question_number: {"text": str|None, "file_id": str|None, "media_type": str}}
    """
    loop = asyncio.get_running_loop()

    task = await loop.run_in_executor(None, _get_task_by_id, task_id)
    if not task:
        raise ValueError(f"Task {task_id} not found")

    lead = await loop.run_in_executor(None, get_crm_lead, task.lead_id)
    if not lead:
        raise ValueError(f"CRM lead {task.lead_id} not found")

    text_field_map = {1: "task_answer_1", 2: "task_answer_2", 3: "task_answer_3"}
    questions_total = sum(
        1 for q in [task.first_task, task.second_task, task.third_task] if q
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

    answer_rows, answer_info = await prepare_answers(bot, answers, file_prefix="task")

    lead.task_db_record_id = str(task_id)
    lead.task_completion_date = int(now_moscow().timestamp())
    lead.task_deadline_missed = "Да" if is_deadline_missed(task.deadline) else "Нет"

    contact_id, contact_name = await loop.run_in_executor(None, get_contact_info, lead)

    def _save_lead():
        with amo_crm_rate_limiter.limit():
            save_entity(lead)

    await loop.run_in_executor(None, _save_lead)

    await push_answers_to_crm(
        lead=lead,
        lead_id=task.lead_id,
        answer_info=answer_info,
        label="задание",
        contact_id=contact_id,
        contact_name=contact_name,
    )

    await loop.run_in_executor(None, _upsert_task_answers, task_id, answer_rows)
    await loop.run_in_executor(
        None, _update_task_status, task_id, TaskStatus.SUBMITTED
    )
    await loop.run_in_executor(
        None,
        update_lead_status_in_pipeline,
        lead,
        config.CRM_SELECTION_PIPELINE,
        config.CRM_TASK_SUBMITTED_STATUS,
    )

    logger.info(f"Task {task_id} submitted successfully")


def update_task_status(task_id: int, status: TaskStatus) -> Task | None:
    """
    Update the status of an existing task in the database.

    Args:
        task_id: Database task ID (required)
        status: Task status (required)

    Returns:
        Updated Task instance if found, None otherwise

    Raises:
        Exception: If database operation fails
    """
    task = _update_task_status(task_id=task_id, status=status)
    if task:
        logger.info(f"Updated task with id={task_id}, status={status.value}")
    else:
        logger.warning(f"Task with id={task_id} not found")
    return task


def get_earliest_task(mentor_id: int) -> Task | None:
    """
    Get the earliest task for a given mentor_id with status UNCHECKED.

    Args:
        mentor_id: Mentor user ID (required)

    Returns:
        Earliest Task instance if found, None otherwise

    Raises:
        Exception: If database operation fails
    """
    # First try to find earliest UNCHECKED task
    task = _find_earliest_task(mentor_id, TaskStatus.UNCHECKED)
    if task:
        logger.info(
            f"Found earliest UNCHECKED task with id={task.id} for mentor_id={mentor_id}"
        )
        return task

    logger.info(f"No tasks found for mentor_id={mentor_id} with status UNCHECKED")
    return None


def approve_task(task_id: int):
    """
    Approve task for user.

    Args:
        task_id: Task ID
    """
    task = get_task_by_id(task_id)
    if not task:
        raise ValueError(f"Task with id={task_id} not found")

    lead = get_crm_lead(task.lead_id)

    if not lead:
        raise ValueError(f"CRM lead with id={task.lead_id} not found; skipping approve")

    if not lead.status:
        raise ValueError(
            f"CRM lead with id={task.lead_id} has no status; skipping approve"
        )

    if str(lead.status.id) in {"142", "143"}:
        raise TaskStatusChangeNotAllowedError(
            f"Cannot approve task_id={task_id} because lead_id={task.lead_id} has status 142 or 143"
        )

    update_lead_status_by_lead(lead, config.CRM_TASK_IS_APPROVED_STATUS)


def disapprove_task(task_id: int):
    """
    Disapprove task for user.

    Args:
        task_id: Task ID
    """
    task = get_task_by_id(task_id)
    if not task:
        raise ValueError(f"Task with id={task_id} not found")

    lead = get_crm_lead(task.lead_id)
    if not lead:
        raise ValueError(
            f"CRM lead with id={task.lead_id} not found; skipping disapprove"
        )

    if not lead.status:
        raise ValueError(
            f"CRM lead with id={task.lead_id} has no status; skipping disapprove"
        )

    if str(lead.status.id) in {"142", "143"}:
        raise TaskStatusChangeNotAllowedError(
            f"Cannot disapprove task_id={task_id} because lead_id={task.lead_id} has status 142 or 143"
        )

    update_lead_status_by_lead(lead, config.CRM_TASK_IS_DISAPPROVED_STATUS)


def postpone_task(task_id: int):
    """
    Postpone task for user (mentor pressed "Сомневаюсь").

    Args:
        task_id: Task ID
    """
    task = get_task_by_id(task_id)
    if not task:
        raise ValueError(f"Task with id={task_id} not found")

    lead = get_crm_lead(task.lead_id)
    if not lead:
        raise ValueError(
            f"CRM lead with id={task.lead_id} not found; skipping postpone"
        )

    if not lead.status:
        raise ValueError(
            f"CRM lead with id={task.lead_id} has no status; skipping postpone"
        )

    if str(lead.status.id) in {"142", "143"}:
        raise TaskStatusChangeNotAllowedError(
            f"Cannot postpone task_id={task_id} because lead_id={task.lead_id} has status 142 or 143"
        )

    update_lead_status_by_lead(lead, config.CRM_TASK_IS_POSTPONED_STATUS)




def get_task_by_id(task_id: int) -> Task | None:
    """
    Get a task by its ID.

    Args:
        task_id: Task ID (required)

    Returns:
        Task instance if found, None otherwise

    Raises:
        Exception: If database operation fails
    """
    return _get_task_by_id(task_id)


def get_decided_task_context(
    mentor_id: int,
    target_task_id: int | None = None,
    cached_task_ids: list[int] | None = None,
) -> DecidedTaskContext | None:
    """
    Build pagination context for decided tasks within the last hour.

    Args:
        mentor_id: Mentor user ID.
        target_task_id: Task ID to navigate to (optional).
        cached_task_ids: Pre-cached list of task IDs to preserve navigation order.

    Returns:
        DecidedTaskContext or None if nothing to show.
    """
    if cached_task_ids is not None:
        task_ids = cached_task_ids
    else:
        tasks = get_decided_tasks(mentor_id)
        task_ids = [task.id for task in tasks]

    if not task_ids:
        return None

    index = 0
    if target_task_id is not None:
        try:
            index = task_ids.index(target_task_id)
        except ValueError:
            index = 0

    task = _get_task_by_id(task_ids[index])
    if not task:
        return None

    total = len(task_ids)
    older_task_id = task_ids[index + 1] if index + 1 < total else None
    newer_task_id = task_ids[index - 1] if index - 1 >= 0 else None

    return DecidedTaskContext(
        task=task,
        index=index,
        total=total,
        older_task_id=older_task_id,
        newer_task_id=newer_task_id,
        cached_task_ids=task_ids,
    )


def get_tasks_for_mentor_by_status(mentor_id: int, status: TaskStatus) -> list[Task]:
    """
    Fetch all mentor tasks that match provided status, newest first.
    """
    tasks = _get_tasks_by_status(mentor_id, status)
    logger.info(
        f"Retrieved {len(tasks)} tasks with status={status.value} for mentor_id={mentor_id}"
    )
    return tasks


def get_postponed_task_context(
    mentor_id: int,
    target_task_id: int | None = None,
    cached_task_ids: list[int] | None = None,
) -> PostponedTaskContext | None:
    """
    Создает контекст для навигации по отложенным заявкам.

    Args:
        mentor_id: Mentor user ID.
        target_task_id: Task ID to navigate to (optional).
        cached_task_ids: Pre-cached list of task IDs to preserve navigation order.

    Returns:
        PostponedTaskContext or None if nothing to show.
    """
    if cached_task_ids is not None:
        task_ids = cached_task_ids
    else:
        tasks = _get_postponed_tasks(mentor_id)
        task_ids = [task.id for task in tasks]

    if not task_ids:
        return None

    index = 0
    if target_task_id is not None:
        try:
            index = task_ids.index(target_task_id)
        except ValueError:
            index = 0

    task = _get_task_by_id(task_ids[index])
    if not task:
        return None

    total = len(task_ids)
    older_task_id = task_ids[index - 1] if index - 1 >= 0 else None
    newer_task_id = task_ids[index + 1] if index + 1 < total else None

    return PostponedTaskContext(
        task=task,
        index=index,
        total=total,
        older_task_id=older_task_id,
        newer_task_id=newer_task_id,
        cached_task_ids=task_ids,
    )
