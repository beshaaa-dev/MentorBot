from dataclasses import dataclass
from database.user_service import (
    create_user as _create_user,
    find_by_tg_id,
    find_by_tg_nickname,
    update_user as _update_user,
    get_by_id,
)
from database.models import User, UserRole
from logger import setup_logger
from config import DEFAULT_STUDENT_ANKETA_FILENAME
from crm.crm_service import (
    resolve_crm_contact as _resolve_crm_contact,
    get_first_lead,
    get_crm_lead,
    is_test_lead,
    is_visit_card_lead,
    Lead,
)
from datetime import datetime, timezone
from timezone_utils import now_moscow
from crm.crm_service import Contact
from repositories.pdf_generator import create_anketa_pdf
from messages import VISIT_CARD_TEXT
import re

logger = setup_logger(__name__)


@dataclass(slots=True)
class VisitCardDetails:
    text: str
    lead_id: str | None = None


@dataclass(slots=True)
class TestDetails:
    lead_id: str


def get_crm_user(user: User) -> User | None:
    crm_user = _resolve_crm_contact(user.tg_id, user.tg_nickname)

    if not crm_user:
        return None

    updated_user = _update_user(
        user.id,
        first_name=crm_user.first_name,
        last_name=crm_user.last_name,
        registered_at=now_moscow(),
    )
    logger.info(f"Updated user with id={user.id} from CRM contact id={crm_user.id}")

    return updated_user


def create_student_if_needed(tg_id: int, tg_nickname: str | None) -> User:
    """
    Создает нового пользователя, если не было найдено оного с совпадением в полях tg_id или tg_nickname
    """

    # Проверяем дупликаты
    existing_user = find_by_tg_id(tg_id)
    if existing_user and not existing_user.tg_nickname:
        return _update_user(user_id=existing_user.id, tg_nickname=tg_nickname)
    if existing_user:
        return existing_user

    # Если не найден по tg_id, пробуем найти по nickname
    if tg_nickname:
        existing_user = find_by_tg_nickname(tg_nickname)
        if existing_user and not existing_user.tg_id:
            return _update_user(user_id=existing_user.id, tg_id=tg_id)
        if existing_user:
            return existing_user

    user = _create_user(tg_id=tg_id, tg_nickname=tg_nickname, role=UserRole.STUDENT)
    logger.info(f"Created student with id={user.id}, tg_id={tg_id}")
    return user


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

    mentor_tg_nickname = mentor_tg_nickname.lstrip("@")

    existing_mentor = find_by_tg_nickname(mentor_tg_nickname)
    if existing_mentor:
        if existing_mentor.role == UserRole.STUDENT:
            _update_user(
                existing_mentor.id, role=UserRole.MENTOR, registered_at=now_moscow()
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


def _build_visit_card_details(lead: Lead | None) -> VisitCardDetails | None:
    if not lead:
        return None

    return VisitCardDetails(text=VISIT_CARD_TEXT, lead_id=lead.id)


def _build_pdf_filename(student_full_name: str) -> str:
    sanitized = re.sub(r"\s+", " ", student_full_name.strip())
    sanitized = re.sub(r"[^\w\s\-]+", "", sanitized, flags=re.UNICODE)
    sanitized = sanitized.strip()

    if not sanitized:
        return DEFAULT_STUDENT_ANKETA_FILENAME

    return f"Анкета {sanitized}.pdf"


def get_test(user: User) -> TestDetails | None:
    crm_user = _resolve_crm_contact(user.tg_id, user.tg_nickname)

    if not crm_user:
        return None

    first_lead = get_first_lead(crm_user)

    if not first_lead or not is_test_lead(first_lead):
        return None

    return TestDetails(lead_id=first_lead.id)


def get_visit_card(user: User) -> VisitCardDetails | None:
    crm_user = _resolve_crm_contact(user.tg_id, user.tg_nickname)

    if not crm_user:
        return None

    first_lead = get_first_lead(crm_user)

    if not first_lead or not is_visit_card_lead(first_lead):
        return None

    return _build_visit_card_details(first_lead)


def _format_deadline(deadline: str | None) -> str | None:
    logger.info(f"Formatting deadline: {deadline}")
    if not deadline:
        return None

    date_obj = datetime.fromtimestamp(int(deadline), tz=timezone.utc)

    from timezone_utils import to_moscow

    moscow_date = to_moscow(date_obj)
    return moscow_date.strftime("%d.%m.%Y %H:%M") if moscow_date else None


def get_student_anketa_pdf(
    student_id: int, lead_id: str
) -> tuple[str, bytes | None, str]:
    """
    Get student anketa PDF by student ID.

    Args:
        student_id: Database user ID
        lead_id: CRM lead ID

    Returns:
        Tuple with suggested filename, PDF bytes (or None if empty), and student's full name
    """
    # Get user from database
    user = get_by_id(student_id)
    if not user:
        logger.warning(f"User with id={student_id} not found")
        return DEFAULT_STUDENT_ANKETA_FILENAME, create_anketa_pdf(None), ""

    student_full_name = " ".join(filter(None, [user.first_name, user.last_name])) or ""

    # Get CRM lead
    lead = get_crm_lead(lead_id)
    if not lead:
        logger.warning(f"CRM lead not found for user id={student_id}")
        pdf_filename = _build_pdf_filename(student_full_name)
        return (
            pdf_filename,
            create_anketa_pdf(None),
            student_full_name,
        )

    # Create PDF from lead
    pdf_bytes = create_anketa_pdf(lead)
    pdf_filename = _build_pdf_filename(student_full_name)
    return pdf_filename, pdf_bytes, student_full_name
