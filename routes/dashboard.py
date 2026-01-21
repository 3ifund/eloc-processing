"""
Dashboard API Routes

Provides REST endpoints for the ELOC processing dashboard.
Includes Server-Sent Events (SSE) for real-time updates.
"""
from fastapi import APIRouter, Query, HTTPException, Request
from fastapi.responses import StreamingResponse
from typing import Optional, List, Any
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
import asyncio
import json

# Eastern timezone (UTC-5)
EASTERN_TZ = timezone(timedelta(hours=-5))

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


class ExtractedFieldValue(BaseModel):
    """Single extracted field with value and confidence"""
    value: Any = None
    confidence: float = 0.0


class ElocDataResponse(BaseModel):
    """Full eloc_data document with all extracted fields"""
    eloc_id: str
    received_at: Optional[datetime] = None
    purchase_notice_market_data_date: Optional[datetime] = None
    purchase_notice_filename: Optional[str] = None
    attachment_hash: Optional[str] = None
    created_at: Optional[datetime] = None
    modified_at: Optional[datetime] = None
    source: Optional[str] = None
    # Extracted fields with {value, confidence} pattern
    company_symbol: Optional[ExtractedFieldValue] = None
    company_name: Optional[ExtractedFieldValue] = None
    agreement_date: Optional[ExtractedFieldValue] = None
    company_signator: Optional[ExtractedFieldValue] = None
    signatory_title: Optional[ExtractedFieldValue] = None
    purchase_notice_company_signature: Optional[ExtractedFieldValue] = None
    vwap_purchase_share_amount: Optional[ExtractedFieldValue] = None
    vwap_purchase_exercise_date: Optional[ExtractedFieldValue] = None
    vwap_purchase_period_start_date: Optional[ExtractedFieldValue] = None
    vwap_purchase_period_end_date: Optional[ExtractedFieldValue] = None
    vwap_purchase_settlement_date: Optional[ExtractedFieldValue] = None
    aggregate_limit_available: Optional[ExtractedFieldValue] = None
    sender_name: Optional[ExtractedFieldValue] = None
    email_subject: Optional[ExtractedFieldValue] = None
    # Confirmation fields (if matched)
    has_confirmation: bool = False
    countersigned_purchase_confirmation_filename: Optional[str] = None
    countersigned_purchase_confirmation_received_at: Optional[datetime] = None


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
            received_at=doc.get("received_at", datetime.now(EASTERN_TZ)),
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
        received_at=doc.get("received_at", datetime.now(EASTERN_TZ)),
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


@router.get("/eloc/{eloc_id}", response_model=ElocDataResponse)
async def get_eloc_data(eloc_id: str, request: Request):
    """
    Get the persisted eloc_data document with all extracted fields.

    Returns the full document from the eloc_data MongoDB collection,
    including all extracted field values and their confidence scores.
    """
    # Get eloc_data_service from app.state
    eloc_data_service = getattr(request.app.state, 'eloc_data_service', None)
    if not eloc_data_service:
        raise HTTPException(status_code=503, detail="ELOC data service unavailable")

    doc = await eloc_data_service.get_eloc_data(eloc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"ELOC not found: {eloc_id}")

    # Extract fields from nested extracted_fields object
    extracted = doc.get("extracted_fields", {})

    # Helper to safely get field with value/confidence pattern
    def get_field(field_name):
        field_data = extracted.get(field_name)
        if field_data and isinstance(field_data, dict):
            return ExtractedFieldValue(
                value=field_data.get("value"),
                confidence=field_data.get("confidence", 0.0)
            )
        return None

    return ElocDataResponse(
        eloc_id=doc.get("eloc_id"),
        received_at=doc.get("received_at"),
        purchase_notice_market_data_date=doc.get("purchase_notice_market_data_date"),
        purchase_notice_filename=doc.get("purchase_notice_filename"),
        attachment_hash=doc.get("attachment_hash"),
        created_at=doc.get("created_at"),
        modified_at=doc.get("modified_at"),
        source=doc.get("source"),
        # Extracted fields
        company_symbol=get_field("company_symbol"),
        company_name=get_field("company_name"),
        agreement_date=get_field("agreement_date"),
        company_signator=get_field("company_signator"),
        signatory_title=get_field("signatory_title"),
        purchase_notice_company_signature=get_field("purchase_notice_company_signature"),
        vwap_purchase_share_amount=get_field("vwap_purchase_share_amount"),
        vwap_purchase_exercise_date=get_field("vwap_purchase_exercise_date"),
        vwap_purchase_period_start_date=get_field("vwap_purchase_period_start_date"),
        vwap_purchase_period_end_date=get_field("vwap_purchase_period_end_date"),
        vwap_purchase_settlement_date=get_field("vwap_purchase_settlement_date"),
        aggregate_limit_available=get_field("aggregate_limit_available"),
        sender_name=get_field("sender_name"),
        email_subject=get_field("email_subject"),
        # Confirmation info
        has_confirmation=doc.get("countersigned_purchase_confirmation_bytes") is not None,
        countersigned_purchase_confirmation_filename=doc.get("countersigned_purchase_confirmation_filename"),
        countersigned_purchase_confirmation_received_at=doc.get("countersigned_purchase_confirmation_received_at")
    )


@router.get("/elocs", response_model=List[ElocDataResponse])
async def list_eloc_data(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200, description="Max results"),
    company_symbol: Optional[str] = Query(default=None, description="Filter by company symbol")
):
    """
    List recent eloc_data documents.

    Returns paginated list of persisted ELOC documents with extracted fields.
    """
    eloc_data_service = getattr(request.app.state, 'eloc_data_service', None)
    if not eloc_data_service:
        raise HTTPException(status_code=503, detail="ELOC data service unavailable")

    if company_symbol:
        docs = await eloc_data_service.find_by_company_symbol(company_symbol, limit=limit)
    else:
        # Get recent documents from collection
        cursor = eloc_data_service.collection.find().sort("created_at", -1).limit(limit)
        docs = await cursor.to_list(length=limit)

    results = []
    for doc in docs:
        extracted = doc.get("extracted_fields", {})

        def get_field(field_name):
            field_data = extracted.get(field_name)
            if field_data and isinstance(field_data, dict):
                return ExtractedFieldValue(
                    value=field_data.get("value"),
                    confidence=field_data.get("confidence", 0.0)
                )
            return None

        results.append(ElocDataResponse(
            eloc_id=doc.get("eloc_id"),
            received_at=doc.get("received_at"),
            purchase_notice_market_data_date=doc.get("purchase_notice_market_data_date"),
            purchase_notice_filename=doc.get("purchase_notice_filename"),
            attachment_hash=doc.get("attachment_hash"),
            created_at=doc.get("created_at"),
            modified_at=doc.get("modified_at"),
            source=doc.get("source"),
            company_symbol=get_field("company_symbol"),
            company_name=get_field("company_name"),
            agreement_date=get_field("agreement_date"),
            company_signator=get_field("company_signator"),
            signatory_title=get_field("signatory_title"),
            purchase_notice_company_signature=get_field("purchase_notice_company_signature"),
            vwap_purchase_share_amount=get_field("vwap_purchase_share_amount"),
            vwap_purchase_exercise_date=get_field("vwap_purchase_exercise_date"),
            vwap_purchase_period_start_date=get_field("vwap_purchase_period_start_date"),
            vwap_purchase_period_end_date=get_field("vwap_purchase_period_end_date"),
            vwap_purchase_settlement_date=get_field("vwap_purchase_settlement_date"),
            aggregate_limit_available=get_field("aggregate_limit_available"),
            sender_name=get_field("sender_name"),
            email_subject=get_field("email_subject"),
            has_confirmation=doc.get("countersigned_purchase_confirmation_bytes") is not None,
            countersigned_purchase_confirmation_filename=doc.get("countersigned_purchase_confirmation_filename"),
            countersigned_purchase_confirmation_received_at=doc.get("countersigned_purchase_confirmation_received_at")
        ))

    return results


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
        "timestamp": datetime.now(EASTERN_TZ).isoformat()
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
