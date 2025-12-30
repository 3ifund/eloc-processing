"""
Dashboard API Routes

Provides REST endpoints for the ELOC processing dashboard.
"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional, List
from datetime import datetime, UTC
from pydantic import BaseModel

from services.processing_tracker import processing_tracker, ProcessingStatus
from services.structured_logger import get_logger

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


# ==================== Response Models ====================

class ClassificationVotes(BaseModel):
    similarity: Optional[str] = None
    claude: Optional[str] = None
    openai: Optional[str] = None


class ClassificationResult(BaseModel):
    result: Optional[str] = None
    votes: Optional[ClassificationVotes] = None
    agreement: Optional[str] = None
    confidence: Optional[str] = None
    similarity_score: Optional[float] = None


class ExtractionResult(BaseModel):
    eloc_id: Optional[str] = None
    company_symbol: Optional[str] = None
    company_name: Optional[str] = None
    fields_extracted: Optional[int] = None
    market_data_date: Optional[datetime] = None


class TimingInfo(BaseModel):
    started_at: Optional[datetime] = None
    classification_ms: Optional[int] = None
    extraction_ms: Optional[int] = None
    total_ms: Optional[int] = None
    completed_at: Optional[datetime] = None


class EmailProcessingRecord(BaseModel):
    email_id: str
    internet_message_id: Optional[str] = None
    subject: str
    sender: str
    recipients: List[str] = []
    received_at: datetime
    status: str
    is_duplicate: bool = False
    has_attachments: bool = False
    attachment_count: int = 0
    classification: Optional[ClassificationResult] = None
    extraction: Optional[ExtractionResult] = None
    timing: Optional[TimingInfo] = None
    error: Optional[dict] = None

    class Config:
        from_attributes = True


class StatsResponse(BaseModel):
    total_emails: int = 0
    today_emails: int = 0
    status_counts: dict = {}
    classification_counts: dict = {}
    agreement_counts: dict = {}
    avg_timing: dict = {}


class LogEntry(BaseModel):
    timestamp: str
    level: str
    message: str
    email_id: Optional[str] = None
    category: Optional[str] = None
    data: Optional[dict] = None
    duration_ms: Optional[int] = None


# ==================== Endpoints ====================

@router.get("/stats", response_model=StatsResponse)
async def get_statistics():
    """
    Get processing statistics for the dashboard

    Returns counts, averages, and breakdowns by status/classification.
    """
    if not processing_tracker:
        raise HTTPException(status_code=503, detail="Processing tracker not initialized")

    stats = await processing_tracker.get_statistics()
    return StatsResponse(**stats)


@router.get("/emails", response_model=List[EmailProcessingRecord])
async def get_emails(
    limit: int = Query(default=50, ge=1, le=200, description="Max results"),
    offset: int = Query(default=0, ge=0, description="Skip N results"),
    status: Optional[str] = Query(default=None, description="Filter by status")
):
    """
    Get list of processed emails

    Returns paginated list of email processing records, most recent first.
    """
    if not processing_tracker:
        raise HTTPException(status_code=503, detail="Processing tracker not initialized")

    # Validate status if provided
    if status:
        valid_statuses = [s.value for s in ProcessingStatus]
        if status not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
            )

    emails = await processing_tracker.get_recent_emails(
        limit=limit,
        offset=offset,
        status_filter=status
    )

    # Convert MongoDB docs to response models
    result = []
    for doc in emails:
        # Handle nested objects
        classification = None
        if doc.get("classification"):
            c = doc["classification"]
            classification = ClassificationResult(
                result=c.get("result"),
                votes=ClassificationVotes(**c.get("votes", {})) if c.get("votes") else None,
                agreement=c.get("agreement"),
                confidence=c.get("confidence"),
                similarity_score=c.get("similarity_score")
            )

        extraction = None
        if doc.get("extraction"):
            e = doc["extraction"]
            extraction = ExtractionResult(**e)

        timing = None
        if doc.get("timing"):
            t = doc["timing"]
            timing = TimingInfo(
                started_at=t.get("started_at"),
                classification_ms=t.get("classification_ms"),
                extraction_ms=t.get("extraction_ms"),
                total_ms=t.get("total_ms"),
                completed_at=t.get("completed_at")
            )

        record = EmailProcessingRecord(
            email_id=doc["email_id"],
            internet_message_id=doc.get("internet_message_id"),
            subject=doc.get("subject", ""),
            sender=doc.get("sender", ""),
            recipients=doc.get("recipients", []),
            received_at=doc.get("received_at", datetime.now(UTC)),
            status=doc.get("status", "UNKNOWN"),
            is_duplicate=doc.get("is_duplicate", False),
            has_attachments=doc.get("has_attachments", False),
            attachment_count=doc.get("attachment_count", 0),
            classification=classification,
            extraction=extraction,
            timing=timing,
            error=doc.get("error")
        )
        result.append(record)

    return result


@router.get("/emails/{email_id}", response_model=EmailProcessingRecord)
async def get_email_detail(email_id: str):
    """
    Get detailed processing record for a single email

    Returns full processing history including all stages and timing.
    """
    if not processing_tracker:
        raise HTTPException(status_code=503, detail="Processing tracker not initialized")

    doc = await processing_tracker.get_email_by_id(email_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Email not found")

    # Same conversion as above
    classification = None
    if doc.get("classification"):
        c = doc["classification"]
        classification = ClassificationResult(
            result=c.get("result"),
            votes=ClassificationVotes(**c.get("votes", {})) if c.get("votes") else None,
            agreement=c.get("agreement"),
            confidence=c.get("confidence"),
            similarity_score=c.get("similarity_score")
        )

    extraction = None
    if doc.get("extraction"):
        extraction = ExtractionResult(**doc["extraction"])

    timing = None
    if doc.get("timing"):
        t = doc["timing"]
        timing = TimingInfo(
            started_at=t.get("started_at"),
            classification_ms=t.get("classification_ms"),
            extraction_ms=t.get("extraction_ms"),
            total_ms=t.get("total_ms"),
            completed_at=t.get("completed_at")
        )

    return EmailProcessingRecord(
        email_id=doc["email_id"],
        internet_message_id=doc.get("internet_message_id"),
        subject=doc.get("subject", ""),
        sender=doc.get("sender", ""),
        recipients=doc.get("recipients", []),
        received_at=doc.get("received_at", datetime.now(UTC)),
        status=doc.get("status", "UNKNOWN"),
        is_duplicate=doc.get("is_duplicate", False),
        has_attachments=doc.get("has_attachments", False),
        attachment_count=doc.get("attachment_count", 0),
        classification=classification,
        extraction=extraction,
        timing=timing,
        error=doc.get("error")
    )


@router.get("/search")
async def search_emails(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(default=20, ge=1, le=100)
):
    """
    Search emails by subject, sender, or ELOC ID

    Returns matching email processing records.
    """
    if not processing_tracker:
        raise HTTPException(status_code=503, detail="Processing tracker not initialized")

    emails = await processing_tracker.search_emails(query=q, limit=limit)
    return emails


@router.get("/logs", response_model=List[LogEntry])
async def get_logs(
    limit: int = Query(default=100, ge=1, le=500, description="Max log entries"),
    email_id: Optional[str] = Query(default=None, description="Filter by email ID"),
    category: Optional[str] = Query(default=None, description="Filter by category"),
    level: Optional[str] = Query(default=None, description="Filter by log level")
):
    """
    Get recent log entries from file

    Returns structured log entries, most recent first.
    """
    logger = get_logger()
    logs = logger.get_recent_logs(
        limit=limit,
        email_id=email_id,
        category=category,
        level=level
    )

    return [LogEntry(**log) for log in logs]


@router.get("/logs/{email_id}", response_model=List[LogEntry])
async def get_logs_for_email(
    email_id: str,
    limit: int = Query(default=50, ge=1, le=200)
):
    """
    Get all log entries for a specific email

    Returns chronological log entries for tracing the processing flow.
    """
    logger = get_logger()
    logs = logger.get_recent_logs(limit=limit, email_id=email_id)

    # Reverse to get chronological order
    logs.reverse()

    return [LogEntry(**log) for log in logs]


@router.get("/status-options")
async def get_status_options():
    """Get list of valid status values for filtering"""
    return {
        "statuses": [s.value for s in ProcessingStatus],
        "descriptions": {
            ProcessingStatus.RECEIVED.value: "Email received, not yet processed",
            ProcessingStatus.DUPLICATE.value: "Duplicate email, skipped",
            ProcessingStatus.CLASSIFYING.value: "Running triple classification",
            ProcessingStatus.NOT_ELOC.value: "Classified as not an ELOC document",
            ProcessingStatus.EXTRACTING.value: "Running dual LLM extraction",
            ProcessingStatus.PERSISTING.value: "Saving to MongoDB",
            ProcessingStatus.COMPLETED.value: "Successfully processed",
            ProcessingStatus.FAILED.value: "Processing failed"
        }
    }
