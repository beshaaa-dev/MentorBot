from datetime import datetime
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
    BROADCAST_DELIVERY_DATA_UNAVAILABLE,
    BROADCAST_DELIVERY_STATS_HEADER,
    BROADCAST_DELIVERY_FAILED_HEADER,
    BROADCAST_DELIVERY_STATS_ERROR,
    BROADCAST_ERROR_NO_START,
    BROADCAST_ERROR_DEACTIVATED,
    BROADCAST_ERROR_BLOCKED,
    BROADCAST_ERROR_CHAT_NOT_FOUND,
)
from keyboards import get_support_keyboard

logger = setup_logger(__name__)

_DELIVERY_STATS_MAX_LEN = 3900


def _classify_telegram_error(error: str) -> str:
    msg = error.lower()
    if "can't initiate conversation" in msg or "bot can't initiate" in msg:
        return BROADCAST_ERROR_NO_START
    if "user is deactivated" in msg:
        return BROADCAST_ERROR_DEACTIVATED
    if "blocked" in msg or "forbidden" in msg:
        return BROADCAST_ERROR_BLOCKED
    if "chat not found" in msg:
        return BROADCAST_ERROR_CHAT_NOT_FOUND
    return error


async def _send_chunked_section(send_fn, header: str, lines: list[str]) -> None:
    """Send header + lines as one or more messages, keeping header on every chunk."""
    current = header
    for line in lines:
        if len(current) + len(line) > _DELIVERY_STATS_MAX_LEN:
            await send_fn(current)
            current = header + line
        else:
            current += line
    await send_fn(current)


async def get_admin_chats_for_user(
    user_tg_id: int, context: ContextTypes.DEFAULT_TYPE
) -> list[tuple[int, str]]:
    """Return (chat_id, chat_title) pairs where user is admin.

    Uses DB-cached admin flags updated by ChatMemberUpdated events.
    Falls back to polling the Telegram API only for users the DB has never seen.
    """
    from database.chat_service import (
        get_all_chats,
        deactivate_chat,
        get_user_admin_chats,
        user_has_any_chat_record,
        get_or_create_chat_member,
    )

    if user_has_any_chat_record(user_tg_id):
        rows = get_user_admin_chats(user_tg_id)
        return [(chat_id, title or f"Чат {chat_id}") for chat_id, title in rows]

    # Unknown user — poll once and populate the DB for future calls
    chats = get_all_chats(active_only=True)
    admin_chats: list[tuple[int, str]] = []

    for chat_id, chat_title in chats:
        try:
            administrators = await context.bot.get_chat_administrators(chat_id)
            is_admin = user_tg_id in {admin.user.id for admin in administrators}
            if is_admin:
                admin_chats.append((chat_id, chat_title or f"Чат {chat_id}"))
            get_or_create_chat_member(chat_id=chat_id, user_tg_id=user_tg_id, is_admin=is_admin)
        except Exception as e:
            error_msg = str(e).lower()
            logger.warning(f"Could not check admin status in chat {chat_id}: {e}")
            if any(
                phrase in error_msg
                for phrase in ("bot was kicked", "forbidden", "chat not found", "bot is not a member")
            ):
                deactivate_chat(chat_id)

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

        elif callback_data.startswith("broadcast_delivery_stats_"):
            try:
                broadcast_id = int(callback_data.split("_")[-1])
                from database.chat_service import get_chat_members_display_info

                delivery = context.bot_data.get(f"broadcast_delivery_{broadcast_id}")
                if not delivery:
                    await query.message.reply_text(
                        BROADCAST_DELIVERY_DATA_UNAVAILABLE.format(broadcast_id=broadcast_id)
                    )
                    return

                sent = delivery["sent"]
                failed = delivery["failed"]

                all_pairs = [(e["chat_db_id"], e["user_tg_id"]) for e in sent + failed]
                member_lookup = get_chat_members_display_info(all_pairs)

                def _display(entry: dict) -> str:
                    info = member_lookup.get((entry["chat_db_id"], entry["user_tg_id"]))
                    if info:
                        display = f"@{info['username']}" if info["username"] else f"ID {info['user_tg_id']}"
                        name = f"{info['first_name'] or ''} {info['last_name'] or ''}".strip()
                        if name:
                            display = f"{name} ({display})"
                    else:
                        display = f"ID {entry['user_tg_id']}"
                    return display

                await _send_chunked_section(
                    query.message.reply_text,
                    BROADCAST_DELIVERY_STATS_HEADER.format(broadcast_id=broadcast_id, count=len(sent)),
                    [f"• {_display(e)}\n" for e in sent],
                )
                await _send_chunked_section(
                    query.message.reply_text,
                    BROADCAST_DELIVERY_FAILED_HEADER.format(count=len(failed)),
                    [f"• {_display(e)} — {_classify_telegram_error(e.get('error', ''))}\n" for e in failed],
                )

                del context.bot_data[f"broadcast_delivery_{broadcast_id}"]
                logger.info(f"User {user.id} viewed delivery stats for broadcast {broadcast_id}")
            except Exception as e:
                logger.error(f"Error showing delivery stats: {e}")
                await query.message.reply_text(BROADCAST_DELIVERY_STATS_ERROR)

        elif callback_data == "admin_export_data":
            try:
                from services.data_export import generate_survey_export
                from telegram import InputFile

                await query.message.reply_text(EXPORT_GENERATING_MESSAGE)

                xlsx_buffer = generate_survey_export()
                xlsx_file = InputFile(
                    xlsx_buffer,
                    filename=f"data_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
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
    handle_admin_menu_callback,
    pattern="^(admin_|cancel_broadcast_|admin_back_to_menu|broadcast_delivery_stats_)",
)
