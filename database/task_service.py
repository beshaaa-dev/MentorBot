from database.db_helper import get_db
from database.models import Task, TaskStatus
from datetime import datetime
from logger import setup_logger

logger = setup_logger(__name__)


def create_task(
    student_id: int,
    mentor_id: int,
    lead_id: str,
    file_id: str,
    status: TaskStatus = TaskStatus.UNCHECKED,
) -> Task:
    """
    Create a new task in the database.

    Args:
        student_id: Student user ID (required)
        mentor_id: Mentor user ID (required)
        lead_id: AmoCRM lead ID (required)
        file_id: File ID (required)
        status: Task status (optional, default is UNCHECKED)

    Returns:
        Created Task instance

    Raises:
        Exception: If database operation fails
    """
    with get_db() as db:
        try:
            task = Task(
                student_id=student_id,
                mentor_id=mentor_id,
                lead_id=lead_id,
                file_id=file_id,
                status=status,
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            return task
        except Exception as e:
            db.rollback()
            raise


def get_task_by_id(task_id: int) -> Task | None:
    with get_db() as db:
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            return task
        except Exception as e:
            logger.error(f"Error getting task {task_id}: {e}")
            raise


def update_task_status(task_id: int, status: TaskStatus | None = None) -> Task | None:
    """
    Update the status of an existing task in the database.

    Args:
        task_id: Database task ID (required)
        status: Task status (optional)

    Returns:
        Updated Task instance if found, None otherwise

    Raises:
        Exception: If database operation fails
    """
    with get_db() as db:
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task:
                return None

            if status is not None:
                task.status = status

            db.commit()
            db.refresh(task)
            return task
        except Exception as e:
            db.rollback()
            raise


def find_earliest_task(mentor_id: int, status: TaskStatus) -> Task | None:
    """
    Find the earliest task for a given mentor_id with a specific status.

    Args:
        mentor_id: Mentor user ID (required)
        status: Task status (required)

    Returns:
        Earliest Task instance if found, None otherwise

    Raises:
        Exception: If database operation fails
    """
    with get_db() as db:
        try:
            task = (
                db.query(Task)
                .filter(Task.mentor_id == mentor_id, Task.status == status)
                .order_by(Task.created_at.asc())
                .first()
            )
            return task
        except Exception as e:
            logger.error(
                f"Error finding task for mentor {mentor_id} with status {status}: {e}"
            )
            raise


def get_next_task(mentor_id: int, current_task_id: int) -> Task | None:
    """
    Get the next task after the current task for a given mentor_id.
    Only considers tasks with status UNCHECKED.

    Args:
        mentor_id: Mentor user ID (required)
        current_task_id: Current task ID (required)

    Returns:
        Next Task instance if found, None otherwise

    Raises:
        Exception: If database operation fails
    """
    with get_db() as db:
        try:
            # Get current task to know its created_at timestamp
            current_task = db.query(Task).filter(Task.id == current_task_id).first()
            if not current_task:
                return None

            # Find next task with UNCHECKED status, created after current task
            task = (
                db.query(Task)
                .filter(
                    Task.mentor_id == mentor_id,
                    Task.id != current_task_id,
                    Task.created_at > current_task.created_at,
                    Task.status == TaskStatus.UNCHECKED,
                )
                .order_by(Task.created_at.asc())
                .first()
            )
            return task
        except Exception as e:
            logger.error(
                f"Error getting next task for mentor {mentor_id} after task {current_task_id}: {e}"
            )
            raise


def get_previous_task(mentor_id: int, current_task_id: int) -> Task | None:
    """
    Get the last updated task for a given mentor_id.

    Args:
        mentor_id: Mentor user ID (required)
        current_task_id: Current task ID (required)

    Returns:
        Last updated Task instance if found, None otherwise

    Raises:
        Exception: If database operation fails
    """
    with get_db() as db:
        try:
            # Get the last updated task for this mentor
            task = (
                db.query(Task)
                .filter(
                    Task.mentor_id == mentor_id,
                    Task.id != current_task_id,
                )
                .order_by(Task.updated_at.desc())
                .first()
            )
            return task
        except Exception as e:
            logger.error(
                f"Error getting previous task for mentor {mentor_id} before task {current_task_id}: {e}"
            )
            raise
