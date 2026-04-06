import asyncio

from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from config import CRM_HOMEWORK_PIPELINE, CRM_HW_EDIT_STATUS, CRM_HW_APPROVED_STATUS
from crm.crm_service import get_crm_lead, update_lead_status_in_pipeline
from database.homework_service import (
    get_homework_by_id,
    update_homework_status,
    update_homework_feedback,
    update_homework_rating,
    get_earliest_pending_mentor_homework,
)
from database.models import HomeworkStatus, UserRole
from database.user_service import find_by_tg_id, find_by_id
from handlers.homework_student import _send_answer_content
from keyboards import (
    get_hw_mentor_decision_keyboard,
    get_hw_rating_keyboard,
    get_mentor_menu_keyboard,
)
from messages import (
    ERROR_MESSAGE,
    HW_NO_PENDING_MENTOR,
    HW_FEEDBACK_PROMPT,
    HW_FEEDBACK_SAVED,
    HW_RATE_PROMPT,
    HW_RATE_SAVED,
    HW_MENTOR_QUESTION_HEADER,
)
from logger import setup_logger

logger = setup_logger(__name__)

AWAITING_FEEDBACK = 200


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _send_homework_to_mentor(
    chat_id: int,
    homework,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Отправляет ментору заголовок ДЗ, затем вопросы и ответы студента, и клавиатуру решения."""
    loop = asyncio.get_running_loop()
    student = await loop.run_in_executor(None, find_by_id, homework.student_id)
    student_name = f"{student.first_name or ''} {student.last_name or ''}".strip()

    await context.bot.send_message(
        chat_id,
        f"Домашняя работа. {student_name}",
        reply_markup=get_hw_mentor_decision_keyboard(homework.id),
    )

    questions = [
        q
        for q in [
            homework.first_hw,
            homework.second_hw,
            homework.third_hw,
            homework.fourth_hw,
            homework.fifth_hw,
        ]
        if q
    ]
    answers_by_num = {a.question_number: a for a in (homework.answers or [])}

    for i, question in enumerate(questions, start=1):
        await context.bot.send_message(
            chat_id,
            HW_MENTOR_QUESTION_HEADER.format(n=i, question=question),
            parse_mode="Markdown",
        )
        answer = answers_by_num.get(i)
        if answer:
            answer_data = {
                "media_type": answer.media_type,
                "text": answer.answer_content if answer.media_type == "text" else None,
                "file_id": answer.answer_content if answer.media_type != "text" else None,
            }
            await _send_answer_content(answer_data, chat_id, context)


async def _show_next_or_menu(
    chat_id: int,
    mentor_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Показывает следующее ДЗ в очереди PENDING_MENTOR или меню, если очередь пуста."""
    loop = asyncio.get_running_loop()
    next_hw = await loop.run_in_executor(
        None, get_earliest_pending_mentor_homework, mentor_id
    )
    if next_hw:
        await _send_homework_to_mentor(chat_id, next_hw, context)
    else:
        await context.bot.send_message(
            chat_id,
            HW_NO_PENDING_MENTOR,
            reply_markup=get_mentor_menu_keyboard(),
        )


def _get_verified_mentor(tg_user_id: int):
    """Возвращает User-ментора или None."""
    user = find_by_tg_id(tg_user_id)
    if not user or user.role != UserRole.MENTOR:
        return None
    return user


# ── Callback: Проверить ───────────────────────────────────────────────────────


async def handle_check_homework_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    mentor = _get_verified_mentor(query.from_user.id)
    if not mentor:
        await query.message.reply_text(ERROR_MESSAGE)
        return

    loop = asyncio.get_running_loop()
    homework = await loop.run_in_executor(
        None, get_earliest_pending_mentor_homework, mentor.id
    )

    try:
        await query.message.delete()
    except Exception:
        pass

    if not homework:
        await query.message.reply_text(
            HW_NO_PENDING_MENTOR, reply_markup=get_mentor_menu_keyboard()
        )
        return

    await _send_homework_to_mentor(query.message.chat_id, homework, context)


# ── Callback: Проверить позже ─────────────────────────────────────────────────


async def handle_hw_postpone_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    try:
        hw_id = int(query.data.split("_")[-1])
    except (ValueError, IndexError):
        await query.message.reply_text(ERROR_MESSAGE)
        return

    mentor = _get_verified_mentor(query.from_user.id)
    if not mentor:
        await query.message.reply_text(ERROR_MESSAGE)
        return

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, update_homework_status, hw_id, HomeworkStatus.POSTPONED)
    logger.info(f"Homework {hw_id} postponed by mentor {mentor.id}")

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    await _show_next_or_menu(query.message.chat_id, mentor.id, context)


# ── Callback: Дать обратную связь ─────────────────────────────────────────────


async def handle_hw_feedback_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()

    try:
        hw_id = int(query.data.split("_")[-1])
    except (ValueError, IndexError):
        await query.message.reply_text(ERROR_MESSAGE)
        return ConversationHandler.END

    mentor = _get_verified_mentor(query.from_user.id)
    if not mentor:
        await query.message.reply_text(ERROR_MESSAGE)
        return ConversationHandler.END

    context.user_data["hw_feedback_id"] = hw_id
    await query.message.reply_text(HW_FEEDBACK_PROMPT, reply_markup=ReplyKeyboardRemove())
    return AWAITING_FEEDBACK


async def handle_hw_feedback_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    hw_id = context.user_data.pop("hw_feedback_id", None)
    if not hw_id:
        return ConversationHandler.END

    mentor = _get_verified_mentor(update.effective_user.id)
    if not mentor:
        await update.message.reply_text(ERROR_MESSAGE)
        return ConversationHandler.END

    feedback_text = update.message.text or ""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, update_homework_feedback, hw_id, feedback_text)
    logger.info(f"Feedback saved for homework {hw_id} by mentor {mentor.id}")

    await update.message.reply_text(HW_FEEDBACK_SAVED)
    return ConversationHandler.END


# ── Callback: Оценить ─────────────────────────────────────────────────────────


async def handle_hw_rate_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    try:
        hw_id = int(query.data.split("_")[-1])
    except (ValueError, IndexError):
        await query.message.reply_text(ERROR_MESSAGE)
        return

    try:
        await query.edit_message_text(
            text=HW_RATE_PROMPT,
            reply_markup=get_hw_rating_keyboard(hw_id),
        )
    except Exception as e:
        logger.warning(f"Could not edit message for rating: {e}")
        await query.message.reply_text(
            HW_RATE_PROMPT, reply_markup=get_hw_rating_keyboard(hw_id)
        )


async def handle_hw_rate_select_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    try:
        parts = query.data.split("_")
        hw_id = int(parts[-2])
        rating = int(parts[-1])
    except (ValueError, IndexError):
        await query.message.reply_text(ERROR_MESSAGE)
        return

    mentor = _get_verified_mentor(query.from_user.id)
    if not mentor:
        await query.message.reply_text(ERROR_MESSAGE)
        return

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, update_homework_rating, hw_id, rating)
    logger.info(f"Rating {rating} saved for homework {hw_id} by mentor {mentor.id}")

    try:
        await query.edit_message_text(text=f"{HW_RATE_SAVED} Оценка: {rating}/5")
    except Exception:
        await query.message.reply_text(f"{HW_RATE_SAVED} Оценка: {rating}/5")


# ── Callback: Доработать ──────────────────────────────────────────────────────


async def handle_hw_reedit_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    try:
        hw_id = int(query.data.split("_")[-1])
    except (ValueError, IndexError):
        await query.message.reply_text(ERROR_MESSAGE)
        return

    mentor = _get_verified_mentor(query.from_user.id)
    if not mentor:
        await query.message.reply_text(ERROR_MESSAGE)
        return

    loop = asyncio.get_running_loop()

    homework = await loop.run_in_executor(None, get_homework_by_id, hw_id)
    if not homework:
        await query.message.reply_text(ERROR_MESSAGE)
        return

    await loop.run_in_executor(None, update_homework_status, hw_id, HomeworkStatus.EDIT)

    try:
        lead = await loop.run_in_executor(None, get_crm_lead, homework.lead_id)
        if lead:
            await loop.run_in_executor(
                None, update_lead_status_in_pipeline, lead, CRM_HOMEWORK_PIPELINE, CRM_HW_EDIT_STATUS
            )
    except Exception as e:
        logger.error(f"Failed to update CRM lead for hw reedit hw_id={hw_id}: {e}", exc_info=True)

    logger.info(f"Homework {hw_id} sent for reedit by mentor {mentor.id}")

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    await _show_next_or_menu(query.message.chat_id, mentor.id, context)


# ── Callback: Одобрить ────────────────────────────────────────────────────────


async def handle_hw_approve_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    try:
        hw_id = int(query.data.split("_")[-1])
    except (ValueError, IndexError):
        await query.message.reply_text(ERROR_MESSAGE)
        return

    mentor = _get_verified_mentor(query.from_user.id)
    if not mentor:
        await query.message.reply_text(ERROR_MESSAGE)
        return

    loop = asyncio.get_running_loop()

    homework = await loop.run_in_executor(None, get_homework_by_id, hw_id)
    if not homework:
        await query.message.reply_text(ERROR_MESSAGE)
        return

    await loop.run_in_executor(None, update_homework_status, hw_id, HomeworkStatus.APPROVED)

    try:
        lead = await loop.run_in_executor(None, get_crm_lead, homework.lead_id)
        if lead:
            await loop.run_in_executor(
                None, update_lead_status_in_pipeline, lead, CRM_HOMEWORK_PIPELINE, CRM_HW_APPROVED_STATUS
            )
    except Exception as e:
        logger.error(f"Failed to update CRM lead for hw approve hw_id={hw_id}: {e}", exc_info=True)

    logger.info(f"Homework {hw_id} approved by mentor {mentor.id}")

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    await _show_next_or_menu(query.message.chat_id, mentor.id, context)


# ── ConversationHandler for feedback flow ─────────────────────────────────────


async def cancel_hw_feedback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    context.user_data.clear()
    return ConversationHandler.END


hw_mentor_feedback_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(handle_hw_feedback_callback, pattern=r"^hw_feedback_\d+$"),
    ],
    states={
        AWAITING_FEEDBACK: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_hw_feedback_text),
        ],
    },
    fallbacks=[
        CommandHandler("cancel", cancel_hw_feedback),
        MessageHandler(filters.COMMAND, cancel_hw_feedback),
        CallbackQueryHandler(handle_hw_feedback_callback, pattern=r"^hw_feedback_\d+$"),
    ],
    name="homework_mentor_feedback",
    conversation_timeout=3600,
)

# ── Standalone CallbackQueryHandlers ──────────────────────────────────────────

hw_check_homework_handler = CallbackQueryHandler(
    handle_check_homework_callback, pattern=r"^check_homework_\d+$"
)

hw_postpone_handler = CallbackQueryHandler(
    handle_hw_postpone_callback, pattern=r"^hw_postpone_\d+$"
)

hw_rate_handler = CallbackQueryHandler(
    handle_hw_rate_callback, pattern=r"^hw_rate_\d+$"
)

hw_rate_select_handler = CallbackQueryHandler(
    handle_hw_rate_select_callback, pattern=r"^hw_rate_val_\d+_\d+$"
)

hw_reedit_handler = CallbackQueryHandler(
    handle_hw_reedit_callback, pattern=r"^hw_reedit_\d+$"
)

hw_approve_handler = CallbackQueryHandler(
    handle_hw_approve_callback, pattern=r"^hw_approve_\d+$"
)
