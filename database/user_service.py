from database.db_helper import get_db
from database.models import User, UserRole
from datetime import datetime
from logger import setup_logger
from sqlalchemy import func

logger = setup_logger(__name__)


def find_by_tg_id(tg_id: int | None) -> User | None:
    """
    Find user by Telegram ID.

    Args:
        tg_id: Telegram user ID (can be None)

    Returns:
        User instance if found, None otherwise
    """
    with get_db() as db:
        return db.query(User).filter(User.tg_id == tg_id).first()


def find_by_tg_nickname(tg_nickname: str | None) -> User | None:
    """
    Find user by Telegram nickname (case-insensitive).

    Args:
        tg_nickname: Telegram nickname (required, cannot be None)

    Returns:
        User instance if found, None otherwise

    Raises:
        ValueError: If tg_nickname is None
    """
    if tg_nickname is None:
        raise ValueError("tg_nickname cannot be None")

    with get_db() as db:
        return (
            db.query(User)
            .filter(func.lower(User.tg_nickname) == func.lower(tg_nickname))
            .first()
        )


def get_by_id(user_id: int) -> User | None:
    """
    Get user by database ID.

    Args:
        user_id: Database user ID

    Returns:
        User instance if found, None otherwise
    """
    with get_db() as db:
        return db.query(User).filter(User.id == user_id).first()


def create_user(
    tg_id: int | None,
    tg_nickname: str | None = None,
    role: UserRole = UserRole.STUDENT,
    first_name: str | None = None,
    last_name: str | None = None,
    created_at: datetime = datetime.utcnow(),
    crm_id: str | None = None,
    registered_at: datetime | None = None,
) -> User:
    """
    Create a new user in the database.

    Args:
        tg_id: Telegram user ID (optional, can be None)
        tg_nickname: Telegram nickname (optional)
        role: User role (MENTOR or STUDENT) (optional, default is STUDENT)
        first_name: User's first name (optional)
        last_name: User's last name (optional)
        created_at: Creation timestamp (optional, default is current UTC time)
        crm_id: AmoCRM contact ID (optional)
        registered_at: Registration timestamp (optional)

    Returns:
        Created User instance

    Raises:
        Exception: If database operation fails
    """
    with get_db() as db:
        try:
            user = User(
                tg_id=tg_id,
                tg_nickname=tg_nickname,
                role=role,
                first_name=first_name,
                last_name=last_name,
                crm_id=crm_id,
                created_at=created_at,
                registered_at=registered_at,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return user
        except Exception as e:
            db.rollback()
            raise


def update_user(
    user_id: int,
    tg_id: int | None = None,
    tg_nickname: str | None = None,
    role: UserRole | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    crm_id: str | None = None,
    registered_at: datetime | None = None,
) -> User | None:
    """
    Update an existing user in the database.

    Args:
        user_id: Database user ID (required)
        tg_id: Telegram user ID (optional)
        tg_nickname: Telegram nickname (optional)
        role: User role (MENTOR or STUDENT) (optional)
        first_name: User's first name (optional)
        last_name: User's last name (optional)
        crm_id: AmoCRM contact ID (optional)
        registered_at: Registration timestamp (optional)

    Returns:
        Updated User instance if found, None otherwise

    Raises:
        Exception: If database operation fails
    """
    with get_db() as db:
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return None

            if tg_id is not None:
                user.tg_id = tg_id
            if tg_nickname is not None:
                user.tg_nickname = tg_nickname
            if role is not None:
                user.role = role
            if first_name is not None:
                user.first_name = first_name
            if last_name is not None:
                user.last_name = last_name
            if crm_id is not None:
                user.crm_id = crm_id
            if registered_at is not None:
                user.registered_at = registered_at

            db.commit()
            db.refresh(user)
            return user
        except Exception as e:
            db.rollback()
            raise
