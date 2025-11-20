from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler
from logger import setup_logger
from repositories.user_repository import create_student_if_needed, get_crm_user
from database.models import UserRole
from messages import (
    CHECKING_TASK,
    USER_NOT_FOUND,
)
from handlers.utils import send_error_message
from handlers.student import (
    handle_student,
    send_task_message,
    create_student_conversation_handler,
)
from handlers.mentor import handle_mentor

logger = setup_logger(__name__)


async def send_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info(f"User {update.effective_user.id} sent /start command")
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
                CHECKING_TASK, reply_markup=ReplyKeyboardRemove()
            )
            user, task = get_crm_user(user)
            if not user:
                await update.message.reply_text(
                    USER_NOT_FOUND, reply_markup=ReplyKeyboardRemove()
                )
                context.user_data.clear()
                return ConversationHandler.END
            return await send_task_message(task, update, context)
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        await send_error_message(update)
        context.user_data.clear()
        return ConversationHandler.END


start_command_handler = CommandHandler("start", send_task)
video_conversation_handler = create_student_conversation_handler(start_command_handler)
