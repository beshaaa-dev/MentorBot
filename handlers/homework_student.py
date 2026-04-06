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
from keyboards import (
    get_hw_answer_confirmation_keyboard,
    get_hw_review_keyboard,
)
from messages import (
    HW_QUESTION_PROMPT,
    HW_ANSWER_CONFIRM_PROMPT,
    HW_REVIEW_CHANGE_PROMPT,
    HW_REVIEW_CHANGE_BUTTON,
    HW_CONFIRM_ALL_BUTTON,
    HW_SUBMITTED,
    HW_NOT_FOUND,
    HW_MEDIA_LABEL,
    ERROR_MESSAGE,
)
from handlers.utils import send_error_message
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


async def _edit_to_question(
    n: int, context: ContextTypes.DEFAULT_TYPE, update: Update
) -> None:
    """Edit the current hw_question_msg to show question n with no keyboard. Falls back to send.
    Also deletes the student's pending answer message."""
    student_msg_id = context.user_data.pop("hw_student_msg_id", None)
    if student_msg_id:
        try:
            await context.bot.delete_message(update.effective_chat.id, student_msg_id)
        except Exception:
            pass

    questions = _get_questions(context)
    total = len(questions)
    text = HW_QUESTION_PROMPT.format(n=n, total=total, question=questions[n - 1])
    msg_id = context.user_data.get("hw_question_msg_id")
    if msg_id:
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=msg_id,
                text=text,
                reply_markup=None,
            )
            return
        except Exception:
            pass
    await _ask_question(n, context, update)


def _store_answer(q_num: int, message: Message, context: ContextTypes.DEFAULT_TYPE) -> None:
    answers: dict = context.user_data.setdefault("hw_answers", {})
    is_text = bool(message.text)
    file_id: str | None = None
    media_type: str = "text"
    if not is_text:
        if message.video:
            file_id = message.video.file_id
            media_type = "video"
        elif message.video_note:
            file_id = message.video_note.file_id
            media_type = "video"
        elif message.audio:
            file_id = message.audio.file_id
            media_type = "other"
        elif message.voice:
            file_id = message.voice.file_id
            media_type = "other"
        elif message.document:
            file_id = message.document.file_id
            media_type = "other"
        elif message.photo:
            file_id = message.photo[-1].file_id
            media_type = "other"
    answers[q_num] = {
        "is_text": is_text,
        "text": message.text if is_text else None,
        "file_id": file_id,
        "media_type": media_type,
    }



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
    for i, q in enumerate(questions, start=1):
        answer_data = answers.get(i, {})
        if answer_data.get("is_text") and answer_data.get("text"):
            answer_label = answer_data["text"]
        else:
            answer_label = HW_MEDIA_LABEL
        await update.effective_chat.send_message(
            f"*Вопрос {i}*: {q}\n*Ответ*: {answer_label}",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
    await update.effective_chat.send_message(
        HW_REVIEW_CHANGE_PROMPT,
        reply_markup=get_hw_review_keyboard(len(questions)),
    )


# ── Entry: student taps Приступить ────────────────────────────────────────────

async def handle_start_homework(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()

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
        hw_id = _hw_id(context)

        # Keep the student's message visible during confirmation; delete it on confirm/retry.
        context.user_data["hw_student_msg_id"] = update.message.message_id

        questions = _get_questions(context)
        total = len(questions)
        question = _question_for(q_num, context)
        confirm_text = (
            HW_QUESTION_PROMPT.format(n=q_num, total=total, question=question)
            + f"\n\n{HW_ANSWER_CONFIRM_PROMPT}"
        )
        keyboard = get_hw_answer_confirmation_keyboard(hw_id, q_num)

        msg_id = context.user_data.get("hw_question_msg_id")
        if msg_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=msg_id,
                    text=confirm_text,
                    reply_markup=keyboard,
                )
            except Exception:
                await update.effective_chat.send_message(confirm_text, reply_markup=keyboard)
        else:
            await update.effective_chat.send_message(confirm_text, reply_markup=keyboard)

        return _CONFIRM_STATE[q_num - 1]
    handler.__name__ = f"handle_answer_hw_{q_num}"
    return handler


def _make_confirm_handler(q_num: int):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        query = update.callback_query
        await query.answer()
        next_state = _next_question_state(q_num, context)
        if next_state == REVIEWING:
            student_msg_id = context.user_data.pop("hw_student_msg_id", None)
            if student_msg_id:
                try:
                    await context.bot.delete_message(update.effective_chat.id, student_msg_id)
                except Exception:
                    pass
            await _show_review(update, context)
            return REVIEWING
        next_q = q_num + 1
        await _edit_to_question(next_q, context, update)  # also deletes hw_student_msg_id
        return _ANSWER_STATE[q_num]  # 0-indexed next q
    handler.__name__ = f"handle_confirm_hw_{q_num}"
    return handler


def _make_retry_handler(q_num: int):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        query = update.callback_query
        await query.answer()
        await _edit_to_question(q_num, context, update)
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
            await _ask_question(n, context, update)
            return _ANSWER_STATE[n - 1]
    await _show_review(update, context)
    return REVIEWING


async def handle_review_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Student taps 'Всё верно, отправить'."""
    hw_id = _hw_id(context)
    answers: dict = context.user_data.get("hw_answers", {})

    await update.message.reply_text("Отправляем ваши ответы…", reply_markup=ReplyKeyboardRemove())

    try:
        from repositories.homework_repository import submit_student_answers
        await submit_student_answers(hw_id, answers, context.bot)
    except Exception as e:
        logger.error(f"Failed to submit homework hw_id={hw_id}: {e}", exc_info=True)
        context.user_data.clear()
        await update.message.reply_text(ERROR_MESSAGE)
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text(HW_SUBMITTED, reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END



# ── Build per-question handler instances ─────────────────────────────────────

_answer_handlers = [_make_answer_handler(n) for n in range(1, 6)]
_confirm_handlers = [_make_confirm_handler(n) for n in range(1, 6)]
_retry_handlers = [_make_retry_handler(n) for n in range(1, 6)]

_review_change_filter = filters.TEXT & ~filters.COMMAND & filters.Regex(
    r"^Изменить вопрос [1-5]$"
)
_review_confirm_filter = filters.TEXT & ~filters.COMMAND & filters.Regex(
    f"^{HW_CONFIRM_ALL_BUTTON}$"
)


# ── ConversationHandler registration ─────────────────────────────────────────

hw_student_conversation_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(handle_start_homework, pattern=r"^start_homework_\d+$"),
    ],
    states={
        # Q1
        ANSWERING_HW_1: [MessageHandler(_ACCEPTED_MEDIA & ~filters.COMMAND, _answer_handlers[0])],
        CONFIRMING_HW_1: [
            CallbackQueryHandler(_confirm_handlers[0], pattern=r"^hw_confirm_\d+_1$"),
            CallbackQueryHandler(_retry_handlers[0], pattern=r"^hw_retry_\d+_1$"),
        ],
        # Q2
        ANSWERING_HW_2: [MessageHandler(_ACCEPTED_MEDIA & ~filters.COMMAND, _answer_handlers[1])],
        CONFIRMING_HW_2: [
            CallbackQueryHandler(_confirm_handlers[1], pattern=r"^hw_confirm_\d+_2$"),
            CallbackQueryHandler(_retry_handlers[1], pattern=r"^hw_retry_\d+_2$"),
        ],
        # Q3
        ANSWERING_HW_3: [MessageHandler(_ACCEPTED_MEDIA & ~filters.COMMAND, _answer_handlers[2])],
        CONFIRMING_HW_3: [
            CallbackQueryHandler(_confirm_handlers[2], pattern=r"^hw_confirm_\d+_3$"),
            CallbackQueryHandler(_retry_handlers[2], pattern=r"^hw_retry_\d+_3$"),
        ],
        # Q4
        ANSWERING_HW_4: [MessageHandler(_ACCEPTED_MEDIA & ~filters.COMMAND, _answer_handlers[3])],
        CONFIRMING_HW_4: [
            CallbackQueryHandler(_confirm_handlers[3], pattern=r"^hw_confirm_\d+_4$"),
            CallbackQueryHandler(_retry_handlers[3], pattern=r"^hw_retry_\d+_4$"),
        ],
        # Q5
        ANSWERING_HW_5: [MessageHandler(_ACCEPTED_MEDIA & ~filters.COMMAND, _answer_handlers[4])],
        CONFIRMING_HW_5: [
            CallbackQueryHandler(_confirm_handlers[4], pattern=r"^hw_confirm_\d+_5$"),
            CallbackQueryHandler(_retry_handlers[4], pattern=r"^hw_retry_\d+_5$"),
        ],
        # Review
        REVIEWING: [
            MessageHandler(_review_confirm_filter, handle_review_confirm),
            MessageHandler(_review_change_filter, handle_review_change),
        ],
    },
    fallbacks=[],
    persistent=True,
    name="homework_student",
    conversation_timeout=259200,  # 3 days
)
