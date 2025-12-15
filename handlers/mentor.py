from telegram import Update, ReplyKeyboardRemove, InputFile, Message, MessageId
from telegram.ext import (
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from logger import setup_logger
from io import BytesIO
import json
from timezone_utils import format_moscow
from repositories.user_repository import get_student_anketa_pdf
from database.user_service import find_by_tg_id, get_by_id
from repositories.task_repository import (
    get_earliest_task,
    update_task_status,
    get_task_by_id,
    approve_task,
    disapprove_task,
    get_decided_task_context,
    DecidedTaskContext,
    get_tasks_for_mentor_by_status,
)
from keyboards import (
    get_mentor_action_keyboard,
    get_support_keyboard,
    get_decided_task_navigation_keyboard,
    get_mentor_menu_keyboard,
)
from messages import (
    ERROR_MESSAGE,
    MENTOR_GREETING_TEMPLATE,
    MENTOR_NO_TASK,
    APPROVE_BUTTON,
    DISAPPROVE_BUTTON,
    BACK_BUTTON,
    MENTOR_PREVIOUS_TASK_INVITE,
    NO_PREVIOUS_TASKS,
    TASK_STATUS_APPROVED,
    TASK_STATUS_DISAPPROVED,
    TASK_STATUS_UNCHECKED,
    TASK_INFO_TEMPLATE,
    DONE_BUTTON,
    CHANGE_STATUS_BUTTON,
    STATUS_UPDATED,
    APPROVED_STUDENTS_BUTTON,
    DISAPPROVED_STUDENTS_BUTTON,
    APPROVED_STUDENTS_HEADER,
    DISAPPROVED_STUDENTS_HEADER,
    STUDENT_LIST_EMPTY_MESSAGE,
    STUDENT_LIST_CONTINUATION_LABEL,
    CHECK_NEW_TASK_BUTTON,
)
from database.models import Task, TaskStatus, User, UserRole
from handlers.utils import send_error_message, delete_user_message

logger = setup_logger(__name__)

HISTORY_STATE_KEY = "history_state"
HISTORY_NAV_LEFT = "Назад"
HISTORY_NAV_RIGHT = "Вперёд"
TELEGRAM_MESSAGE_CHAR_LIMIT = 4096


async def handle_mentor(
    user: User, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle mentor user logic."""
    context.user_data.clear()
    await update.message.reply_text(
        MENTOR_GREETING_TEMPLATE,
        reply_markup=ReplyKeyboardRemove(),
    )
    task = get_earliest_task(user.id)
    if task:
        try:
            await send_task(update.effective_chat.id, task, context=context)
        except Exception as e:
            logger.error(f"Error sending earliest task in handle_mentor: {e}")
            await send_error_message(update)
    else:
        await update.message.reply_text(
            MENTOR_NO_TASK, reply_markup=get_mentor_menu_keyboard()
        )


async def send_task(
    chat_id: int,
    task: Task,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Send a task to a mentor with action buttons that include a Back option."""

    context.user_data["current_task_id"] = task.id

    pdf_data = get_student_anketa_pdf(student_id=task.student_id, lead_id=task.lead_id)

    await _send_task_info_message(
        chat_id=chat_id,
        task=task,
        context=context,
        student_name=pdf_data[2],
    )
    await _send_task_payload(
        chat_id=chat_id,
        task=task,
        context=context,
        pdf_data=pdf_data,
        reply_markup=get_mentor_action_keyboard(),
    )


async def _send_task_info_message(
    chat_id: int,
    task: Task,
    context: ContextTypes.DEFAULT_TYPE,
    student_name: str | None = None,
) -> None:
    """Send textual information about the task before attachments."""
    text = _build_task_info_text(task, student_name=student_name)
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )


async def _send_task_payload(
    chat_id: int,
    task: Task,
    context: ContextTypes.DEFAULT_TYPE,
    pdf_data: tuple[str, bytes | None, str | None] | None = None,
    reply_markup=None,
) -> None:
    if pdf_data is None:
        pdf_data = get_student_anketa_pdf(
            student_id=task.student_id, lead_id=task.lead_id
        )

    pdf_filename, pdf_bytes, _ = pdf_data

    # Only send PDF document if it has content
    if pdf_bytes is not None:
        pdf_file = InputFile(BytesIO(pdf_bytes), filename=pdf_filename)
        await context.bot.send_document(
            chat_id=chat_id,
            document=pdf_file,
        )

    await send_media_to_chat(
        context.bot, chat_id, task.file_id, reply_markup=reply_markup
    )


async def send_media_to_chat(
    bot, chat_id: int, file_id: str, reply_markup=None
) -> Message | MessageId:
    """Send task media directly to a chat and return the Telegram message metadata."""
    # Check if it's a message reference (text message)
    msg_ref = parse_message_reference(file_id)
    if msg_ref:
        from_chat_id, message_id = msg_ref
        # Copy the original message to mentor
        return await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=from_chat_id,
            message_id=message_id,
            reply_markup=reply_markup,
        )
    else:
        # It's a regular file_id, try to send as different media types
        return await _try_send_media_types(
            bot, chat_id, file_id, reply_markup=reply_markup
        )


async def _try_send_media_types(
    bot, chat_id: int, file_id: str, reply_markup=None
) -> Message | MessageId:
    """Try to send media as different types (video, video_note, audio, document, photo, voice)."""
    try:
        return await bot.send_video(
            chat_id=chat_id, video=file_id, reply_markup=reply_markup
        )
    except Exception:
        try:
            return await bot.send_video_note(
                chat_id=chat_id, video_note=file_id, reply_markup=reply_markup
            )
        except Exception:
            try:
                return await bot.send_audio(
                    chat_id=chat_id, audio=file_id, reply_markup=reply_markup
                )
            except Exception:
                try:
                    return await bot.send_document(
                        chat_id=chat_id, document=file_id, reply_markup=reply_markup
                    )
                except Exception:
                    try:
                        return await bot.send_photo(
                            chat_id=chat_id, photo=file_id, reply_markup=reply_markup
                        )
                    except Exception:
                        try:
                            return await bot.send_voice(
                                chat_id=chat_id,
                                voice=file_id,
                                reply_markup=reply_markup,
                            )
                        except Exception as e:
                            logger.error(
                                f"Could not send media with file_id {file_id} to chat {chat_id}: {e}"
                            )
                            raise


async def handle_mentor_action(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle mentor action buttons: approve, disapprove."""
    await delete_user_message(update.message)

    text = update.message.text

    user = find_by_tg_id(update.effective_user.id)
    if not user or user.role != UserRole.MENTOR:
        logger.warning("Mentor action attempted by non-mentor user")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=ReplyKeyboardRemove()
        )
        context.user_data.clear()
        return

    current_task_id = context.user_data.get("current_task_id")
    if not current_task_id:
        logger.warning("Missing current_task_id in context")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=ReplyKeyboardRemove()
        )
        context.user_data.clear()
        return

    # Map button text to TaskStatus
    status_mapping = {
        APPROVE_BUTTON: TaskStatus.APPROVED,
        DISAPPROVE_BUTTON: TaskStatus.DISAPPROVED,
    }

    if text not in status_mapping:
        # Invalid button, show error
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_mentor_action_keyboard()
        )
        return

    # Update task status
    try:
        new_status = status_mapping[text]
        update_task_status(current_task_id, new_status)
        if text == APPROVE_BUTTON:
            approve_task(current_task_id)
        elif text == DISAPPROVE_BUTTON:
            disapprove_task(current_task_id)
        logger.info(f"Updated task {current_task_id} to status {new_status.value}")
    except Exception as e:
        logger.error(f"Error updating task status: {e}")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=ReplyKeyboardRemove()
        )
        context.user_data.clear()
        return

    # Send status confirmation with menu keyboard
    status_label = _get_status_label(new_status)
    await update.message.reply_text(
        STATUS_UPDATED.format(status=status_label),
        reply_markup=get_mentor_menu_keyboard(),
    )
    context.user_data.clear()


async def handle_pagination_back(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle pagination back button - show previous task."""
    message = update.message

    await delete_user_message(message)

    mentor = find_by_tg_id(update.effective_user.id)
    if not mentor or mentor.role != UserRole.MENTOR:
        logger.warning("Back button used by non-mentor user")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )
        context.user_data.clear()
        return

    try:
        history_message = await _present_decided_task_view(
            chat_id=update.effective_chat.id,
            mentor_id=mentor.id,
            context=context,
            resend_media=True,
        )
        if not history_message:
            logger.warning("No decided tasks found for back navigation")
            await update.message.reply_text(
                NO_PREVIOUS_TASKS,
                reply_markup=get_mentor_menu_keyboard(),
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
            context.user_data.pop(HISTORY_STATE_KEY, None)
    except Exception as e:
        logger.error(f"Error showing decided task: {e}")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )
        context.user_data.clear()


async def _present_decided_task_view(
    chat_id: int,
    mentor_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    target_task_id: int | None = None,
    resend_media: bool = True,
    cached_task_ids: list[int] | None = None,
) -> Message | None:
    decided_context = get_decided_task_context(
        mentor_id, target_task_id, cached_task_ids=cached_task_ids
    )
    if not decided_context:
        return None

    message = await _send_decided_task_summary(
        chat_id=chat_id,
        decided_context=decided_context,
        context=context,
    )

    if resend_media:
        await _send_task_payload(
            chat_id=chat_id,
            task=decided_context.task,
            context=context,
            reply_markup=None,
        )

    context.user_data[HISTORY_STATE_KEY] = {
        "chat_id": chat_id,
        "message_id": message.message_id,
        "task_id": decided_context.task.id,
        "cached_task_ids": decided_context.cached_task_ids,
    }

    return message


async def _send_decided_task_summary(
    chat_id: int,
    decided_context: DecidedTaskContext,
    context: ContextTypes.DEFAULT_TYPE,
) -> Message:
    keyboard = get_decided_task_navigation_keyboard(
        older_task_id=decided_context.older_task_id,
        newer_task_id=decided_context.newer_task_id,
    )
    text = _build_task_info_text(decided_context.task)

    return await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


def _get_status_label(status: TaskStatus) -> str:
    """Get human-readable label for a task status."""
    status_labels = {
        TaskStatus.APPROVED: TASK_STATUS_APPROVED,
        TaskStatus.DISAPPROVED: TASK_STATUS_DISAPPROVED,
        TaskStatus.UNCHECKED: TASK_STATUS_UNCHECKED,
    }
    return status_labels.get(status, status.value.title())


def _get_student_name(student_id: int) -> str:
    student = get_by_id(student_id)
    if not student:
        return "-"
    parts = [student.first_name, student.last_name]
    name = " ".join(filter(None, parts)).strip()
    return name or "-"


def _build_task_info_text(
    task: Task,
    student_name: str | None = None,
) -> str:
    status_text = _get_status_label(task.status)
    created_at = format_moscow(task.created_at)
    student_text = student_name or _get_student_name(task.student_id)

    return TASK_INFO_TEMPLATE.format(
        student_name=student_text,
        status=status_text,
        created_at=created_at,
    )


def _build_student_names_from_tasks(tasks: list[Task]) -> list[str]:
    seen_ids: set[int] = set()
    names: list[str] = []
    for task in tasks:
        if task.student_id in seen_ids:
            continue
        seen_ids.add(task.student_id)
        names.append(_get_student_name(task.student_id))
    return names


def _chunk_student_list_messages(header: str, student_names: list[str]) -> list[str]:
    if not student_names:
        return [f"{header}\n{STUDENT_LIST_EMPTY_MESSAGE}"]

    messages: list[str] = []
    current = header

    for name in student_names:
        line = f"\n• {name}"
        if len(current) + len(line) > TELEGRAM_MESSAGE_CHAR_LIMIT:
            messages.append(current)
            current = f"{STUDENT_LIST_CONTINUATION_LABEL}{line}"
        else:
            current += line

    messages.append(current)
    return messages


async def _notify_history_status_change(
    context: ContextTypes.DEFAULT_TYPE,
    mentor_id: int,
    task_id: int,
) -> None:
    """Refresh inline summary after mentor changes status via history flow."""
    history_state = context.user_data.get(HISTORY_STATE_KEY, {})
    chat_id = history_state.get("chat_id")
    cached_task_ids = history_state.get("cached_task_ids")

    if chat_id is None:
        return

    try:
        decided_context = get_decided_task_context(
            mentor_id, task_id, cached_task_ids=cached_task_ids
        )
        if not decided_context:
            return

        keyboard = get_decided_task_navigation_keyboard(
            older_task_id=decided_context.older_task_id,
            newer_task_id=decided_context.newer_task_id,
        )
        status_text = _get_status_label(decided_context.task.status)
        await context.bot.send_message(
            chat_id=chat_id,
            text=STATUS_UPDATED.format(status=status_text),
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.error(f"Error notifying about history status change: {e}")


async def end_conversation_with_mentor(
    update: Update, context: ContextTypes.DEFAULT_TYPE, mentor_id: int
) -> None:
    """End conversation with mentor, checking for previous tasks."""
    context.user_data.clear()
    await update.message.reply_text(
        MENTOR_PREVIOUS_TASK_INVITE,
        reply_markup=get_mentor_menu_keyboard(),
    )


async def handle_history_navigation_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle reply keyboard navigation buttons for decided tasks."""
    message = update.message
    await delete_user_message(message)

    text = message.text if message else None
    if text not in (HISTORY_NAV_LEFT, HISTORY_NAV_RIGHT):
        return

    mentor = find_by_tg_id(update.effective_user.id)
    if not mentor or mentor.role != UserRole.MENTOR:
        logger.warning("History navigation attempted by non-mentor user")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )
        context.user_data.clear()
        return

    history_state = context.user_data.get(HISTORY_STATE_KEY) or {}
    current_task_id = history_state.get("task_id")
    cached_task_ids = history_state.get("cached_task_ids")
    if not current_task_id or not cached_task_ids:
        await update.message.reply_text(
            NO_PREVIOUS_TASKS,
            reply_markup=get_mentor_menu_keyboard(),
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
        return

    decided_context = get_decided_task_context(
        mentor.id, current_task_id, cached_task_ids=cached_task_ids
    )
    if not decided_context:
        await update.message.reply_text(
            NO_PREVIOUS_TASKS,
            reply_markup=get_mentor_menu_keyboard(),
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
        return

    target_task_id = (
        decided_context.older_task_id
        if text == HISTORY_NAV_LEFT
        else decided_context.newer_task_id
    )

    if not target_task_id:
        await update.message.reply_text(
            NO_PREVIOUS_TASKS,
            reply_markup=get_mentor_menu_keyboard(),
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
        return

    try:
        message = await _present_decided_task_view(
            chat_id=update.effective_chat.id,
            mentor_id=mentor.id,
            context=context,
            target_task_id=target_task_id,
            resend_media=True,
            cached_task_ids=cached_task_ids,
        )
        if not message:
            await update.message.reply_text(
                NO_PREVIOUS_TASKS,
                reply_markup=get_mentor_menu_keyboard(),
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
            context.user_data.pop(HISTORY_STATE_KEY, None)
    except Exception as e:
        logger.error(f"Error navigating decided tasks: {e}")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )
        context.user_data.clear()


async def handle_history_done_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle 'Done' or 'Check new task' button - fetch earliest task."""
    message = update.message
    await delete_user_message(message)

    mentor = find_by_tg_id(update.effective_user.id)
    if not mentor or mentor.role != UserRole.MENTOR:
        logger.warning("Check new task attempted by non-mentor user")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )
        context.user_data.clear()
        return

    context.user_data.pop(HISTORY_STATE_KEY, None)

    task = get_earliest_task(mentor.id)
    if task:
        try:
            await send_task(update.effective_chat.id, task, context=context)
        except Exception as e:
            logger.error(f"Error sending earliest task: {e}")
            await update.message.reply_text(
                ERROR_MESSAGE, reply_markup=get_support_keyboard()
            )
            context.user_data.clear()
    else:
        await update.message.reply_text(
            MENTOR_NO_TASK, reply_markup=get_mentor_menu_keyboard()
        )


async def handle_check_task_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle callback when mentor clicks 'Check task' button."""
    query = update.callback_query
    await query.answer()

    # Extract task_id from callback_data (format: "check_task_{task_id}")
    try:
        task_id = int(query.data.split("_")[-1])
    except (ValueError, IndexError):
        logger.error(f"Invalid callback data: {query.data}")
        await query.message.reply_text(
            ERROR_MESSAGE, reply_markup=ReplyKeyboardRemove()
        )
        context.user_data.clear()
        return

    # Get task
    task = get_task_by_id(task_id)
    if not task:
        logger.warning(f"Task {task_id} not found")
        await query.message.reply_text(
            ERROR_MESSAGE, reply_markup=ReplyKeyboardRemove()
        )
        context.user_data.clear()
        return

    # Get mentor
    mentor = get_by_id(task.mentor_id)
    if not mentor or mentor.tg_id != query.from_user.id:
        logger.warning(f"Mentor {task.mentor_id} mismatch or not found")
        await query.message.reply_text(
            ERROR_MESSAGE, reply_markup=ReplyKeyboardRemove()
        )
        context.user_data.clear()
        return

    # Send the task and store context
    try:
        await send_task(mentor.tg_id, task, context=context)
        logger.info(f"Sent task {task_id} to mentor {mentor.id} via callback")
    except Exception as e:
        logger.error(f"Error sending task {task_id} to mentor: {e}")
        await query.message.reply_text(
            ERROR_MESSAGE, reply_markup=ReplyKeyboardRemove()
        )
        context.user_data.clear()


def parse_message_reference(file_id: str) -> tuple[int, int] | None:
    """Parse message reference from file_id field. Returns (chat_id, message_id) or None."""
    if file_id.startswith("msg:"):
        try:
            data = json.loads(file_id[4:])
            return (data["chat_id"], data["message_id"])
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Error parsing message reference: {e}")
            return None
    return None


async def handle_history_change_button(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Toggle decided task status between approved/disapproved."""
    message = update.message
    await delete_user_message(message)

    mentor = find_by_tg_id(update.effective_user.id)
    if not mentor or mentor.role != UserRole.MENTOR:
        logger.warning("History change attempted by non-mentor user")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )
        context.user_data.clear()
        return

    history_state = context.user_data.get(HISTORY_STATE_KEY) or {}
    task_id = history_state.get("task_id")
    if not task_id:
        await update.message.reply_text(
            NO_PREVIOUS_TASKS,
            reply_markup=get_mentor_menu_keyboard(),
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
        return

    task = get_task_by_id(task_id)
    if not task:
        logger.warning(f"History task {task_id} not found for mentor {mentor.id}")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )
        context.user_data.pop(HISTORY_STATE_KEY, None)
        return

    if task.status == TaskStatus.APPROVED:
        new_status = TaskStatus.DISAPPROVED
        status_callback = disapprove_task
    elif task.status == TaskStatus.DISAPPROVED:
        new_status = TaskStatus.APPROVED
        status_callback = approve_task
    else:
        logger.warning(
            f"Cannot toggle status {task.status} for task {task.id} in history view"
        )
        await update.message.reply_text(
            NO_PREVIOUS_TASKS,
            reply_markup=get_mentor_menu_keyboard(),
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
        return

    try:
        update_task_status(task.id, new_status)
        status_callback(task.id)
        logger.info(
            f"Toggled history task {task.id} status to {new_status.value} for mentor {mentor.id}"
        )
    except Exception as e:
        logger.error(f"Error toggling history task {task.id} status: {e}")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )
        context.user_data.clear()
        return

    await _notify_history_status_change(context, mentor.id, task.id)


async def handle_mentor_student_list_request(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.message
    await delete_user_message(message)

    text = message.text if message else ""
    status_mapping = {
        APPROVED_STUDENTS_BUTTON: (
            TaskStatus.APPROVED,
            APPROVED_STUDENTS_HEADER,
        ),
        DISAPPROVED_STUDENTS_BUTTON: (
            TaskStatus.DISAPPROVED,
            DISAPPROVED_STUDENTS_HEADER,
        ),
    }

    if text not in status_mapping:
        return

    mentor = find_by_tg_id(update.effective_user.id)
    if not mentor or mentor.role != UserRole.MENTOR:
        logger.warning("Student list requested by non-mentor user")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )
        context.user_data.clear()
        return

    target_status, header = status_mapping[text]

    try:
        tasks = get_tasks_for_mentor_by_status(mentor.id, target_status)
    except Exception as e:
        logger.error(
            f"Error fetching {target_status.value} tasks for mentor {mentor.id}: {e}"
        )
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )
        context.user_data.clear()
        return

    student_names = _build_student_names_from_tasks(tasks)
    messages = _chunk_student_list_messages(header, student_names)

    chat_id = update.effective_chat.id

    for idx, chunk in enumerate(messages):
        await context.bot.send_message(
            chat_id=chat_id,
            text=chunk,
            reply_markup=(
                get_mentor_menu_keyboard() if idx == len(messages) - 1 else None
            ),
        )


# Standalone handlers for mentor flow
mentor_back_button_handler = MessageHandler(
    filters.TEXT & ~filters.COMMAND & filters.Regex(f"^{BACK_BUTTON}$"),
    handle_pagination_back,
)

mentor_action_handler = MessageHandler(
    filters.TEXT
    & ~filters.COMMAND
    & filters.Regex(f"^({APPROVE_BUTTON}|{DISAPPROVE_BUTTON})$"),
    handle_mentor_action,
)

mentor_check_task_handler = CallbackQueryHandler(
    handle_check_task_callback, pattern="^check_task_"
)

mentor_history_nav_handler = MessageHandler(
    filters.TEXT
    & ~filters.COMMAND
    & filters.Regex(f"^({HISTORY_NAV_LEFT}|{HISTORY_NAV_RIGHT})$"),
    handle_history_navigation_message,
)

mentor_history_change_handler = MessageHandler(
    filters.TEXT & ~filters.COMMAND & filters.Regex(f"^{CHANGE_STATUS_BUTTON}$"),
    handle_history_change_button,
)

mentor_history_done_handler = MessageHandler(
    filters.TEXT
    & ~filters.COMMAND
    & filters.Regex(f"^({DONE_BUTTON}|{CHECK_NEW_TASK_BUTTON})$"),
    handle_history_done_message,
)

mentor_student_list_handler = MessageHandler(
    filters.TEXT
    & ~filters.COMMAND
    & filters.Regex(f"^({APPROVED_STUDENTS_BUTTON}|{DISAPPROVED_STUDENTS_BUTTON})$"),
    handle_mentor_student_list_request,
)
