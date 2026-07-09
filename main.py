import os
from dotenv import load_dotenv

# Load environment variables FIRST before any other imports that depend on config
load_dotenv(override=True)

from telegram import Update
from telegram.ext import Application, JobQueue
from logger import setup_logger
from handlers import handlers
from handlers.error_handler import handle_error
from database.db_helper import init_db
from crm.crm_service import init_amo_crm_integration
from thread_safe_persistence import ThreadSafePicklePersistence

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

    # Persistence для сохранения состояния между перезапусками
    persistence = ThreadSafePicklePersistence(
        filepath="bot_persistence.pickle", update_interval=60
    )

    # Регистрируем обработчики (админские, общие, платежные, и т.д.)
    application = (
        Application.builder()
        .token(token)
        .persistence(persistence)
        .concurrent_updates(True)
        .job_queue(JobQueue())
        .build()
    )
    for handler in handlers:
        application.add_handler(handler)

    application.add_error_handler(handle_error)

    # Restore scheduled jobs after startup
    from services.broadcast_scheduler import restore_scheduled_jobs
    from services.broadcast_reminders import restore_reminder_jobs

    application.job_queue.run_once(
        restore_scheduled_jobs,
        when=10,  # Run 10 seconds after startup to ensure everything is initialized
        name="restore_jobs_on_startup",
    )
    
    application.job_queue.run_once(
        restore_reminder_jobs,
        when=12,  # Run 12 seconds after startup, after scheduled jobs are restored
        name="restore_reminders_on_startup",
    )

    # Запускаем бота
    logger.info("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
