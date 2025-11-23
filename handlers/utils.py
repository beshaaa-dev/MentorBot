from telegram import Update, Message
from logger import setup_logger
from keyboards import get_support_keyboard
from messages import ERROR_MESSAGE

logger = setup_logger(__name__)


async def send_error_message(update: Update):
    reply_markup = get_support_keyboard()
    await update.message.reply_text(ERROR_MESSAGE, reply_markup=reply_markup)


async def delete_user_message(message: Message | None) -> None:
    """Best-effort deletion of the triggering user message."""
    if not message:
        return
    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"Failed to delete user message: {e}")
