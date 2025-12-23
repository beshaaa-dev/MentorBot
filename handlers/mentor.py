from telegram import Update, ReplyKeyboardRemove, InputFile, Message
from telegram.ext import (
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from logger import setup_logger
from io import BytesIO
from timezone_utils import format_moscow
from repositories.user_repository import get_student_anketa_pdf
from database.user_service import find_by_tg_id, get_by_id
from repositories.task_repository import (
    get_earliest_task,
    update_task_status,
    get_task_by_id,
    approve_task,
    disapprove_task,
    TaskStatusChangeNotAllowedError,
    get_decided_task_context,
    DecidedTaskContext,
    get_tasks_for_mentor_by_status,
    get_postponed_task_context,
    PostponedTaskContext,
)
from keyboards import (
    get_mentor_task_decision_keyboard,
    get_support_keyboard,
    get_decided_task_navigation_keyboard,
    get_mentor_menu_keyboard,
    get_postponed_task_navigation_keyboard,
)
from messages import (
    ERROR_MESSAGE,
    MENTOR_GREETING_TEMPLATE,
    MENTOR_NO_TASK,
    BACK_BUTTON,
    MENU_INFO,
    NO_PREVIOUS_TASKS,
    TASK_STATUS_APPROVED,
    TASK_STATUS_DISAPPROVED,
    TASK_STATUS_UNCHECKED,
    TASK_STATUS_POSTPONED,
    TASK_INFO_TEMPLATE,
    TO_MENU_BUTTON,
    APPROVED_STUDENTS_BUTTON,
    DISAPPROVED_STUDENTS_BUTTON,
    APPROVED_STUDENTS_HEADER,
    DISAPPROVED_STUDENTS_HEADER,
    STUDENT_LIST_EMPTY_MESSAGE,
    STUDENT_LIST_CONTINUATION_LABEL,
    CHECK_NEW_TASK_BUTTON,
    POSTPONED_TASKS_BUTTON,
    NO_POSTPONED_TASKS,
    TASK_STATUS_CHANGE_NOT_ALLOWED,
)
from database.models import Task, TaskStatus, User, UserRole
from handlers.utils import (
    send_error_message,
    delete_user_message,
    send_media_to_chat,
)

logger = setup_logger(__name__)

HISTORY_STATE_KEY = "history_state"
POSTPONED_STATE_KEY = "postponed_state"
HISTORY_NAV_LEFT = "Назад"
HISTORY_NAV_RIGHT = "Вперёд"
POSTPONED_NAV_LEFT = "Предыдущая заявка"
POSTPONED_NAV_RIGHT = "Следующая заявка"
TELEGRAM_MESSAGE_CHAR_LIMIT = 4096


# ================================
# Mentor: entry/menu handlers
# ================================


async def handle_mentor(
    user: User, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle mentor user logic."""
    context.user_data.clear()
    await update.message.reply_text(
        MENTOR_GREETING_TEMPLATE,
        reply_markup=ReplyKeyboardRemove(),
    )
    await _send_earliest_task(
        chat_id=update.effective_chat.id,
        mentor_id=user.id,
        context=context,
        update=update,
    )


async def handle_check_new_task_button(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Обработка экшена в меню 'Проверить задание'"""
    message = update.message
    await delete_user_message(message)

    mentor = find_by_tg_id(update.effective_user.id)
    if not mentor or mentor.role != UserRole.MENTOR:
        logger.warning("Check new task button used by non-mentor user")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )
        context.user_data.clear()
        return

    context.user_data.clear()
    await _send_earliest_task(
        chat_id=update.effective_chat.id,
        mentor_id=mentor.id,
        context=context,
        update=update,
    )


# ================================
# Mentor: Task sending
# ================================


async def _send_earliest_task(
    chat_id: int,
    mentor_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    update: Update,
) -> None:
    """Helper to send earliest task or show menu if no tasks available."""
    task = get_earliest_task(mentor_id)
    if task:
        try:
            await send_task(chat_id, task, context=context)
        except Exception as e:
            logger.error(f"Error sending earliest task: {e}")
            await send_error_message(update)
    else:
        await context.bot.send_message(chat_id=chat_id, text=MENTOR_NO_TASK)
        await update.message.reply_text(
            MENU_INFO,
            reply_markup=get_mentor_menu_keyboard(),
            parse_mode="Markdown",
        )


async def handle_to_menu_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Обработка экшена 'В меню'"""
    await delete_user_message(update.message)
    context.user_data.clear()
    await update.message.reply_text(
        MENU_INFO,
        reply_markup=get_mentor_menu_keyboard(),
        parse_mode="Markdown",
    )


async def send_task(
    chat_id: int,
    task: Task,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Send a task to a mentor with action buttons that include a Back option."""
    pdf_data = get_student_anketa_pdf(student_id=task.student_id, lead_id=task.lead_id)

    await _send_task_payload(
        chat_id=chat_id,
        task=task,
        context=context,
        pdf_data=pdf_data,
        reply_markup=get_mentor_menu_keyboard(),
    )

    await _send_task_info_message(
        chat_id=chat_id,
        task=task,
        context=context,
        student_name=pdf_data[2],
        reply_markup=get_mentor_task_decision_keyboard(
            task.id,
            is_check_later_button_hidden=task.status
            in (TaskStatus.APPROVED, TaskStatus.DISAPPROVED),
        ),
    )


async def _send_task_info_message(
    chat_id: int,
    task: Task,
    context: ContextTypes.DEFAULT_TYPE,
    student_name: str | None = None,
    reply_markup=None,
) -> None:
    """Send textual information about the task before attachments."""
    text = _build_task_info_text(task, student_name=student_name)
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=reply_markup,
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

    # Send all task messages, ordered by task_number
    task_messages = sorted(task.task_messages, key=lambda tm: tm.task_number)

    if not task_messages:
        logger.warning(f"Task {task.id} has no task_messages")
        return

    # Send all messages, add reply_markup only to the last one
    for i, task_message in enumerate(task_messages):
        is_last = i == len(task_messages) - 1
        await send_media_to_chat(
            context.bot,
            chat_id,
            task_message.file_id,
            reply_markup=reply_markup if is_last else None,
        )


# ================================
# Mentor: decided tasks history (navigation)
# ================================


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
    cached_task_ids: list[int] | None = None,
) -> Message | None:
    decided_context = get_decided_task_context(
        mentor_id, target_task_id, cached_task_ids=cached_task_ids
    )
    if not decided_context:
        return None

    navigation_keyboard = get_decided_task_navigation_keyboard(
        older_task_id=decided_context.older_task_id,
        newer_task_id=decided_context.newer_task_id,
    )
    await _send_task_payload(
        chat_id=chat_id,
        task=decided_context.task,
        context=context,
        reply_markup=navigation_keyboard,
    )

    message = await _send_decided_task_summary(
        chat_id=chat_id,
        decided_context=decided_context,
        context=context,
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
    keyboard = get_mentor_task_decision_keyboard(
        decided_context.task.id, is_check_later_button_hidden=True
    )
    text = _build_task_info_text(decided_context.task)

    return await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


# ================================
# Mentor: text/formatting helpers
# ================================


def _get_status_label(status: TaskStatus) -> str:
    """Get human-readable label for a task status."""
    status_labels = {
        TaskStatus.APPROVED: TASK_STATUS_APPROVED,
        TaskStatus.DISAPPROVED: TASK_STATUS_DISAPPROVED,
        TaskStatus.UNCHECKED: TASK_STATUS_UNCHECKED,
        TaskStatus.POSTPONED: TASK_STATUS_POSTPONED,
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


# ================================
# Mentor: decided tasks history (reply-keyboard navigation)
# ================================


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


# ================================
# Mentor: inline callbacks (task actions)
# ================================


async def handle_check_task_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle callback when mentor clicks 'Check task' button."""
    query = update.callback_query
    await query.answer()

    # Delete the original message with the button
    try:
        await query.message.delete()
    except Exception:
        pass  # Ignore if message is already deleted or too old

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


# ================================
# Mentor: approve/disapprove/postpone actions
# ================================


async def handle_approve_disapprove_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Обработка экшенов 'Одобрить' и 'Отклонить'"""
    query = update.callback_query
    await query.answer()

    # Extract action and task_id from callback_data (format: "approve_{task_id}" or "disapprove_{task_id}")
    try:
        parts = query.data.split("_")
        action = parts[0]
        task_id = int(parts[1])
    except (ValueError, IndexError):
        logger.error(f"Invalid callback data: {query.data}")
        await query.message.reply_text(
            ERROR_MESSAGE, reply_markup=ReplyKeyboardRemove()
        )
        return

    # Verify user is mentor
    user = find_by_tg_id(query.from_user.id)
    if not user or user.role != UserRole.MENTOR:
        logger.warning("Approve/disapprove callback by non-mentor user")
        await query.message.reply_text(
            ERROR_MESSAGE, reply_markup=ReplyKeyboardRemove()
        )
        return

    # Update task status
    try:
        if action == "approve":
            new_status = TaskStatus.APPROVED
            approve_task(task_id)
        elif action == "disapprove":
            new_status = TaskStatus.DISAPPROVED
            disapprove_task(task_id)
        else:
            raise ValueError(f"Unknown action: {action}")

        task = update_task_status(task_id, new_status)
        logger.info(f"Updated task {task_id} to action {action} via callback")
    except TaskStatusChangeNotAllowedError as e:
        logger.info(f"Task status change is not allowed for task_id={task_id}: {e}")
        await query.message.reply_text(
            TASK_STATUS_CHANGE_NOT_ALLOWED,
            reply_markup=get_mentor_menu_keyboard(),
        )
        return
    except Exception as e:
        logger.error(f"Error updating task status: {e}")
        await query.message.reply_text(
            ERROR_MESSAGE, reply_markup=ReplyKeyboardRemove()
        )
        return

    # Edit the message to show task info with updated status
    if task:
        text = _build_task_info_text(task)
        try:
            await query.edit_message_text(
                text=text,
                parse_mode="Markdown",
                reply_markup=get_mentor_task_decision_keyboard(
                    task.id,
                    is_check_later_button_hidden=True,
                ),
            )
        except Exception as e:
            logger.warning(f"Could not edit message: {e}")

    # Check for next earliest task
    next_task = get_earliest_task(user.id)
    if next_task:
        try:
            await send_task(query.message.chat_id, next_task, context=context)
        except Exception as e:
            logger.error(f"Error sending next earliest task: {e}")
            await send_error_message(update)


async def handle_postpone_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Обработчик экшена 'Сомневаюсь'"""
    query = update.callback_query
    await query.answer()

    # Extract task_id from callback_data (format: "postpone_{task_id}")
    try:
        task_id = int(query.data.split("_")[-1])
    except (ValueError, IndexError):
        logger.error(f"Invalid callback data: {query.data}")
        await query.message.reply_text(
            ERROR_MESSAGE, reply_markup=ReplyKeyboardRemove()
        )
        return

    # Verify user is mentor
    user = find_by_tg_id(query.from_user.id)
    if not user or user.role != UserRole.MENTOR:
        logger.warning("Check later callback by non-mentor user")
        await query.message.reply_text(
            ERROR_MESSAGE, reply_markup=ReplyKeyboardRemove()
        )
        return

    # Update task status to POSTPONED
    try:
        task = update_task_status(task_id, TaskStatus.POSTPONED)
        logger.info(f"Updated task {task_id} to status POSTPONED via callback")
    except Exception as e:
        logger.error(f"Error updating task status to POSTPONED: {e}")
        await query.message.reply_text(
            ERROR_MESSAGE, reply_markup=ReplyKeyboardRemove()
        )
        return

    # Edit the message to show task info with updated status

    if not task:
        logger.error("Error updating task status to POSTPONED")
        await query.message.reply_text(
            ERROR_MESSAGE, reply_markup=ReplyKeyboardRemove()
        )
        return

    text = _build_task_info_text(task)
    try:
        await query.edit_message_text(
            text=text,
            parse_mode="Markdown",
            reply_markup=get_mentor_task_decision_keyboard(
                task.id,
                is_check_later_button_hidden=True,
            ),
        )
    except Exception as e:
        logger.warning(f"Could not edit message: {e}")

    # Check for next earliest task
    next_task = get_earliest_task(user.id)
    if next_task:
        try:
            await send_task(query.message.chat_id, next_task, context=context)
        except Exception as e:
            logger.error(f"Error sending next earliest task: {e}")
            await send_error_message(update)


# ================================
# Mentor: approved/disapproved students lists
# ================================


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


# ================================
# Mentor: postponed tasks flow (list & navigation)
# ================================


async def handle_postponed_tasks_button(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Обработка экшена в меню 'Отложенные заявки'"""
    message = update.message
    await delete_user_message(message)

    mentor = find_by_tg_id(update.effective_user.id)
    if not mentor or mentor.role != UserRole.MENTOR:
        logger.warning("Postponed tasks button used by non-mentor user")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )
        context.user_data.clear()
        return

    try:
        result = await _present_postponed_task_view(
            chat_id=update.effective_chat.id,
            mentor_id=mentor.id,
            context=context,
            resend_media=True,
        )
        if not result:
            await update.message.reply_text(
                NO_POSTPONED_TASKS,
                reply_markup=get_mentor_menu_keyboard(),
            )
            context.user_data.pop(POSTPONED_STATE_KEY, None)
    except Exception as e:
        logger.error(f"Error showing postponed task: {e}")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )
        context.user_data.clear()


async def _present_postponed_task_view(
    chat_id: int,
    mentor_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    target_task_id: int | None = None,
    resend_media: bool = True,
    cached_task_ids: list[int] | None = None,
) -> Message | None:
    """Present a postponed task with navigation and decision buttons."""
    postponed_context = get_postponed_task_context(
        mentor_id, target_task_id, cached_task_ids=cached_task_ids
    )
    if not postponed_context:
        return None

    if resend_media:
        # Send navigation keyboard with task payload
        keyboard = get_postponed_task_navigation_keyboard(
            older_task_id=postponed_context.older_task_id,
            newer_task_id=postponed_context.newer_task_id,
        )
        await _send_task_payload(
            chat_id=chat_id,
            task=postponed_context.task,
            context=context,
            reply_markup=keyboard,
        )

    message = await _send_postponed_task_summary(
        chat_id=chat_id,
        postponed_context=postponed_context,
        context=context,
    )

    context.user_data[POSTPONED_STATE_KEY] = {
        "chat_id": chat_id,
        "message_id": message.message_id,
        "task_id": postponed_context.task.id,
        "cached_task_ids": postponed_context.cached_task_ids,
    }

    return message


async def _send_postponed_task_summary(
    chat_id: int,
    postponed_context: PostponedTaskContext,
    context: ContextTypes.DEFAULT_TYPE,
) -> Message:
    """Send postponed task info with inline decision buttons."""
    text = _build_task_info_text(postponed_context.task)
    return await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=get_mentor_task_decision_keyboard(
            postponed_context.task.id,
            is_check_later_button_hidden=True,
        ),
    )


async def handle_postponed_navigation_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle reply keyboard navigation buttons for postponed tasks."""
    # Check if we're in postponed state
    if POSTPONED_STATE_KEY not in context.user_data:
        return

    message = update.message
    await delete_user_message(message)

    text = message.text if message else None
    if text not in (POSTPONED_NAV_LEFT, POSTPONED_NAV_RIGHT):
        return

    mentor = find_by_tg_id(update.effective_user.id)
    if not mentor or mentor.role != UserRole.MENTOR:
        logger.warning("Postponed navigation attempted by non-mentor user")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )
        context.user_data.clear()
        return

    postponed_state = context.user_data.get(POSTPONED_STATE_KEY) or {}
    current_task_id = postponed_state.get("task_id")
    cached_task_ids = postponed_state.get("cached_task_ids")
    if not current_task_id or not cached_task_ids:
        await update.message.reply_text(
            NO_POSTPONED_TASKS,
            reply_markup=get_mentor_menu_keyboard(),
        )
        context.user_data.pop(POSTPONED_STATE_KEY, None)
        return

    postponed_context = get_postponed_task_context(
        mentor.id, current_task_id, cached_task_ids=cached_task_ids
    )
    if not postponed_context:
        await update.message.reply_text(
            NO_POSTPONED_TASKS,
            reply_markup=get_mentor_menu_keyboard(),
        )
        context.user_data.pop(POSTPONED_STATE_KEY, None)
        return

    target_task_id = (
        postponed_context.older_task_id
        if text == POSTPONED_NAV_LEFT
        else postponed_context.newer_task_id
    )

    if not target_task_id:
        await update.message.reply_text(
            NO_POSTPONED_TASKS,
            reply_markup=get_mentor_menu_keyboard(),
        )
        return

    try:
        result = await _present_postponed_task_view(
            chat_id=update.effective_chat.id,
            mentor_id=mentor.id,
            context=context,
            target_task_id=target_task_id,
            resend_media=True,
            cached_task_ids=cached_task_ids,
        )
        if not result:
            await update.message.reply_text(
                NO_POSTPONED_TASKS,
                reply_markup=get_mentor_menu_keyboard(),
            )
            context.user_data.pop(POSTPONED_STATE_KEY, None)
    except Exception as e:
        logger.error(f"Error navigating postponed tasks: {e}")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )
        context.user_data.clear()


# ================================
# Mentor: handler registrations
# ================================

# Standalone handlers for mentor flow
mentor_back_button_handler = MessageHandler(
    filters.TEXT & ~filters.COMMAND & filters.Regex(f"^{BACK_BUTTON}$"),
    handle_pagination_back,
)

mentor_check_task_handler = CallbackQueryHandler(
    handle_check_task_callback, pattern="^check_task_"
)

mentor_approve_disapprove_handler = CallbackQueryHandler(
    handle_approve_disapprove_callback, pattern="^(approve|disapprove)_\\d+$"
)

mentor_history_nav_handler = MessageHandler(
    filters.TEXT
    & ~filters.COMMAND
    & filters.Regex(f"^({HISTORY_NAV_LEFT}|{HISTORY_NAV_RIGHT})$"),
    handle_history_navigation_message,
)

mentor_to_menu_handler = MessageHandler(
    filters.TEXT & ~filters.COMMAND & filters.Regex(f"^{TO_MENU_BUTTON}$"),
    handle_to_menu_message,
)

mentor_student_list_handler = MessageHandler(
    filters.TEXT
    & ~filters.COMMAND
    & filters.Regex(f"^({APPROVED_STUDENTS_BUTTON}|{DISAPPROVED_STUDENTS_BUTTON})$"),
    handle_mentor_student_list_request,
)

mentor_postpone_handler = CallbackQueryHandler(
    handle_postpone_callback, pattern="^postpone_\\d+$"
)

mentor_check_new_task_handler = MessageHandler(
    filters.TEXT & ~filters.COMMAND & filters.Regex(f"^{CHECK_NEW_TASK_BUTTON}$"),
    handle_check_new_task_button,
)

mentor_postponed_tasks_handler = MessageHandler(
    filters.TEXT & ~filters.COMMAND & filters.Regex(f"^{POSTPONED_TASKS_BUTTON}$"),
    handle_postponed_tasks_button,
)

mentor_postponed_nav_handler = MessageHandler(
    filters.TEXT
    & ~filters.COMMAND
    & filters.Regex(f"^({POSTPONED_NAV_LEFT}|{POSTPONED_NAV_RIGHT})$"),
    handle_postponed_navigation_message,
)
