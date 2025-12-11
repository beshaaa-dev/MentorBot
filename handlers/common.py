from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)
from logger import setup_logger
from repositories.user_repository import create_student_if_needed, get_crm_user
from database.models import UserRole
from messages import (
    FINDING_USER,
    USER_NOT_FOUND,
    SUPPORT_MESSAGE,
    UNKNOWN_MESSAGE,
)
from handlers.utils import send_error_message, delete_user_message
from handlers.student import (
    handle_student,
    create_student_conversation_handler,
)
from handlers.mentor import handle_mentor
from keyboards import get_support_keyboard

logger = setup_logger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info(f"User {update.effective_user.id} sent /start command")
    await delete_user_message(update.message)
    try:
        user = create_student_if_needed(
            update.effective_user.id, update.effective_user.username
        )

        if user.role == UserRole.MENTOR:
            await handle_mentor(user, update, context)
            return ConversationHandler.END  # Mentor flow uses standalone handlers
        elif user.role == UserRole.STUDENT and user.crm_id:
            return await handle_student(user, update, context)
        else:
            await update.message.reply_text(
                FINDING_USER, reply_markup=ReplyKeyboardRemove()
            )
            user, _ = get_crm_user(user)
            if not user:
                await update.message.reply_text(
                    USER_NOT_FOUND, reply_markup=ReplyKeyboardRemove()
                )
                context.user_data.clear()
                return ConversationHandler.END
            return await handle_student(user, update, context)
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        await send_error_message(update)
        context.user_data.clear()
        return ConversationHandler.END


async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_user_message(update.message)
    await update.message.reply_text(
        SUPPORT_MESSAGE, reply_markup=get_support_keyboard()
    )


async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle any unrecognized commands or messages."""
    await update.message.reply_text(UNKNOWN_MESSAGE)


start_command_handler = CommandHandler("start", start)
support_command_handler = CommandHandler("support", support)
video_conversation_handler = create_student_conversation_handler(start_command_handler)
unknown_message_handler = MessageHandler(filters.ALL, unknown_message)
