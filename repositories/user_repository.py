from database.user_service import (
    create_user as _create_user,
    find_by_tg_id,
    update_user as _update_user,
)
from database.models import User, UserRole
from logger import setup_logger
from crm_service import get_crm_user as _get_crm_user, get_crm_lead, Lead
from datetime import datetime
from crm_service import Contact

logger = setup_logger(__name__)


def create_user_if_needed(tg_id: int, tg_nickname: str | None) -> User:
    """
    Create a new user with duplicate checking by tg_id.
    If duplicate found, returns existing user.

    Args:
        tg_id: Telegram user ID (required, unique)
        tg_nickname: Telegram nickname (optional)

    Returns:
        Created or existing User instance

    Raises:
        Exception: If database operation fails
    """
    # Проверяем дупликаты
    existing_user = find_by_tg_id(tg_id)
    if existing_user:
        return existing_user

    user = _create_user(tg_id=tg_id, tg_nickname=tg_nickname, role=UserRole.STUDENT)
    logger.info(f"Created user with id={user.id}, tg_id={tg_id}")
    return user


def get_crm_user(user: User) -> tuple[User | None, str | None]:
    crm_user = _get_crm_user(user.tg_nickname)

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

    first_lead = next(iter(crm_user.leads), None) if crm_user.leads else None
    task = first_lead.task if first_lead else None

    return updated_user, task


def get_task(user_crm_id: str) -> str | None:
    crm_user = _get_crm_user(user_crm_id)
    if not crm_user:
        return None

    first_lead = next(iter(crm_user.leads), None) if crm_user.leads else None
    task = first_lead.task if first_lead else None
    return task
