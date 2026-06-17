from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, filters
from logger import setup_logger
from messages import (
    ADMIN_MENU_TITLE,
    SEND_BROADCAST_BUTTON,
    SCHEDULED_BROADCASTS_BUTTON,
    EXPORT_DATA_BUTTON,
    EXPORT_GENERATING_MESSAGE,
    EXPORT_DATA_CAPTION,
    EXPORT_ERROR_MESSAGE,
    ERROR_MESSAGE,
)
from keyboards import get_support_keyboard

logger = setup_logger(__name__)

_admin_chats_cache: dict[int, tuple[list[tuple[int, str]], datetime]] = {}
_ADMIN_CACHE_TTL = timedelta(minutes=5)


async def get_admin_chats_for_user(
    user_tg_id: int, context: ContextTypes.DEFAULT_TYPE
) -> list[tuple[int, str]]:
    """Return (chat_id, chat_title) pairs where user is admin. Cached for 5 minutes."""
    from database.chat_service import get_all_chats, deactivate_chat

    cached = _admin_chats_cache.get(user_tg_id)
    if cached and cached[1] > datetime.utcnow():
        return cached[0]

    chats = get_all_chats(active_only=True)
    admin_chats: list[tuple[int, str]] = []

    for chat_id, chat_title in chats:
        try:
            administrators = await context.bot.get_chat_administrators(chat_id)
            if user_tg_id in {admin.user.id for admin in administrators}:
                admin_chats.append((chat_id, chat_title or f"Чат {chat_id}"))
        except Exception as e:
            error_msg = str(e).lower()
            logger.warning(f"Could not check admin status in chat {chat_id}: {e}")
            if any(
                phrase in error_msg
                for phrase in ("bot was kicked", "forbidden", "chat not found", "bot is not a member")
            ):
                deactivate_chat(chat_id)

    _admin_chats_cache[user_tg_id] = (admin_chats, datetime.utcnow() + _ADMIN_CACHE_TTL)
    return admin_chats


async def check_user_is_admin_in_any_chat(
    user_tg_id: int, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """Check if user is admin in at least one active chat where bot is a member."""
    try:
        return bool(await get_admin_chats_for_user(user_tg_id, context))
    except Exception as e:
        logger.error(f"Error checking admin rights for user {user_tg_id}: {e}")
        return False


def get_admin_menu_keyboard() -> InlineKeyboardMarkup:
    """Create admin menu keyboard."""
    keyboard = [
        [InlineKeyboardButton(SEND_BROADCAST_BUTTON, callback_data="admin_send_broadcast")],
        [
            InlineKeyboardButton(
                SCHEDULED_BROADCASTS_BUTTON, callback_data="admin_scheduled_broadcasts"
            )
        ],
        [InlineKeyboardButton(EXPORT_DATA_BUTTON, callback_data="admin_export_data")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def handle_admin_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /admin command - check rights and show menu."""
    if not update.message:
        return

    user = update.effective_user
    if not user:
        return

    try:
        is_admin = await check_user_is_admin_in_any_chat(user.id, context)

        if not is_admin:
            logger.warning(f"User {user.id} is not admin in any chat, access denied")
            return

        await update.message.reply_text(
            ADMIN_MENU_TITLE, reply_markup=get_admin_menu_keyboard(), parse_mode="Markdown"
        )
        logger.info(f"Admin menu shown to user {user.id}")

    except Exception as e:
        logger.error(f"Error handling /admin command: {e}")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )


async def handle_admin_menu_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle admin menu button callbacks."""
    query = update.callback_query
    if not query:
        return

    await query.answer()

    user = update.effective_user
    if not user:
        return

    try:
        is_admin = await check_user_is_admin_in_any_chat(user.id, context)
        if not is_admin:
            return

        callback_data = query.data

        if callback_data == "admin_scheduled_broadcasts":
            try:
                from database.broadcast_service import get_scheduled_broadcasts
                from timezone_utils import format_moscow
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup

                scheduled = get_scheduled_broadcasts(curator_tg_id=user.id)

                if not scheduled:
                    await query.edit_message_text("У вас нет запланированных рассылок.")
                    return

                message_text = "📅 *Запланированные рассылки:*\n\n"
                keyboard_rows = []

                for broadcast in scheduled:
                    time_str = format_moscow(broadcast.scheduled_time, "%d.%m.%Y %H:%M")
                    message_text += f"• Рассылка #{broadcast.id} — {time_str}\n"
                    keyboard_rows.append(
                        [
                            InlineKeyboardButton(
                                f"Отменить #{broadcast.id}",
                                callback_data=f"cancel_broadcast_{broadcast.id}",
                            )
                        ]
                    )

                keyboard_rows.append(
                    [
                        InlineKeyboardButton(
                            "◀️ Назад", callback_data="admin_back_to_menu"
                        )
                    ]
                )

                await query.edit_message_text(
                    message_text,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard_rows),
                )

                logger.info(f"User {user.id} viewed scheduled broadcasts")
            except Exception as e:
                logger.error(f"Error showing scheduled broadcasts: {e}")
                await query.message.reply_text(
                    "Ошибка при загрузке запланированных рассылок."
                )

        elif callback_data.startswith("cancel_broadcast_"):
            try:
                broadcast_id = int(callback_data.split("_")[-1])
                from services.broadcast_scheduler import cancel_scheduled_broadcast

                if cancel_scheduled_broadcast(broadcast_id, context.application.job_queue):
                    await query.answer("Рассылка отменена.")
                    await query.edit_message_text("Рассылка успешно отменена.")
                else:
                    await query.answer("Не удалось отменить рассылку.", show_alert=True)

                logger.info(f"User {user.id} cancelled broadcast {broadcast_id}")
            except Exception as e:
                logger.error(f"Error cancelling broadcast: {e}")
                await query.answer("Ошибка при отмене рассылки.", show_alert=True)

        elif callback_data == "admin_back_to_menu":
            await query.edit_message_text(
                ADMIN_MENU_TITLE, reply_markup=get_admin_menu_keyboard()
            )

        elif callback_data == "admin_export_data":
            try:
                from services.data_export import generate_survey_export
                from telegram import InputFile

                await query.message.reply_text(EXPORT_GENERATING_MESSAGE)

                xlsx_buffer = generate_survey_export()
                xlsx_file = InputFile(
                    xlsx_buffer,
                    filename=f"survey_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                )

                await context.bot.send_document(
                    chat_id=user.id,
                    document=xlsx_file,
                    caption=EXPORT_DATA_CAPTION,
                )

                logger.info(f"User {user.id} exported survey data")
            except Exception as e:
                logger.error(f"Error exporting data: {e}")
                await query.message.reply_text(
                    EXPORT_ERROR_MESSAGE
                )

    except Exception as e:
        logger.error(f"Error handling admin menu callback: {e}")
        await query.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )


# Handler registrations
admin_command_handler = CommandHandler("admin", handle_admin_command, filters=filters.ChatType.PRIVATE)
admin_menu_callback_handler = CallbackQueryHandler(
    handle_admin_menu_callback, pattern="^(admin_|cancel_broadcast_|admin_back_to_menu)"
)
