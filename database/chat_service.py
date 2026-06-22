from datetime import datetime
from database.db_helper import get_db
from database.models import Chat, ChatMember
from logger import setup_logger
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError

logger = setup_logger(__name__)


def get_or_create_chat(chat_id: int, chat_title: str | None = None) -> Chat:
    """Get existing chat or create new one. Marks chat as active."""
    with get_db() as db:
        try:
            chat = db.query(Chat).filter(Chat.chat_id == chat_id).first()
            if chat:
                if chat_title and chat.chat_title != chat_title:
                    chat.chat_title = chat_title
                chat.is_active = True
                db.commit()
                db.refresh(chat)
                return chat

            chat = Chat(chat_id=chat_id, chat_title=chat_title, is_active=True)
            db.add(chat)
            db.commit()
            db.refresh(chat)
            return chat
        except IntegrityError:
            db.rollback()
            chat = db.query(Chat).filter(Chat.chat_id == chat_id).first()
            if chat:
                return chat
            raise
        except Exception as e:
            db.rollback()
            logger.error(f"Error getting/creating chat {chat_id}: {e}")
            raise


def get_chat_by_telegram_id(telegram_chat_id: int) -> Chat | None:
    """Get chat by Telegram chat ID."""
    with get_db() as db:
        return db.query(Chat).filter(Chat.chat_id == telegram_chat_id).first()


def get_or_create_chat_member(
    chat_id: int,
    user_tg_id: int,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    is_admin: bool = False,
    update_admin: bool = True,
) -> ChatMember:
    """Get existing chat member or create new one.

    update_admin=False preserves the existing is_admin value (use when the
    Telegram admin-status check failed transiently).
    """
    with get_db() as db:
        try:
            chat = db.query(Chat).filter(Chat.chat_id == chat_id).first()
            if not chat:
                raise ValueError(f"Chat with telegram_id {chat_id} not found")

            member = (
                db.query(ChatMember)
                .filter(
                    and_(
                        ChatMember.chat_id == chat.id,
                        ChatMember.user_tg_id == user_tg_id,
                    )
                )
                .first()
            )

            if member:
                member.is_active = True
                if username is not None:
                    member.username = username
                if first_name is not None:
                    member.first_name = first_name
                if last_name is not None:
                    member.last_name = last_name
                if update_admin:
                    member.is_admin = is_admin
                    member.admin_status_updated_at = datetime.utcnow()
                db.commit()
                db.refresh(member)
                return member

            member = ChatMember(
                chat_id=chat.id,
                user_tg_id=user_tg_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                is_admin=is_admin,
                admin_status_updated_at=datetime.utcnow() if is_admin else None,
            )
            db.add(member)
            db.commit()
            db.refresh(member)
            return member
        except IntegrityError:
            db.rollback()
            chat = db.query(Chat).filter(Chat.chat_id == chat_id).first()
            if chat:
                member = (
                    db.query(ChatMember)
                    .filter(
                        and_(
                            ChatMember.chat_id == chat.id,
                            ChatMember.user_tg_id == user_tg_id,
                        )
                    )
                    .first()
                )
                if member:
                    return member
            raise
        except Exception as e:
            db.rollback()
            logger.error(
                f"Error getting/creating chat member {user_tg_id} in chat {chat_id}: {e}"
            )
            raise


def deactivate_chat_member(chat_id: int, user_tg_id: int) -> bool:
    """Mark chat member as inactive (user left chat)."""
    with get_db() as db:
        try:
            chat = db.query(Chat).filter(Chat.chat_id == chat_id).first()
            if not chat:
                return False

            member = (
                db.query(ChatMember)
                .filter(
                    and_(
                        ChatMember.chat_id == chat.id,
                        ChatMember.user_tg_id == user_tg_id,
                    )
                )
                .first()
            )

            if member:
                member.is_active = False
                db.commit()
                return True
            return False
        except Exception as e:
            db.rollback()
            logger.error(
                f"Error deactivating chat member {user_tg_id} in chat {chat_id}: {e}"
            )
            return False


def get_active_chat_members(chat_id: int, exclude_admins: bool = True):
    """Get active chat members, optionally excluding admins."""
    with get_db() as db:
        chat = db.query(Chat).filter(Chat.chat_id == chat_id).first()
        if not chat:
            return []

        query = db.query(ChatMember).filter(
            and_(
                ChatMember.chat_id == chat.id,
                ChatMember.is_active == True,
            )
        )

        if exclude_admins:
            query = query.filter(ChatMember.is_admin == False)

        return query.all()


def update_chat_member_admin_status(
    chat_id: int, user_tg_id: int, is_admin: bool
) -> bool:
    """Update admin status for a chat member."""
    with get_db() as db:
        try:
            chat = db.query(Chat).filter(Chat.chat_id == chat_id).first()
            if not chat:
                return False

            member = (
                db.query(ChatMember)
                .filter(
                    and_(
                        ChatMember.chat_id == chat.id,
                        ChatMember.user_tg_id == user_tg_id,
                    )
                )
                .first()
            )

            if member:
                member.is_admin = is_admin
                member.admin_status_updated_at = datetime.utcnow()
                db.commit()
                return True
            return False
        except Exception as e:
            db.rollback()
            logger.error(
                f"Error updating admin status for {user_tg_id} in chat {chat_id}: {e}"
            )
            return False


def get_all_chats(active_only: bool = False) -> list[tuple[int, str | None]]:
    """Get all chats where bot is a member. Returns list of (chat_id, chat_title) tuples."""
    with get_db() as db:
        query = db.query(Chat.chat_id, Chat.chat_title)
        if active_only:
            query = query.filter(Chat.is_active == True)
        return query.all()


def deactivate_chat(chat_id: int) -> bool:
    """Mark chat as inactive (bot was removed)."""
    with get_db() as db:
        try:
            chat = db.query(Chat).filter(Chat.chat_id == chat_id).first()
            if chat:
                chat.is_active = False
                db.commit()
                return True
            return False
        except Exception as e:
            db.rollback()
            logger.error(f"Error deactivating chat {chat_id}: {e}")
            return False


def activate_chat(chat_id: int) -> bool:
    """Mark chat as active (bot was added back)."""
    with get_db() as db:
        try:
            chat = db.query(Chat).filter(Chat.chat_id == chat_id).first()
            if chat:
                chat.is_active = True
                db.commit()
                return True
            return False
        except Exception as e:
            db.rollback()
            logger.error(f"Error activating chat {chat_id}: {e}")
            return False


def get_all_chat_members(chat_db_id: int) -> list[ChatMember]:
    """Get all chat members by database chat ID."""
    with get_db() as db:
        return db.query(ChatMember).filter(ChatMember.chat_id == chat_db_id).all()


def get_chat_by_db_id(chat_db_id: int) -> Chat | None:
    """Get chat by database ID."""
    with get_db() as db:
        return db.query(Chat).filter(Chat.id == chat_db_id).first()


def get_chat_member_by_user_tg_id(chat_db_id: int, user_tg_id: int) -> ChatMember | None:
    """Get chat member by chat database ID and user Telegram ID."""
    with get_db() as db:
        return (
            db.query(ChatMember)
            .filter(
                and_(
                    ChatMember.chat_id == chat_db_id,
                    ChatMember.user_tg_id == user_tg_id,
                )
            )
            .first()
        )


def get_chat_members_display_info(
    pairs: list[tuple[int, int]],
) -> dict[tuple[int, int], dict]:
    """Fetch display fields for multiple (chat_db_id, user_tg_id) pairs in one query.

    Returns a dict keyed by (chat_db_id, user_tg_id) with scalar values extracted
    inside the session so callers never touch a detached ORM object.
    """
    if not pairs:
        return {}
    with get_db() as db:
        conditions = [
            and_(ChatMember.chat_id == chat_db_id, ChatMember.user_tg_id == user_tg_id)
            for chat_db_id, user_tg_id in pairs
        ]
        rows = (
            db.query(
                ChatMember.chat_id,
                ChatMember.user_tg_id,
                ChatMember.username,
                ChatMember.first_name,
                ChatMember.last_name,
            )
            .filter(or_(*conditions))
            .all()
        )
        return {
            (row.chat_id, row.user_tg_id): {
                "username": row.username,
                "first_name": row.first_name,
                "last_name": row.last_name,
                "user_tg_id": row.user_tg_id,
            }
            for row in rows
        }


def get_active_memberships_with_titles() -> list[tuple[int, str | None]]:
    """Return (user_tg_id, chat_title) for all active chat memberships."""
    with get_db() as db:
        return (
            db.query(ChatMember.user_tg_id, Chat.chat_title)
            .join(Chat, ChatMember.chat_id == Chat.id)
            .filter(ChatMember.is_active == True)
            .all()
        )


def get_all_active_chat_members() -> list[ChatMember]:
    """Return all active ChatMember rows."""
    with get_db() as db:
        return db.query(ChatMember).filter(ChatMember.is_active == True).all()


def get_user_admin_chats(user_tg_id: int) -> list[tuple[int, str | None]]:
    """Return (chat_id, chat_title) for chats where the user is an active admin."""
    with get_db() as db:
        return (
            db.query(Chat.chat_id, Chat.chat_title)
            .join(ChatMember, ChatMember.chat_id == Chat.id)
            .filter(
                ChatMember.user_tg_id == user_tg_id,
                ChatMember.is_admin == True,
                ChatMember.is_active == True,
                Chat.is_active == True,
            )
            .all()
        )


def user_has_any_chat_record(user_tg_id: int) -> bool:
    """Return True if the DB has any ChatMember row for this user."""
    with get_db() as db:
        return (
            db.query(ChatMember.id)
            .filter(ChatMember.user_tg_id == user_tg_id)
            .first()
        ) is not None
