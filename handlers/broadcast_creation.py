import re
import asyncio
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from logger import setup_logger
from database.broadcast_service import create_broadcast, add_chat_to_broadcast
from database.models import BroadcastStatus, BroadcastType
from timezone_utils import now_moscow, MOSCOW_TZ
from messages import (
    SELECT_CHATS_MESSAGE,
    NO_CHATS_AVAILABLE,
    SELECT_BROADCAST_TYPE_MESSAGE,
    MESSAGE_TYPE_BUTTON,
    SURVEY_TYPE_BUTTON,
    ENTER_MESSAGE_CONTENT_MESSAGE,
    MESSAGE_CONTENT_EMPTY_ERROR,
    MESSAGE_CONTENT_TOO_LONG_ERROR,
    SELECT_TIMING_MESSAGE,
    SEND_NOW_BUTTON,
    SCHEDULED_SEND_BUTTON,
    ENTER_DATETIME_MESSAGE,
    INVALID_DATETIME_FORMAT,
    PAST_DATETIME_ERROR,
    SURVEY_CANCELLED,
    CONFIRM_BUTTON,
    CANCEL_BUTTON,
    ERROR_MESSAGE,
)
from keyboards import get_support_keyboard

logger = setup_logger(__name__)

# Conversation states
SELECT_CHATS = 1
SELECT_BROADCAST_TYPE = 2
ENTER_MESSAGE_CONTENT = 3
SELECT_TIMING = 4
ENTER_DATETIME = 5
CONFIRM = 6

# Pagination settings
CHATS_PER_PAGE = 10
PAGINATION_THRESHOLD = 20  # Enable pagination if more than this many chats


async def get_admin_chats_for_user(
    user_tg_id: int, context: ContextTypes.DEFAULT_TYPE
) -> list[tuple[int, str]]:
    """Get list of (chat_id, chat_title) where user is admin."""
    from database.chat_service import get_all_chats, deactivate_chat

    chats = get_all_chats(active_only=True)
    admin_chats = []

    for chat_id, chat_title in chats:
        try:
            administrators = await context.bot.get_chat_administrators(chat_id)
            admin_ids = {admin.user.id for admin in administrators}
            if user_tg_id in admin_ids:
                title = chat_title or f"Чат {chat_id}"
                admin_chats.append((chat_id, title))
        except Exception as e:
            logger.warning(f"Could not check admin status in chat {chat_id}: {e}")
            # If we can't access chat, it might be removed - deactivate it
            deactivate_chat(chat_id)
            continue

    return admin_chats


def create_chat_selection_keyboard(
    chats: list[tuple[int, str]],
    selected: list[int],
    page: int = 0,
    use_pagination: bool = False,
) -> InlineKeyboardMarkup:
    """Create keyboard for chat selection with optional pagination."""
    keyboard = []

    if use_pagination:
        # Calculate pagination
        total_pages = (len(chats) + CHATS_PER_PAGE - 1) // CHATS_PER_PAGE
        start_idx = page * CHATS_PER_PAGE
        end_idx = min(start_idx + CHATS_PER_PAGE, len(chats))
        page_chats = chats[start_idx:end_idx]
    else:
        page_chats = chats
        total_pages = 1

    # Add chat buttons
    for chat_id, chat_title in page_chats:
        display_title = chat_title[:30] + "..." if len(chat_title) > 30 else chat_title
        checkmark = "☑️" if chat_id in selected else "☐"
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"{checkmark} {display_title}",
                    callback_data=f"chat_select_{chat_id}",
                )
            ]
        )

    # Add pagination controls if needed
    if use_pagination and total_pages > 1:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton("◀️ Назад", callback_data=f"page_{page-1}")
            )
        nav_buttons.append(
            InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="page_info")
        )
        if page < total_pages - 1:
            nav_buttons.append(
                InlineKeyboardButton("Вперёд ▶️", callback_data=f"page_{page+1}")
            )
        keyboard.append(nav_buttons)

    # Control buttons
    keyboard.append([InlineKeyboardButton("✅ Продолжить", callback_data="chats_done")])
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])

    return InlineKeyboardMarkup(keyboard)


def create_broadcast_type_keyboard() -> InlineKeyboardMarkup:
    """Create keyboard for broadcast type selection."""
    keyboard = [
        [
            InlineKeyboardButton(
                MESSAGE_TYPE_BUTTON, callback_data="broadcast_type_message"
            )
        ],
        [
            InlineKeyboardButton(
                SURVEY_TYPE_BUTTON, callback_data="broadcast_type_survey"
            )
        ],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel")],
    ]
    return InlineKeyboardMarkup(keyboard)


def create_timing_keyboard() -> InlineKeyboardMarkup:
    """Create keyboard for timing selection."""
    keyboard = [
        [InlineKeyboardButton(SEND_NOW_BUTTON, callback_data="timing_now")],
        [InlineKeyboardButton(SCHEDULED_SEND_BUTTON, callback_data="timing_scheduled")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def start_survey_creation(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Start survey creation flow."""
    query = update.callback_query
    if not query:
        return ConversationHandler.END

    await query.answer()

    user = update.effective_user
    if not user:
        return ConversationHandler.END

    try:
        # Get chats where user is admin
        admin_chats = await get_admin_chats_for_user(user.id, context)

        if not admin_chats:
            await query.edit_message_text(
                NO_CHATS_AVAILABLE, reply_markup=get_support_keyboard()
            )
            return ConversationHandler.END

        # Store chats in context
        context.user_data["available_chats"] = {
            cid: title for cid, title in admin_chats
        }
        context.user_data["selected_chats"] = []
        context.user_data["current_page"] = 0
        context.user_data["use_pagination"] = len(admin_chats) > PAGINATION_THRESHOLD

        # Show chat selection
        use_pagination = context.user_data["use_pagination"]
        keyboard = create_chat_selection_keyboard(
            admin_chats, [], page=0, use_pagination=use_pagination
        )

        page_info = f" (Страница 1)" if use_pagination else ""
        await query.edit_message_text(
            SELECT_CHATS_MESSAGE + page_info, reply_markup=keyboard
        )

        return SELECT_CHATS

    except Exception as e:
        logger.error(f"Error starting survey creation: {e}")
        await query.edit_message_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )
        return ConversationHandler.END


async def handle_chat_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle chat selection toggle and pagination."""
    query = update.callback_query
    if not query:
        return SELECT_CHATS

    await query.answer()

    callback_data = query.data

    if callback_data == "chats_done":
        selected = context.user_data.get("selected_chats", [])
        if not selected:
            await query.answer("Выберите хотя бы один чат!", show_alert=True)
            return SELECT_CHATS

        # Move to broadcast type selection
        keyboard = create_broadcast_type_keyboard()
        await query.edit_message_text(
            SELECT_BROADCAST_TYPE_MESSAGE, reply_markup=keyboard
        )
        return SELECT_BROADCAST_TYPE

    elif callback_data == "cancel":
        await query.edit_message_text(SURVEY_CANCELLED)
        context.user_data.clear()
        return ConversationHandler.END

    elif callback_data == "page_info":
        # Just info button, do nothing
        return SELECT_CHATS

    elif callback_data.startswith("page_"):
        # Handle pagination
        page = int(callback_data.split("_")[-1])
        context.user_data["current_page"] = page

        available = context.user_data.get("available_chats", {})
        chats = [(cid, available[cid]) for cid in available.keys()]
        selected = context.user_data.get("selected_chats", [])
        use_pagination = context.user_data.get("use_pagination", False)

        keyboard = create_chat_selection_keyboard(
            chats, selected, page=page, use_pagination=use_pagination
        )

        page_info = f" (Страница {page + 1})" if use_pagination else ""
        await query.edit_message_text(
            SELECT_CHATS_MESSAGE + page_info, reply_markup=keyboard
        )
        return SELECT_CHATS

    elif callback_data.startswith("chat_select_"):
        # Toggle chat selection
        chat_id = int(callback_data.split("_")[-1])
        selected = context.user_data.get("selected_chats", [])

        if chat_id in selected:
            selected.remove(chat_id)
        else:
            selected.append(chat_id)

        context.user_data["selected_chats"] = selected

        # Update keyboard with current selection
        available = context.user_data.get("available_chats", {})
        chats = [(cid, available[cid]) for cid in available.keys()]
        current_page = context.user_data.get("current_page", 0)
        use_pagination = context.user_data.get("use_pagination", False)

        keyboard = create_chat_selection_keyboard(
            chats, selected, page=current_page, use_pagination=use_pagination
        )

        await query.edit_message_reply_markup(reply_markup=keyboard)
        return SELECT_CHATS

    return SELECT_CHATS


async def handle_broadcast_type_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle broadcast type selection."""
    query = update.callback_query
    if not query:
        return SELECT_BROADCAST_TYPE

    await query.answer()

    callback_data = query.data

    if callback_data == "broadcast_type_message":
        context.user_data["broadcast_type"] = BroadcastType.MESSAGE
        await query.edit_message_text(ENTER_MESSAGE_CONTENT_MESSAGE)
        return ENTER_MESSAGE_CONTENT

    elif callback_data == "broadcast_type_survey":
        context.user_data["broadcast_type"] = BroadcastType.SURVEY
        context.user_data["message_content"] = None
        # Move to timing selection
        keyboard = create_timing_keyboard()
        await query.edit_message_text(SELECT_TIMING_MESSAGE, reply_markup=keyboard)
        return SELECT_TIMING

    elif callback_data == "cancel":
        await query.edit_message_text(SURVEY_CANCELLED)
        context.user_data.clear()
        return ConversationHandler.END

    return SELECT_BROADCAST_TYPE


async def handle_message_content_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle message content input."""
    if not update.message:
        return ENTER_MESSAGE_CONTENT

    text = update.message.text.strip()

    # Validate message content
    if not text:
        await update.message.reply_text(MESSAGE_CONTENT_EMPTY_ERROR)
        return ENTER_MESSAGE_CONTENT

    if len(text) > 4096:
        await update.message.reply_text(MESSAGE_CONTENT_TOO_LONG_ERROR)
        return ENTER_MESSAGE_CONTENT

    context.user_data["message_content"] = text

    # Move to timing selection
    keyboard = create_timing_keyboard()
    await update.message.reply_text(SELECT_TIMING_MESSAGE, reply_markup=keyboard)
    return SELECT_TIMING


async def handle_timing_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle timing selection."""
    query = update.callback_query
    if not query:
        return SELECT_TIMING

    await query.answer()

    callback_data = query.data

    if callback_data == "timing_now":
        context.user_data["send_immediately"] = True
        context.user_data["scheduled_time"] = None
        return await show_confirmation(update, context)

    elif callback_data == "timing_scheduled":
        context.user_data["send_immediately"] = False
        await query.edit_message_text(ENTER_DATETIME_MESSAGE)
        return ENTER_DATETIME

    elif callback_data == "cancel":
        await query.edit_message_text(SURVEY_CANCELLED)
        context.user_data.clear()
        return ConversationHandler.END

    return SELECT_TIMING


def validate_datetime(text: str) -> datetime | None:
    """Validate datetime format DD.MM.YYYY HH:MM and check it's in future."""
    pattern = r"^(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})$"
    match = re.match(pattern, text.strip())

    if not match:
        return None

    try:
        day, month, year, hour, minute = map(int, match.groups())
        # Create datetime in Moscow timezone
        dt_moscow = datetime(year, month, day, hour, minute, tzinfo=MOSCOW_TZ)

        # Check if in future
        if dt_moscow <= now_moscow():
            return None

        # Convert to UTC and store as naive datetime
        dt_utc = dt_moscow.astimezone(timezone.utc).replace(tzinfo=None)
        return dt_utc
    except ValueError:
        return None


async def handle_datetime_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle datetime input for scheduled sending."""
    if not update.message:
        return ENTER_DATETIME

    text = update.message.text.strip()

    dt = validate_datetime(text)

    if dt is None:
        # Check if it's format error or past date
        pattern = r"^(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})$"
        if not re.match(pattern, text):
            await update.message.reply_text(INVALID_DATETIME_FORMAT)
            return ENTER_DATETIME
        else:
            await update.message.reply_text(PAST_DATETIME_ERROR)
            return ENTER_DATETIME

    context.user_data["scheduled_time"] = dt
    return await show_confirmation(update, context)


async def show_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show confirmation message."""
    selected_chat_ids = context.user_data.get("selected_chats", [])
    available_chats = context.user_data.get("available_chats", {})
    send_immediately = context.user_data.get("send_immediately", True)
    scheduled_time = context.user_data.get("scheduled_time")
    broadcast_type = context.user_data.get("broadcast_type", BroadcastType.SURVEY)
    message_content = context.user_data.get("message_content")

    # Build chats list
    chat_titles = [available_chats.get(cid, f"Чат {cid}") for cid in selected_chat_ids]
    chats_list = "\n".join(f"• {title}" for title in chat_titles)

    # Build send time text
    if send_immediately:
        send_time = "Сейчас"
    else:
        from timezone_utils import format_moscow

        send_time = format_moscow(scheduled_time, "%d.%m.%Y %H:%M")

    # Build broadcast type text
    if broadcast_type == BroadcastType.MESSAGE:
        broadcast_type_text = f"📨 *Тип*: Сообщение\n📝 *Текст*: {message_content[:100]}{'...' if len(message_content) > 100 else ''}\n\n"
    else:
        broadcast_type_text = "📋 *Тип*: Опрос\n\n"

    confirmation_text = (
        "Подтвердите отправку рассылки:\n\n"
        f"{broadcast_type_text}"
        f"⏰ *Время отправки*: {send_time}\n"
        f"💬 *Чаты*:\n{chats_list}"
    )

    # Create inline keyboard with confirm/cancel buttons
    keyboard = [
        [
            InlineKeyboardButton("Да, отправить", callback_data="confirm_broadcast"),
            InlineKeyboardButton("Отменить", callback_data="cancel"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(
            confirmation_text, parse_mode="Markdown", reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            confirmation_text, parse_mode="Markdown", reply_markup=reply_markup
        )

    return CONFIRM


async def handle_confirmation(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle final confirmation via callback query."""
    query = update.callback_query
    if not query:
        return CONFIRM

    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text(SURVEY_CANCELLED)
        context.user_data.clear()
        return ConversationHandler.END

    if query.data != "confirm_broadcast":
        return CONFIRM

    user = update.effective_user
    if not user:
        return ConversationHandler.END

    try:
        selected_chat_ids = context.user_data.get("selected_chats", [])
        send_immediately = context.user_data.get("send_immediately", True)
        scheduled_time = context.user_data.get("scheduled_time")
        broadcast_type = context.user_data.get("broadcast_type", BroadcastType.SURVEY)
        message_content = context.user_data.get("message_content")

        # Create broadcast
        status = (
            BroadcastStatus.SCHEDULED
            if not send_immediately
            else BroadcastStatus.SCHEDULED
        )
        broadcast = create_broadcast(
            curator_tg_id=user.id,
            scheduled_time=scheduled_time if not send_immediately else None,
            status=status,
            broadcast_type=broadcast_type,
            message_content=message_content,
        )

        # Add chats to broadcast
        from database.chat_service import get_chat_by_telegram_id

        for telegram_chat_id in selected_chat_ids:
            chat = get_chat_by_telegram_id(telegram_chat_id)
            if chat:
                add_chat_to_broadcast(broadcast.id, chat.id)

        # Send immediately or schedule
        if send_immediately:
            from services.broadcast_sender import send_broadcast_to_chats

            stats = await send_broadcast_to_chats(broadcast.id, context)
            await query.edit_message_text(
                f"Рассылка отправлена! Успешно: {stats['sent']}, ошибок: {stats['failed']}"
            )
        else:
            # Schedule broadcast
            from services.broadcast_scheduler import schedule_broadcast

            schedule_broadcast(
                broadcast.id, scheduled_time, context.application.job_queue
            )
            from timezone_utils import format_moscow

            send_time_str = format_moscow(scheduled_time, "%d.%m.%Y %H:%M")
            await query.edit_message_text(
                f"Рассылка запланирована на {send_time_str} (МСК)."
            )

        # For surveys: update CRM lead status.
        # This runs in a thread to avoid blocking the event loop.
        if broadcast_type == BroadcastType.SURVEY:
            from database.chat_service import get_active_chat_members
            from repositories.survey_repository import update_survey_lead_by_conducting

            # Use the admin-selected scheduled_time if provided; otherwise use current time.
            survey_date = scheduled_time if scheduled_time else datetime.utcnow()

            def _update_all_members_for_selected_chats() -> None:
                for telegram_chat_id in selected_chat_ids:
                    chat = get_chat_by_telegram_id(telegram_chat_id)
                    if not chat:
                        continue

                    chat_name = chat.chat_title or f"chat_{chat.chat_id}"
                    members = get_active_chat_members(chat.id, exclude_admins=True)

                    for member in members:
                        try:
                            update_survey_lead_by_conducting(
                                survey_date,
                                chat_name,
                                member.user_tg_id,
                                member.username,
                            )
                        except Exception as e:
                            logger.warning(
                                "CRM survey lead update failed for tg_id=%s: %s",
                                member.user_tg_id,
                                e,
                            )

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _update_all_members_for_selected_chats)

        context.user_data.clear()
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error creating survey: {e}")
        await query.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )
        context.user_data.clear()
        return ConversationHandler.END


async def cancel_survey_creation(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Cancel survey creation."""
    await update.message.reply_text(SURVEY_CANCELLED)
    context.user_data.clear()
    return ConversationHandler.END


# Conversation handler
survey_creation_handler = ConversationHandler(
    name="survey_creation",
    persistent=True,
    allow_reentry=True,
    entry_points=[
        CallbackQueryHandler(start_survey_creation, pattern="^admin_send_broadcast$")
    ],
    states={
        SELECT_CHATS: [
            CallbackQueryHandler(
                handle_chat_selection, pattern="^(chat_select_|chats_done|cancel|page_)"
            )
        ],
        SELECT_BROADCAST_TYPE: [
            CallbackQueryHandler(
                handle_broadcast_type_selection,
                pattern="^(broadcast_type_message|broadcast_type_survey|cancel)",
            )
        ],
        ENTER_MESSAGE_CONTENT: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND, handle_message_content_input
            ),
            CallbackQueryHandler(cancel_survey_creation, pattern="^cancel$"),
        ],
        SELECT_TIMING: [
            CallbackQueryHandler(
                handle_timing_selection, pattern="^(timing_now|timing_scheduled|cancel)"
            )
        ],
        ENTER_DATETIME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_datetime_input),
            CallbackQueryHandler(cancel_survey_creation, pattern="^cancel$"),
        ],
        CONFIRM: [
            CallbackQueryHandler(
                handle_confirmation, pattern="^(confirm_broadcast|cancel)$"
            )
        ],
    },
    fallbacks=[
        MessageHandler(filters.COMMAND, cancel_survey_creation),
        CallbackQueryHandler(cancel_survey_creation, pattern="^cancel$"),
    ],
)
