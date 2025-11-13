from database.task_service import (
    create_task as _create_task,
    update_task_status as _update_task_status,
    find_earliest_task as _find_earliest_task,
)
from database.user_service import find_by_tg_id, find_by_tg_nickname
from database.models import Task, TaskStatus
from logger import setup_logger
from crm_service import get_crm_lead, update_lead_status, get_crm_user as _get_crm_user
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
        crm_id=student.crm_id,
        file_id=file_id,
        status=TaskStatus.UNCHECKED,
    )
    if not task:
        raise ValueError(f"Failed to create task for student {student.id}")

    logger.info(
        f"Created task with id={task.id}, student_id={student.id}, mentor_id={mentor.id}, crm_id={student.crm_id}"
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
    If no such tasks exist, return the earliest task with status CHECK_LATER.

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

    # If no UNCHECKED tasks, try CHECK_LATER
    task = _find_earliest_task(mentor_id, TaskStatus.CHECK_LATER)
    if task:
        logger.info(
            f"Found earliest CHECK_LATER task with id={task.id} for mentor_id={mentor_id}"
        )
        return task

    logger.info(
        f"No tasks found for mentor_id={mentor_id} with status UNCHECKED or CHECK_LATER"
    )
    return None


def approve_task(user_crm_id: str):
    """
    Approve task for user.

    Args:
        user_crm_id: CRM user ID
    """
    crm_user = _get_crm_user(user_crm_id)
    if not crm_user:
        logger.warning(f"CRM user with id={user_crm_id} not found")
        return False

    first_lead = get_first_lead(crm_user)
    if not first_lead:
        logger.warning(f"No leads found for CRM user id={crm_user.id}")
        return False

    update_lead_status(first_lead.id, "А4")
    return


def disapprove_task(user_crm_id: str):
    """
    Disapprove task for user.

    Args:
        user_crm_id: CRM user ID
    """
    crm_user = _get_crm_user(user_crm_id)
    if not crm_user:
        logger.warning(f"CRM user with id={user_crm_id} not found")
        return

    first_lead = get_first_lead(crm_user)
    if not first_lead:
        logger.warning(f"No leads found for CRM user id={crm_user.id}")
        return

    update_lead_status(first_lead.id, "А5")
    return
