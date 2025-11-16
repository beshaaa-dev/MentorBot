from telegram import Update, ReplyKeyboardRemove, InputFile
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from logger import setup_logger
from io import BytesIO
import json
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
    get_back_only_keyboard,
    get_check_task_keyboard,
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
    MENTOR_PREVIOUS_TASK_INVITE,
    MENTOR_NEW_TASK_NOTIFICATION,
    CHECK_TASK_BUTTON,
)
from database.models import Task, TaskStatus, User, UserRole
from database.user_service import get_by_id

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

        if user.role == UserRole.MENTOR:
            return await handle_mentor(user, update, context)
        elif user.role == UserRole.STUDENT and user.crm_id:
            return await handle_student(user, update, context)
        else:
            await update.message.reply_text(
                CHECKING_TASK, reply_markup=ReplyKeyboardRemove()
            )
            user, task = get_crm_user(user)
            if not user:
                await update.message.reply_text(
                    USER_NOT_FOUND, reply_markup=ReplyKeyboardRemove()
                )
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
        GREETING_WITH_NAME_TEMPLATE.format(name=user.first_name),
        reply_markup=ReplyKeyboardRemove(),
    )
    task = get_task(user.crm_id)
    return await send_task_message(task, update, context)


async def send_task_message(
    task: str | None, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not task:
        await update.message.reply_text(
            STUDENT_NO_TASK, reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
    message = TASK.format(text=task)
    await update.message.reply_text(
        message, parse_mode="Markdown", reply_markup=ReplyKeyboardRemove()
    )
    return WAITING_FOR_VIDEO


async def send_error_message(update: Update):
    reply_markup = get_support_keyboard()
    await update.message.reply_text(ERROR_MESSAGE, reply_markup=reply_markup)


def create_message_reference(chat_id: int, message_id: int) -> str:
    """Create a message reference string to store in file_id field."""
    return f"msg:{json.dumps({'chat_id': chat_id, 'message_id': message_id})}"


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


async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle received media of any type (text, video, audio, photo, document, etc.)."""
    file_id = None

    # Extract file_id from different media types
    if update.message.video:
        file_id = update.message.video.file_id
    elif update.message.video_note:
        file_id = update.message.video_note.file_id
    elif update.message.audio:
        file_id = update.message.audio.file_id
    elif update.message.document:
        file_id = update.message.document.file_id
    elif update.message.photo:
        # Use the largest photo
        file_id = update.message.photo[-1].file_id
    elif update.message.voice:
        file_id = update.message.voice.file_id
    elif update.message.text:
        # Store message reference instead of converting to file
        file_id = create_message_reference(
            update.effective_chat.id, update.message.message_id
        )

    if file_id:
        # Store file_id in context
        context.user_data["file_id"] = file_id

        reply_markup = get_confirmation_keyboard()
        await update.message.reply_text(VIDEO_RECEIVED, reply_markup=reply_markup)
        return WAITING_FOR_CONFIRMATION
    else:
        await update.message.reply_text(
            REQUEST_VIDEO, reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_FOR_VIDEO


async def confirm_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle media confirmation."""
    text = update.message.text

    if text == CONFIRM_BUTTON:
        await update.message.reply_text(
            VIDEO_CONFIRMED, reply_markup=ReplyKeyboardRemove()
        )
        # Create task with file_id
        try:
            file_id = context.user_data.get("file_id")
            if file_id:
                student_tg_id = update.effective_user.id
                task = create_task(student_tg_id=student_tg_id, file_id=file_id)
                # Send task notification to mentor if they have tg_id
                if task and task.mentor_id:
                    mentor = get_by_id(task.mentor_id)
                    if mentor and mentor.tg_id:
                        try:
                            # Send invitation message with button
                            keyboard = get_check_task_keyboard(task.id)
                            await context.bot.send_message(
                                chat_id=mentor.tg_id,
                                text=MENTOR_NEW_TASK_NOTIFICATION,
                                reply_markup=keyboard,
                            )
                            logger.info(
                                f"Sent task notification to mentor {mentor.id} (tg_id: {mentor.tg_id})"
                            )
                        except Exception as e:
                            logger.error(
                                f"Failed to send task notification to mentor {task.mentor_id}: {e}"
                            )
            else:
                logger.warning("No file_id found in context when confirming")
                await send_error_message(update)
        except Exception as e:
            logger.error(f"Error creating task: {e}")
            await send_error_message(update)
        return ConversationHandler.END
    elif text == CANCEL_BUTTON:
        # Clear the stored file_id since user wants to send again
        context.user_data.pop("file_id", None)
        await update.message.reply_text(
            REQUEST_VIDEO, reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_FOR_VIDEO

    await update.message.reply_text(
        VIDEO_RECEIVED, reply_markup=get_confirmation_keyboard()
    )
    return WAITING_FOR_CONFIRMATION


async def cancel_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the video conversation."""
    await update.message.reply_text(VIDEO_CANCELLED, reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


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


async def send_media(
    update: Update, context: ContextTypes.DEFAULT_TYPE, file_id: str
) -> None:
    """Send task media to mentor. For text messages, uses copy_message. For media, uses file_id."""
    # Check if it's a message reference (text message)
    msg_ref = parse_message_reference(file_id)
    if msg_ref:
        chat_id, message_id = msg_ref
        # Copy the original message to mentor
        await context.bot.copy_message(
            chat_id=update.effective_chat.id,
            from_chat_id=chat_id,
            message_id=message_id,
        )
    else:
        # It's a regular file_id, try to send as different media types
        await _try_send_media_types(context.bot, update.effective_chat.id, file_id)


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
    await send_media_to_chat(bot, chat_id, task.file_id)
    pdf_bytes = get_student_anketa_pdf(student_id=task.student_id)
    pdf_file = InputFile(BytesIO(pdf_bytes), filename="anketa.pdf")

    if keyboard_type == "action":
        reply_markup = get_mentor_action_keyboard()
    elif keyboard_type == "action_with_back":
        reply_markup = get_mentor_action_with_back_keyboard()

    await bot.send_document(
        chat_id=chat_id,
        document=pdf_file,
        reply_markup=reply_markup,
    )

    # Store task info in context if provided
    if context:
        context.user_data["current_task_id"] = task.id
        context.user_data["mentor_id"] = task.mentor_id


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
        raise


async def handle_mentor(
    user: User, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle mentor user logic."""
    await update.message.reply_text(
        MENTOR_GREETING_TEMPLATE.format(first_name=user.first_name),
        reply_markup=ReplyKeyboardRemove(),
    )
    # Store mentor_id in context for later use
    context.user_data["mentor_id"] = user.id
    task = get_earliest_task(user.id)
    if task:
        try:
            await show_task_to_mentor(update, context, task, keyboard_type="action")
        except Exception as e:
            logger.error(f"Error sending video or PDF: {e}")
            await update.message.reply_text(
                ERROR_MESSAGE, reply_markup=ReplyKeyboardRemove()
            )
            return ConversationHandler.END
        return WAITING_FOR_MENTOR_ACTION
    else:
        # Check if there's a previous task (pass None to get most recent regardless of time)
        previous_task = get_previous_task(user.id, current_task_id=None)
        if previous_task:
            # Store previous task ID for back button handler
            context.user_data["previous_task_id"] = previous_task.id
            # нужно ли?
            context.user_data["current_task_id"] = None
            await update.message.reply_text(
                MENTOR_PREVIOUS_TASK_INVITE, reply_markup=get_back_only_keyboard()
            )
            return WAITING_FOR_MENTOR_ACTION
        else:
            await update.message.reply_text(
                MENTOR_NO_TASK, reply_markup=ReplyKeyboardRemove()
            )
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
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=ReplyKeyboardRemove()
        )
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
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=ReplyKeyboardRemove()
        )
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
            # Check if there's a previous task (updated within last 60 minutes and created before current)
            previous_task = get_previous_task(mentor_id, None)
            print("previous_task", previous_task)
            if previous_task:
                # Store previous task ID for back button handler
                context.user_data["previous_task_id"] = previous_task.id
                # нужно ли?
                context.user_data["current_task_id"] = None
                await update.message.reply_text(
                    MENTOR_PREVIOUS_TASK_INVITE,
                    reply_markup=get_back_only_keyboard(),
                )
                return WAITING_FOR_MENTOR_ACTION
            else:
                await update.message.reply_text(
                    MENTOR_NO_TASK, reply_markup=ReplyKeyboardRemove()
                )
                return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error getting next task: {e}")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=ReplyKeyboardRemove()
        )
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
    mentor_id = context.user_data.get("mentor_id")
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

    # Normal back navigation using get_previous_task
    if not current_task_id or not mentor_id:
        logger.warning("Cannot go back: missing current_task_id or mentor_id")
        await update.message.reply_text(
            ERROR_MESSAGE, reply_markup=get_support_keyboard()
        )
        return ConversationHandler.END

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
            return WAITING_FOR_MENTOR_ACTION
        else:
            logger.warning("No previous task found")
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


async def handle_check_task_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
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
        return ConversationHandler.END

    # Get task
    task = get_task_by_id(task_id)
    if not task:
        logger.warning(f"Task {task_id} not found")
        await query.message.reply_text(
            ERROR_MESSAGE, reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

    # Get mentor
    mentor = get_by_id(task.mentor_id)
    if not mentor or mentor.tg_id != query.from_user.id:
        logger.warning(f"Mentor {task.mentor_id} mismatch or not found")
        await query.message.reply_text(
            ERROR_MESSAGE, reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

    # Send the task and store context
    try:
        await show_task_to_mentor_chat(
            context.bot, mentor.tg_id, task, keyboard_type="action", context=context
        )
        logger.info(f"Sent task {task_id} to mentor {mentor.id} via callback")
        return WAITING_FOR_MENTOR_ACTION
    except Exception as e:
        logger.error(f"Error sending task {task_id} to mentor: {e}")
        await query.message.reply_text(
            ERROR_MESSAGE, reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END


video_conversation_handler = ConversationHandler(
    entry_points=[
        CommandHandler("start", send_task),
        CallbackQueryHandler(handle_check_task_callback, pattern="^check_task_"),
    ],
    states={
        WAITING_FOR_VIDEO: [
            MessageHandler(~filters.COMMAND, receive_video),
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
