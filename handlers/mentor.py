from telegram import Update, ReplyKeyboardRemove, InputFile
from telegram.ext import (
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from logger import setup_logger
from io import BytesIO
import json
from repositories.user_repository import get_student_anketa_pdf
from database.user_service import find_by_tg_id, get_by_id
from repositories.task_repository import (
    get_earliest_task,
    get_next_task,
    get_previous_task,
    update_task_status,
    get_task_by_id,
    approve_task,
    disapprove_task,
)
from keyboards import (
    get_mentor_action_keyboard,
    get_mentor_action_with_back_keyboard,
    get_back_only_keyboard,
    get_support_keyboard,
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
)
from database.models import Task, TaskStatus, User, UserRole
from handlers.utils import send_error_message

logger = setup_logger(__name__)


async def handle_mentor(
    user: User, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle mentor user logic."""
    await update.message.reply_text(
        MENTOR_GREETING_TEMPLATE.format(first_name=user.first_name),
        reply_markup=ReplyKeyboardRemove(),
    )
    task = get_earliest_task(user.id)
    if task:
        try:
            await show_task_to_mentor(update, context, task, keyboard_type="action")
        except Exception as e:
            logger.error(f"Error sending video or PDF: {e}")
            await update.message.reply_text(
                ERROR_MESSAGE, reply_markup=ReplyKeyboardRemove()
            )
            context.user_data.clear()
    else:
        await update.message.reply_text(
            MENTOR_NO_TASK, reply_markup=get_back_only_keyboard()
        )
        context.user_data.clear()


async def show_task_to_mentor(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    task: Task,
    keyboard_type: str = "action",
) -> None:
    """
     Show task to mentor with video, PDF, and appropriate keyboard.

    Args:
        update: Telegram update object
        context: Bot context
        task: Task instance to show
        keyboard_type: "action" for action buttons, "pagination" for back button only, "action_with_back" for action buttons with back
    """
    try:
        await show_task_to_mentor_chat(
            context.bot, update.effective_chat.id, task, keyboard_type
        )

        # Store task info in context
        context.user_data["current_task_id"] = task.id
    except Exception as e:
        logger.error(f"Error showing task to mentor: {e}")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=ReplyKeyboardRemove()
        )
        context.user_data.clear()
        return


async def show_task_to_mentor_chat(
    bot,
    chat_id: int,
    task: Task,
    keyboard_type: str = "action",
    context: ContextTypes.DEFAULT_TYPE = None,
) -> None:
    """
    Show task to mentor with video, PDF, and appropriate keyboard.

    Args:
        bot: Bot instance
        chat_id: Chat ID to send to
        task: Task instance to show
        keyboard_type: "action" for action buttons, "action_with_back" for action buttons with back
        context: Optional context to store task info
    """
    pdf_filename, pdf_bytes, student_full_name = get_student_anketa_pdf(
        student_id=task.student_id
    )
    pdf_file = InputFile(BytesIO(pdf_bytes), filename=pdf_filename)

    if keyboard_type == "action":
        reply_markup = get_mentor_action_keyboard()
    elif keyboard_type == "action_with_back":
        reply_markup = get_mentor_action_with_back_keyboard()

    await bot.send_document(
        chat_id=chat_id,
        document=pdf_file,
        caption=f"{student_full_name}" if student_full_name else None,
        reply_markup=reply_markup,
    )

    if context:
        context.user_data["current_task_id"] = task.id
        context.user_data["mentor_id"] = task.mentor_id

    await send_media_to_chat(bot, chat_id, task.file_id)


async def send_media_to_chat(bot, chat_id: int, file_id: str) -> None:
    """Send task media directly to a chat. For text messages, uses copy_message. For media, uses file_id."""
    # Check if it's a message reference (text message)
    msg_ref = parse_message_reference(file_id)
    if msg_ref:
        from_chat_id, message_id = msg_ref
        # Copy the original message to mentor
        await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=from_chat_id,
            message_id=message_id,
        )
    else:
        # It's a regular file_id, try to send as different media types
        await _try_send_media_types(bot, chat_id, file_id)


async def _try_send_media_types(bot, chat_id: int, file_id: str) -> None:
    """Try to send media as different types (video, video_note, audio, document, photo, voice)."""
    try:
        await bot.send_video(chat_id=chat_id, video=file_id)
    except Exception:
        try:
            await bot.send_video_note(chat_id=chat_id, video_note=file_id)
        except Exception:
            try:
                await bot.send_audio(chat_id=chat_id, audio=file_id)
            except Exception:
                try:
                    await bot.send_document(chat_id=chat_id, document=file_id)
                except Exception:
                    try:
                        await bot.send_photo(chat_id=chat_id, photo=file_id)
                    except Exception:
                        try:
                            await bot.send_voice(chat_id=chat_id, voice=file_id)
                        except Exception as e:
                            logger.error(
                                f"Could not send media with file_id {file_id} to chat {chat_id}: {e}"
                            )
                            raise


async def end_conversation_with_mentor(
    update: Update, context: ContextTypes.DEFAULT_TYPE, mentor_id: int
) -> None:
    """End conversation with mentor, checking for previous tasks."""
    # Check if there's a previous task (updated within last 60 minutes and created before current)
    previous_task = get_previous_task(mentor_id, None)
    if previous_task:
        # Store data for back button handler
        context.user_data["previous_task_id"] = previous_task.id
        context.user_data["current_task_id"] = None
        await update.message.reply_text(
            MENTOR_PREVIOUS_TASK_INVITE,
            reply_markup=get_back_only_keyboard(),
        )
    else:
        await update.message.reply_text(
            MENTOR_NO_TASK, reply_markup=ReplyKeyboardRemove()
        )
        context.user_data.clear()


async def handle_mentor_action(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle mentor action buttons: approve, disapprove."""
    text = update.message.text

    mentor = find_by_tg_id(update.effective_user.id)
    if not mentor or mentor.role != UserRole.MENTOR:
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
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=ReplyKeyboardRemove()
        )
        context.user_data.clear()
        return

    # Get next task
    try:
        next_task = get_next_task(mentor.id, current_task_id)
        if next_task:
            await show_task_to_mentor(
                update, context, next_task, keyboard_type="action_with_back"
            )
        else:
            await end_conversation_with_mentor(update, context, mentor.id)
    except Exception as e:
        logger.error(f"Error getting next task: {e}")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=ReplyKeyboardRemove()
        )
        context.user_data.clear()


async def handle_pagination_back(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle pagination back button - show previous task."""
    text = update.message.text

    if text != BACK_BUTTON:
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )
        context.user_data.clear()
        return

    mentor = find_by_tg_id(update.effective_user.id)
    if not mentor or mentor.role != UserRole.MENTOR:
        logger.warning("Back button used by non-mentor user")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )
        context.user_data.clear()
        return

    current_task_id = context.user_data.get("current_task_id")
    mentor_id = mentor.id
    previous_task_id = context.user_data.get("previous_task_id")

    # Check if we're coming from the "no earliest task" state
    if previous_task_id and not current_task_id:
        try:
            previous_task = get_task_by_id(previous_task_id)
            if previous_task:
                # Check if there is a task before previous_task - if not, no back button needed
                task_before_previous = get_previous_task(mentor_id, previous_task.id)
                keyboard_type = (
                    "action" if task_before_previous is None else "action_with_back"
                )
                await show_task_to_mentor(
                    update,
                    context,
                    previous_task,
                    keyboard_type=keyboard_type,
                )
                # Clear the stored previous_task_id since we've shown it
                context.user_data.pop("previous_task_id", None)
                return
            else:
                logger.warning(f"Previous task {previous_task_id} not found")
                await update.message.reply_text(
                    ERROR_MESSAGE, reply_markup=get_support_keyboard()
                )
                context.user_data.clear()
                return
        except Exception as e:
            logger.error(f"Error getting previous task: {e}")
            await update.message.reply_text(
                ERROR_MESSAGE, reply_markup=get_support_keyboard()
            )
            context.user_data.clear()
            return

    # Normal back navigation using get_previous_task
    if not current_task_id:
        await update.message.reply_text(
            NO_PREVIOUS_TASKS, reply_markup=get_support_keyboard()
        )
        return

    try:
        # Get previous task chronologically
        previous_task = get_previous_task(mentor_id, current_task_id)
        if previous_task:
            # Check if there is a task before previous_task - if not, no back button needed
            task_before_previous = get_previous_task(mentor_id, previous_task.id)
            keyboard_type = (
                "action" if task_before_previous is None else "action_with_back"
            )
            await show_task_to_mentor(
                update,
                context,
                previous_task,
                keyboard_type=keyboard_type,
            )
        else:
            logger.warning("No previous task found")
            await update.message.reply_text(
                NO_PREVIOUS_TASKS, reply_markup=get_support_keyboard()
            )
            context.user_data.clear()
    except Exception as e:
        logger.error(f"Error getting previous task: {e}")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )
        context.user_data.clear()


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
        await show_task_to_mentor_chat(
            context.bot, mentor.tg_id, task, keyboard_type="action", context=context
        )
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
