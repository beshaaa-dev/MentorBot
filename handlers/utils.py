from telegram import Update
from logger import setup_logger
from keyboards import get_support_keyboard
from messages import ERROR_MESSAGE

logger = setup_logger(__name__)


async def send_error_message(update: Update):
    reply_markup = get_support_keyboard()
    await update.message.reply_text(ERROR_MESSAGE, reply_markup=reply_markup)
