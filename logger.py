import logging
import os


def setup_logger(name: str = None) -> logging.Logger:
    """
    Setup and return a logger instance.

    Args:
        name: Logger name (usually __name__). If None, uses root logger.

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Only configure if not already configured
    if not logger.handlers:
        # Create logs directory if it doesn't exist
        if not os.path.exists("logs"):
            os.makedirs("logs")

        # Set logging level
        logger.setLevel(logging.INFO)

        # Create formatter
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)

        # File handler
        file_handler = logging.FileHandler("logs/bot.log")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)

        # Add handlers
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

    return logger
