import asyncio

from telegram import Update, ReplyKeyboardRemove, Message
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from database.homework_service import (
    get_homework_by_id,
    update_homework_status,
)
from database.models import HomeworkStatus
from handlers.answer_utils import (
    answers_from_rows,
    clear_flow_data,
    send_answer_content as _send_answer_content,
    store_answer,
)
from keyboards import (
    get_answer_confirmation_keyboard,
    get_hw_review_keyboard,
)
from messages import (
    HW_QUESTION_PROMPT,
    HW_ANSWER_CONFIRM_PROMPT,
    HW_CONFIRM_YES_BUTTON,
    HW_CONFIRM_RETRY_BUTTON,
    HW_REVIEW_CHANGE_PROMPT,
    HW_REVIEW_CHANGE_BUTTON,
    HW_CONFIRM_ALL_BUTTON,
    HW_SUBMITTED,
    HW_NOT_FOUND,
    ERROR_MESSAGE,
)
from logger import setup_logger

logger = setup_logger(__name__)

# ── Conversation states ──────────────────────────────────────────────────────
ANSWERING_HW_1 = 100
CONFIRMING_HW_1 = 101
ANSWERING_HW_2 = 102
CONFIRMING_HW_2 = 103
ANSWERING_HW_3 = 104
CONFIRMING_HW_3 = 105
ANSWERING_HW_4 = 106
CONFIRMING_HW_4 = 107
ANSWERING_HW_5 = 108
CONFIRMING_HW_5 = 109
REVIEWING = 110

_ANSWER_STATE = [
    ANSWERING_HW_1,
    ANSWERING_HW_2,
    ANSWERING_HW_3,
    ANSWERING_HW_4,
    ANSWERING_HW_5,
]
_CONFIRM_STATE = [
    CONFIRMING_HW_1,
    CONFIRMING_HW_2,
    CONFIRMING_HW_3,
    CONFIRMING_HW_4,
    CONFIRMING_HW_5,
]

_ACCEPTED_MEDIA = (
    filters.TEXT
    | filters.AUDIO
    | filters.VIDEO
    | filters.PHOTO
    | filters.VOICE
    | filters.VIDEO_NOTE
    | filters.Document.ALL
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_questions(context: ContextTypes.DEFAULT_TYPE) -> list[str]:
    return context.user_data.get("hw_questions", [])


def _hw_id(context: ContextTypes.DEFAULT_TYPE) -> int:
    return context.user_data.get("hw_id", 0)


def _question_for(n: int, context: ContextTypes.DEFAULT_TYPE) -> str:
    questions = _get_questions(context)
    return questions[n - 1] if len(questions) >= n else ""


async def _ask_question(
    n: int, context: ContextTypes.DEFAULT_TYPE, update: Update
) -> None:
    questions = _get_questions(context)
    total = len(questions)
    text = HW_QUESTION_PROMPT.format(n=n, total=total, question=questions[n - 1])
    msg = await update.effective_chat.send_message(text)
    context.user_data["hw_question_msg_id"] = msg.message_id


async def _delete_answer_msgs(context: ContextTypes.DEFAULT_TYPE, update: Update) -> None:
    """Delete the student's answer message and the current confirm message."""
    for key in ("hw_student_msg_id", "hw_question_msg_id"):
        msg_id = context.user_data.pop(key, None)
        if msg_id:
            try:
                await context.bot.delete_message(update.effective_chat.id, msg_id)
            except Exception:
                pass


async def _transition_to_question(
    n: int, context: ContextTypes.DEFAULT_TYPE, update: Update
) -> None:
    """Delete answer messages and send a fresh question."""
    await _delete_answer_msgs(context, update)
    await _ask_question(n, context, update)


def _store_answer(q_num: int, message: Message, context: ContextTypes.DEFAULT_TYPE) -> None:
    store_answer(q_num, message, context.user_data.setdefault("hw_answers", {}))


def _next_question_state(current_q: int, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Return the ANSWERING state for the next unanswered question, or REVIEWING."""
    questions = _get_questions(context)
    total = len(questions)
    if current_q < total:
        return _ANSWER_STATE[current_q]  # 0-indexed → current_q is next q_num
    return REVIEWING


async def _show_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    questions = _get_questions(context)
    answers: dict = context.user_data.get("hw_answers", {})
    chat_id = update.effective_chat.id
    for i, q in enumerate(questions, start=1):
        await context.bot.send_message(
            chat_id,
            f"*Вопрос {i}*: {q}",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove() if i == 1 else None,
        )
        await _send_answer_content(answers.get(i, {}), chat_id, context)
    await context.bot.send_message(
        chat_id,
        HW_REVIEW_CHANGE_PROMPT,
        reply_markup=get_hw_review_keyboard(len(questions)),
    )


# ── Entry: student taps Приступить / Исправить ───────────────────────────────

async def handle_edit_homework(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Точка входа: студент нажимает «Исправить» после возврата на доработку."""
    query = update.callback_query
    await query.answer()
    clear_flow_data(context, "hw_")

    try:
        hw_id = int(query.data.split("_")[-1])
    except (ValueError, IndexError):
        await query.message.reply_text(HW_NOT_FOUND)
        return ConversationHandler.END

    loop = asyncio.get_running_loop()
    homework = await loop.run_in_executor(None, get_homework_by_id, hw_id)
    if not homework or homework.status not in (HomeworkStatus.EDIT, HomeworkStatus.EDIT_FROM_MENTOR):
        await query.message.reply_text(HW_NOT_FOUND)
        return ConversationHandler.END

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

    context.user_data["hw_id"] = hw_id
    context.user_data["hw_questions"] = questions
    context.user_data["hw_answers"] = answers_from_rows(homework.answers)

    await loop.run_in_executor(None, update_homework_status, hw_id, HomeworkStatus.IN_PROGRESS)

    try:
        await query.message.delete()
    except Exception:
        pass

    await _show_review(update, context)
    return REVIEWING


async def handle_start_homework(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    clear_flow_data(context, "hw_")

    try:
        hw_id = int(query.data.split("_")[-1])
    except (ValueError, IndexError):
        await query.message.reply_text(HW_NOT_FOUND)
        return ConversationHandler.END

    loop = asyncio.get_running_loop()
    homework = await loop.run_in_executor(None, get_homework_by_id, hw_id)
    if not homework:
        await query.message.reply_text(HW_NOT_FOUND)
        return ConversationHandler.END

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

    context.user_data["hw_id"] = hw_id
    context.user_data["hw_questions"] = questions
    context.user_data["hw_answers"] = {}

    await loop.run_in_executor(None, update_homework_status, hw_id, HomeworkStatus.IN_PROGRESS)

    try:
        await query.message.delete()
    except Exception:
        pass

    await _ask_question(1, context, update)
    return ANSWERING_HW_1


# ── Per-question answer handlers ──────────────────────────────────────────────

def _make_answer_handler(q_num: int):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        _store_answer(q_num, update.message, context)

        # Keep student's message visible during confirmation; delete it on confirm/retry.
        context.user_data["hw_student_msg_id"] = update.message.message_id

        questions = _get_questions(context)
        total = len(questions)
        question = _question_for(q_num, context)
        confirm_text = (
            HW_QUESTION_PROMPT.format(n=q_num, total=total, question=question)
            + f"\n\n{HW_ANSWER_CONFIRM_PROMPT}"
        )

        # Delete the plain question message, then send the confirm prompt with reply keyboard.
        old_msg_id = context.user_data.pop("hw_question_msg_id", None)
        if old_msg_id:
            try:
                await context.bot.delete_message(update.effective_chat.id, old_msg_id)
            except Exception:
                pass

        confirm_msg = await update.effective_chat.send_message(
            confirm_text, reply_markup=get_answer_confirmation_keyboard()
        )
        context.user_data["hw_question_msg_id"] = confirm_msg.message_id

        return _CONFIRM_STATE[q_num - 1]
    handler.__name__ = f"handle_answer_hw_{q_num}"
    return handler


def _make_confirm_handler(q_num: int):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        try:
            await update.message.delete()
        except Exception:
            pass
        if context.user_data.pop("hw_review_edit", False) or _next_question_state(q_num, context) == REVIEWING:
            await _delete_answer_msgs(context, update)
            await _show_review(update, context)
            return REVIEWING
        await _transition_to_question(q_num + 1, context, update)
        return _ANSWER_STATE[q_num]  # 0-indexed next q
    handler.__name__ = f"handle_confirm_hw_{q_num}"
    return handler


def _make_retry_handler(q_num: int):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        try:
            await update.message.delete()
        except Exception:
            pass
        await _transition_to_question(q_num, context, update)
        return _ANSWER_STATE[q_num - 1]
    handler.__name__ = f"handle_retry_hw_{q_num}"
    return handler


# ── Review state handlers ─────────────────────────────────────────────────────

async def handle_review_change(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Route 'Изменить вопрос N' back to ANSWERING_HW_N."""
    text = update.message.text or ""
    for n in range(1, 6):
        if text == HW_REVIEW_CHANGE_BUTTON.format(n=n):
            questions = _get_questions(context)
            if n > len(questions):
                break
            context.user_data["hw_review_edit"] = True
            await _ask_question(n, context, update)
            return _ANSWER_STATE[n - 1]
    await _show_review(update, context)
    return REVIEWING


async def handle_review_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Student taps 'Всё верно, отправить'."""
    hw_id = _hw_id(context)
    answers: dict = context.user_data.get("hw_answers", {})

    pending_msg = await update.message.reply_text("Отправляем ваши ответы…", reply_markup=ReplyKeyboardRemove())

    try:
        from repositories.homework_repository import submit_student_answers
        await submit_student_answers(hw_id, answers, context.bot)
    except Exception as e:
        logger.error(f"Failed to submit homework hw_id={hw_id}: {e}", exc_info=True)
        clear_flow_data(context, "hw_")
        try:
            await pending_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(ERROR_MESSAGE)
        return ConversationHandler.END

    clear_flow_data(context, "hw_")
    try:
        await pending_msg.delete()
    except Exception:
        pass
    await update.message.reply_text(HW_SUBMITTED)
    return ConversationHandler.END



# ── Build per-question handler instances ─────────────────────────────────────

_answer_handlers = [_make_answer_handler(n) for n in range(1, 6)]
_confirm_handlers = [_make_confirm_handler(n) for n in range(1, 6)]
_retry_handlers = [_make_retry_handler(n) for n in range(1, 6)]

_hw_confirm_filter = filters.TEXT & ~filters.COMMAND & filters.Regex(f"^{HW_CONFIRM_YES_BUTTON}$")
_hw_retry_filter = filters.TEXT & ~filters.COMMAND & filters.Regex(f"^{HW_CONFIRM_RETRY_BUTTON}$")
_review_change_filter = filters.TEXT & ~filters.COMMAND & filters.Regex(r"^Изменить вопрос [1-5]$")
_review_confirm_filter = filters.TEXT & ~filters.COMMAND & filters.Regex(f"^{HW_CONFIRM_ALL_BUTTON}$")


# ── ConversationHandler registration ─────────────────────────────────────────

hw_student_conversation_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(handle_start_homework, pattern=r"^start_homework_\d+$"),
        CallbackQueryHandler(handle_edit_homework, pattern=r"^edit_homework_\d+$"),
    ],
    states={
        # Q1
        ANSWERING_HW_1: [MessageHandler(_ACCEPTED_MEDIA & ~filters.COMMAND, _answer_handlers[0])],
        CONFIRMING_HW_1: [
            MessageHandler(_hw_confirm_filter, _confirm_handlers[0]),
            MessageHandler(_hw_retry_filter, _retry_handlers[0]),
        ],
        # Q2
        ANSWERING_HW_2: [MessageHandler(_ACCEPTED_MEDIA & ~filters.COMMAND, _answer_handlers[1])],
        CONFIRMING_HW_2: [
            MessageHandler(_hw_confirm_filter, _confirm_handlers[1]),
            MessageHandler(_hw_retry_filter, _retry_handlers[1]),
        ],
        # Q3
        ANSWERING_HW_3: [MessageHandler(_ACCEPTED_MEDIA & ~filters.COMMAND, _answer_handlers[2])],
        CONFIRMING_HW_3: [
            MessageHandler(_hw_confirm_filter, _confirm_handlers[2]),
            MessageHandler(_hw_retry_filter, _retry_handlers[2]),
        ],
        # Q4
        ANSWERING_HW_4: [MessageHandler(_ACCEPTED_MEDIA & ~filters.COMMAND, _answer_handlers[3])],
        CONFIRMING_HW_4: [
            MessageHandler(_hw_confirm_filter, _confirm_handlers[3]),
            MessageHandler(_hw_retry_filter, _retry_handlers[3]),
        ],
        # Q5
        ANSWERING_HW_5: [MessageHandler(_ACCEPTED_MEDIA & ~filters.COMMAND, _answer_handlers[4])],
        CONFIRMING_HW_5: [
            MessageHandler(_hw_confirm_filter, _confirm_handlers[4]),
            MessageHandler(_hw_retry_filter, _retry_handlers[4]),
        ],
        # Review
        REVIEWING: [
            MessageHandler(_review_confirm_filter, handle_review_confirm),
            MessageHandler(_review_change_filter, handle_review_change),
        ],
    },
    fallbacks=[
        CallbackQueryHandler(handle_start_homework, pattern=r"^start_homework_\d+$"),
        CallbackQueryHandler(handle_edit_homework, pattern=r"^edit_homework_\d+$"),
    ],
    persistent=True,
    name="homework_student",
    conversation_timeout=259200,  # 3 days
)
