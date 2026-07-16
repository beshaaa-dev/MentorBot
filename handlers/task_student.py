import asyncio
import re

from telegram import Update, ReplyKeyboardRemove, Message
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from database.task_service import get_task_by_id, update_task_status
from database.models import TaskStatus
from handlers.answer_utils import (
    answers_from_rows,
    clear_flow_data,
    media_exceeds_size_limit,
    send_answer_content,
    store_answer,
)
from keyboards import (
    get_task_answer_confirmation_keyboard,
    get_task_review_keyboard,
)
from messages import (
    TASK_QUESTION_PROMPT,
    TASK_ANSWER_RECEIVED,
    TASK_ANSWERS_REVIEW_QUESTION,
    TASK_REVIEW_QUESTION_HEADER,
    TASK_REVIEW_CHANGE_BUTTON,
    TASK_SUBMITTING,
    TASK_SUBMITTED,
    TASK_NOT_FOUND,
    TASK_CONFIRM_YES_BUTTON,
    TASK_CONFIRM_RETRY_BUTTON,
    TASK_CONFIRM_ALL_BUTTON,
    ERROR_MESSAGE,
    ANSWER_FILE_TOO_LARGE,
)
from logger import setup_logger

logger = setup_logger(__name__)

# ── Conversation states ──────────────────────────────────────────────────────
ANSWERING_TASK_1 = 120
CONFIRMING_TASK_1 = 121
ANSWERING_TASK_2 = 122
CONFIRMING_TASK_2 = 123
ANSWERING_TASK_3 = 124
CONFIRMING_TASK_3 = 125
TASK_REVIEWING = 126

_ANSWER_STATE = [ANSWERING_TASK_1, ANSWERING_TASK_2, ANSWERING_TASK_3]
_CONFIRM_STATE = [CONFIRMING_TASK_1, CONFIRMING_TASK_2, CONFIRMING_TASK_3]

_QUESTION_COUNT = 3

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
    return context.user_data.get("task_questions", [])


def _task_id(context: ContextTypes.DEFAULT_TYPE) -> int:
    return context.user_data.get("task_id", 0)


def _questions_of(task) -> list[str]:
    return [q for q in [task.first_task, task.second_task, task.third_task] if q]


async def _ask_question(
    n: int, context: ContextTypes.DEFAULT_TYPE, update: Update
) -> None:
    questions = _get_questions(context)
    text = TASK_QUESTION_PROMPT.format(
        n=n, total=len(questions), question=questions[n - 1]
    )
    msg = await update.effective_chat.send_message(text)
    context.user_data["task_question_msg_id"] = msg.message_id


async def _delete_answer_msgs(context: ContextTypes.DEFAULT_TYPE, update: Update) -> None:
    """Delete the student's answer message and the current confirm message."""
    for key in ("task_student_msg_id", "task_question_msg_id"):
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
    store_answer(q_num, message, context.user_data.setdefault("task_answers", {}))


def _next_question_state(current_q: int, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Return the ANSWERING state for the next question, or TASK_REVIEWING."""
    if current_q < len(_get_questions(context)):
        return _ANSWER_STATE[current_q]  # 0-indexed → current_q is next q_num
    return TASK_REVIEWING


async def _show_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    questions = _get_questions(context)
    answers: dict = context.user_data.get("task_answers", {})
    chat_id = update.effective_chat.id
    for i, q in enumerate(questions, start=1):
        await context.bot.send_message(
            chat_id,
            TASK_REVIEW_QUESTION_HEADER.format(n=i, question=q),
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove() if i == 1 else None,
        )
        await send_answer_content(answers.get(i, {}), chat_id, context)
    await context.bot.send_message(
        chat_id,
        TASK_ANSWERS_REVIEW_QUESTION,
        reply_markup=get_task_review_keyboard(len(questions)),
    )


# ── Entry: Студент нажал Приступить / Исправить ───────────────────────────────


_OPENABLE_STATUSES = (TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.EDIT)


async def _open_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Общая точка входа.
    """
    query = update.callback_query
    await query.answer()
    clear_flow_data(context, "task_")

    try:
        task_id = int(query.data.split("_")[-1])
    except (ValueError, IndexError):
        await query.message.reply_text(TASK_NOT_FOUND)
        return ConversationHandler.END

    loop = asyncio.get_running_loop()
    task = await loop.run_in_executor(None, get_task_by_id, task_id)
    if not task or not task.first_task or task.status not in _OPENABLE_STATUSES:
        await query.message.reply_text(TASK_NOT_FOUND)
        return ConversationHandler.END

    context.user_data["task_id"] = task_id
    context.user_data["task_questions"] = _questions_of(task)
    context.user_data["task_answers"] = answers_from_rows(task.answers)

    await loop.run_in_executor(
        None, update_task_status, task_id, TaskStatus.IN_PROGRESS
    )

    try:
        await query.message.delete()
    except Exception:
        pass

    if context.user_data["task_answers"]:
        await _show_review(update, context)
        return TASK_REVIEWING

    await _ask_question(1, context, update)
    return ANSWERING_TASK_1


# ── Per-question answer handlers ──────────────────────────────────────────────


def _make_answer_handler(q_num: int):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        if media_exceeds_size_limit(update.message):
            await update.message.reply_text(ANSWER_FILE_TOO_LARGE)
            return _ANSWER_STATE[q_num - 1]  # stay on the same question so the student can resend

        _store_answer(q_num, update.message, context)

        # Keep student's message visible during confirmation; delete it on confirm/retry.
        context.user_data["task_student_msg_id"] = update.message.message_id

        questions = _get_questions(context)
        confirm_text = (
            TASK_QUESTION_PROMPT.format(
                n=q_num, total=len(questions), question=questions[q_num - 1]
            )
            + f"\n\n{TASK_ANSWER_RECEIVED}"
        )

        old_msg_id = context.user_data.pop("task_question_msg_id", None)
        if old_msg_id:
            try:
                await context.bot.delete_message(update.effective_chat.id, old_msg_id)
            except Exception:
                pass

        confirm_msg = await update.effective_chat.send_message(
            confirm_text, reply_markup=get_task_answer_confirmation_keyboard()
        )
        context.user_data["task_question_msg_id"] = confirm_msg.message_id

        return _CONFIRM_STATE[q_num - 1]

    handler.__name__ = f"handle_answer_task_{q_num}"
    return handler


def _make_confirm_handler(q_num: int):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        try:
            await update.message.delete()
        except Exception:
            pass
        if (
            context.user_data.pop("task_review_edit", False)
            or _next_question_state(q_num, context) == TASK_REVIEWING
        ):
            await _delete_answer_msgs(context, update)
            await _show_review(update, context)
            return TASK_REVIEWING
        await _transition_to_question(q_num + 1, context, update)
        return _ANSWER_STATE[q_num]  # 0-indexed next q

    handler.__name__ = f"handle_confirm_task_{q_num}"
    return handler


def _make_retry_handler(q_num: int):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        try:
            await update.message.delete()
        except Exception:
            pass
        await _transition_to_question(q_num, context, update)
        return _ANSWER_STATE[q_num - 1]

    handler.__name__ = f"handle_retry_task_{q_num}"
    return handler


# ── Review state handlers ─────────────────────────────────────────────────────


async def handle_review_change(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text or ""
    for n in range(1, _QUESTION_COUNT + 1):
        if text == TASK_REVIEW_CHANGE_BUTTON.format(n=n):
            if n > len(_get_questions(context)):
                break
            context.user_data["task_review_edit"] = True
            await _ask_question(n, context, update)
            return _ANSWER_STATE[n - 1]
    await _show_review(update, context)
    return TASK_REVIEWING


async def handle_review_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    task_id = _task_id(context)
    answers: dict = context.user_data.get("task_answers", {})

    pending_msg = await update.message.reply_text(
        TASK_SUBMITTING, reply_markup=ReplyKeyboardRemove()
    )

    try:
        from repositories.task_repository import submit_student_task_answers

        await submit_student_task_answers(task_id, answers, context.bot)
    except Exception as e:
        logger.error(f"Failed to submit task task_id={task_id}: {e}", exc_info=True)
        clear_flow_data(context, "task_")
        try:
            await pending_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(ERROR_MESSAGE)
        return ConversationHandler.END

    clear_flow_data(context, "task_")
    try:
        await pending_msg.delete()
    except Exception:
        pass
    await update.message.reply_text(TASK_SUBMITTED)
    return ConversationHandler.END


# ── Build per-question handler instances ─────────────────────────────────────

_answer_handlers = [_make_answer_handler(n) for n in range(1, _QUESTION_COUNT + 1)]
_confirm_handlers = [_make_confirm_handler(n) for n in range(1, _QUESTION_COUNT + 1)]
_retry_handlers = [_make_retry_handler(n) for n in range(1, _QUESTION_COUNT + 1)]

_change_button_pattern = "|".join(
    re.escape(TASK_REVIEW_CHANGE_BUTTON.format(n=n))
    for n in range(1, _QUESTION_COUNT + 1)
)

_confirm_filter = filters.TEXT & ~filters.COMMAND & filters.Regex(f"^{re.escape(TASK_CONFIRM_YES_BUTTON)}$")
_retry_filter = filters.TEXT & ~filters.COMMAND & filters.Regex(f"^{re.escape(TASK_CONFIRM_RETRY_BUTTON)}$")
_review_change_filter = filters.TEXT & ~filters.COMMAND & filters.Regex(f"^({_change_button_pattern})$")
_review_confirm_filter = filters.TEXT & ~filters.COMMAND & filters.Regex(f"^{re.escape(TASK_CONFIRM_ALL_BUTTON)}$")


# ── ConversationHandler registration ─────────────────────────────────────────

task_student_conversation_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(_open_task, pattern=r"^start_task_\d+$"),
        CallbackQueryHandler(_open_task, pattern=r"^edit_task_\d+$"),
    ],
    states={
        ANSWERING_TASK_1: [
            MessageHandler(_ACCEPTED_MEDIA & ~filters.COMMAND, _answer_handlers[0])
        ],
        CONFIRMING_TASK_1: [
            MessageHandler(_confirm_filter, _confirm_handlers[0]),
            MessageHandler(_retry_filter, _retry_handlers[0]),
        ],
        ANSWERING_TASK_2: [
            MessageHandler(_ACCEPTED_MEDIA & ~filters.COMMAND, _answer_handlers[1])
        ],
        CONFIRMING_TASK_2: [
            MessageHandler(_confirm_filter, _confirm_handlers[1]),
            MessageHandler(_retry_filter, _retry_handlers[1]),
        ],
        ANSWERING_TASK_3: [
            MessageHandler(_ACCEPTED_MEDIA & ~filters.COMMAND, _answer_handlers[2])
        ],
        CONFIRMING_TASK_3: [
            MessageHandler(_confirm_filter, _confirm_handlers[2]),
            MessageHandler(_retry_filter, _retry_handlers[2]),
        ],
        TASK_REVIEWING: [
            MessageHandler(_review_confirm_filter, handle_review_confirm),
            MessageHandler(_review_change_filter, handle_review_change),
        ],
    },
    fallbacks=[
        CallbackQueryHandler(_open_task, pattern=r"^start_task_\d+$"),
        CallbackQueryHandler(_open_task, pattern=r"^edit_task_\d+$"),
    ],
    persistent=True,
    name="task_student",
    conversation_timeout=259200,  # 3 days
)
