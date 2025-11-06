import os
from telegram.ext import Application
from dotenv import load_dotenv
from logger import setup_logger
from handlers.greeting import handlers as greeting_handlers
from database.db_helper import init_db

load_dotenv()

logger = setup_logger(__name__)


def main() -> None:
    # Инициализируем базу данных
    try:
        init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        return

    # Получаем токен
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment variables")
        return

    # Регистрируем обработчики (админские, общие, платежные, и т.д.)
    application = Application.builder().token(token).build()
    for handler in greeting_handlers:
        application.add_handler(handler)

    # Запускаем бота
    logger.info("Bot is starting...")
    application.run_polling()
    logger.info("Bot is started")


if __name__ == "__main__":
    main()
