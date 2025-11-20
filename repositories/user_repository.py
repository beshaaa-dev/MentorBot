from database.user_service import (
    create_user as _create_user,
    find_by_tg_id,
    find_by_tg_nickname,
    update_user as _update_user,
    get_by_id,
)
from database.models import User, UserRole
from logger import setup_logger
from crm_service import (
    get_crm_user_by_tg_nickname as _get_crm_user_by_tg_nickname,
    get_crm_user_by_id as _get_crm_user_by_id,
    Lead,
)
from datetime import datetime
from crm_service import Contact
from repositories.pdf_generator import create_anketa_pdf
import re

logger = setup_logger(__name__)

DEFAULT_ANKETA_FILENAME = "anketa.pdf"


def _build_pdf_filename(student_full_name: str) -> str:
    sanitized = re.sub(r"\s+", " ", student_full_name.strip())
    sanitized = re.sub(r"[^\w\s\-]+", "", sanitized, flags=re.UNICODE)
    sanitized = sanitized.strip()

    if not sanitized:
        return DEFAULT_ANKETA_FILENAME

    return f"Анкета {sanitized}.pdf"


def create_student_if_needed(tg_id: int, tg_nickname: str | None) -> User:
    """
    Create a new user with duplicate checking by tg_id.
    If duplicate found, returns existing user.

    Args:
        tg_id: Telegram user ID
        tg_nickname: Telegram nickname (optional)

    Returns:
        Created or existing User instance

    Raises:
        Exception: If database operation fails
    """
    # Проверяем дупликаты
    existing_user = find_by_tg_id(tg_id)
    if existing_user:
        if not existing_user.tg_nickname:
            return _update_user(user_id=existing_user.id, tg_nickname=tg_nickname)
        return existing_user

    # Если не найден по tg_id, пробуем найти по nickname
    if tg_nickname:
        existing_user = find_by_tg_nickname(tg_nickname)
        if existing_user:
            if not existing_user.tg_id:
                return _update_user(user_id=existing_user.id, tg_id=tg_id)
            return existing_user

    user = _create_user(tg_id=tg_id, tg_nickname=tg_nickname, role=UserRole.STUDENT)
    logger.info(f"Created student with id={user.id}, tg_id={tg_id}")
    return user


def get_crm_user(user: User) -> tuple[User | None, str | None]:
    crm_user = _get_crm_user_by_tg_nickname(user.tg_nickname)

    if not crm_user:
        return None, None

    updated_user = _update_user(
        user.id,
        crm_id=crm_user.id,
        first_name=crm_user.first_name,
        last_name=crm_user.last_name,
        registered_at=datetime.now(),
    )
    logger.info(f"Updated user with id={user.id}, crm_id={crm_user.id}")

    first_lead = get_first_lead(crm_user)

    if not first_lead:
        return updated_user, None

    task = first_lead.task if first_lead else None

    # Создаем ментора если он еще не существует в БД
    mentor_tg_nickname = first_lead.mentor_tg_nickname if first_lead else None
    create_mentor_if_needed(mentor_tg_nickname)

    return updated_user, task


def create_mentor_if_needed(mentor_tg_nickname: str | None):
    """
    Create a new mentor user if ones doesn't exist.

    Args:
        mentor_tg_nickname: Telegram nickname of the mentor

    Raises:
        Exception: If database operation fails
    """
    if not mentor_tg_nickname:
        return

    existing_mentor = find_by_tg_nickname(mentor_tg_nickname)
    if existing_mentor:
        if existing_mentor.role == UserRole.STUDENT:
            _update_user(
                existing_mentor.id, role=UserRole.MENTOR, registered_at=datetime.now()
            )
            logger.info(
                f"Updated student to mentor with id={existing_mentor.id}, tg_nickname={mentor_tg_nickname}"
            )
        return

    mentor_user = _create_user(
        tg_id=None, tg_nickname=mentor_tg_nickname, role=UserRole.MENTOR
    )
    logger.info(
        f"Created mentor with id={mentor_user.id}, tg_nickname={mentor_tg_nickname}"
    )


def get_task(user_crm_id: str) -> str | None:
    crm_user = _get_crm_user_by_id(user_crm_id)

    if not crm_user:
        return None

    first_lead = get_first_lead(crm_user)

    if not first_lead:
        return None

    # Создаем ментора если он еще не существует в БД
    mentor_tg_nickname = first_lead.mentor_tg_nickname if first_lead else None
    create_mentor_if_needed(mentor_tg_nickname)

    task = first_lead.task if first_lead else None
    return task


def get_first_lead(crm_user: Contact) -> Lead | None:
    """
    Get the first lead with status.name == "A1" from CRM user's leads.

    Args:
        crm_user: CRM Contact instance

    Returns:
        First Lead with status A1, or None if not found
    """
    if not crm_user.leads:
        return None

    return next(
        (lead for lead in crm_user.leads if lead.status and lead.status.name == "А1"),
        None,
    )


def get_student_anketa_pdf(student_id: int) -> tuple[str, bytes, str]:
    """
    Get student anketa PDF by student ID.

    Args:
        student_id: Database user ID

    Returns:
        Tuple with suggested filename, PDF bytes, and student's full name
    """
    # Get user from database
    user = get_by_id(student_id)
    if not user:
        logger.warning(f"User with id={student_id} not found")
        return DEFAULT_ANKETA_FILENAME, create_anketa_pdf(None), ""

    student_full_name = f"{user.first_name} {user.last_name}"

    # Get CRM user
    crm_user = _get_crm_user_by_id(user.crm_id)
    if not crm_user or not crm_user.leads:
        logger.warning(f"CRM user or leads not found for user id={student_id}")
        pdf_filename = _build_pdf_filename(student_full_name)
        return (
            pdf_filename,
            create_anketa_pdf(None, student_full_name),
            student_full_name,
        )

    # Get first lead
    first_lead = next(iter(crm_user.leads), None)
    if not first_lead:
        logger.warning(f"No leads found for CRM user id={crm_user.id}")
        pdf_filename = _build_pdf_filename(student_full_name)
        return (
            pdf_filename,
            create_anketa_pdf(None, student_full_name),
            student_full_name,
        )

    # Create PDF from lead
    pdf_bytes = create_anketa_pdf(first_lead, student_full_name)
    pdf_filename = _build_pdf_filename(student_full_name)
    return pdf_filename, pdf_bytes, student_full_name
