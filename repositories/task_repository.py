from dataclasses import dataclass

from database.task_service import (
    create_task as _create_task,
    update_task_status as _update_task_status,
    find_earliest_task as _find_earliest_task,
    get_task_by_id as _get_task_by_id,
    get_decided_tasks,
    get_tasks_by_status as _get_tasks_by_status,
    get_postponed_tasks as _get_postponed_tasks,
)
from database.user_service import find_by_tg_id, find_by_tg_nickname
from database.models import Task, TaskStatus
from logger import setup_logger
from crm.crm_service import (
    get_crm_lead,
    resolve_crm_contact,
    get_first_lead,
    update_lead_status_by_lead,
    send_note,
)
import config

logger = setup_logger(__name__)


class TaskStatusChangeNotAllowedError(Exception):
    pass


@dataclass
class TaskMessageData:
    """Data class for task message information."""

    file_id: str
    task_number: int  # 1, 2, or 3


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


def create_task(student_tg_id: int, task_messages: list[TaskMessageData]) -> Task:
    """
    Create a new task in the database with TaskMessages.

    Args:
        student_tg_id: Student Telegram user ID (required)
        task_messages: List of TaskMessageData objects (required)

    Returns:
        Created Task instance

    Raises:
        ValueError: If student with given Telegram ID is not found or student has no CRM ID
        Exception: If database operation fails
    """
    if not task_messages:
        raise ValueError(
            "Cannot create task: task_messages list is empty. "
            "At least one task message is required."
        )

    student = find_by_tg_id(student_tg_id)
    if not student:
        raise ValueError(
            f"Cannot create task: student not found in database. "
            f"Telegram ID: {student_tg_id}. "
            f"The student must register with the bot first."
        )

    crm_user = resolve_crm_contact(student.tg_id, student.tg_nickname)
    if not crm_user:
        raise ValueError(
            f"Cannot create task: CRM contact not found. "
            f"Student Telegram ID: {student_tg_id}, DB ID: {student.id}."
        )

    lead = get_first_lead(crm_user)
    if not lead:
        raise ValueError(
            f"Cannot create task: CRM lead not found. "
            f"Student Telegram ID: {student_tg_id}, DB ID: {student.id}. "
            f"The lead may have been deleted or the student has no active lead."
        )

    mentor_tg_nickname = lead.mentor_tg_nickname
    if not mentor_tg_nickname:
        raise ValueError(
            f"Cannot create task: no mentor assigned in CRM. "
            f"Student Telegram ID: {student_tg_id}, Lead ID: {lead.id}. "
            f"A mentor must be assigned to this lead in the CRM system."
        )
    mentor_tg_nickname = mentor_tg_nickname.lstrip("@")
    if not mentor_tg_nickname:
        raise ValueError(
            f"Cannot create task: mentor nickname is invalid (empty after removing '@'). "
            f"Student Telegram ID: {student_tg_id}, Lead ID: {lead.id}. "
            f"Please update the mentor's Telegram nickname in the CRM."
        )

    # Find mentor user by nickname
    mentor = find_by_tg_nickname(mentor_tg_nickname)
    if not mentor:
        raise ValueError(
            f"Cannot create task: mentor not found in database. "
            f"Mentor nickname: @{mentor_tg_nickname}, Student Telegram ID: {student_tg_id}. "
            f"The mentor must register with the bot before receiving tasks."
        )

    update_lead_status_by_lead(lead, config.CRM_TASK_IS_SENT_STATUS)

    # Convert TaskMessageData to dict format for database service
    task_messages_dict = [
        {"file_id": msg.file_id, "task_number": msg.task_number}
        for msg in task_messages
    ]

    task = _create_task(
        student_id=student.id,
        mentor_id=mentor.id,
        lead_id=lead.id,
        task_messages=task_messages_dict,
        status=TaskStatus.UNCHECKED,
    )
    if not task:
        raise ValueError(
            f"Cannot create task: database operation failed. "
            f"Student DB ID: {student.id}, Mentor DB ID: {mentor.id}, Lead ID: {lead.id}. "
            f"This may indicate a database connection issue or constraint violation."
        )

    logger.info(
        f"Created task with id={task.id}, student_id={student.id}, mentor_id={mentor.id}, lead_id={lead.id}, "
        f"with {len(task_messages)} task message(s)"
    )
    return task


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


def mark_task_as_failed(task_id: int):
    task = get_task_by_id(task_id)
    if not task:
        logger.warning(f"Task with id={task_id} not found")
        return

    send_note(
        task.lead_id,
        "Не удалось отправить задание наставнику: наставник не указан или не зарегистрирован в боте.",
    )


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
