"""
Async File Logger for ELOC Processing

Provides non-blocking file logging using QueueHandler and QueueListener.
Log writes happen on a separate thread to avoid blocking the async event loop.

Log format: {datetime} - {module} - {funcName} - {level} - {message}
Log path: C:\logging\ELOC Processing\eloc_processing.log
"""
import logging
import os
import atexit
from pathlib import Path
from queue import Queue
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from datetime import datetime

# Log directory and file
LOG_DIR = Path(r"C:\logging\ELOC Processing")
LOG_FILE = LOG_DIR / "eloc_processing.log"
MAX_LOG_SIZE = 10 * 1024 * 1024  # 10 MB
BACKUP_COUNT = 5  # Keep 5 backup files

# Global listener (needs to be stopped on exit)
_queue_listener: QueueListener = None
_log_queue: Queue = None


def setup_async_file_logging(level: int = logging.INFO) -> logging.Handler:
    """
    Set up async file logging with QueueHandler.

    This creates:
    1. A log directory if it doesn't exist
    2. A RotatingFileHandler for the actual file writes
    3. A QueueHandler that puts log records in a queue (non-blocking)
    4. A QueueListener that processes the queue on a separate thread

    Args:
        level: Logging level (default: INFO)

    Returns:
        QueueHandler to be added to loggers
    """
    global _queue_listener, _log_queue

    # Create log directory if it doesn't exist
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Create formatter with datetime, module, function, level, message
    formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(funcName)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Create rotating file handler (writes to file)
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=MAX_LOG_SIZE,
        backupCount=BACKUP_COUNT,
        encoding='utf-8'
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    # Create queue for async logging
    _log_queue = Queue(-1)  # No size limit

    # Create queue handler (non-blocking, puts records in queue)
    queue_handler = QueueHandler(_log_queue)
    queue_handler.setLevel(level)

    # Create queue listener (processes queue on separate thread)
    _queue_listener = QueueListener(
        _log_queue,
        file_handler,
        respect_handler_level=True
    )

    # Start the listener thread
    _queue_listener.start()

    # Register cleanup on exit
    atexit.register(stop_async_logging)

    return queue_handler


def stop_async_logging():
    """Stop the queue listener (call on application shutdown)"""
    global _queue_listener
    if _queue_listener:
        _queue_listener.stop()
        _queue_listener = None


def configure_all_loggers(level: int = logging.INFO):
    """
    Configure the root logger and all existing loggers to use async file logging.

    This should be called once at application startup.

    Args:
        level: Logging level (default: INFO)
    """
    # Get the queue handler
    queue_handler = setup_async_file_logging(level)

    # Also keep console output
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # Add our handlers
    root_logger.addHandler(queue_handler)
    root_logger.addHandler(console_handler)

    # Log startup
    logger = logging.getLogger(__name__)
    logger.info(f"Async file logging initialized: {LOG_FILE}")
    logger.info(f"Log rotation: {MAX_LOG_SIZE / 1024 / 1024:.0f}MB max, {BACKUP_COUNT} backups")


def get_log_file_path() -> Path:
    """Return the log file path"""
    return LOG_FILE
