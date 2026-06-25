import asyncio
import re
from io import BytesIO

from telegram import InputFile, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from database.user_service import find_by_tg_nickname
from handlers.broadcast.admin import check_user_is_admin_in_any_chat, get_admin_menu_keyboard
from keyboards import get_support_keyboard
from logger import setup_logger
from messages import (
    ADMIN_MENU_TITLE,
    ENTER_MENTOR_NICKNAME_MESSAGE,
    GENERATING_PDFS_MESSAGE,
    MENTOR_NOT_FOUND_MESSAGE,
    NO_TASKS_FOR_MENTOR_MESSAGE,
    PDFS_DONE_MESSAGE,
    ERROR_MESSAGE,
)
from repositories.anketa_repository import generate_mentor_pdfs
from thread_safe_token_manager import ThreadSafeTokenManager

logger = setup_logger(__name__)

ENTER_MENTOR_NICKNAME = 100


def _cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Отмена", callback_data="admin_pdfs_cancel")]]
    )


def _pdf_filename(student_label: str) -> str:
    sanitized = re.sub(r"\s+", " ", student_label.strip())
    sanitized = re.sub(r"[^\w\s\-]+", "", sanitized, flags=re.UNICODE).strip()
    return f"Анкета {sanitized}.pdf" if sanitized else "Анкета.pdf"


async def handle_download_pdfs_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()

    user = update.effective_user
    if not user or not await check_user_is_admin_in_any_chat(user.id, context):
        return ConversationHandler.END

    await query.edit_message_text(
        ENTER_MENTOR_NICKNAME_MESSAGE,
        reply_markup=_cancel_keyboard(),
    )
    return ENTER_MENTOR_NICKNAME


async def handle_mentor_nickname_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return ENTER_MENTOR_NICKNAME

    user = update.effective_user
    if not user or not await check_user_is_admin_in_any_chat(user.id, context):
        return ConversationHandler.END

    nickname = update.message.text.strip().lstrip("@")

    mentor = find_by_tg_nickname(nickname)
    if not mentor:
        await update.message.reply_text(
            MENTOR_NOT_FOUND_MESSAGE.format(nickname=nickname)
        )
        return ConversationHandler.END

    status_msg = await update.message.reply_text(GENERATING_PDFS_MESSAGE)

    try:
        access_token = await ThreadSafeTokenManager.get_instance().get_access_token()
        results, total_students = await asyncio.to_thread(
            generate_mentor_pdfs, mentor.id, access_token
        )
    except Exception as exc:
        logger.error(
            f"[mentor_pdfs] Error generating PDFs for mentor_id={mentor.id}: {exc}",
            exc_info=True,
        )
        await status_msg.edit_text(ERROR_MESSAGE)
        return ConversationHandler.END

    if total_students == 0:
        await status_msg.edit_text(NO_TASKS_FOR_MENTOR_MESSAGE)
        return ConversationHandler.END

    await status_msg.delete()

    chat_id = update.effective_chat.id
    for student_label, pdf_bytes in results:
        filename = _pdf_filename(student_label)
        await context.bot.send_document(
            chat_id=chat_id,
            document=InputFile(BytesIO(pdf_bytes), filename=filename),
            caption=student_label,
        )

    skipped = total_students - len(results)
    await context.bot.send_message(
        chat_id=chat_id,
        text=PDFS_DONE_MESSAGE.format(generated=len(results), skipped=skipped),
    )
    return ConversationHandler.END


async def handle_pdfs_cancel_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    await query.edit_message_text(
        ADMIN_MENU_TITLE,
        reply_markup=get_admin_menu_keyboard(),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


mentor_pdf_download_handler = ConversationHandler(
    name="mentor_pdf_download",
    persistent=True,
    allow_reentry=True,
    entry_points=[
        CallbackQueryHandler(
            handle_download_pdfs_callback, pattern="^admin_download_mentor_pdfs$"
        )
    ],
    states={
        ENTER_MENTOR_NICKNAME: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND, handle_mentor_nickname_input
            ),
            CallbackQueryHandler(
                handle_pdfs_cancel_callback, pattern="^admin_pdfs_cancel$"
            ),
        ],
    },
    fallbacks=[
        CommandHandler("admin", handle_pdfs_cancel_callback),
        CallbackQueryHandler(handle_pdfs_cancel_callback, pattern="^admin_pdfs_cancel$"),
    ],
)
