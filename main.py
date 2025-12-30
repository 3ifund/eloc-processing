from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Optional, Dict, List
import logging
import os
import msal
import aiohttp
from dotenv import load_dotenv
from collections import deque
from datetime import datetime, timedelta
import threading

from repositories.mongo_client import mongo_client
from workflow import ELOCWorkflow
from webhooks.webhook_sender import WebhookSender
from services.trading_calendar_service import TradingCalendarService
from services.verification.orchestrator import VerificationOrchestrator
from services.verification.examples_repository import ExamplesRepository
from services.processing_tracker import ProcessingTracker
from services.structured_logger import StructuredLogger, get_logger
import services.processing_tracker as tracker_module
import services.structured_logger as logger_module
from routes.dashboard import router as dashboard_router

# Load environment variables
load_dotenv()

# PostgreSQL config for trading calendar (explicit params to handle special chars in password)
PG_CONFIG = {
    'host': os.getenv('PG_HOST', '10.90.98.123'),
    'port': int(os.getenv('PG_PORT', '5432')),
    'database': os.getenv('PG_DATABASE', 'DealTerms'),
    'user': os.getenv('PG_USER', 'postgres'),
    'password': os.getenv('PG_PASSWORD', 'Drl270!!')
}

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ==================== DEDUPLICATION CACHE ====================
# Stores (email_id, timestamp) for recently processed emails
processed_emails_cache = deque(maxlen=1000)  # Keep last 1000 emails
cache_lock = threading.Lock()
DEDUP_WINDOW_MINUTES = 5  # Ignore duplicates within 5 minutes


def is_duplicate_notification(email_id: str) -> bool:
    """
    Check if this email was recently processed (deduplication)
    
    Args:
        email_id: The email message ID
    
    Returns:
        True if duplicate (already processed recently), False if new
    """
    with cache_lock:
        now = datetime.utcnow()
        cutoff = now - timedelta(minutes=DEDUP_WINDOW_MINUTES)
        
        # Remove old entries outside the deduplication window
        while processed_emails_cache and processed_emails_cache[0][1] < cutoff:
            processed_emails_cache.popleft()
        
        # Check if email_id exists in cache
        for cached_id, _ in processed_emails_cache:
            if cached_id == email_id:
                return True  # Duplicate found!
        
        # Not a duplicate - add to cache
        processed_emails_cache.append((email_id, now))
        return False


# ==================== MICROSOFT GRAPH API HELPERS ====================

def get_graph_access_token() -> str:
    """Get access token for Microsoft Graph API"""
    tenant_id = os.getenv("TENANT_ID")
    client_id = os.getenv("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET")
    
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = msal.ConfidentialClientApplication(
        client_id,
        authority=authority,
        client_credential=client_secret
    )
    
    result = app.acquire_token_for_client(
        scopes=["https://graph.microsoft.com/.default"]
    )
    
    if "access_token" not in result:
        raise Exception(f"Failed to get access token: {result.get('error_description')}")
    
    return result["access_token"]


async def fetch_email_from_graph(email_id: str) -> Dict:
    """
    Fetch email details from Microsoft Graph API
    
    Args:
        email_id: The email message ID from Azure notification
    
    Returns:
        Dict containing email metadata (subject, from, to, cc, body, etc.)
    """
    mailbox_id = os.getenv("MAILBOX_OBJECT_ID")
    access_token = get_graph_access_token()
    
    url = f"https://graph.microsoft.com/v1.0/users/{mailbox_id}/messages/{email_id}"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    # Request specific fields
    params = {
        "$select": "id,subject,from,toRecipients,ccRecipients,receivedDateTime,body,hasAttachments,internetMessageId"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as response:
            if response.status != 200:
                error_text = await response.text()
                logger.error(f"Failed to fetch email {email_id}: {response.status} - {error_text}")
                raise Exception(f"Failed to fetch email: {response.status}")
            
            email_data = await response.json()
            logger.info(f"Fetched email: {email_data.get('subject')}")
            return email_data


async def fetch_attachments(email_id: str) -> List[Dict]:
    """
    Fetch attachments from an email
    
    Args:
        email_id: The email message ID
    
    Returns:
        List of attachments with metadata and content
    """
    mailbox_id = os.getenv("MAILBOX_OBJECT_ID")
    access_token = get_graph_access_token()
    
    url = f"https://graph.microsoft.com/v1.0/users/{mailbox_id}/messages/{email_id}/attachments"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                error_text = await response.text()
                logger.error(f"Failed to fetch attachments for {email_id}: {response.status} - {error_text}")
                return []
            
            data = await response.json()
            attachments = data.get("value", [])
            
            logger.info(f"Found {len(attachments)} attachment(s) for email {email_id}")
            return attachments


async def download_attachment_content(email_id: str, attachment_id: str) -> bytes:
    """
    Download attachment content
    
    Args:
        email_id: The email message ID
        attachment_id: The attachment ID
    
    Returns:
        Attachment content as bytes
    """
    mailbox_id = os.getenv("MAILBOX_OBJECT_ID")
    access_token = get_graph_access_token()
    
    url = f"https://graph.microsoft.com/v1.0/users/{mailbox_id}/messages/{email_id}/attachments/{attachment_id}/$value"
    
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                error_text = await response.text()
                logger.error(f"Failed to download attachment {attachment_id}: {response.status} - {error_text}")
                raise Exception(f"Failed to download attachment: {response.status}")
            
            content = await response.read()
            logger.info(f"Downloaded attachment {attachment_id} ({len(content)} bytes)")
            return content


async def save_attachment_to_disk(content: bytes, filename: str) -> str:
    """
    Save attachment to temporary directory
    
    Args:
        content: Attachment content as bytes
        filename: Original filename
    
    Returns:
        Path to saved file
    """
    import uuid
    from pathlib import Path
    
    temp_dir = Path(os.getenv("TEMP_ATTACHMENTS_DIR", "C:/temp/attachments"))
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate unique filename to avoid collisions
    unique_id = uuid.uuid4().hex[:8]
    safe_filename = f"{unique_id}_{filename}"
    file_path = temp_dir / safe_filename
    
    # Write content to file
    with open(file_path, "wb") as f:
        f.write(content)
    
    logger.info(f"Saved attachment to: {file_path}")
    return str(file_path)


async def process_email_notification(email_id: str):
    """
    Process a single email notification with deduplication, tracking, and logging

    Args:
        email_id: The email message ID from Azure notification
    """
    from services.processing_tracker import processing_tracker
    from services.structured_logger import get_logger

    structured_log = get_logger()

    # Check for duplicate notification
    if is_duplicate_notification(email_id):
        logger.info(f"⏭️  Skipping duplicate notification for email: {email_id}")
        structured_log.duplicate_detected(email_id, "In-memory cache hit")
        if processing_tracker:
            await processing_tracker.mark_duplicate(email_id)
        return

    try:
        logger.info(f"📧 Processing email notification: {email_id}")

        # Step 1: Fetch email metadata
        email_data = await fetch_email_from_graph(email_id)

        # Extract email fields
        email_info = {
            "message_id": email_data.get("id"),
            "internet_message_id": email_data.get("internetMessageId"),
            "subject": email_data.get("subject"),
            "from": email_data.get("from", {}).get("emailAddress", {}).get("address"),
            "to": [r.get("emailAddress", {}).get("address") for r in email_data.get("toRecipients", [])],
            "cc": [r.get("emailAddress", {}).get("address") for r in email_data.get("ccRecipients", [])],
            "received_at": email_data.get("receivedDateTime"),
            "body": email_data.get("body", {}).get("content", ""),
            "body_type": email_data.get("body", {}).get("contentType", "html"),
            "has_attachments": email_data.get("hasAttachments", False)
        }

        logger.info(f"  From: {email_info['from']}")
        logger.info(f"  Subject: {email_info['subject']}")
        logger.info(f"  Attachments: {email_info['has_attachments']}")

        # Step 2: Fetch and download attachments
        attachments_info = []
        if email_info["has_attachments"]:
            attachments = await fetch_attachments(email_id)

            for attachment in attachments:
                # Skip inline attachments and non-file attachments
                if attachment.get("@odata.type") != "#microsoft.graph.fileAttachment":
                    continue

                attachment_id = attachment.get("id")
                filename = attachment.get("name")
                content_type = attachment.get("contentType")
                size = attachment.get("size", 0)

                logger.info(f"  📎 Downloading: {filename} ({content_type}, {size} bytes)")

                # Download attachment content
                content = await download_attachment_content(email_id, attachment_id)

                # Save to disk
                file_path = await save_attachment_to_disk(content, filename)

                attachments_info.append({
                    "filename": filename,
                    "content_type": content_type,
                    "size_bytes": size,
                    "file_path": file_path,
                    "content": content  # Keep content for classification
                })

        logger.info(f"  ✓ Downloaded {len(attachments_info)} attachment(s)")

        # Start tracking in MongoDB
        if processing_tracker:
            await processing_tracker.start_tracking(
                email_id=email_id,
                internet_message_id=email_info.get("internet_message_id", ""),
                subject=email_info.get("subject", ""),
                sender=email_info.get("from", ""),
                recipients=email_info.get("to", []),
                received_at=datetime.fromisoformat(email_info["received_at"].replace("Z", "+00:00")) if email_info.get("received_at") else None,
                has_attachments=email_info.get("has_attachments", False),
                attachment_count=len(attachments_info)
            )

        # Log email received
        structured_log.email_received(
            email_id=email_id,
            subject=email_info.get("subject", ""),
            sender=email_info.get("from", ""),
            has_attachments=email_info.get("has_attachments", False),
            attachment_count=len(attachments_info)
        )

        # Step 3: Process each PDF attachment through classification and extraction
        from workflow import eloc_workflow

        for attachment in attachments_info:
            if not attachment["filename"].lower().endswith(".pdf"):
                continue

            # Classification
            if processing_tracker:
                await processing_tracker.start_classification(email_id)
            structured_log.classification_start(email_id, attachment["filename"])

            # Extract text from PDF for classification
            import pdfplumber
            import io

            pdf_text = ""
            try:
                with pdfplumber.open(io.BytesIO(attachment["content"])) as pdf:
                    for page in pdf.pages[:10]:
                        page_text = page.extract_text()
                        if page_text:
                            pdf_text += page_text + "\n"
            except Exception as e:
                logger.error(f"Failed to extract PDF text: {e}")
                continue

            # Run classification
            classification_result = eloc_workflow.classifier.classify(pdf_text)

            # Get votes for tracking
            votes = {}
            if classification_result.get("similarity_result"):
                votes["similarity"] = classification_result["similarity_result"].get("classification", "ERROR")
            if classification_result.get("claude_result"):
                votes["claude"] = classification_result["claude_result"].get("classification", "ERROR")
            if classification_result.get("openai_result"):
                votes["openai"] = classification_result["openai_result"].get("classification", "ERROR")

            # Update tracking with classification result
            if processing_tracker:
                await processing_tracker.set_classification_result(
                    email_id=email_id,
                    result=classification_result.get("final_classification", "UNKNOWN"),
                    votes=votes,
                    agreement=classification_result.get("agreement", "unknown"),
                    confidence=classification_result.get("final_confidence", "UNKNOWN"),
                    similarity_score=classification_result.get("similarity_result", {}).get("scores", {}).get("max_similarity")
                )

            structured_log.classification_result(
                email_id=email_id,
                result=classification_result.get("final_classification", "UNKNOWN"),
                votes=votes,
                agreement=classification_result.get("agreement", "unknown"),
                confidence=classification_result.get("final_confidence", "UNKNOWN"),
                similarity_score=classification_result.get("similarity_result", {}).get("scores", {}).get("max_similarity")
            )

            # If not ELOC, skip extraction
            if classification_result.get("final_classification") != "ELOC":
                logger.info(f"  Document classified as {classification_result.get('final_classification')} - skipping extraction")
                continue

            # Extraction (if ELOC)
            if processing_tracker:
                await processing_tracker.start_extraction(email_id)
            structured_log.extraction_start(email_id)

            # TODO: Implement full extraction workflow
            # For now, log that extraction would happen
            logger.info(f"  ✓ Document classified as ELOC - extraction would run here")

            # Mark completed (for now)
            if processing_tracker:
                await processing_tracker.mark_completed(email_id)
            structured_log.processing_complete(email_id)

        logger.info(f"✅ Email {email_id} processing complete")

    except Exception as e:
        logger.error(f"❌ Error processing email {email_id}: {str(e)}", exc_info=True)

        # Log failure
        structured_log.processing_failed(email_id, str(e), exc_info=True)
        if processing_tracker:
            await processing_tracker.mark_failed(email_id, str(e))

        raise


# ==================== FASTAPI APPLICATION ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for FastAPI app"""
    logger.info("=" * 60)
    logger.info("ELOC EXTRACTION SERVICE - Starting...")
    logger.info("=" * 60)

    # Connect to MongoDB
    mongodb_enabled = os.getenv("MONGODB_ENABLED", "true").lower() == "true"
    examples_repository = None

    # Initialize structured file logger
    structured_log = StructuredLogger(
        log_dir=os.getenv("LOG_DIR", "logs"),
        console_output=True
    )
    logger_module.structured_logger = structured_log
    logger.info("✓ Structured logger initialized")

    if mongodb_enabled:
        try:
            await mongo_client.connect()
            logger.info("✓ MongoDB connected")

            # Initialize Processing Tracker for dashboard
            processing_tracker = ProcessingTracker(mongo_client.db)
            await processing_tracker.ensure_indexes()
            tracker_module.processing_tracker = processing_tracker
            logger.info("✓ Processing tracker initialized")

            # Initialize Examples Repository for classification
            examples_repository = ExamplesRepository(mongo_client.db)
            example_count = await examples_repository.count()
            logger.info(f"✓ Examples repository initialized ({example_count} examples)")
        except Exception as e:
            logger.warning(f"⚠ MongoDB connection failed: {e} - Running without MongoDB")
            mongodb_enabled = False
    else:
        logger.info("⚠ MongoDB DISABLED - Running in test mode")
    
    # Initialize webhook sender (OUTGOING to processing app)
    processing_webhook_url = os.getenv("PROCESSING_WEBHOOK_URL")
    processing_webhook_secret = os.getenv("PROCESSING_WEBHOOK_SECRET")
    
    if processing_webhook_url:
        import webhooks.webhook_sender as webhook_module
        webhook_module.webhook_sender = WebhookSender(
            webhook_url=processing_webhook_url,
            webhook_secret=processing_webhook_secret,
            timeout=int(os.getenv("PROCESSING_WEBHOOK_TIMEOUT", "30")),
            max_retries=int(os.getenv("PROCESSING_WEBHOOK_MAX_RETRIES", "3"))
        )
        logger.info(f"✓ Processing webhook sender initialized: {processing_webhook_url}")
    else:
        logger.warning("⚠ PROCESSING_WEBHOOK_URL not configured - webhooks disabled")
    
    # Initialize Trading Calendar Service
    trading_calendar_service = TradingCalendarService(pg_config=PG_CONFIG)
    logger.info("✓ Trading calendar service initialized")

    # Initialize Verification Orchestrator (dual LLM + trading calendar)
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
    openai_api_key = os.getenv("OPENAI_API_KEY")

    verification_orchestrator = None
    if anthropic_api_key and openai_api_key:
        verification_orchestrator = VerificationOrchestrator(
            anthropic_api_key=anthropic_api_key,
            openai_api_key=openai_api_key,
            trading_calendar_service=trading_calendar_service
        )
        logger.info("✓ Verification orchestrator initialized (Claude + OpenAI + Trading Calendar)")
    else:
        logger.warning("⚠ Missing API keys - verification orchestrator disabled")

    # Store services in app state for access in routes
    app.state.trading_calendar_service = trading_calendar_service
    app.state.verification_orchestrator = verification_orchestrator

    # Initialize workflow
    references_dir = os.getenv("REFERENCES_DIR", "references")

    import workflow as workflow_module
    workflow_module.eloc_workflow = ELOCWorkflow(
        anthropic_api_key=anthropic_api_key,
        openai_api_key=openai_api_key,
        references_dir=references_dir
    )
    # Pass orchestrator to workflow for integrated extraction
    workflow_module.eloc_workflow.verification_orchestrator = verification_orchestrator

    # Load MongoDB examples into classifier (for similarity-based classification)
    if examples_repository:
        example_count = await workflow_module.eloc_workflow.classifier.load_mongodb_examples(
            examples_repository
        )
        if example_count > 0:
            logger.info(f"✓ Loaded {example_count} MongoDB examples into classifier")
        else:
            logger.info("✓ Using local reference files for classification")
    else:
        logger.info("✓ Using local reference files for classification (MongoDB disabled)")

    logger.info("✓ ELOC extraction workflow initialized")
    
    logger.info("=" * 60)
    logger.info("✅ ELOC EXTRACTION SERVICE - Ready")
    logger.info("=" * 60)
    
    yield

    # Cleanup
    logger.info("Shutting down...")
    # Close trading calendar service connection pool
    if hasattr(app.state, 'trading_calendar_service') and app.state.trading_calendar_service:
        await app.state.trading_calendar_service.close()
        logger.info("✓ Trading calendar service closed")
    # await mongo_client.close()
    # mongo_client.close_sync()
    logger.info("✓ Shutdown complete")


app = FastAPI(
    title="ELOC Extraction Service",
    description="Extracts data from ELOC documents and sends webhook notifications",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware for React dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],  # React dev servers
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include dashboard API routes
app.include_router(dashboard_router)

# Serve React dashboard static files (production build)
dashboard_build_path = os.path.join(os.path.dirname(__file__), "dashboard", "dist")
if os.path.exists(dashboard_build_path):
    app.mount("/dashboard", StaticFiles(directory=dashboard_build_path, html=True), name="dashboard")
    logger.info(f"✓ Dashboard UI mounted at /dashboard")


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "ELOC Extraction Service",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health():
    """Health check endpoint"""
    # Check MongoDB connection (DISABLED FOR TESTING)
    # try:
    #     await mongo_client.db.command("ping")
    #     mongo_status = "connected"
    # except:
    #     mongo_status = "disconnected"
    
    mongo_status = "disabled"
    
    from webhooks.webhook_sender import webhook_sender
    processing_webhook_configured = webhook_sender is not None
    
    # Get deduplication stats
    with cache_lock:
        dedup_cache_size = len(processed_emails_cache)
    
    return {
        "status": "healthy",
        "mongodb": mongo_status,
        "processing_webhook_configured": processing_webhook_configured,
        "azure_webhook_url": os.getenv("AZURE_WEBHOOK_URL", "not configured"),
        "deduplication_cache_size": dedup_cache_size,
        "dedup_window_minutes": DEDUP_WINDOW_MINUTES
    }


@app.post("/webhook/email")
@app.get("/webhook/email")
async def receive_azure_webhook(
    request: Request,
    validationToken: Optional[str] = Query(None)
):
    """
    Receives webhook notifications FROM Azure
    
    Handles two types of requests:
    1. GET with validationToken - Azure subscription validation (one-time)
    2. POST with notification data - Actual email notifications (ongoing)
    """
    # 1. Handle subscription validation (one-time, GET request with validationToken)
    if validationToken:
        logger.info(f"Azure subscription validation request received: {validationToken}")
        return Response(content=validationToken, media_type="text/plain")
    
    # 2. Process webhook notification (POST request with notification data)
    try:
        body = await request.json()
        logger.info(f"📬 Azure webhook notification received")
        
        # 3. Verify clientState (optional security check)
        expected_client_state = os.getenv("AZURE_CLIENT_STATE")
        if expected_client_state:
            for notification in body.get("value", []):
                client_state = notification.get("clientState")
                if client_state and client_state != expected_client_state:
                    logger.warning(f"Invalid clientState in webhook notification")
                    raise HTTPException(status_code=403, detail="Invalid clientState")
        
        # 4. Process each notification
        notification_count = len(body.get("value", []))
        logger.info(f"Processing {notification_count} notification(s)")
        
        processed_count = 0
        duplicate_count = 0
        error_count = 0
        
        for notification in body.get("value", []):
            # Extract email ID from notification
            resource_data = notification.get("resourceData", {})
            email_id = resource_data.get("id")
            
            if not email_id:
                logger.warning("Notification missing email ID, skipping")
                continue
            
            logger.info(f"Email notification - ID: {email_id}")
            
            # Check if duplicate before processing
            if is_duplicate_notification(email_id):
                logger.info(f"⏭️  Skipping duplicate: {email_id}")
                duplicate_count += 1
                continue
            
            # Process email asynchronously
            try:
                await process_email_notification(email_id)
                processed_count += 1
            except Exception as e:
                # Log error but don't fail the webhook response
                logger.error(f"Failed to process email {email_id}: {str(e)}", exc_info=True)
                error_count += 1
        
        logger.info(f"✓ Webhook complete: {processed_count} processed, {duplicate_count} duplicates, {error_count} errors")
        
        return {
            "status": "accepted",
            "notifications_received": notification_count,
            "processed": processed_count,
            "duplicates_skipped": duplicate_count,
            "errors": error_count,
            "message": "Webhook processed successfully"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.post("/api/process-email")
async def manual_process_email(email_id: str):
    """
    Manual endpoint to trigger email processing for testing
    
    Args:
        email_id: The email message ID to process
    """
    logger.info(f"Manual processing triggered for email: {email_id}")
    
    try:
        await process_email_notification(email_id)
        return {
            "status": "success",
            "email_id": email_id,
            "message": "Email processed successfully"
        }
    except Exception as e:
        logger.error(f"Error processing email {email_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to process email: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )