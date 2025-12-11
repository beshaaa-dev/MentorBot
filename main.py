import os
from dotenv import load_dotenv

# Load environment variables FIRST before any other imports that depend on config
load_dotenv(override=True)

from telegram.ext import Application
from logger import setup_logger
from handlers import handlers
from database.db_helper import init_db
from crm.crm_service import init_amo_crm_integration

logger = setup_logger(__name__)


def main() -> None:
    # Инициализируем базу данных
    try:
        init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        return

    # Инициализируем AmoCRM интеграцию
    try:
        init_amo_crm_integration()
        logger.info("AmoCRM integration initialized successfully")
    except Exception as e:
        logger.error(f"AmoCRM integration initialization error: {e}")
        return

    # Получаем токен
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment variables")
        return

    # Регистрируем обработчики (админские, общие, платежные, и т.д.)
    application = Application.builder().token(token).build()
    for handler in handlers:
        application.add_handler(handler)

    # Запускаем бота
    logger.info("Bot is starting...")
    application.run_polling()


if __name__ == "__main__":
    main()
