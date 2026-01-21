"""
Structured File Logger

JSON-formatted logging with rotation for ELOC processing.
Logs are written to files with correlation IDs for tracing.
Broadcasts events to SSE subscribers for real-time dashboard updates.

Log directory: logs/
- eloc_processing.log (current)
- eloc_processing.log.1, .2, etc. (rotated)
"""
import logging
import json
import asyncio
from datetime import datetime, UTC
from logging.handlers import RotatingFileHandler
from typing import Optional, Dict, Any, Callable
from enum import Enum
from pathlib import Path


class LogCategory(str, Enum):
    """Log categories for filtering"""
    EMAIL_RECEIVED = "EMAIL_RECEIVED"
    DUPLICATE_DETECTED = "DUPLICATE_DETECTED"
    CLASSIFICATION_START = "CLASSIFICATION_START"
    CLASSIFICATION_RESULT = "CLASSIFICATION_RESULT"
    EXTRACTION_START = "EXTRACTION_START"
    EXTRACTION_RESULT = "EXTRACTION_RESULT"
    PERSISTENCE_START = "PERSISTENCE_START"
    PERSISTENCE_RESULT = "PERSISTENCE_RESULT"
    PROCESSING_COMPLETE = "PROCESSING_COMPLETE"
    PROCESSING_FAILED = "PROCESSING_FAILED"
    WEBHOOK_SENT = "WEBHOOK_SENT"
    WEBHOOK_FAILED = "WEBHOOK_FAILED"


class JSONFormatter(logging.Formatter):
    """Format log records as JSON"""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add extra fields if present
        if hasattr(record, "email_id"):
            log_data["email_id"] = record.email_id
        if hasattr(record, "category"):
            log_data["category"] = record.category
        if hasattr(record, "data"):
            log_data["data"] = record.data
        if hasattr(record, "duration_ms"):
            log_data["duration_ms"] = record.duration_ms

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


class StructuredLogger:
    """
    Structured logger for ELOC processing.

    Provides JSON-formatted logs with correlation IDs (email_id) for tracing.
    Also broadcasts events via SSE for real-time dashboard updates.
    """

    # Callback for broadcasting SSE events (set by dashboard routes)
    _sse_broadcast: Optional[Callable] = None

    def __init__(
        self,
        log_dir: str = "logs",
        log_file: str = "eloc_processing.log",
        max_bytes: int = 10 * 1024 * 1024,  # 10 MB
        backup_count: int = 10,
        console_output: bool = True
    ):
        """
        Initialize structured logger

        Args:
            log_dir: Directory for log files
            log_file: Log file name
            max_bytes: Max size before rotation
            backup_count: Number of backup files to keep
            console_output: Also log to console
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.log_path = self.log_dir / log_file

        # Create logger
        self.logger = logging.getLogger("eloc.structured")
        self.logger.setLevel(logging.DEBUG)

        # Prevent duplicate handlers
        if not self.logger.handlers:
            # File handler with rotation
            file_handler = RotatingFileHandler(
                self.log_path,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8"
            )
            file_handler.setFormatter(JSONFormatter())
            file_handler.setLevel(logging.DEBUG)
            self.logger.addHandler(file_handler)

            # Console handler (optional)
            if console_output:
                console_handler = logging.StreamHandler()
                console_handler.setFormatter(logging.Formatter(
                    "%(asctime)s [%(levelname)s] %(message)s"
                ))
                console_handler.setLevel(logging.INFO)
                self.logger.addHandler(console_handler)

    def log(
        self,
        level: int,
        message: str,
        email_id: Optional[str] = None,
        category: Optional[LogCategory] = None,
        data: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[int] = None,
        exc_info: bool = False
    ):
        """
        Log a structured message

        Args:
            level: Log level (logging.INFO, etc.)
            message: Log message
            email_id: Correlation ID for tracing
            category: Log category for filtering
            data: Additional structured data
            duration_ms: Duration in milliseconds
            exc_info: Include exception info
        """
        extra = {}
        if email_id:
            extra["email_id"] = email_id
        if category:
            extra["category"] = category.value if isinstance(category, LogCategory) else category
        if data:
            extra["data"] = data
        if duration_ms is not None:
            extra["duration_ms"] = duration_ms

        self.logger.log(level, message, extra=extra, exc_info=exc_info)

    def info(self, message: str, **kwargs):
        """Log INFO level message"""
        self.log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs):
        """Log WARNING level message"""
        self.log(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs):
        """Log ERROR level message"""
        self.log(logging.ERROR, message, **kwargs)

    def debug(self, message: str, **kwargs):
        """Log DEBUG level message"""
        self.log(logging.DEBUG, message, **kwargs)

    def _broadcast_sse(self, event_type: str, data: dict):
        """Broadcast an SSE event to connected clients"""
        callback = StructuredLogger._sse_broadcast
        if callback:
            try:
                # Run async broadcast in background
                asyncio.create_task(callback(event_type, data))
            except RuntimeError:
                # No event loop running (e.g., during startup)
                pass

    @classmethod
    def set_sse_broadcast(cls, callback: Callable):
        """Set the SSE broadcast callback"""
        cls._sse_broadcast = staticmethod(callback)

    # ==================== Convenience Methods ====================

    def email_received(
        self,
        email_id: str,
        subject: str,
        sender: str,
        has_attachments: bool,
        attachment_count: int = 0
    ):
        """Log email received event"""
        self.info(
            f"Email received: {subject[:50]}",
            email_id=email_id,
            category=LogCategory.EMAIL_RECEIVED,
            data={
                "subject": subject,
                "sender": sender,
                "has_attachments": has_attachments,
                "attachment_count": attachment_count
            }
        )
        # Broadcast to dashboard
        self._broadcast_sse("email_received", {
            "email_id": email_id,
            "subject": subject,
            "sender": sender
        })

    def duplicate_detected(self, email_id: str, reason: str = "Already processed"):
        """Log duplicate email detected"""
        self.info(
            f"Duplicate email detected: {reason}",
            email_id=email_id,
            category=LogCategory.DUPLICATE_DETECTED,
            data={"reason": reason}
        )

    def classification_start(self, email_id: str, attachment_name: str = None):
        """Log classification started"""
        self.info(
            "Starting classification",
            email_id=email_id,
            category=LogCategory.CLASSIFICATION_START,
            data={"attachment_name": attachment_name}
        )

    def classification_result(
        self,
        email_id: str,
        result: str,
        votes: Dict[str, str],
        agreement: str,
        confidence: str,
        similarity_score: float = None,
        duration_ms: int = None
    ):
        """Log classification result"""
        self.info(
            f"Classification: {result} ({confidence}) - {agreement}",
            email_id=email_id,
            category=LogCategory.CLASSIFICATION_RESULT,
            data={
                "result": result,
                "votes": votes,
                "agreement": agreement,
                "confidence": confidence,
                "similarity_score": similarity_score
            },
            duration_ms=duration_ms
        )
        # Broadcast to dashboard
        self._broadcast_sse("status_changed", {
            "email_id": email_id,
            "status": "CLASSIFIED",
            "result": result
        })

    def extraction_start(self, email_id: str):
        """Log extraction started"""
        self.info(
            "Starting dual LLM extraction",
            email_id=email_id,
            category=LogCategory.EXTRACTION_START
        )

    def extraction_result(
        self,
        email_id: str,
        eloc_id: str,
        company_symbol: str,
        company_name: str,
        fields_count: int,
        market_data_date: str = None,
        duration_ms: int = None
    ):
        """Log extraction result"""
        self.info(
            f"Extraction complete: {eloc_id} ({company_symbol})",
            email_id=email_id,
            category=LogCategory.EXTRACTION_RESULT,
            data={
                "eloc_id": eloc_id,
                "company_symbol": company_symbol,
                "company_name": company_name,
                "fields_count": fields_count,
                "market_data_date": market_data_date
            },
            duration_ms=duration_ms
        )

    def persistence_start(self, email_id: str, eloc_id: str):
        """Log persistence started"""
        self.info(
            f"Persisting to MongoDB: {eloc_id}",
            email_id=email_id,
            category=LogCategory.PERSISTENCE_START,
            data={"eloc_id": eloc_id}
        )

    def persistence_result(self, email_id: str, eloc_id: str, success: bool):
        """Log persistence result"""
        status = "success" if success else "failed"
        self.info(
            f"Persistence {status}: {eloc_id}",
            email_id=email_id,
            category=LogCategory.PERSISTENCE_RESULT,
            data={"eloc_id": eloc_id, "success": success}
        )

    def processing_complete(
        self,
        email_id: str,
        eloc_id: str = None,
        total_duration_ms: int = None
    ):
        """Log processing complete"""
        self.info(
            f"Processing complete: {eloc_id or 'N/A'}",
            email_id=email_id,
            category=LogCategory.PROCESSING_COMPLETE,
            data={"eloc_id": eloc_id},
            duration_ms=total_duration_ms
        )
        # Broadcast to dashboard
        self._broadcast_sse("processing_complete", {
            "email_id": email_id,
            "eloc_id": eloc_id
        })

    def processing_failed(
        self,
        email_id: str,
        error: str,
        stage: str = None,
        exc_info: bool = False
    ):
        """Log processing failure"""
        self.error(
            f"Processing failed at {stage or 'unknown'}: {error}",
            email_id=email_id,
            category=LogCategory.PROCESSING_FAILED,
            data={"error": error, "stage": stage},
            exc_info=exc_info
        )

    def webhook_sent(
        self,
        email_id: str,
        webhook_url: str,
        eloc_id: str,
        status_code: int
    ):
        """Log webhook sent"""
        self.info(
            f"Webhook sent: {eloc_id} -> {status_code}",
            email_id=email_id,
            category=LogCategory.WEBHOOK_SENT,
            data={
                "webhook_url": webhook_url,
                "eloc_id": eloc_id,
                "status_code": status_code
            }
        )

    def webhook_failed(
        self,
        email_id: str,
        webhook_url: str,
        error: str
    ):
        """Log webhook failure"""
        self.error(
            f"Webhook failed: {error}",
            email_id=email_id,
            category=LogCategory.WEBHOOK_FAILED,
            data={"webhook_url": webhook_url, "error": error}
        )

    # ==================== Log Reading (for Dashboard) ====================

    def get_recent_logs(
        self,
        limit: int = 100,
        email_id: Optional[str] = None,
        category: Optional[str] = None,
        level: Optional[str] = None
    ) -> list:
        """
        Read recent logs from file (for dashboard)

        Args:
            limit: Max number of log entries
            email_id: Filter by email ID
            category: Filter by category
            level: Filter by log level

        Returns:
            List of log entries (most recent first)
        """
        logs = []

        if not self.log_path.exists():
            return logs

        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # Read from end for most recent
            for line in reversed(lines):
                if len(logs) >= limit:
                    break

                try:
                    entry = json.loads(line.strip())

                    # Apply filters
                    if email_id and entry.get("email_id") != email_id:
                        continue
                    if category and entry.get("category") != category:
                        continue
                    if level and entry.get("level") != level:
                        continue

                    logs.append(entry)
                except json.JSONDecodeError:
                    continue

        except Exception as e:
            self.logger.error(f"Error reading logs: {e}")

        return logs


# Global instance (initialized in main.py)
structured_logger: Optional[StructuredLogger] = None


def get_logger() -> StructuredLogger:
    """Get or create the structured logger instance"""
    global structured_logger
    if structured_logger is None:
        structured_logger = StructuredLogger()
    return structured_logger
