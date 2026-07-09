import traceback

from telegram import Update
from telegram.ext import ContextTypes

from logger import setup_logger

logger = setup_logger(__name__)


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log any exception raised inside a handler.

    Without a registered error handler, python-telegram-bot aborts the handler
    group and the user simply gets no reply.
    """
    tb = "".join(
        traceback.format_exception(
            type(context.error), context.error, context.error.__traceback__
        )
    )

    user_id = None
    chat_id = None
    if isinstance(update, Update):
        if update.effective_user:
            user_id = update.effective_user.id
        if update.effective_chat:
            chat_id = update.effective_chat.id

    logger.error(
        f"Unhandled exception (user={user_id}, chat={chat_id}): "
        f"{context.error}\n{tb}"
    )
