from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)
from logger import setup_logger
from repositories.user_repository import (
    create_user_if_needed,
    get_crm_user,
    get_task,
)
from repositories.task_repository import create_task
from keyboards import get_support_keyboard, get_confirmation_keyboard
from messages import (
    ERROR_MESSAGE,
    GREETING_WITH_NAME_TEMPLATE,
    CHECKING_TASK,
    USER_NOT_FOUND,
    NO_TASK,
    TASK,
    REQUEST_VIDEO,
    VIDEO_RECEIVED,
    VIDEO_CONFIRMED,
    VIDEO_CANCELLED,
    TASK_SENT_TO_MENTOR,
    CONFIRM_BUTTON,
    CANCEL_BUTTON,
)
from database.models import User

logger = setup_logger(__name__)

# Conversation states
WAITING_FOR_VIDEO = 1
WAITING_FOR_CONFIRMATION = 2


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info(f"User {update.effective_user.id} sent /start command")
    try:
        user = create_user_if_needed(
            update.effective_user.id, update.effective_user.username
        )

        # Если айди нет, то значит либо его нет в AMO CRM, либо информации о нем нет в БД
        if user.crm_id:
            await update.message.reply_text(
                GREETING_WITH_NAME_TEMPLATE.format(name=user.first_name)
            )
            task = get_task(user.crm_id)
            return await send_task(task, update, context)
        else:
            await update.message.reply_text(CHECKING_TASK)
            user, task = get_crm_user(user)
            if not user:
                await update.message.reply_text(USER_NOT_FOUND)
                return ConversationHandler.END
            return await send_task(task, update, context)
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        await send_error_message(update)
        return ConversationHandler.END


async def send_task(
    task: str | None, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not task:
        await update.message.reply_text(NO_TASK)
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
                await update.message.reply_text(TASK_SENT_TO_MENTOR)
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


video_conversation_handler = ConversationHandler(
    entry_points=[
        CommandHandler("start", start),
    ],
    states={
        WAITING_FOR_VIDEO: [
            MessageHandler(filters.VIDEO | filters.VIDEO_NOTE, receive_video),
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_video),
        ],
        WAITING_FOR_CONFIRMATION: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_video),
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel_video)],
)

handlers = [
    video_conversation_handler,
]
