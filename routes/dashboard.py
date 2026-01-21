"""
Dashboard API Routes

Provides REST endpoints for the ELOC processing dashboard.
Includes Server-Sent Events (SSE) for real-time updates.
"""
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse
from typing import Optional, List
from datetime import datetime, UTC
from pydantic import BaseModel
import asyncio
import json

import services.processing_tracker as tracker_module
from services.processing_tracker import ProcessingStatus
from services.structured_logger import get_logger


def get_tracker():
    """Get the processing tracker instance (may be None if not initialized)"""
    return tracker_module.processing_tracker

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

# Event subscribers for SSE
_event_subscribers: List[asyncio.Queue] = []


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
    field_confidences: Optional[dict] = None  # field_name -> confidence (0-100)
    avg_confidence: Optional[float] = None
    ner_validated_count: Optional[int] = None  # Fields validated by NER
    ner_applicable_count: Optional[int] = None  # Fields where NER applies
    llm_only_count: Optional[int] = None  # Fields using LLM agreement only


class SignatureVerificationResult(BaseModel):
    company_signed: bool = False
    investor_signed: bool = False
    both_signed: bool = False
    company_signatory: Optional[str] = None
    investor_signatory: Optional[str] = None
    notes: Optional[str] = None
    llm_agreement: Optional[bool] = None  # Whether Claude and OpenAI agreed
    agreement_details: Optional[dict] = None  # Detailed comparison info


class TimingInfo(BaseModel):
    started_at: Optional[datetime] = None
    classification_ms: Optional[int] = None
    extraction_ms: Optional[int] = None
    verification_ms: Optional[int] = None
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
    document_type: Optional[str] = None  # PURCHASE_NOTICE, PURCHASE_CONFIRMATION, NOT_RELEVANT
    is_duplicate: bool = False
    has_attachments: bool = False
    attachment_count: int = 0
    classification: Optional[ClassificationResult] = None
    extraction: Optional[ExtractionResult] = None
    signature_verification: Optional[SignatureVerificationResult] = None
    timing: Optional[TimingInfo] = None
    error: Optional[dict] = None

    class Config:
        from_attributes = True


class StatsResponse(BaseModel):
    total_emails: int = 0
    today_emails: int = 0
    status_counts: dict = {}
    document_type_counts: dict = {}  # PURCHASE_NOTICE, PURCHASE_CONFIRMATION, NOT_RELEVANT
    classification_counts: dict = {}
    agreement_counts: dict = {}  # For classification triple-classifier agreement
    avg_timing: dict = {}
    # Signature verification stats (for Purchase Confirmations)
    signature_verification_counts: dict = {}  # both_signed, investor_only, company_only, neither
    signature_llm_agreement_counts: dict = {}  # agree, disagree


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
    if not get_tracker():
        # Return empty stats when MongoDB is unavailable
        return StatsResponse()

    stats = await get_tracker().get_statistics()
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
    if not get_tracker():
        # Return empty list when MongoDB is unavailable
        return []

    # Validate status if provided
    if status:
        valid_statuses = [s.value for s in ProcessingStatus]
        if status not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
            )

    emails = await get_tracker().get_recent_emails(
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

        signature_verification = None
        if doc.get("signature_verification"):
            sv = doc["signature_verification"]
            signature_verification = SignatureVerificationResult(**sv)

        timing = None
        if doc.get("timing"):
            t = doc["timing"]
            timing = TimingInfo(
                started_at=t.get("started_at"),
                classification_ms=t.get("classification_ms"),
                extraction_ms=t.get("extraction_ms"),
                verification_ms=t.get("verification_ms"),
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
            document_type=doc.get("document_type"),
            is_duplicate=doc.get("is_duplicate", False),
            has_attachments=doc.get("has_attachments", False),
            attachment_count=doc.get("attachment_count", 0),
            classification=classification,
            extraction=extraction,
            signature_verification=signature_verification,
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
    if not get_tracker():
        raise HTTPException(status_code=404, detail="Email not found (MongoDB unavailable)")

    doc = await get_tracker().get_email_by_id(email_id)
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

    signature_verification = None
    if doc.get("signature_verification"):
        signature_verification = SignatureVerificationResult(**doc["signature_verification"])

    timing = None
    if doc.get("timing"):
        t = doc["timing"]
        timing = TimingInfo(
            started_at=t.get("started_at"),
            classification_ms=t.get("classification_ms"),
            extraction_ms=t.get("extraction_ms"),
            verification_ms=t.get("verification_ms"),
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
        document_type=doc.get("document_type"),
        is_duplicate=doc.get("is_duplicate", False),
        has_attachments=doc.get("has_attachments", False),
        attachment_count=doc.get("attachment_count", 0),
        classification=classification,
        extraction=extraction,
        signature_verification=signature_verification,
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
    if not get_tracker():
        # Return empty results when MongoDB is unavailable
        return []

    emails = await get_tracker().search_emails(query=q, limit=limit)
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
            ProcessingStatus.NOT_RELEVANT.value: "Classified as not relevant (neither Purchase Notice nor Confirmation)",
            ProcessingStatus.EXTRACTING.value: "Running dual LLM extraction (Purchase Notice)",
            ProcessingStatus.VERIFYING_SIGNATURES.value: "Verifying signatures (Purchase Confirmation)",
            ProcessingStatus.PERSISTING.value: "Saving to MongoDB",
            ProcessingStatus.COMPLETED.value: "Successfully processed",
            ProcessingStatus.FAILED.value: "Processing failed"
        }
    }


# ==================== Server-Sent Events (SSE) ====================

async def broadcast_event(event_type: str, data: dict):
    """
    Broadcast an event to all connected SSE clients.

    Args:
        event_type: Type of event (email_received, status_changed, etc.)
        data: Event data to send
    """
    message = {
        "type": event_type,
        "data": data,
        "timestamp": datetime.now(UTC).isoformat()
    }

    # Send to all subscribers
    dead_queues = []
    for queue in _event_subscribers:
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            dead_queues.append(queue)

    # Remove dead queues
    for q in dead_queues:
        if q in _event_subscribers:
            _event_subscribers.remove(q)


async def event_generator():
    """Generate SSE events for a client"""
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _event_subscribers.append(queue)

    try:
        # Send initial connection message
        yield f"event: connected\ndata: {json.dumps({'message': 'Connected to ELOC dashboard'})}\n\n"

        while True:
            try:
                # Wait for events with timeout (sends keepalive)
                message = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"event: {message['type']}\ndata: {json.dumps(message)}\n\n"
            except asyncio.TimeoutError:
                # Send keepalive comment
                yield ": keepalive\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        if queue in _event_subscribers:
            _event_subscribers.remove(queue)


@router.get("/events")
async def subscribe_to_events():
    """
    Server-Sent Events endpoint for real-time updates.

    Connect to this endpoint to receive real-time notifications about:
    - New emails received
    - Status changes (classification, extraction, completion)
    - Errors

    Usage in JavaScript:
        const eventSource = new EventSource('/api/dashboard/events');
        eventSource.addEventListener('email_received', (e) => {
            const data = JSON.parse(e.data);
            console.log('New email:', data);
        });
    """
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )
