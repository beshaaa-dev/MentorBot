from database.db_helper import get_db
from database.models import Task, TaskStatus
from datetime import datetime, timedelta, timezone
from logger import setup_logger
from timezone_utils import now_moscow

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

            task.updated_at = now_moscow()
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


def get_recent_decided_tasks(mentor_id: int, window_minutes: int = 180) -> list[Task]:
    """
    Return mentor tasks that were decided (approved/disapproved) within the last window.

    Args:
        mentor_id: Mentor user ID.
        window_minutes: Time window (minutes) to consider.
    """
    with get_db() as db:
        try:
            threshold_time = now_moscow() - timedelta(minutes=window_minutes)
            tasks = (
                db.query(Task)
                .filter(
                    Task.mentor_id == mentor_id,
                    Task.updated_at >= threshold_time,
                    Task.status.in_([TaskStatus.APPROVED, TaskStatus.DISAPPROVED]),
                )
                .order_by(Task.updated_at.desc())
                .all()
            )
            return tasks
        except Exception as e:
            logger.error(f"Error getting decided tasks for mentor {mentor_id}: {e}")
            raise


def get_tasks_by_status(mentor_id: int, status: TaskStatus) -> list[Task]:
    """
    Return all tasks for a mentor filtered by status, ordered by latest update.
    """
    with get_db() as db:
        try:
            tasks = (
                db.query(Task)
                .filter(Task.mentor_id == mentor_id, Task.status == status)
                .order_by(Task.updated_at.desc(), Task.id.desc())
                .all()
            )
            return tasks
        except Exception as e:
            logger.error(
                f"Error getting tasks for mentor {mentor_id} with status {status}: {e}"
            )
            raise


def get_postponed_tasks(mentor_id: int) -> list[Task]:
    """
    Возвращает все отложенные заявки, отсортированные от самых ранних до самых поздних
    """
    with get_db() as db:
        try:
            tasks = (
                db.query(Task)
                .filter(
                    Task.mentor_id == mentor_id, Task.status == TaskStatus.POSTPONED
                )
                .order_by(Task.created_at.asc())
                .all()
            )
            return tasks
        except Exception as e:
            logger.error(f"Error getting postponed tasks for mentor {mentor_id}: {e}")
            raise
