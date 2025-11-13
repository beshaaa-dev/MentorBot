from database.task_service import (
    create_task as _create_task,
    update_task_status as _update_task_status,
)
from database.user_service import find_by_tg_id
from database.models import Task, TaskStatus
from logger import setup_logger
from crm_service import get_crm_lead

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

    mentor_id = lead.mentor_id
    if not mentor_id:
        raise ValueError(f"Lead with CRM ID {student.crm_id} has no mentor ID")

    task = _create_task(
        student_id=student.id,
        mentor_id=mentor_id,
        crm_id=student.crm_id,
        file_id=file_id,
        status=TaskStatus.UNCHECKED,
    )
    if not task:
        raise ValueError(f"Failed to create task for student {student.id}")
    logger.info(
        f"Created task with id={task.id}, student_id={student.id}, mentor_id={mentor_id}, crm_id={student.crm_id}"
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
