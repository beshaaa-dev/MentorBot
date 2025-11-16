from database.task_service import (
    create_task as _create_task,
    update_task_status as _update_task_status,
    find_earliest_task as _find_earliest_task,
    get_next_task as _get_next_task,
    get_previous_task as _get_previous_task,
    get_task_by_id as _get_task_by_id,
)
from database.user_service import find_by_tg_id, find_by_tg_nickname
from database.models import Task, TaskStatus
from logger import setup_logger
from crm_service import get_crm_lead, update_lead_status
from repositories.user_repository import create_mentor_if_needed, get_first_lead

logger = setup_logger(__name__)


def create_task(student_tg_id: int, file_id: str) -> Task:
    """
    Create a new task in the database.

    Args:
        student_tg_id: Student Telegram user ID (required)
        file_id: Telegram video file ID (required)

    Returns:
        Created Task instance

    Raises:
        ValueError: If student with given Telegram ID is not found or student has no CRM ID
        Exception: If database operation fails
    """
    student = find_by_tg_id(student_tg_id)
    if not student:
        raise ValueError(f"Student with Telegram ID {student_tg_id} not found")

    if not student.crm_id:
        raise ValueError(f"Student with Telegram ID {student_tg_id} has no CRM ID")

    lead = get_crm_lead(student.crm_id)
    if not lead:
        raise ValueError(f"Lead with CRM ID {student.crm_id} not found")

    mentor_tg_nickname = lead.mentor_tg_nickname
    if not mentor_tg_nickname:
        raise ValueError(f"Lead with CRM ID {student.crm_id} has no mentor ID")

    # Find mentor user by nickname
    mentor = find_by_tg_nickname(mentor_tg_nickname)
    if not mentor:
        raise ValueError(
            f"Mentor with Telegram nickname {mentor_tg_nickname} not found"
        )

    update_lead_status(student.crm_id, "А2")

    task = _create_task(
        student_id=student.id,
        mentor_id=mentor.id,
        # TODO: change to lead_id
        lead_id=student.crm_id,
        file_id=file_id,
        status=TaskStatus.UNCHECKED,
    )
    if not task:
        raise ValueError(f"Failed to create task for student {student.id}")

    logger.info(
        f"Created task with id={task.id}, student_id={student.id}, mentor_id={mentor.id}, lead_id={student.crm_id}"
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
        logger.warning(f"Task with id={task_id} not found")
        return

    update_lead_status(task.lead_id, "А3")


def disapprove_task(task_id: int):
    """
    Disapprove task for user.

    Args:
        task_id: Task ID
    """
    task = get_task_by_id(task_id)
    if not task:
        logger.warning(f"Task with id={task_id} not found")
        return

    update_lead_status(task.lead_id, "А4")


def get_next_task(mentor_id: int, current_task_id: int) -> Task | None:
    """
    Get the next task after the current task for a given mentor_id.

    Args:
        mentor_id: Mentor user ID (required)
        current_task_id: Current task ID (required)

    Returns:
        Next Task instance if found, None otherwise

    Raises:
        Exception: If database operation fails
    """
    task = _get_next_task(mentor_id, current_task_id)
    if task:
        logger.info(
            f"Found next task with id={task.id} for mentor_id={mentor_id} after task {current_task_id}"
        )
    return task


def get_previous_task(
    mentor_id: int, current_task_id: int | None = None
) -> Task | None:
    """
    Get the previous task before the current task for a given mentor_id.
    Only returns tasks updated within the last 60 minutes.
    If current_task_id is provided, only returns tasks created before it.

    Args:
        mentor_id: Mentor user ID (required)
        current_task_id: Current task ID (optional). If provided, excludes this task and only returns tasks created before it.

    Returns:
        Previous Task instance if found, None otherwise

    Raises:
        Exception: If database operation fails
    """
    task = _get_previous_task(mentor_id, current_task_id)
    if task:
        if current_task_id is not None:
            logger.info(
                f"Found previous task with id={task.id} for mentor_id={mentor_id} before task {current_task_id}"
            )
        else:
            logger.info(
                f"Found previous task with id={task.id} for mentor_id={mentor_id} updated within last 60 minutes"
            )
    return task


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
