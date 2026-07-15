import asyncio

from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from logger import setup_logger
from repositories.user_repository import (
    get_visit_card,
    get_test,
    get_crm_user,
    VisitCardDetails,
)
from database.homework_service import get_pending_homework_by_student_id
from database.task_service import get_pending_task_by_student_id
from crm.crm_service import (
    get_crm_lead,
    get_first_lead,
    is_task_lead,
    resolve_crm_contact,
    get_contact_referral_link,
)
from database.models import Homework, HomeworkStatus, Task, TaskStatus, User
from database.user_service import find_by_tg_id
from keyboards import (
    get_confirmation_keyboard,
    get_start_homework_keyboard,
    get_edit_homework_keyboard,
    get_start_task_keyboard,
    get_edit_task_keyboard,
    get_student_menu_keyboard,
    STUDENT_CHECK_TASKS_CB,
    STUDENT_INVITE_FRIEND_CB,
)
from messages import (
    TASK_CHECKING,
    STUDENT_MENU_INFO,
    STUDENT_NO_TASK,
    VIDEO_CANCELLED,
    CONFIRM_BUTTON,
    CANCEL_BUTTON,
    VISIT_CARD_TASK,
    REQUEST_VISIT_CARD_VIDEO,
    INVALID_MEDIA_TYPE,
    FILE_TOO_LARGE,
    VISIT_CARD_VIDEO_RECEIVED,
    VISIT_CARD_UPLOADING,
    VISIT_CARD_VIDEO_CONFIRMED,
    TASK_NEW_ASSIGNMENT,
    TASK_CONTINUE_ASSIGNMENT,
    TASK_EDIT_NOTIFICATION,
    HW_NEW_ASSIGNMENT,
    HW_EDIT_NOTIFICATION,
    INVITE_FRIEND_LINK_MESSAGE,
    INVITE_FRIEND_NO_LINK,
)
from handlers.answer_utils import with_deadline
from handlers.utils import (
    send_error_message,
    delete_user_message,
    safe_delete_message,
)

logger = setup_logger(__name__)

# Conversation states (for student flow only).
# States 1–7 used to hold the inline task flow; tasks now live in task_student.py.
WAITING_FOR_STUDENT_MENU = 0
WAITING_FOR_VISIT_CARD_VIDEO = 8
WAITING_FOR_VISIT_CARD_CONFIRMATION = 9
# Test states
ASKING_QUESTION = 10
ASKING_CASE = 11

# Import test handlers for callback handling (after defining states to avoid circular import)
from handlers.test import handle_question_answer, handle_case_answer


async def handle_student(
    first_name: str, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await update.message.reply_text(
        STUDENT_MENU_INFO.format(name=first_name),
        reply_markup=get_student_menu_keyboard(),
    )
    return WAITING_FOR_STUDENT_MENU


async def _process_student_tasks(
    user, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await update.effective_chat.send_message(
        TASK_CHECKING,
    )

    # Проверяем есть ли задание на прохождение теста
    test = get_test(user)
    if test:
        from handlers.test import start_test

        return await start_test(user, test, update, context)

    # Проверяем есть ли задание на отправку видеовизитки
    visit_card = get_visit_card(user)
    if visit_card:
        return await send_visit_card_message(visit_card, update, context)

    # Проверяем есть ли тестовое задание
    task = _resolve_pending_task(user)
    if task:
        return await send_task_start_message(task, update, context)

    # Проверяем есть ли домашнее задание
    homework = get_pending_homework_by_student_id(user.id)
    if homework:
        return await send_homework_start_message(homework, update, context)

    # Задание не найдено
    await update.effective_chat.send_message(STUDENT_NO_TASK)
    context.user_data.clear()
    return ConversationHandler.END


async def handle_check_tasks_button(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await update.callback_query.answer()
    await safe_delete_message(update.callback_query.message)

    db_user = find_by_tg_id(update.effective_user.id)
    if not db_user:
        await send_error_message(update)
        return ConversationHandler.END

    user = get_crm_user(db_user)
    if not user:
        await update.effective_chat.send_message(STUDENT_NO_TASK)
        return ConversationHandler.END

    return await _process_student_tasks(user, update, context)


async def handle_invite_friend_button(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await update.callback_query.answer()
    await safe_delete_message(update.callback_query.message)

    db_user = find_by_tg_id(update.effective_user.id)
    if not db_user:
        await send_error_message(update)
        return ConversationHandler.END

    loop = asyncio.get_running_loop()
    contact = await loop.run_in_executor(
        None, resolve_crm_contact, db_user.tg_id, db_user.tg_nickname
    )

    referral_link = None
    if contact:
        referral_link = await loop.run_in_executor(
            None, get_contact_referral_link, contact
        )

    text = (
        INVITE_FRIEND_LINK_MESSAGE.format(link=referral_link)
        if referral_link
        else INVITE_FRIEND_NO_LINK
    )
    await update.effective_chat.send_message(text, parse_mode="HTML")
    await update.effective_chat.send_message(
        STUDENT_MENU_INFO.format(name=db_user.first_name or ""),
        reply_markup=get_student_menu_keyboard(),
    )
    return WAITING_FOR_STUDENT_MENU


def _resolve_pending_task(user: User) -> Task | None:
    """
    Ищет незавершённое тестовое задание студента.

    Сначала в БД (его туда кладёт вебхук /task/assigned). Если записи нет, но лид
    в CRM стоит в статусе «Ожидаем тестовое» — значит вебхук не дошёл, поэтому
    создаём задание тем же кодом, что и вебхук.
    """
    task = get_pending_task_by_student_id(user.id)
    if task:
        return task

    contact = resolve_crm_contact(user.tg_id, user.tg_nickname)
    if not contact:
        return None

    lead = get_first_lead(contact)
    if not lead or not is_task_lead(lead):
        return None

    try:
        from repositories.task_repository import save_task_from_webhook

        task, _ = save_task_from_webhook(str(lead.id))
        logger.info(f"Recovered task from CRM lead {lead.id} for user {user.id}")
        return task
    except ValueError as e:
        logger.warning(f"Could not build task from lead {lead.id}: {e}")
        return None


async def send_task_start_message(
    task: Task, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Отправляет кнопку «Приступить»/«Исправить» — дальше работает task_student_conversation_handler."""
    if task.status == TaskStatus.EDIT:
        text = (
            TASK_EDIT_NOTIFICATION.format(reason=task.edit_reason)
            if task.edit_reason
            else TASK_EDIT_NOTIFICATION.split("\n\n")[0]
        )
        keyboard = get_edit_task_keyboard(task.id)
    elif task.answers:
        # Студент уже что-то отправлял: ответы подгрузятся, поэтому это «Исправить».
        text = TASK_CONTINUE_ASSIGNMENT
        keyboard = get_edit_task_keyboard(task.id)
    else:
        text = TASK_NEW_ASSIGNMENT
        keyboard = get_start_task_keyboard(task.id)

    await update.effective_chat.send_message(
        with_deadline(text, task.deadline), reply_markup=keyboard
    )
    return ConversationHandler.END


async def send_homework_start_message(
    homework: Homework, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if homework.status == HomeworkStatus.EDIT_FROM_MENTOR:
        text = (
            HW_EDIT_NOTIFICATION.format(reason=homework.edit_reason_from_mentor)
            if homework.edit_reason_from_mentor
            else HW_EDIT_NOTIFICATION.split("\n\n")[0]
        )
        await update.effective_chat.send_message(
            text,
            reply_markup=get_edit_homework_keyboard(homework.id),
        )
    elif homework.status == HomeworkStatus.EDIT:
        edit_reason = None
        try:
            loop = asyncio.get_running_loop()
            lead = await loop.run_in_executor(None, get_crm_lead, homework.lead_id)
            if lead:
                edit_reason = getattr(lead, "hw_edit_reason", None)
        except Exception as e:
            logger.warning(f"Failed to fetch edit_reason from CRM for hw={homework.id}: {e}")
        text = (
            HW_EDIT_NOTIFICATION.format(reason=edit_reason)
            if edit_reason
            else HW_EDIT_NOTIFICATION.split("\n\n")[0]
        )
        await update.effective_chat.send_message(
            text,
            reply_markup=get_edit_homework_keyboard(homework.id),
        )
    else:
        await update.effective_chat.send_message(
            HW_NEW_ASSIGNMENT,
            reply_markup=get_start_homework_keyboard(homework.id),
        )
    return ConversationHandler.END


async def cancel_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the task conversation."""
    await delete_user_message(update.message)
    await update.message.reply_text(VIDEO_CANCELLED, reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END



# ============== Visit Card Flow ==============


async def send_visit_card_message(
    visit_card: VisitCardDetails | None,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Send visit card task to student and prompt for video."""
    if not visit_card:
        await update.effective_chat.send_message(STUDENT_NO_TASK)
        context.user_data.clear()
        return ConversationHandler.END

    message = VISIT_CARD_TASK.format(text=visit_card.text)
    await update.effective_chat.send_message(message, parse_mode="Markdown")
    await update.effective_chat.send_message(REQUEST_VISIT_CARD_VIDEO)
    return WAITING_FOR_VISIT_CARD_VIDEO


MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB - Telegram Bot API download limit


async def receive_visit_card_video(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle received media for visit card - accepts video, video_note, or video document."""
    file_id = None
    file_size = None

    # Accept video, video_note, or document with video mime type
    if update.message.video:
        file_id = update.message.video.file_id
        file_size = update.message.video.file_size
    elif update.message.video_note:
        file_id = update.message.video_note.file_id
        file_size = update.message.video_note.file_size
    elif update.message.document:
        mime_type = update.message.document.mime_type or ""
        if mime_type.startswith("video/"):
            file_id = update.message.document.file_id
            file_size = update.message.document.file_size
        else:
            await update.message.reply_text(
                INVALID_MEDIA_TYPE, reply_markup=ReplyKeyboardRemove()
            )
            return WAITING_FOR_VISIT_CARD_VIDEO
    else:
        # Reject all other media types
        await update.message.reply_text(
            INVALID_MEDIA_TYPE, reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_FOR_VISIT_CARD_VIDEO

    # Check file size limit (Telegram Bot API can only download files up to 20 MB)
    if file_size and file_size > MAX_FILE_SIZE_BYTES:
        await update.message.reply_text(
            FILE_TOO_LARGE, reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_FOR_VISIT_CARD_VIDEO

    if file_id:
        context.user_data["visit_card_file_id"] = file_id
        reply_markup = get_confirmation_keyboard()
        await update.message.reply_text(
            VISIT_CARD_VIDEO_RECEIVED, reply_markup=reply_markup
        )
        return WAITING_FOR_VISIT_CARD_CONFIRMATION

    await update.message.reply_text(
        REQUEST_VISIT_CARD_VIDEO, reply_markup=ReplyKeyboardRemove()
    )
    return WAITING_FOR_VISIT_CARD_VIDEO


async def confirm_visit_card_video(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle visit card video confirmation."""
    from repositories.visit_card_repository import (
        process_visit_card_video,
        VisitCardProcessingError,
    )

    text = update.message.text
    await delete_user_message(update.message)

    if text == CONFIRM_BUTTON:
        file_id = context.user_data.get("visit_card_file_id")

        if not file_id:
            logger.warning("No file_id found in context for visit card")
            await send_error_message(update)
            context.user_data.clear()
            return ConversationHandler.END

        # Send uploading message
        uploading_msg = await update.message.reply_text(
            VISIT_CARD_UPLOADING, reply_markup=ReplyKeyboardRemove()
        )

        try:
            # Download video from Telegram
            file = await context.bot.get_file(file_id)
            file_bytes = await file.download_as_bytearray()

            # Process visit card video (upload to Drive + send to chat)
            await process_visit_card_video(
                telegram_user_id=update.effective_user.id, file_bytes=bytes(file_bytes)
            )

            await uploading_msg.delete()
            await update.message.reply_text(
                VISIT_CARD_VIDEO_CONFIRMED, reply_markup=ReplyKeyboardRemove()
            )

        except VisitCardProcessingError as e:
            logger.error(f"Visit card processing failed: {e}")
            await uploading_msg.delete()
            await send_error_message(update)
        except Exception as e:
            logger.error(
                f"Unexpected error in visit card video handler: {e}", exc_info=True
            )
            await uploading_msg.delete()
            await send_error_message(update)

        context.user_data.clear()
        return ConversationHandler.END

    elif text == CANCEL_BUTTON:
        context.user_data.pop("visit_card_file_id", None)
        await update.message.reply_text(
            REQUEST_VISIT_CARD_VIDEO, reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_FOR_VISIT_CARD_VIDEO

    await update.message.reply_text(
        VISIT_CARD_VIDEO_RECEIVED, reply_markup=get_confirmation_keyboard()
    )
    return WAITING_FOR_VISIT_CARD_CONFIRMATION


# Student conversation handler factory (video submission flow)
def create_student_conversation_handler(
    start_handler: CommandHandler,
) -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            start_handler,
        ],
        states={
            WAITING_FOR_STUDENT_MENU: [
                CallbackQueryHandler(handle_check_tasks_button, pattern=f"^{STUDENT_CHECK_TASKS_CB}$"),
                CallbackQueryHandler(handle_invite_friend_button, pattern=f"^{STUDENT_INVITE_FRIEND_CB}$"),
            ],
            WAITING_FOR_VISIT_CARD_VIDEO: [
                MessageHandler(~filters.COMMAND, receive_visit_card_video),
            ],
            WAITING_FOR_VISIT_CARD_CONFIRMATION: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, confirm_visit_card_video
                ),
            ],
            ASKING_QUESTION: [
                CallbackQueryHandler(
                    handle_question_answer, pattern=r"^answer_(yes|no)_\d+$"
                )
            ],
            ASKING_CASE: [
                CallbackQueryHandler(handle_case_answer, pattern=r"^case_\d+_[A-D]$")
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_task)],
        allow_reentry=True,  # Allow /start to restart conversation
        per_message=False,
        name="student_conversation",
        persistent=True,
        conversation_timeout=60 * 60 * 24 * 3,  # 3 дня
    )
