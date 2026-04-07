import asyncio

from telegram import Update
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    CommandHandler,
    filters,
)

from config import CRM_HOMEWORK_PIPELINE, CRM_HW_APPROVED_STATUS, CRM_HW_EDIT_FROM_MENTOR_STATUS
from crm.crm_service import (
    get_crm_lead,
    update_lead_status_in_pipeline,
    update_lead_hw_rating,
    update_lead_hw_feedback,
    update_lead_hw_edit_reason_mentor,
)
from dataclasses import dataclass
from database.homework_service import (
    get_homework_by_id,
    update_homework_status,
    update_homework_feedback,
    update_homework_edit_reason_from_mentor,
    update_homework_rating,
    get_earliest_pending_mentor_homework,
    get_homeworks_for_mentor_by_status,
)
from database.models import Homework, HomeworkStatus, UserRole
from database.user_service import find_by_tg_id, get_by_id
from handlers.homework_student import _send_answer_content
from handlers.utils import delete_user_message
from keyboards import (
    get_hw_mentor_decision_keyboard,
    get_hw_rating_with_skip_keyboard,
    get_hw_feedback_skip_keyboard,
    get_hw_edit_reason_skip_keyboard,
    get_mentor_homework_menu_keyboard,
    get_hw_navigation_keyboard,
)
from messages import (
    ERROR_MESSAGE,
    HW_NO_PENDING_MENTOR,
    HW_FEEDBACK_PROMPT,
    HW_RATE_PROMPT,
    HW_MENTOR_QUESTION_HEADER,
    HW_EDIT_REASON_PROMPT,
    HW_APPROVE_CANCELLED,
    HW_EDIT_FROM_MENTOR_CANCELLED,
    MENTOR_HW_CHECK_NEW_BUTTON,
    MENTOR_HW_CHECK_POSTPONED_BUTTON,
    MENTOR_HW_CHECK_HISTORY_BUTTON,
    MENTOR_HW_NO_POSTPONED,
    MENTOR_HW_NO_HISTORY,
    MENTOR_HW_NAV_PREV,
    MENTOR_HW_NAV_NEXT,
    MENTOR_HW_MENU_INFO,
)
from logger import setup_logger

logger = setup_logger(__name__)

APPROVE_RATING = 201
APPROVE_FEEDBACK = 202
EDIT_FROM_MENTOR_NOTE = 203
HW_POSTPONED_STATE_KEY = "hw_postponed_state"
HW_HISTORY_STATE_KEY = "hw_history_state"


@dataclass
class HwNavigationContext:
    """Контекст навигации по домашним заданиям ментора."""
    homework: Homework
    index: int
    total: int
    older_hw_id: int | None
    newer_hw_id: int | None
    cached_hw_ids: list[int]


def _get_hw_navigation_context(
    mentor_id: int,
    status: HomeworkStatus | list[HomeworkStatus],
    target_hw_id: int | None = None,
    cached_hw_ids: list[int] | None = None,
) -> HwNavigationContext | None:
    """Создаёт контекст навигации по домашним заданиям с указанным статусом."""
    if cached_hw_ids is not None:
        hw_ids = cached_hw_ids
    else:
        homeworks = get_homeworks_for_mentor_by_status(mentor_id, status)
        hw_ids = [hw.id for hw in homeworks]

    if not hw_ids:
        return None

    index = 0
    if target_hw_id is not None:
        try:
            index = hw_ids.index(target_hw_id)
        except ValueError:
            index = 0

    homework = get_homework_by_id(hw_ids[index])
    if not homework:
        return None

    total = len(hw_ids)
    older_hw_id = hw_ids[index - 1] if index - 1 >= 0 else None
    newer_hw_id = hw_ids[index + 1] if index + 1 < total else None

    return HwNavigationContext(
        homework=homework,
        index=index,
        total=total,
        older_hw_id=older_hw_id,
        newer_hw_id=newer_hw_id,
        cached_hw_ids=hw_ids,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _send_homework_to_mentor(
    chat_id: int,
    homework,
    context: ContextTypes.DEFAULT_TYPE,
    nav_reply_markup=None,
) -> None:
    """Отправляет ментору вопросы и ответы студента, затем карточку-ревью с кнопками."""
    loop = asyncio.get_running_loop()
    student = await loop.run_in_executor(None, get_by_id, homework.student_id)
    student_name = f"{student.first_name or ''} {student.last_name or ''}".strip()

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

    # 1. Send all Q&A pairs first, tracking message IDs for later cleanup
    qa_msg_ids = []
    for i, question in enumerate(questions, start=1):
        kwargs = {
            "chat_id": chat_id,
            "text": HW_MENTOR_QUESTION_HEADER.format(n=i, question=question),
            "parse_mode": "Markdown",
        }
        if i == 1 and nav_reply_markup is not None:
            kwargs["reply_markup"] = nav_reply_markup
        q_msg = await context.bot.send_message(**kwargs)
        qa_msg_ids.append(q_msg.message_id)
        answer = answers_by_num.get(i)
        if answer:
            answer_data = {
                "media_type": answer.media_type,
                "text": answer.answer_content if answer.media_type == "text" else None,
                "file_id": (
                    answer.answer_content if answer.media_type != "text" else None
                ),
            }
            ans_msg = await _send_answer_content(answer_data, chat_id, context)
            if ans_msg:
                qa_msg_ids.append(ans_msg.message_id)

    # 2. Send review message at the bottom; store its id for later deletion
    student_tg = student.tg_nickname if student else None
    review_text = _build_review_text(
        student_name, homework.feedback, homework.rating, homework.status,
        tg_nickname=student_tg,
    )
    review_msg = await context.bot.send_message(
        chat_id,
        review_text,
        reply_markup=get_hw_mentor_decision_keyboard(
            homework.id,
            show_postpone=(homework.status == HomeworkStatus.PENDING_MENTOR),
        ),
    )
    context.user_data["hw_qa_msg_ids"] = qa_msg_ids
    context.user_data["hw_review_msg_id"] = review_msg.message_id
    context.user_data["hw_review_student_name"] = student_name
    context.user_data["hw_review_hw_id"] = homework.id
    context.user_data["hw_review_student_tg"] = student_tg or ""


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
            reply_markup=get_mentor_homework_menu_keyboard(),
        )


def _get_verified_mentor(tg_user_id: int):
    """Возвращает User-ментора или None."""
    user = find_by_tg_id(tg_user_id)
    if not user or user.role != UserRole.MENTOR:
        return None
    return user


_STATUS_LABELS = {
    HomeworkStatus.PENDING:         "Ожидает выполнения",
    HomeworkStatus.IN_PROGRESS:     "Выполняется",
    HomeworkStatus.SUBMITTED:       "Сдано",
    HomeworkStatus.PENDING_MENTOR:  "Ожидает проверки",
    HomeworkStatus.POSTPONED:       "Отложено",
    HomeworkStatus.APPROVED:        "Одобрено",
    HomeworkStatus.EDIT:            "На доработке",
    HomeworkStatus.EDIT_FROM_MENTOR: "На переработке",
}


def _build_review_text(
    student_name: str,
    feedback: str | None,
    rating: int | None,
    status: HomeworkStatus | None = None,
    tg_nickname: str | None = None,
    edit_reason: str | None = None,
) -> str:
    """Строит текст карточки-ревью: имя студента + tg + статус + причина возврата + обратная связь + оценка."""
    text = f"Домашняя работа. {student_name}"
    if tg_nickname:
        text += f" (@{tg_nickname.lstrip('@')})"
    if status is not None:
        text += f"\nСтатус: {_STATUS_LABELS.get(status, status.value)}"
    if edit_reason and not feedback:
        text += f"\nПричина возврата на переработку: {edit_reason}"
    if feedback:
        text += f"\n\nОбратная связь: {feedback}"
    if rating is not None:
        text += f"\nОценка: {rating}/5"
    return text


# ── Callback: Проверить ───────────────────────────────────────────────────────


async def handle_check_homework_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    logger.debug("check_homework: callback handler called")
    query = update.callback_query
    await query.answer()

    tg_id = query.from_user.id if query.from_user else None
    chat_id = query.message.chat_id if query.message else None
    logger.info(
        f"check_homework callba/hck: tg_id={tg_id} chat_id={chat_id} data={query.data!r}"
    )

    logger.debug("check_homework: callback query answered")

    mentor = _get_verified_mentor(query.from_user.id)
    if not mentor:
        logger.warning(f"check_homework: not a mentor or user not found tg_id={tg_id}")
        await query.message.reply_text(ERROR_MESSAGE)
        return

    logger.info(f"check_homework: loading pending homework mentor_id={mentor.id}")
    loop = asyncio.get_running_loop()
    homework = await loop.run_in_executor(
        None, get_earliest_pending_mentor_homework, mentor.id
    )
    hw_id = homework.id if homework else None
    logger.info(
        f"check_homework: earliest pending mentor_id={mentor.id} homework_id={hw_id}"
    )

    try:
        await query.message.delete()
        logger.debug(f"check_homework: deleted message chat_id={chat_id}")
    except Exception as e:
        logger.warning(
            f"check_homework: could not delete message chat_id={chat_id}: {e}",
            exc_info=True,
        )

    if not homework:
        logger.info(
            f"check_homework: no pending homework mentor_id={mentor.id}, sending menu"
        )
        await query.message.reply_text(
            HW_NO_PENDING_MENTOR, reply_markup=get_mentor_homework_menu_keyboard()
        )
        return

    logger.info(
        f"check_homework: sending homework_id={homework.id} to mentor_id={mentor.id} "
        f"chat_id={query.message.chat_id}"
    )
    await _send_homework_to_mentor(query.message.chat_id, homework, context)


# ── Helpers: удаление Q/A и review-сообщений после действия ───────────────────


async def _delete_hw_messages(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Удаляет все Q/A-сообщения и review-сообщение из чата ментора."""
    msg_ids = list(context.user_data.pop("hw_qa_msg_ids", []))
    review_msg_id = context.user_data.pop("hw_review_msg_id", None)
    if review_msg_id:
        msg_ids.append(review_msg_id)
    for msg_id in msg_ids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception as e:
            logger.warning(f"Could not delete message {msg_id} in chat {chat_id}: {e}")


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
    await loop.run_in_executor(
        None, update_homework_status, hw_id, HomeworkStatus.POSTPONED
    )
    logger.info(f"Homework {hw_id} postponed by mentor {mentor.id}")

    await _delete_hw_messages(query.message.chat_id, context)
    await _show_next_or_menu(query.message.chat_id, mentor.id, context)


# ── Approve flow: оценка → обратная связь → финализация ───────────────────────


async def _handle_approve_entry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Точка входа: ментор нажал 'Одобрить'. Показываем клавиатуру оценки с кнопкой Пропустить."""
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

    context.user_data["hw_approve_id"] = hw_id
    try:
        await query.edit_message_text(
            text=HW_RATE_PROMPT,
            reply_markup=get_hw_rating_with_skip_keyboard(hw_id),
        )
    except Exception as e:
        logger.warning(f"Could not edit review message for approve rating: {e}")
        new_msg = await query.message.reply_text(
            HW_RATE_PROMPT, reply_markup=get_hw_rating_with_skip_keyboard(hw_id)
        )
        context.user_data["hw_review_msg_id"] = new_msg.message_id
    return APPROVE_RATING


async def _handle_approve_rate_select(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Ментор выбрал оценку. Сохраняем и переходим к обратной связи."""
    query = update.callback_query
    await query.answer()

    hw_id = context.user_data.get("hw_approve_id")
    if not hw_id:
        return ConversationHandler.END

    try:
        parts = query.data.split("_")
        rating = int(parts[-1])
    except (ValueError, IndexError):
        await query.message.reply_text(ERROR_MESSAGE)
        return ConversationHandler.END

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, update_homework_rating, hw_id, rating)
    logger.info(f"Approve flow: rating {rating} saved for homework {hw_id}")

    try:
        await query.edit_message_text(
            text=HW_FEEDBACK_PROMPT,
            reply_markup=get_hw_feedback_skip_keyboard(hw_id),
        )
    except Exception as e:
        logger.warning(f"Could not edit message for approve feedback: {e}")
        new_msg = await query.message.reply_text(
            HW_FEEDBACK_PROMPT, reply_markup=get_hw_feedback_skip_keyboard(hw_id)
        )
        context.user_data["hw_review_msg_id"] = new_msg.message_id
    return APPROVE_FEEDBACK


async def _handle_approve_skip_rate(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Ментор пропустил оценку. Переходим к обратной связи."""
    query = update.callback_query
    await query.answer()

    hw_id = context.user_data.get("hw_approve_id")
    if not hw_id:
        return ConversationHandler.END

    try:
        await query.edit_message_text(
            text=HW_FEEDBACK_PROMPT,
            reply_markup=get_hw_feedback_skip_keyboard(hw_id),
        )
    except Exception as e:
        logger.warning(f"Could not edit message for approve feedback (skip rate): {e}")
        new_msg = await query.message.reply_text(
            HW_FEEDBACK_PROMPT, reply_markup=get_hw_feedback_skip_keyboard(hw_id)
        )
        context.user_data["hw_review_msg_id"] = new_msg.message_id
    return APPROVE_FEEDBACK


async def _finalize_approve(
    chat_id: int, hw_id: int, mentor_id: int, context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Финализация одобрения: обновление БД + CRM + удаление сообщений + следующее ДЗ."""
    context.user_data.pop("hw_approve_id", None)
    loop = asyncio.get_running_loop()

    await loop.run_in_executor(
        None, update_homework_status, hw_id, HomeworkStatus.APPROVED
    )

    homework = await loop.run_in_executor(None, get_homework_by_id, hw_id)
    if not homework:
        logger.error(f"Homework {hw_id} not found after status update")
        return

    try:
        lead = await loop.run_in_executor(None, get_crm_lead, homework.lead_id)
        if lead:
            await loop.run_in_executor(
                None,
                update_lead_status_in_pipeline,
                lead,
                CRM_HOMEWORK_PIPELINE,
                CRM_HW_APPROVED_STATUS,
            )
            if homework.rating is not None:
                await loop.run_in_executor(
                    None, update_lead_hw_rating, lead, homework.rating
                )
            if homework.feedback:
                await loop.run_in_executor(
                    None, update_lead_hw_feedback, lead, homework.feedback
                )
    except Exception as e:
        logger.error(
            f"Failed to update CRM lead for hw approve hw_id={hw_id}: {e}",
            exc_info=True,
        )

    logger.info(f"Homework {hw_id} approved by mentor {mentor_id}")

    await _delete_hw_messages(chat_id, context)
    await _show_next_or_menu(chat_id, mentor_id, context)


async def _handle_approve_feedback_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Ментор ввёл обратную связь. Сохраняем и финализируем."""
    hw_id = context.user_data.get("hw_approve_id")
    if not hw_id:
        return ConversationHandler.END

    mentor = _get_verified_mentor(update.effective_user.id)
    if not mentor:
        await update.message.reply_text(ERROR_MESSAGE)
        return ConversationHandler.END

    feedback_text = update.message.text or ""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, update_homework_feedback, hw_id, feedback_text)
    logger.info(f"Approve flow: feedback saved for homework {hw_id}")

    await delete_user_message(update.message)
    await _finalize_approve(update.effective_chat.id, hw_id, mentor.id, context)
    return ConversationHandler.END


async def _handle_approve_skip_feedback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Ментор пропустил обратную связь. Финализируем."""
    query = update.callback_query
    await query.answer()

    hw_id = context.user_data.get("hw_approve_id")
    if not hw_id:
        return ConversationHandler.END

    mentor = _get_verified_mentor(query.from_user.id)
    if not mentor:
        await query.message.reply_text(ERROR_MESSAGE)
        return ConversationHandler.END

    await _finalize_approve(query.message.chat_id, hw_id, mentor.id, context)
    return ConversationHandler.END


async def _cancel_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("hw_approve_id", None)
    return ConversationHandler.END


def _make_approve_escape(delegate):
    """Фабрика escape-обработчиков для ConversationHandler одобрения."""

    async def _handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data.pop("hw_approve_id", None)
        await update.callback_query.message.reply_text(HW_APPROVE_CANCELLED)
        await delegate(update, context)
        return ConversationHandler.END

    return _handler


# ── Edit-from-mentor flow: причина возврата → финализация ─────────────────────


async def _handle_edit_from_mentor_entry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Точка входа: ментор нажал 'На доработку'. Показываем запрос причины."""
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

    context.user_data["hw_edit_from_mentor_id"] = hw_id
    try:
        await query.edit_message_text(
            text=HW_EDIT_REASON_PROMPT,
            reply_markup=get_hw_edit_reason_skip_keyboard(hw_id),
        )
    except Exception as e:
        logger.warning(f"Could not edit review message for edit_from_mentor prompt: {e}")
        await query.message.reply_text(
            HW_EDIT_REASON_PROMPT,
            reply_markup=get_hw_edit_reason_skip_keyboard(hw_id),
        )
    return EDIT_FROM_MENTOR_NOTE


async def _finalize_edit_from_mentor(
    chat_id: int, hw_id: int, mentor_id: int,
    reason: str | None, context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Финализация возврата на переработку: обновление БД + CRM + удаление сообщений + следующее ДЗ."""
    loop = asyncio.get_running_loop()

    await loop.run_in_executor(
        None, update_homework_status, hw_id, HomeworkStatus.EDIT_FROM_MENTOR
    )
    if reason:
        await loop.run_in_executor(
            None, update_homework_edit_reason_from_mentor, hw_id, reason
        )

    homework = await loop.run_in_executor(None, get_homework_by_id, hw_id)
    if not homework:
        logger.error(f"Homework {hw_id} not found after status update")
        return

    try:
        lead = await loop.run_in_executor(None, get_crm_lead, homework.lead_id)
        if lead:
            await loop.run_in_executor(
                None,
                update_lead_status_in_pipeline,
                lead,
                CRM_HOMEWORK_PIPELINE,
                CRM_HW_EDIT_FROM_MENTOR_STATUS,
            )
            if reason:
                await loop.run_in_executor(
                    None, update_lead_hw_edit_reason_mentor, lead, reason
                )
    except Exception as e:
        logger.error(
            f"Failed to update CRM lead for hw edit_from_mentor hw_id={hw_id}: {e}",
            exc_info=True,
        )

    logger.info(f"Homework {hw_id} sent for edit_from_mentor by mentor {mentor_id}")

    await _delete_hw_messages(chat_id, context)
    await _show_next_or_menu(chat_id, mentor_id, context)


async def _handle_edit_from_mentor_note_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Ментор ввёл причину возврата. Обновляем CRM и БД, финализируем."""
    hw_id = context.user_data.pop("hw_edit_from_mentor_id", None)
    if not hw_id:
        return ConversationHandler.END

    mentor = _get_verified_mentor(update.effective_user.id)
    if not mentor:
        await update.message.reply_text(ERROR_MESSAGE)
        return ConversationHandler.END

    reason = update.message.text or ""
    await delete_user_message(update.message)
    await _finalize_edit_from_mentor(
        update.effective_chat.id, hw_id, mentor.id, reason, context,
    )
    return ConversationHandler.END


async def _handle_edit_from_mentor_skip_reason(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Ментор пропустил ввод причины. Финализируем без причины."""
    query = update.callback_query
    await query.answer()

    hw_id = context.user_data.pop("hw_edit_from_mentor_id", None)
    if not hw_id:
        return ConversationHandler.END

    mentor = _get_verified_mentor(query.from_user.id)
    if not mentor:
        await query.message.reply_text(ERROR_MESSAGE)
        return ConversationHandler.END

    await _finalize_edit_from_mentor(
        query.message.chat_id, hw_id, mentor.id, None, context,
    )
    return ConversationHandler.END


async def _cancel_edit_from_mentor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("hw_edit_from_mentor_id", None)
    return ConversationHandler.END


def _make_edit_from_mentor_escape(delegate):
    """Фабрика escape-обработчиков для ConversationHandler возврата на переработку."""

    async def _handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data.pop("hw_edit_from_mentor_id", None)
        await update.callback_query.message.reply_text(HW_EDIT_FROM_MENTOR_CANCELLED)
        await delegate(update, context)
        return ConversationHandler.END

    return _handler


# ── ConversationHandler: Approve flow ─────────────────────────────────────────


hw_approve_conversation_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(_handle_approve_entry, pattern=r"^hw_approve_\d+$"),
    ],
    states={
        APPROVE_RATING: [
            CallbackQueryHandler(
                _handle_approve_rate_select, pattern=r"^hw_rate_val_\d+_\d+$"
            ),
            CallbackQueryHandler(
                _handle_approve_skip_rate, pattern=r"^hw_skip_rate_\d+$"
            ),
        ],
        APPROVE_FEEDBACK: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND, _handle_approve_feedback_text
            ),
            CallbackQueryHandler(
                _handle_approve_skip_feedback, pattern=r"^hw_skip_feedback_\d+$"
            ),
        ],
    },
    fallbacks=[
        CommandHandler("cancel", _cancel_approve),
        MessageHandler(filters.COMMAND, _cancel_approve),
        CallbackQueryHandler(
            _make_approve_escape(handle_hw_postpone_callback),
            pattern=r"^hw_postpone_\d+$",
        ),
        CallbackQueryHandler(
            _make_approve_escape(handle_check_homework_callback),
            pattern=r"^check_homework_\d+$",
        ),
    ],
    persistent=True,
    name="homework_mentor_approve",
    conversation_timeout=3600,
)


# ── ConversationHandler: Edit-from-mentor flow ───────────────────────────────


hw_edit_from_mentor_conversation_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(_handle_edit_from_mentor_entry, pattern=r"^hw_edit_from_mentor_\d+$"),
    ],
    states={
        EDIT_FROM_MENTOR_NOTE: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND, _handle_edit_from_mentor_note_text
            ),
            CallbackQueryHandler(
                _handle_edit_from_mentor_skip_reason, pattern=r"^hw_skip_edit_reason_\d+$"
            ),
        ],
    },
    fallbacks=[
        CommandHandler("cancel", _cancel_edit_from_mentor),
        MessageHandler(filters.COMMAND, _cancel_edit_from_mentor),
        CallbackQueryHandler(
            _make_edit_from_mentor_escape(handle_hw_postpone_callback),
            pattern=r"^hw_postpone_\d+$",
        ),
        CallbackQueryHandler(
            _make_edit_from_mentor_escape(handle_check_homework_callback),
            pattern=r"^check_homework_\d+$",
        ),
    ],
    persistent=True,
    name="homework_mentor_edit_from_mentor",
    conversation_timeout=3600,
)


# ── Standalone CallbackQueryHandlers ──────────────────────────────────────────

hw_check_homework_handler = CallbackQueryHandler(
    handle_check_homework_callback, pattern=r"^check_homework_\d+$"
)

hw_postpone_handler = CallbackQueryHandler(
    handle_hw_postpone_callback, pattern=r"^hw_postpone_\d+$"
)


# ── Homework menu: button handlers ───────────────────────────────────────────


async def handle_hw_check_new_button(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Обработка кнопки 'Проверить новые Д/З'."""
    await delete_user_message(update.message)

    mentor = _get_verified_mentor(update.effective_user.id)
    if not mentor:
        await update.message.reply_text(ERROR_MESSAGE)
        return

    await _delete_hw_messages(update.effective_chat.id, context)
    context.user_data.clear()
    await _show_next_or_menu(update.effective_chat.id, mentor.id, context)


async def _present_hw_navigation_view(
    chat_id: int,
    mentor_id: int,
    status: HomeworkStatus | list[HomeworkStatus],
    state_key: str,
    context: ContextTypes.DEFAULT_TYPE,
    target_hw_id: int | None = None,
    cached_hw_ids: list[int] | None = None,
) -> bool:
    """Показывает домашнее задание с навигационной клавиатурой. Возвращает True, если показано."""
    loop = asyncio.get_running_loop()
    nav_ctx = await loop.run_in_executor(
        None, _get_hw_navigation_context, mentor_id, status, target_hw_id, cached_hw_ids
    )
    if not nav_ctx:
        return False

    nav_keyboard = get_hw_navigation_keyboard(
        older_hw_id=nav_ctx.older_hw_id,
        newer_hw_id=nav_ctx.newer_hw_id,
    )
    await _send_homework_to_mentor(
        chat_id, nav_ctx.homework, context, nav_reply_markup=nav_keyboard
    )

    context.user_data[state_key] = {
        "chat_id": chat_id,
        "hw_id": nav_ctx.homework.id,
        "cached_hw_ids": nav_ctx.cached_hw_ids,
    }
    return True


async def handle_hw_check_postponed_button(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Обработка кнопки 'Отложенные Д/З'."""
    await delete_user_message(update.message)

    mentor = _get_verified_mentor(update.effective_user.id)
    if not mentor:
        await update.message.reply_text(ERROR_MESSAGE)
        return

    await _delete_hw_messages(update.effective_chat.id, context)
    context.user_data.pop(HW_POSTPONED_STATE_KEY, None)

    shown = await _present_hw_navigation_view(
        chat_id=update.effective_chat.id,
        mentor_id=mentor.id,
        status=HomeworkStatus.POSTPONED,
        state_key=HW_POSTPONED_STATE_KEY,
        context=context,
    )
    if not shown:
        await update.message.reply_text(
            MENTOR_HW_NO_POSTPONED,
            reply_markup=get_mentor_homework_menu_keyboard(),
        )


async def handle_hw_check_history_button(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Обработка кнопки 'История Д/З'."""
    await delete_user_message(update.message)

    mentor = _get_verified_mentor(update.effective_user.id)
    if not mentor:
        await update.message.reply_text(ERROR_MESSAGE)
        return

    await _delete_hw_messages(update.effective_chat.id, context)
    context.user_data.pop(HW_HISTORY_STATE_KEY, None)

    shown = await _present_hw_navigation_view(
        chat_id=update.effective_chat.id,
        mentor_id=mentor.id,
        status=[HomeworkStatus.APPROVED, HomeworkStatus.EDIT_FROM_MENTOR],
        state_key=HW_HISTORY_STATE_KEY,
        context=context,
    )
    if not shown:
        await update.message.reply_text(
            MENTOR_HW_NO_HISTORY,
            reply_markup=get_mentor_homework_menu_keyboard(),
        )


# ── Homework menu: navigation handlers ──────────────────────────────────────


async def _handle_hw_nav_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    state_key: str,
    status: HomeworkStatus | list[HomeworkStatus],
    empty_message: str,
) -> None:
    """Общий обработчик навигации по домашним заданиям (предыдущее/следующее)."""
    await delete_user_message(update.message)

    mentor = _get_verified_mentor(update.effective_user.id)
    if not mentor:
        await _delete_hw_messages(update.effective_chat.id, context)
        await update.message.reply_text(ERROR_MESSAGE)
        context.user_data.clear()
        return

    await _delete_hw_messages(update.effective_chat.id, context)

    state = context.user_data.get(state_key) or {}
    current_hw_id = state.get("hw_id")
    cached_hw_ids = state.get("cached_hw_ids")
    if not current_hw_id or not cached_hw_ids:
        await update.message.reply_text(
            empty_message,
            reply_markup=get_mentor_homework_menu_keyboard(),
        )
        context.user_data.pop(state_key, None)
        return

    loop = asyncio.get_running_loop()
    nav_ctx = await loop.run_in_executor(
        None, _get_hw_navigation_context, mentor.id, status, current_hw_id, cached_hw_ids
    )
    if not nav_ctx:
        await update.message.reply_text(
            empty_message,
            reply_markup=get_mentor_homework_menu_keyboard(),
        )
        context.user_data.pop(state_key, None)
        return

    text = update.message.text if update.message else None
    target_hw_id = (
        nav_ctx.older_hw_id if text == MENTOR_HW_NAV_PREV else nav_ctx.newer_hw_id
    )

    if not target_hw_id:
        await update.message.reply_text(
            empty_message,
            reply_markup=get_mentor_homework_menu_keyboard(),
        )
        return
    try:
        shown = await _present_hw_navigation_view(
            chat_id=update.effective_chat.id,
            mentor_id=mentor.id,
            status=status,
            state_key=state_key,
            context=context,
            target_hw_id=target_hw_id,
            cached_hw_ids=cached_hw_ids,
        )
        if not shown:
            await update.message.reply_text(
                empty_message,
                reply_markup=get_mentor_homework_menu_keyboard(),
            )
            context.user_data.pop(state_key, None)
    except Exception as e:
        logger.error(f"Error navigating {status.value} homeworks: {e}")
        await update.message.reply_text(ERROR_MESSAGE)
        context.user_data.clear()


async def handle_hw_nav_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Навигация по Д/З — определяет активный режим (отложенные / история) и переключает."""
    if HW_POSTPONED_STATE_KEY in context.user_data:
        await _handle_hw_nav_message(
            update, context, HW_POSTPONED_STATE_KEY,
            HomeworkStatus.POSTPONED, MENTOR_HW_NO_POSTPONED,
        )
    elif HW_HISTORY_STATE_KEY in context.user_data:
        await _handle_hw_nav_message(
            update, context, HW_HISTORY_STATE_KEY,
            [HomeworkStatus.APPROVED, HomeworkStatus.EDIT_FROM_MENTOR], MENTOR_HW_NO_HISTORY,
        )


async def handle_hw_to_menu_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Обработка кнопки 'В меню' из навигации по Д/З."""
    if HW_POSTPONED_STATE_KEY not in context.user_data and HW_HISTORY_STATE_KEY not in context.user_data:
        return
    await delete_user_message(update.message)
    await _delete_hw_messages(update.effective_chat.id, context)
    context.user_data.pop(HW_POSTPONED_STATE_KEY, None)
    context.user_data.pop(HW_HISTORY_STATE_KEY, None)
    await update.message.reply_text(
        MENTOR_HW_MENU_INFO,
        reply_markup=get_mentor_homework_menu_keyboard(),
        parse_mode="Markdown",
    )


# ── Homework menu: MessageHandler registrations ─────────────────────────────

hw_check_new_button_handler = MessageHandler(
    filters.TEXT & ~filters.COMMAND & filters.Regex(f"^{MENTOR_HW_CHECK_NEW_BUTTON}$"),
    handle_hw_check_new_button,
)

hw_check_postponed_button_handler = MessageHandler(
    filters.TEXT & ~filters.COMMAND & filters.Regex(f"^{MENTOR_HW_CHECK_POSTPONED_BUTTON}$"),
    handle_hw_check_postponed_button,
)

hw_check_history_button_handler = MessageHandler(
    filters.TEXT & ~filters.COMMAND & filters.Regex(f"^{MENTOR_HW_CHECK_HISTORY_BUTTON}$"),
    handle_hw_check_history_button,
)

hw_nav_handler = MessageHandler(
    filters.TEXT
    & ~filters.COMMAND
    & filters.Regex(f"^({MENTOR_HW_NAV_PREV}|{MENTOR_HW_NAV_NEXT})$"),
    handle_hw_nav_message,
)

hw_to_menu_from_nav_handler = MessageHandler(
    filters.TEXT & ~filters.COMMAND & filters.Regex(r"^В меню$"),
    handle_hw_to_menu_message,
)
