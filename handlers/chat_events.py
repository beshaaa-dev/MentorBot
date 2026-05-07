import asyncio

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, ChatMemberHandler, filters
from repositories.education_repository import handle_kicked_member
from logger import setup_logger
from database.chat_service import (
    get_or_create_chat,
    get_or_create_chat_member,
    deactivate_chat_member,
    update_chat_member_admin_status,
)
from telegram.constants import ChatMemberStatus

logger = setup_logger(__name__)



async def handle_user_message_in_chat(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle when a user sends a message in a group chat."""
    if not update.message or not update.message.chat:
        return

    chat = update.message.chat
    user = update.effective_user
    if not user:
        return

    # Skip bots
    if user.is_bot:
        return

    try:
        # Ensure chat exists
        chat_title = chat.title if hasattr(chat, "title") else None
        get_or_create_chat(chat_id=chat.id, chat_title=chat_title)

        is_admin = False
        admin_check_succeeded = False
        try:
            chat_member = await context.bot.get_chat_member(chat.id, user.id)
            is_admin = chat_member.status in (
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.OWNER,
            )
            admin_check_succeeded = True
        except Exception as e:
            error_msg = str(e)
            if (
                "bot was kicked" in error_msg.lower()
                or "forbidden" in error_msg.lower()
            ):
                from database.chat_service import deactivate_chat

                deactivate_chat(chat.id)
                logger.info(f"Bot was kicked from chat {chat.id}, marked as inactive")
                return
            logger.warning(
                f"Could not check admin status for user {user.id} in chat {chat.id}: {e}"
            )

        get_or_create_chat_member(
            chat_id=chat.id,
            user_tg_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            is_admin=is_admin,
            update_admin=admin_check_succeeded,
        )
        logger.debug(f"Registered/updated chat member {user.id} in chat {chat.id}")
    except Exception as e:
        logger.error(f"Error handling user message in chat {chat.id}: {e}")


async def handle_chat_member_update(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle chat member status changes (left, joined, admin status changed)."""
    if not update.chat_member:
        return

    chat = update.chat_member.chat
    if chat.type not in ("group", "supergroup"):
        return

    old_status = update.chat_member.old_chat_member.status
    new_status = update.chat_member.new_chat_member.status
    user = update.chat_member.new_chat_member.user

    if not user:
        return

    # Skip bots
    if user.is_bot:
        return

    try:
        # Ensure chat exists
        chat_title = chat.title if hasattr(chat, "title") else None
        get_or_create_chat(chat_id=chat.id, chat_title=chat_title)

        # Handle user left or kicked/banned
        if new_status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
            deactivate_chat_member(chat_id=chat.id, user_tg_id=user.id)
            status_text = (
                "left" if new_status == ChatMemberStatus.LEFT else "kicked/banned from"
            )
            logger.info(f"User {user.id} {status_text} chat {chat.id}")
            if new_status == ChatMemberStatus.LEFT:
                was_not_admin = old_status not in (
                    ChatMemberStatus.ADMINISTRATOR,
                    ChatMemberStatus.OWNER,
                )
                if was_not_admin:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(
                        None, handle_kicked_member, user.id, user.username
                    )

        # Handle user joined
        elif new_status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        ):
            is_admin = new_status in (
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.OWNER,
            )
            get_or_create_chat_member(
                chat_id=chat.id,
                user_tg_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                is_admin=is_admin,
            )
            logger.info(f"User {user.id} joined/reactivated in chat {chat.id}")

        # Handle restricted status (user restricted by admin)
        elif new_status == ChatMemberStatus.RESTRICTED:
            deactivate_chat_member(chat_id=chat.id, user_tg_id=user.id)
            logger.info(f"User {user.id} restricted in chat {chat.id}, marked inactive")

    except Exception as e:
        logger.error(f"Error handling chat member update in chat {chat.id}: {e}")


async def handle_my_chat_member_update(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle changes to the bot's own membership status in a chat."""
    if not update.my_chat_member:
        return

    chat = update.my_chat_member.chat
    if chat.type not in ("group", "supergroup"):
        return

    new_status = update.my_chat_member.new_chat_member.status
    chat_title = chat.title if hasattr(chat, "title") else None

    try:
        if new_status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
            from database.chat_service import deactivate_chat

            deactivate_chat(chat.id)
            logger.info(f"Bot removed from chat {chat.id} ({chat_title}), marked inactive")
        elif new_status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        ):
            get_or_create_chat(chat_id=chat.id, chat_title=chat_title)
            logger.info(f"Bot added/re-added to chat {chat.id} ({chat_title})")
    except Exception as e:
        logger.error(f"Error handling bot membership change in chat {chat.id}: {e}")


# Handler registrations
chat_message_handler = MessageHandler(
    filters.ChatType.GROUP | filters.ChatType.SUPERGROUP,
    handle_user_message_in_chat,
)

chat_member_handler = ChatMemberHandler(
    handle_chat_member_update,
    chat_member_types=ChatMemberHandler.CHAT_MEMBER,
)

my_chat_member_handler = ChatMemberHandler(
    handle_my_chat_member_update,
    chat_member_types=ChatMemberHandler.MY_CHAT_MEMBER,
)

