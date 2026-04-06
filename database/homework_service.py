from database.db_helper import get_db
from database.models import Homework, HomeworkAnswer, HomeworkStatus, MentorHomeworkNotification
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


def update_homework(
    hw_id: int,
    first_hw: str,
    status: HomeworkStatus | None = None,
    second_hw: str | None = None,
    third_hw: str | None = None,
    fourth_hw: str | None = None,
    fifth_hw: str | None = None,
    deadline: datetime | None = None,
    mentor_id: int | None = None,
) -> Homework | None:
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
            homework.first_hw = first_hw
            homework.second_hw = second_hw
            homework.third_hw = third_hw
            homework.fourth_hw = fourth_hw
            homework.fifth_hw = fifth_hw
            homework.deadline = deadline
            if mentor_id is not None:
                homework.mentor_id = mentor_id
            if status is not None:
                homework.status = status
            homework.updated_at = now_moscow()
            db.commit()
            db.refresh(homework)
            return homework
        except Exception:
            db.rollback()
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
    """Return the most recent homework in PENDING, IN_PROGRESS, or EDIT status for a student."""
    with get_db() as db:
        try:
            return (
                db.query(Homework)
                .filter(
                    Homework.student_id == student_id,
                    Homework.status.in_([HomeworkStatus.PENDING, HomeworkStatus.IN_PROGRESS, HomeworkStatus.EDIT]),
                )
                .order_by(Homework.created_at.desc())
                .first()
            )
        except Exception as e:
            logger.error(f"Error getting pending homework for student_id={student_id}: {e}")
            raise


def update_homework_feedback(hw_id: int, feedback: str) -> Homework | None:
    """Сохраняет обратную связь ментора по домашнему заданию."""
    with get_db() as db:
        try:
            homework = db.query(Homework).filter(Homework.id == hw_id).first()
            if not homework:
                return None
            homework.feedback = feedback
            homework.updated_at = now_moscow()
            db.commit()
            db.refresh(homework)
            return homework
        except Exception:
            db.rollback()
            raise


def update_homework_rating(hw_id: int, rating: int) -> Homework | None:
    """Сохраняет оценку ментора по домашнему заданию."""
    with get_db() as db:
        try:
            homework = db.query(Homework).filter(Homework.id == hw_id).first()
            if not homework:
                return None
            homework.rating = rating
            homework.updated_at = now_moscow()
            db.commit()
            db.refresh(homework)
            return homework
        except Exception:
            db.rollback()
            raise


def get_earliest_pending_mentor_homework(mentor_id: int) -> Homework | None:
    """Возвращает самое раннее домашнее задание в статусе PENDING_MENTOR для данного ментора."""
    with get_db() as db:
        try:
            return (
                db.query(Homework)
                .options(joinedload(Homework.answers))
                .filter(
                    Homework.mentor_id == mentor_id,
                    Homework.status == HomeworkStatus.PENDING_MENTOR,
                )
                .order_by(Homework.updated_at.asc())
                .first()
            )
        except Exception as e:
            logger.error(f"Error getting earliest pending mentor homework for mentor_id={mentor_id}: {e}")
            raise


def get_postponed_homeworks_for_mentor(mentor_id: int) -> list[Homework]:
    """Возвращает список отложенных домашних заданий для данного ментора."""
    with get_db() as db:
        try:
            return (
                db.query(Homework)
                .options(joinedload(Homework.answers))
                .filter(
                    Homework.mentor_id == mentor_id,
                    Homework.status == HomeworkStatus.POSTPONED,
                )
                .order_by(Homework.updated_at.asc())
                .all()
            )
        except Exception as e:
            logger.error(f"Error getting postponed homeworks for mentor_id={mentor_id}: {e}")
            raise


def get_mentor_hw_notification(mentor_id: int) -> MentorHomeworkNotification | None:
    """Возвращает запись последнего уведомления о ДЗ для данного ментора."""
    with get_db() as db:
        try:
            return (
                db.query(MentorHomeworkNotification)
                .filter(MentorHomeworkNotification.mentor_id == mentor_id)
                .first()
            )
        except Exception as e:
            logger.error(f"Error getting mentor hw notification for mentor_id={mentor_id}: {e}")
            raise


def upsert_mentor_hw_notification(mentor_id: int, message_id: int, chat_id: int) -> MentorHomeworkNotification:
    """Создаёт или обновляет запись уведомления ментора о новом ДЗ."""
    with get_db() as db:
        try:
            notification = (
                db.query(MentorHomeworkNotification)
                .filter(MentorHomeworkNotification.mentor_id == mentor_id)
                .first()
            )
            if notification:
                notification.message_id = message_id
                notification.chat_id = chat_id
            else:
                notification = MentorHomeworkNotification(
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


def upsert_homework_answers(
    hw_id: int, answers: list[dict]
) -> list[HomeworkAnswer]:
    """
    Create or replace HomeworkAnswer rows for the given homework.

    Each dict in `answers` must have:
        question_number (int), answer_content (str), media_type (str)
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
