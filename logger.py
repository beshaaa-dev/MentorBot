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
    # Create logs directory if it doesn't exist
    if not os.path.exists("logs"):
        os.makedirs("logs")

    # Get or create logger
    logger = logging.getLogger(name)
    
    # Set logging level
    logger.setLevel(logging.DEBUG)  # Set to DEBUG to catch all levels
    
    # Prevent propagation to root logger to avoid duplicate logs
    logger.propagate = False

    # Only configure if not already configured
    if not logger.handlers:
        # Create formatter
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)

        # File handler
        file_handler = logging.FileHandler("logs/bot.log", encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)  # Log everything to file
        file_handler.setFormatter(formatter)

        # Add handlers
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

    return logger
