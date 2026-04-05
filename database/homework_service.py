from database.db_helper import get_db
from database.models import Homework, HomeworkAnswer, HomeworkStatus
from logger import setup_logger
from timezone_utils import now_moscow
from sqlalchemy.orm import joinedload
from datetime import datetime

logger = setup_logger(__name__)


def create_homework(
    student_id: int,
    lead_id: str,
    status: HomeworkStatus,
    first_hw: str,
    second_hw: str | None = None,
    third_hw: str | None = None,
    fourth_hw: str | None = None,
    fifth_hw: str | None = None,
    deadline: datetime | None = None,
    mentor_id: int | None = None,
) -> Homework:
    with get_db() as db:
        try:
            homework = Homework(
                student_id=student_id,
                mentor_id=mentor_id,
                lead_id=lead_id,
                status=status,
                first_hw=first_hw,
                second_hw=second_hw,
                third_hw=third_hw,
                fourth_hw=fourth_hw,
                fifth_hw=fifth_hw,
                deadline=deadline,
            )
            db.add(homework)
            db.commit()
            db.refresh(homework)
            return homework
        except Exception:
            db.rollback()
            raise


def get_homework_by_id(hw_id: int) -> Homework | None:
    with get_db() as db:
        try:
            return (
                db.query(Homework)
                .options(joinedload(Homework.answers))
                .filter(Homework.id == hw_id)
                .first()
            )
        except Exception as e:
            logger.error(f"Error getting homework {hw_id}: {e}")
            raise


def get_homework_by_lead_id(lead_id: str) -> Homework | None:
    with get_db() as db:
        try:
            return (
                db.query(Homework)
                .options(joinedload(Homework.answers))
                .filter(Homework.lead_id == lead_id)
                .first()
            )
        except Exception as e:
            logger.error(f"Error getting homework by lead_id={lead_id}: {e}")
            raise


def update_homework_status(hw_id: int, status: HomeworkStatus) -> Homework | None:
    with get_db() as db:
        try:
            homework = (
                db.query(Homework)
                .options(joinedload(Homework.answers))
                .filter(Homework.id == hw_id)
                .first()
            )
            if not homework:
                return None
            homework.status = status
            homework.updated_at = now_moscow()
            db.commit()
            db.refresh(homework)
            return homework
        except Exception:
            db.rollback()
            raise


def get_pending_homework_by_student_id(student_id: int) -> Homework | None:
    """Return the most recent homework in PENDING or IN_PROGRESS status for a student."""
    with get_db() as db:
        try:
            return (
                db.query(Homework)
                .filter(
                    Homework.student_id == student_id,
                    Homework.status.in_([HomeworkStatus.PENDING, HomeworkStatus.IN_PROGRESS]),
                )
                .order_by(Homework.created_at.desc())
                .first()
            )
        except Exception as e:
            logger.error(f"Error getting pending homework for student_id={student_id}: {e}")
            raise


def upsert_homework_answers(
    hw_id: int, answers: list[dict]
) -> list[HomeworkAnswer]:
    """
    Create or replace HomeworkAnswer rows for the given homework.

    Each dict in `answers` must have:
        question_number (int), answer_content (str), is_text (bool)
    """
    with get_db() as db:
        try:
            q_nums = [a["question_number"] for a in answers]
            db.query(HomeworkAnswer).filter(
                HomeworkAnswer.homework_id == hw_id,
                HomeworkAnswer.question_number.in_(q_nums),
            ).delete(synchronize_session=False)

            rows = []
            for a in answers:
                row = HomeworkAnswer(
                    homework_id=hw_id,
                    question_number=a["question_number"],
                    answer_content=a["answer_content"],
                    is_text=a["is_text"],
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
