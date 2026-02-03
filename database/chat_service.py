from datetime import datetime
from database.db_helper import get_db
from database.models import Chat, ChatMember
from logger import setup_logger
from sqlalchemy import and_

logger = setup_logger(__name__)


def get_or_create_chat(chat_id: int, chat_title: str | None = None) -> Chat:
    """Get existing chat or create new one. Marks chat as active."""
    with get_db() as db:
        try:
            chat = db.query(Chat).filter(Chat.chat_id == chat_id).first()
            if chat:
                # Update title if provided and different
                if chat_title and chat.chat_title != chat_title:
                    chat.chat_title = chat_title
                # Mark as active (bot is in chat)
                chat.is_active = True
                db.commit()
                db.refresh(chat)
                return chat

            chat = Chat(chat_id=chat_id, chat_title=chat_title, is_active=True)
            db.add(chat)
            db.commit()
            db.refresh(chat)
            return chat
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
) -> ChatMember:
    """Get existing chat member or create new one."""
    with get_db() as db:
        try:
            # First get the Chat record
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
                # Update existing member
                member.is_active = True
                if username is not None:
                    member.username = username
                if first_name is not None:
                    member.first_name = first_name
                if last_name is not None:
                    member.last_name = last_name
                member.is_admin = is_admin
                member.admin_status_updated_at = datetime.utcnow()
                db.commit()
                db.refresh(member)
                return member

            # Create new member
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
