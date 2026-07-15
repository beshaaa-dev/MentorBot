from datetime import datetime

from database.db_helper import get_db
from database.models import (
    MentorTaskNotification,
    Task,
    TaskAnswer,
    TaskStatus,
)
from logger import setup_logger
from timezone_utils import now_moscow
from sqlalchemy.orm import joinedload

logger = setup_logger(__name__)


ACTIVE_TASK_STATUSES = [
    TaskStatus.PENDING,
    TaskStatus.IN_PROGRESS,
    TaskStatus.SUBMITTED,
    TaskStatus.EDIT,
]


def create_task_from_lead(
    student_id: int,
    lead_id: str,
    status: TaskStatus,
    first_task: str,
    second_task: str | None = None,
    third_task: str | None = None,
    deadline: datetime | None = None,
    mentor_id: int | None = None,
) -> Task:
    with get_db() as db:
        try:
            task = Task(
                student_id=student_id,
                mentor_id=mentor_id,
                lead_id=lead_id,
                status=status,
                first_task=first_task,
                second_task=second_task,
                third_task=third_task,
                deadline=deadline,
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            return task
        except Exception:
            db.rollback()
            raise


def update_task(
    task_id: int,
    first_task: str,
    status: TaskStatus | None = None,
    second_task: str | None = None,
    third_task: str | None = None,
    deadline: datetime | None = None,
    mentor_id: int | None = None,
    edit_reason: str | None = None,
) -> Task | None:
    with get_db() as db:
        try:
            task = (
                db.query(Task)
                .options(joinedload(Task.answers), joinedload(Task.task_messages))
                .filter(Task.id == task_id)
                .first()
            )
            if not task:
                return None
            task.first_task = first_task
            task.second_task = second_task
            task.third_task = third_task
            task.deadline = deadline
            if mentor_id is not None:
                task.mentor_id = mentor_id
            if status is not None:
                task.status = status
            if edit_reason is not None:
                task.edit_reason = edit_reason
            task.updated_at = now_moscow()
            db.commit()
            db.refresh(task)
            return task
        except Exception:
            db.rollback()
            raise


def get_active_task_by_lead_id(lead_id: str) -> Task | None:
    """
    Возвращает самое последнее незавершённое задание.

    lead_id не уникален, поэтому
    идемпотентность назначения обеспечивается фильтром по статусу, а не
    констрейнтом: исторические записи сюда не попадают, и новое назначение
    создаёт новую строку вместо переиспользования старой.
    """
    with get_db() as db:
        try:
            return (
                db.query(Task)
                .options(joinedload(Task.answers))
                .filter(
                    Task.lead_id == lead_id,
                    Task.status.in_(ACTIVE_TASK_STATUSES),
                )
                .order_by(Task.created_at.desc())
                .first()
            )
        except Exception as e:
            logger.error(f"Error getting active task by lead_id={lead_id}: {e}")
            raise


def get_latest_task_by_lead_id(lead_id: str) -> Task | None:
    """
    Возвращает самое последнее задание.
    """
    with get_db() as db:
        try:
            return (
                db.query(Task)
                .options(joinedload(Task.answers))
                .filter(Task.lead_id == lead_id)
                .order_by(Task.created_at.desc(), Task.id.desc())
                .first()
            )
        except Exception as e:
            logger.error(f"Error getting latest task by lead_id={lead_id}: {e}")
            raise


def get_pending_task_by_student_id(student_id: int) -> Task | None:
    """Возвращает самое последнее незавершённое задание студента."""
    with get_db() as db:
        try:
            return (
                db.query(Task)
                .options(joinedload(Task.answers))
                .filter(
                    Task.student_id == student_id,
                    Task.status.in_(
                        [TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.EDIT]
                    ),
                )
                .order_by(Task.created_at.desc())
                .first()
            )
        except Exception as e:
            logger.error(f"Error getting pending task for student_id={student_id}: {e}")
            raise


def upsert_task_answers(task_id: int, answers: list[dict]) -> list[TaskAnswer]:
    """
    Each dict in `answers` must have:
        question_number (int), answer_content (str), media_type (str)
    """
    with get_db() as db:
        try:
            q_nums = [a["question_number"] for a in answers]
            db.query(TaskAnswer).filter(
                TaskAnswer.task_id == task_id,
                TaskAnswer.question_number.in_(q_nums),
            ).delete(synchronize_session=False)

            rows = []
            for a in answers:
                row = TaskAnswer(
                    task_id=task_id,
                    question_number=a["question_number"],
                    answer_content=a["answer_content"],
                    media_type=a["media_type"],
                )
                db.add(row)
                rows.append(row)

            db.commit()
            for r in rows:
                db.refresh(r)
            return rows
        except Exception:
            db.rollback()
            raise


def get_task_by_id(task_id: int) -> Task | None:
    with get_db() as db:
        try:
            task = (
                db.query(Task)
                .options(joinedload(Task.task_messages), joinedload(Task.answers))
                .filter(Task.id == task_id)
                .first()
            )
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
            task = (
                db.query(Task)
                .options(joinedload(Task.task_messages), joinedload(Task.answers))
                .filter(Task.id == task_id)
                .first()
            )
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
                .options(joinedload(Task.task_messages), joinedload(Task.answers))
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


def get_decided_tasks(mentor_id: int) -> list[Task]:
    """
    Return mentor tasks that were decided (approved/disapproved).

    Args:
        mentor_id: Mentor user ID.
    """
    with get_db() as db:
        try:
            tasks = (
                db.query(Task)
                .options(joinedload(Task.task_messages), joinedload(Task.answers))
                .filter(
                    Task.mentor_id == mentor_id,
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
                .options(joinedload(Task.task_messages), joinedload(Task.answers))
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
                .options(joinedload(Task.task_messages), joinedload(Task.answers))
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


def get_all_tasks() -> list[Task]:
    with get_db() as db:
        return (
            db.query(Task)
            .options(joinedload(Task.task_messages), joinedload(Task.answers))
            .order_by(Task.id)
            .all()
        )


def get_mentor_task_notification(mentor_id: int) -> MentorTaskNotification | None:
    """Возвращает запись последнего уведомления о задании для данного ментора."""
    with get_db() as db:
        try:
            return (
                db.query(MentorTaskNotification)
                .filter(MentorTaskNotification.mentor_id == mentor_id)
                .first()
            )
        except Exception as e:
            logger.error(f"Error getting mentor task notification for mentor_id={mentor_id}: {e}")
            raise


def upsert_mentor_task_notification(mentor_id: int, message_id: int, chat_id: int) -> MentorTaskNotification:
    """Создаёт или обновляет запись уведомления ментора о новом задании."""
    with get_db() as db:
        try:
            notification = (
                db.query(MentorTaskNotification)
                .filter(MentorTaskNotification.mentor_id == mentor_id)
                .first()
            )
            if notification:
                notification.message_id = message_id
                notification.chat_id = chat_id
            else:
                notification = MentorTaskNotification(
                    mentor_id=mentor_id,
                    message_id=message_id,
                    chat_id=chat_id,
                )
                db.add(notification)
            db.commit()
            db.refresh(notification)
            return notification
        except Exception:
            db.rollback()
            raise
