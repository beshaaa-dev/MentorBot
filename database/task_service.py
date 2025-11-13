from database.db_helper import get_db
from database.models import Task, TaskStatus
from datetime import datetime
from logger import setup_logger

logger = setup_logger(__name__)


def create_task(
    student_id: int,
    mentor_id: int,
    crm_id: str,
    file_id: str,
    status: TaskStatus = TaskStatus.UNCHECKED,
) -> Task:
    """
    Create a new task in the database.

    Args:
        student_id: Student user ID (required)
        mentor_id: Mentor user ID (required)
        crm_id: AmoCRM task ID (required)
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
                crm_id=crm_id,
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
