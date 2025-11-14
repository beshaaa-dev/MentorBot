from telegram import Update, ReplyKeyboardRemove, InputFile
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)
from logger import setup_logger
from io import BytesIO
from repositories.user_repository import (
    create_student_if_needed,
    get_crm_user,
    get_task,
    get_student_anketa_pdf,
)
from repositories.task_repository import (
    create_task,
    get_earliest_task,
    get_next_task,
    get_previous_task,
    update_task_status,
    get_task_by_id,
    approve_task,
    disapprove_task,
)
from keyboards import (
    get_support_keyboard,
    get_confirmation_keyboard,
    get_mentor_action_keyboard,
    get_mentor_action_with_back_keyboard,
)
from messages import (
    ERROR_MESSAGE,
    GREETING_WITH_NAME_TEMPLATE,
    MENTOR_GREETING_TEMPLATE,
    CHECKING_TASK,
    USER_NOT_FOUND,
    MENTOR_NO_TASK,
    STUDENT_NO_TASK,
    TASK,
    REQUEST_VIDEO,
    VIDEO_RECEIVED,
    VIDEO_CONFIRMED,
    VIDEO_CANCELLED,
    CONFIRM_BUTTON,
    CANCEL_BUTTON,
    APPROVE_BUTTON,
    DISAPPROVE_BUTTON,
    BACK_BUTTON,
)
from database.models import Task, TaskStatus, User, UserRole

logger = setup_logger(__name__)

# Conversation states
WAITING_FOR_VIDEO = 1
WAITING_FOR_CONFIRMATION = 2
WAITING_FOR_MENTOR_ACTION = 3


async def send_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info(f"User {update.effective_user.id} sent /start command")
    try:
        user = create_student_if_needed(
            update.effective_user.id, update.effective_user.username
        )

        # Если айди нет, то значит либо его нет в AMO CRM, либо информации о нем нет в БД
        if user.crm_id:
            if user.role == UserRole.STUDENT:
                return await handle_student(user, update, context)
            elif user.role == UserRole.MENTOR:
                return await handle_mentor(user, update, context)
        else:
            await update.message.reply_text(CHECKING_TASK)
            user, task = get_crm_user(user)
            if not user:
                await update.message.reply_text(USER_NOT_FOUND)
                return ConversationHandler.END
            return await send_task_message(task, update, context)
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        await send_error_message(update)
        return ConversationHandler.END


async def handle_student(
    user: User, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle student user logic."""
    await update.message.reply_text(
        GREETING_WITH_NAME_TEMPLATE.format(name=user.first_name)
    )
    task = get_task(user.crm_id)
    return await send_task_message(task, update, context)


async def send_task_message(
    task: str | None, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not task:
        await update.message.reply_text(STUDENT_NO_TASK)
        return ConversationHandler.END
    message = TASK.format(text=task)
    await update.message.reply_text(message, parse_mode="Markdown")
    return WAITING_FOR_VIDEO


async def send_error_message(update: Update):
    reply_markup = get_support_keyboard()
    await update.message.reply_text(ERROR_MESSAGE, reply_markup=reply_markup)


async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle received video."""
    if update.message.video or update.message.video_note:
        # Store video in context for later use
        if update.message.video:
            context.user_data["video"] = update.message.video
        elif update.message.video_note:
            context.user_data["video_note"] = update.message.video_note

        reply_markup = get_confirmation_keyboard()
        await update.message.reply_text(VIDEO_RECEIVED, reply_markup=reply_markup)
        return WAITING_FOR_CONFIRMATION
    else:
        await update.message.reply_text(REQUEST_VIDEO)
        return WAITING_FOR_VIDEO


async def confirm_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle video confirmation."""
    text = update.message.text

    if text == CONFIRM_BUTTON:
        await update.message.reply_text(
            VIDEO_CONFIRMED, reply_markup=ReplyKeyboardRemove()
        )
        # Create task with video
        try:
            video = context.user_data.get("video") or context.user_data.get(
                "video_note"
            )
            if video:
                file_id = video.file_id
                student_tg_id = update.effective_user.id
                create_task(student_tg_id=student_tg_id, file_id=file_id)
            else:
                logger.warning("No video found in context when confirming")
                await send_error_message(update)
        except Exception as e:
            logger.error(f"Error creating task: {e}")
            await send_error_message(update)
        return ConversationHandler.END
    elif text == CANCEL_BUTTON:
        await update.message.reply_text(
            VIDEO_CANCELLED, reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

    await update.message.reply_text(
        VIDEO_RECEIVED, reply_markup=get_confirmation_keyboard()
    )
    return WAITING_FOR_CONFIRMATION


async def cancel_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the video conversation."""
    await update.message.reply_text(VIDEO_CANCELLED, reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def send_video(update: Update, file_id: str) -> None:
    """Send task video to mentor, trying video first, then video_note."""
    try:
        await update.message.reply_video(file_id)
    except Exception:
        await update.message.reply_video_note(file_id)


async def show_task_to_mentor(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    task: Task,
    keyboard_type: str = "action",
    add_to_history: bool = True,
) -> None:
    """
    Show task to mentor with video, PDF, and appropriate keyboard.

    Args:
        update: Telegram update object
        context: Bot context
        task: Task instance to show
        keyboard_type: "action" for action buttons, "pagination" for back button only, "action_with_back" for action buttons with back
        add_to_history: Whether to add task to history (default True)
    """
    try:
        await send_video(update, task.file_id)
        pdf_bytes = get_student_anketa_pdf(student_id=task.student_id)
        pdf_file = InputFile(BytesIO(pdf_bytes), filename="anketa.pdf")

        if keyboard_type == "action":
            reply_markup = get_mentor_action_keyboard()
        elif keyboard_type == "action_with_back":
            reply_markup = get_mentor_action_with_back_keyboard()

        await update.message.reply_document(
            document=pdf_file, reply_markup=reply_markup
        )

        # Store task info in context
        context.user_data["current_task_id"] = task.id
        if add_to_history:
            if "task_history" not in context.user_data:
                context.user_data["task_history"] = []
            context.user_data["task_history"].append(task.id)
    except Exception as e:
        logger.error(f"Error showing task to mentor: {e}")
        raise


async def handle_mentor(
    user: User, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle mentor user logic."""
    await update.message.reply_text(
        MENTOR_GREETING_TEMPLATE.format(first_name=user.first_name)
    )
    # Store mentor_id in context for later use
    context.user_data["mentor_id"] = user.id
    task = get_earliest_task(user.id)
    if task:
        try:
            await show_task_to_mentor(update, context, task, keyboard_type="action")
        except Exception as e:
            logger.error(f"Error sending video or PDF: {e}")
            await update.message.reply_text(ERROR_MESSAGE)
            return ConversationHandler.END
        return WAITING_FOR_MENTOR_ACTION
    else:
        await update.message.reply_text(MENTOR_NO_TASK)
        return ConversationHandler.END


async def handle_mentor_action(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle mentor action buttons: approve, disapprove, or check later."""
    text = update.message.text
    current_task_id = context.user_data.get("current_task_id")
    mentor_id = context.user_data.get("mentor_id")

    if not current_task_id or not mentor_id:
        logger.warning("Missing current_task_id or mentor_id in context")
        await update.message.reply_text(ERROR_MESSAGE)
        return ConversationHandler.END

    # Map button text to TaskStatus
    status_mapping = {
        APPROVE_BUTTON: TaskStatus.APPROVED,
        DISAPPROVE_BUTTON: TaskStatus.DISAPPROVED,
    }

    if text not in status_mapping:
        # Invalid button, show error and keep waiting
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_mentor_action_keyboard()
        )
        return WAITING_FOR_MENTOR_ACTION

    # Update task status
    try:
        update_task_status(current_task_id, status_mapping[text])
        if text == APPROVE_BUTTON:
            approve_task(current_task_id)
        elif text == DISAPPROVE_BUTTON:
            disapprove_task(current_task_id)
        logger.info(
            f"Updated task {current_task_id} to status {status_mapping[text].value}"
        )
    except Exception as e:
        logger.error(f"Error updating task status: {e}")
        await update.message.reply_text(ERROR_MESSAGE)
        return ConversationHandler.END

    # Get next task
    try:
        next_task = get_next_task(mentor_id, current_task_id)
        if next_task:
            await show_task_to_mentor(
                update, context, next_task, keyboard_type="action_with_back"
            )
            return WAITING_FOR_MENTOR_ACTION
        else:
            await update.message.reply_text(
                MENTOR_NO_TASK, reply_markup=ReplyKeyboardRemove()
            )
            return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error getting next task: {e}")
        await update.message.reply_text(ERROR_MESSAGE)
        return ConversationHandler.END


async def handle_pagination_back(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle pagination back button - show previous task."""
    text = update.message.text

    if text != BACK_BUTTON:
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )
        return ConversationHandler.END

    current_task_id = context.user_data.get("current_task_id")
    task_history = context.user_data.get("task_history", [])

    if not current_task_id or len(task_history) < 2:
        logger.warning("Cannot go back: insufficient history")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )
        return ConversationHandler.END

    # Remove current task from history
    task_history.pop()
    previous_task_id = task_history[-1]

    try:
        # Get previous task by ID from history
        previous_task = get_task_by_id(previous_task_id)
        if previous_task:
            await show_task_to_mentor(
                update,
                context,
                previous_task,
                keyboard_type="action",
                add_to_history=False,
            )
            return WAITING_FOR_MENTOR_ACTION
        else:
            logger.warning(f"Previous task {previous_task_id} not found")
            await update.message.reply_text(
                ERROR_MESSAGE, reply_markup=get_support_keyboard()
            )
            return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error getting previous task: {e}")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )
        return ConversationHandler.END


video_conversation_handler = ConversationHandler(
    entry_points=[
        CommandHandler("start", send_task),
    ],
    states={
        WAITING_FOR_VIDEO: [
            MessageHandler(filters.VIDEO | filters.VIDEO_NOTE, receive_video),
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_video),
        ],
        WAITING_FOR_CONFIRMATION: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_video),
        ],
        WAITING_FOR_MENTOR_ACTION: [
            MessageHandler(
                filters.TEXT
                & ~filters.COMMAND
                & filters.Regex(f"^({APPROVE_BUTTON}|{DISAPPROVE_BUTTON})$"),
                handle_mentor_action,
            ),
            MessageHandler(
                filters.TEXT & ~filters.COMMAND & filters.Regex(f"^{BACK_BUTTON}$"),
                handle_pagination_back,
            ),
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel_video)],
)

handlers = [
    video_conversation_handler,
]
