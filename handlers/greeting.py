from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from logger import setup_logger

logger = setup_logger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info(f"User {update.effective_user.id} sent /start command")
    await update.message.reply_text("Hello, World!")


handlers = [
    CommandHandler("start", start),
]
