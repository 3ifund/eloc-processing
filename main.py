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
import asyncio
from dotenv import load_dotenv
from collections import deque
from datetime import datetime, timedelta, UTC
import threading
import hashlib


def parse_date_as_utc_noon(date_str: Optional[str]) -> Optional[datetime]:
    """
    Parse a date string as UTC noon to avoid day boundary issues.

    LLMs return dates like "2026-01-20". We store at noon UTC so that
    timezone conversion to any US timezone still shows the correct date.

    Args:
        date_str: Date string in YYYY-MM-DD format (or None)

    Returns:
        datetime object at noon UTC, or None if input is None/empty
    """
    if not date_str or not isinstance(date_str, str):
        return None

    try:
        # Parse the date string
        date_str = date_str.strip()

        # Handle YYYY-MM-DD format
        if len(date_str) == 10 and date_str[4] == '-' and date_str[7] == '-':
            year = int(date_str[0:4])
            month = int(date_str[5:7])
            day = int(date_str[8:10])

            # Create datetime at noon UTC
            dt = datetime(year, month, day, 12, 0, 0, tzinfo=UTC)
            return dt

        # Try parsing other formats
        for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"]:
            try:
                parsed = datetime.strptime(date_str, fmt)
                # Store at noon UTC
                dt = datetime(parsed.year, parsed.month, parsed.day, 12, 0, 0, tzinfo=UTC)
                return dt
            except ValueError:
                continue

        logger.warning(f"Could not parse date string: {date_str}")
        return None

    except Exception as e:
        logger.warning(f"Error parsing date '{date_str}': {e}")
        return None

from repositories.mongo_client import mongo_client
from workflow import ELOCWorkflow
from services.trading_calendar_service import TradingCalendarService
from services.verification.orchestrator import VerificationOrchestrator, SignatureVerificationOrchestrator
from services.verification.examples_repository import ExamplesRepository
from services.processing_tracker import ProcessingTracker
from services.structured_logger import StructuredLogger, get_logger
from services.async_file_logger import configure_all_loggers, stop_async_logging
from services.eloc_id_service import ElocIdService
from services.eloc_data_service import ElocDataService
from services.eloc_state_service import ElocStateService
from services.company_lookup_service import CompanyLookupService
import services.processing_tracker as tracker_module
import services.structured_logger as logger_module
from routes.dashboard import router as dashboard_router, broadcast_event

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

# Setup async file logging (writes to C:\logging\ELOC Processing\)
configure_all_loggers(level=logging.INFO)
logger = logging.getLogger(__name__)


# ==================== DEDUPLICATION CACHE ====================
# Stores (email_id, timestamp) for recently processed emails
processed_emails_cache = deque(maxlen=1000)  # Keep last 1000 emails
cache_lock = threading.Lock()
DEDUP_WINDOW_MINUTES = 5  # Ignore duplicates within 5 minutes

# Hash-based deduplication - prevents race condition during processing
# Hashes are added immediately when processing starts, before DB persistence
processing_hashes: set = set()  # Set of hashes currently being processed
hash_lock = threading.Lock()


def is_duplicate_notification(email_id: str) -> bool:
    """
    Check if this email was recently processed (deduplication)
    
    Args:
        email_id: The email message ID
    
    Returns:
        True if duplicate (already processed recently), False if new
    """
    with cache_lock:
        now = datetime.now(UTC)
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


async def check_attachment_duplicate(pdf_bytes: bytes) -> tuple:
    """
    Check if attachment is a duplicate using SHA256 hash.

    Uses two-layer deduplication:
    1. In-memory set for race condition prevention (hashes currently being processed)
    2. Database lookup for previously processed attachments

    Args:
        pdf_bytes: Raw PDF file bytes

    Returns:
        (is_duplicate, hash, original_eloc_id or None)
    """
    # Compute SHA256 hash of PDF bytes
    attachment_hash = hashlib.sha256(pdf_bytes).hexdigest()

    with hash_lock:
        # Layer 1: Check in-memory set (prevents race condition)
        if attachment_hash in processing_hashes:
            return True, attachment_hash, "(processing)"

        # Layer 2: Check database for previously processed attachments
        if mongo_client.db is not None:
            existing = await mongo_client.db["eloc_data"].find_one(
                {"attachment_hash": attachment_hash},
                {"eloc_id": 1}
            )
            if existing:
                return True, attachment_hash, existing.get("eloc_id")

        # Not a duplicate - add to processing set immediately
        processing_hashes.add(attachment_hash)

    return False, attachment_hash, None


def remove_processing_hash(attachment_hash: str) -> bool:
    """
    Remove a hash from the processing set.

    Called when processing fails to allow reprocessing of the same attachment.

    Args:
        attachment_hash: The SHA256 hash to remove

    Returns:
        True if hash was removed, False if it wasn't in the set
    """
    with hash_lock:
        if attachment_hash in processing_hashes:
            processing_hashes.discard(attachment_hash)
            logger.debug(f"Removed hash from processing set: {attachment_hash[:16]}...")
            return True
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


# ==================== SUBSCRIPTION AUTO-RENEWAL ====================

# Global variable to track the renewal task
_renewal_task: Optional[asyncio.Task] = None


async def get_active_subscription() -> Optional[Dict]:
    """
    Get the active subscription for this mailbox, if any.

    Returns:
        Dict with subscription details, or None if no subscription exists
    """
    access_token = get_graph_access_token()
    mailbox_id = os.getenv("MAILBOX_OBJECT_ID")
    webhook_url = os.getenv("AZURE_WEBHOOK_URL")

    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://graph.microsoft.com/v1.0/subscriptions",
            headers={"Authorization": f"Bearer {access_token}"}
        ) as response:
            if response.status != 200:
                logger.error(f"Failed to fetch subscriptions: {response.status}")
                return None

            data = await response.json()
            subscriptions = data.get("value", [])

            # Find subscription matching our mailbox and webhook URL
            for sub in subscriptions:
                if mailbox_id in sub.get("resource", "") and webhook_url in sub.get("notificationUrl", ""):
                    return sub

            return None


async def create_or_renew_subscription() -> bool:
    """
    Create a new subscription or renew an existing one.

    Returns:
        True if successful, False otherwise
    """
    access_token = get_graph_access_token()
    mailbox_id = os.getenv("MAILBOX_OBJECT_ID")
    webhook_url = os.getenv("AZURE_WEBHOOK_URL")
    client_state = os.getenv("AZURE_CLIENT_STATE", "eloc-processing-secret")

    if not webhook_url:
        logger.error("AZURE_WEBHOOK_URL not configured - cannot create subscription")
        return False

    # Check for existing subscription
    existing = await get_active_subscription()

    if existing:
        # Check if it expires within 24 hours
        expiration = datetime.fromisoformat(existing["expirationDateTime"].replace("Z", "+00:00"))
        time_until_expiry = expiration - datetime.now(UTC)

        if time_until_expiry > timedelta(hours=24):
            logger.info(f"✓ Subscription valid for {time_until_expiry.days}d {time_until_expiry.seconds//3600}h")
            return True

        # Renew the subscription
        logger.info(f"Subscription expires in {time_until_expiry.seconds//3600}h - renewing...")
        new_expiration = (datetime.now(UTC) + timedelta(days=3)).isoformat().replace("+00:00", "Z")

        async with aiohttp.ClientSession() as session:
            async with session.patch(
                f"https://graph.microsoft.com/v1.0/subscriptions/{existing['id']}",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                },
                json={"expirationDateTime": new_expiration}
            ) as response:
                if response.status == 200:
                    logger.info(f"✓ Subscription renewed until {new_expiration}")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to renew subscription: {response.status} - {error_text}")
                    # Fall through to create new subscription

    # Create new subscription
    logger.info(f"Creating new subscription...")
    logger.info(f"  Webhook URL: {webhook_url}")

    expiration = (datetime.now(UTC) + timedelta(days=3)).isoformat().replace("+00:00", "Z")

    subscription_data = {
        "changeType": "created",
        "notificationUrl": webhook_url,
        "resource": f"/users/{mailbox_id}/mailFolders('Inbox')/messages",
        "expirationDateTime": expiration,
        "clientState": client_state
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://graph.microsoft.com/v1.0/subscriptions",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            },
            json=subscription_data
        ) as response:
            if response.status == 201:
                sub = await response.json()
                logger.info(f"✓ Subscription created successfully!")
                logger.info(f"  ID: {sub['id']}")
                logger.info(f"  Expires: {sub['expirationDateTime']}")
                return True
            else:
                error_text = await response.text()
                logger.error(f"Failed to create subscription: {response.status} - {error_text}")
                return False


async def subscription_renewal_task():
    """
    Background task that periodically checks and renews the subscription.
    Runs every 12 hours.
    """
    logger.info("Subscription auto-renewal task started (runs every 12 hours)")

    while True:
        try:
            await asyncio.sleep(12 * 60 * 60)  # Sleep 12 hours
            logger.info("Running scheduled subscription renewal check...")
            await create_or_renew_subscription()
        except asyncio.CancelledError:
            logger.info("Subscription renewal task cancelled")
            break
        except Exception as e:
            logger.error(f"Subscription renewal error: {e}")
            # Continue running despite errors


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


async def extract_purchase_notice_fields(
    pdf_text: str,
    email_info: Dict,
    email_id: str,
    pdf_bytes: Optional[bytes] = None
) -> Dict:
    """
    Extract fields from a Purchase Notice document using dual LLM verification.

    Uses the verification orchestrator (Claude + OpenAI) to extract and verify:
    - Company identification (symbol, name)
    - Signatory information
    - Transaction details (dates, amounts)
    - Email metadata

    Supports multimodal extraction when pdf_bytes is provided - the LLMs will
    see the PDF as an image, improving accuracy for complex layouts and signatures.

    Args:
        pdf_text: Extracted text from the PDF (used as fallback)
        email_info: Email metadata dict
        email_id: Email ID for logging
        pdf_bytes: Optional raw PDF bytes for multimodal extraction

    Returns:
        Dict with extraction results including:
        - success: bool
        - eloc_id: generated ELOC ID (e.g., "ZSPC-00000056")
        - company_id: company ID from PostgreSQL
        - company_symbol, company_name
        - fields_count: number of fields extracted
        - market_data_date: resolved market data date
        - all_fields: complete extracted fields dict
        - confidence_scores: per-field confidence scores
        - error: error message if failed
    """
    import time

    start_time = time.time()

    try:
        # Get orchestrator from app.state (initialized during startup)
        verification_orchestrator = getattr(app.state, 'verification_orchestrator', None)
        if not verification_orchestrator:
            return {
                "success": False,
                "error": "Verification orchestrator not initialized"
            }

        # Run dual LLM verification (multimodal if pdf_bytes provided)
        mode = "multimodal" if pdf_bytes else "text"
        logger.info(f"  Running dual LLM extraction ({mode}, Claude + OpenAI)...")

        result = await verification_orchestrator.verify(
            document_text=pdf_text,
            email_subject=email_info.get("subject", ""),
            email_body=email_info.get("body", ""),
            email_sender=email_info.get("from", ""),
            pdf_bytes=pdf_bytes
        )

        # Check if verification passed (both LLMs agree)
        if not result.passed:
            disagreements = result.get_disagreements()
            disagreement_fields = [d.field_name for d in disagreements]
            logger.warning(f"  Dual LLM disagreement on: {disagreement_fields}")
            # Continue anyway but flag it - in production might require review

        # Get merged fields from all categories
        merged_fields = result.get_merged_fields()
        fields_count = len(merged_fields)

        # Extract key fields for tracking
        company_symbol = merged_fields.get("company_symbol", "")
        company_name = merged_fields.get("company_name", "")

        # Validate and enrich company data using PostgreSQL fuzzy matching
        company_lookup_svc = getattr(app.state, 'company_lookup_service', None)
        company_validated = False
        company_enriched = False
        db_similarity_score = 0.0
        lookup_company_id = None  # Capture company_id from lookup as fallback

        if company_lookup_svc:
            try:
                lookup_result = await company_lookup_svc.validate_and_enrich(
                    extracted_symbol=company_symbol or None,
                    extracted_name=company_name or None
                )

                if lookup_result['validated']:
                    company_validated = True
                    db_similarity_score = lookup_result['similarity_score']
                    lookup_company_id = lookup_result.get('company_id')  # Capture for fallback

                    # Always use validated symbol from DB (handles cases like "Not specified")
                    db_symbol = lookup_result['symbol']
                    if db_symbol and db_symbol != company_symbol:
                        logger.info(f"  Company symbol updated from DB: '{company_symbol}' -> '{db_symbol}'")
                        company_symbol = db_symbol
                        merged_fields['company_symbol'] = company_symbol
                        company_enriched = True

                    # Use validated name from DB
                    company_name = lookup_result['name']
                    merged_fields['company_name'] = company_name

                    logger.info(
                        f"  Company validated (score={db_similarity_score:.3f}): "
                        f"{company_symbol} - {company_name}"
                    )
                else:
                    logger.warning(f"  Company not found in DB: {company_symbol} / {company_name}")
            except Exception as e:
                logger.warning(f"  Company lookup failed: {e}")

        # Generate ELOC ID using the ElocIdService (proper sequential IDs)
        eloc_id = None
        company_id = None
        eloc_id_svc = getattr(app.state, 'eloc_id_service', None)
        logger.info(f"  ELOC ID service available: {eloc_id_svc is not None}, company_symbol: '{company_symbol}'")
        if eloc_id_svc and company_symbol:
            try:
                eloc_id, company_id = await eloc_id_svc.generate_eloc_id(company_symbol)
                logger.info(f"  Generated ELOC ID: {eloc_id} (company_id={company_id})")
            except ValueError as e:
                logger.warning(f"  Could not generate ELOC ID (ValueError): {e}")
                # Fallback to simple ID format
                eloc_id = f"ELOC-{company_symbol}-{email_id[:8]}"
            except Exception as e:
                logger.error(f"  Could not generate ELOC ID (unexpected error): {type(e).__name__}: {e}")
                # Fallback to simple ID format
                eloc_id = f"ELOC-{company_symbol}-{email_id[:8]}"
        else:
            # Fallback if service not available
            logger.warning(f"  Using fallback ELOC ID (service={eloc_id_svc is not None}, symbol='{company_symbol}')")
            eloc_id = f"ELOC-{company_symbol}-{email_id[:8]}"

        # Use lookup_company_id as fallback if ELOC ID generation didn't provide one
        if company_id is None and lookup_company_id is not None:
            company_id = lookup_company_id
            logger.info(f"  Using company_id from lookup fallback: {company_id}")

        # Get market data date if resolved (use noon UTC to avoid day boundary issues)
        market_data_date = None
        if result.market_data_date_info:
            market_data_date = datetime(
                result.market_data_date_info.market_data_date.year,
                result.market_data_date_info.market_data_date.month,
                result.market_data_date_info.market_data_date.day,
                12, 0, 0,
                tzinfo=UTC
            )

        # Get confidence scores from LLM agreement verification
        # Formula: LLM_agree ? 100 : 0
        confidence_scores = result.get_field_confidences()

        # Boost confidence for DB-validated company fields
        # If company was validated in DB, set company_symbol and company_name to 100%
        if company_validated:
            if 'company_symbol' in confidence_scores:
                confidence_scores['company_symbol'] = 100.0
            if 'company_name' in confidence_scores:
                confidence_scores['company_name'] = 100.0
            logger.info(f"  DB validation: company_symbol and company_name boosted to 100%")

        # LLM agreement stats
        field_details = result.get_field_details()
        llm_agree_count = sum(1 for d in field_details.values() if d.get("llm_agree"))
        logger.info(f"  LLM agreement: {llm_agree_count}/{len(field_details)} fields")

        duration_ms = int((time.time() - start_time) * 1000)

        logger.info(f"  Extraction completed in {duration_ms}ms")
        logger.info(f"  Company: {company_symbol} ({company_name})")
        logger.info(f"  Fields extracted: {fields_count}")
        logger.info(f"  Agreement: {'PASSED' if result.passed else 'DISAGREEMENT'}")

        # Log key transaction fields
        exercise_date = merged_fields.get("vwap_purchase_exercise_date", "N/A")
        share_amount = merged_fields.get("vwap_purchase_share_amount", "N/A")
        logger.info(f"  Exercise Date: {exercise_date}, Shares: {share_amount}")

        return {
            "success": True,
            "eloc_id": eloc_id,
            "company_id": company_id,
            "company_symbol": company_symbol,
            "company_name": company_name,
            "fields_count": fields_count,
            "market_data_date": market_data_date,
            "duration_ms": duration_ms,
            "all_fields": merged_fields,
            "confidence_scores": confidence_scores,
            "verification_passed": result.passed,
            "agreement_summary": result.agreement_summary,
            "company_validated": company_validated,
            "company_enriched": company_enriched,
            "db_similarity_score": db_similarity_score,
            "llm_agree_count": llm_agree_count,
            "llm_total_count": len(field_details)
        }

    except Exception as e:
        logger.error(f"  Extraction error: {e}")
        duration_ms = int((time.time() - start_time) * 1000)
        return {
            "success": False,
            "error": str(e),
            "duration_ms": duration_ms
        }


async def verify_signatures_and_extract(pdf_text: str, workflow) -> Dict:
    """
    Verify signatures on a Purchase Confirmation document and extract matching fields.

    Args:
        pdf_text: Extracted text from the PDF
        workflow: ELOCWorkflow instance with Claude client

    Returns:
        Dict with signature verification results and matching fields
    """
    try:
        prompt = f"""Analyze this VWAP Purchase Confirmation document.

Document text:
{pdf_text[:8000]}

IMPORTANT: This is a VWAP Purchase Confirmation document. Extract the following:

1. SIGNATURE VERIFICATION:
   - INVESTOR SIGNATURE (top): The investor (e.g., "Tumim Stone Capital LLC") signs first
   - COMPANY SIGNATURE (bottom): Under "AGREED AND ACCEPTED:" section
   - A signature IS VALID if BOTH the "Name:" AND "Title:" fields contain actual names/titles (not blank, not template placeholders)
   - NOTE: The "By:" line may appear empty in text - ignore this. Visual signatures cannot be extracted as text.
   - ONLY check if Name: and Title: have real values filled in

2. MATCHING FIELDS (to link to original Purchase Notice):
   - company_name: The target company name (the share issuer, NOT the investor)
   - company_symbol: The stock ticker ONLY if explicitly shown in the document, otherwise null
   - vwap_purchase_share_amount: Number of shares (integer)
   - vwap_purchase_exercise_date: The exercise date in YYYY-MM-DD format

Respond with JSON only:
{{
  "investor_signed": true/false,
  "company_signed": true/false,
  "investor_signatory": "Name, Title" or null,
  "company_signatory": "Name, Title" or null,
  "investor_company": "Name of investor company",
  "target_company": "Name of target company",
  "company_symbol": "TICKER" or null,
  "vwap_purchase_share_amount": 75000,
  "vwap_purchase_exercise_date": "2025-11-17",
  "notes": "Brief explanation"
}}"""

        response = workflow.claude_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )

        import json
        result_text = response.content[0].text.strip()

        # Remove markdown code blocks if present
        if result_text.startswith("```"):
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]
            result_text = result_text.strip()

        result = json.loads(result_text)
        logger.info(
            f"Signature verification: investor={result.get('investor_signed')}, "
            f"company={result.get('company_signed')}"
        )
        logger.info(
            f"Matching fields: company={result.get('target_company')}, "
            f"shares={result.get('vwap_purchase_share_amount')}, "
            f"exercise_date={result.get('vwap_purchase_exercise_date')}"
        )
        return result

    except Exception as e:
        logger.error(f"Signature verification error: {e}")
        return {
            "company_signed": False,
            "investor_signed": False,
            "company_signatory": None,
            "investor_signatory": None,
            "notes": f"Verification failed: {str(e)}"
        }


async def process_email_notification(email_id: str):
    """
    Process a single email notification with deduplication, tracking, and logging

    Args:
        email_id: The email message ID from Azure notification
    """
    from services.processing_tracker import processing_tracker
    from services.structured_logger import get_logger

    structured_log = get_logger()

    # Note: Duplicate check already performed in webhook handler (line ~1140)
    # which adds email_id to cache. Checking again here would always find it.

    try:
        logger.info(f"📧 Processing email notification: {email_id}")

        # Step 1: Fetch email metadata
        email_data = await fetch_email_from_graph(email_id)

        # Extract email fields (use 'or {}' to handle None values, not just missing keys)
        email_info = {
            "message_id": email_data.get("id"),
            "internet_message_id": email_data.get("internetMessageId"),
            "subject": email_data.get("subject"),
            "from": (email_data.get("from") or {}).get("emailAddress", {}).get("address"),
            "to": [(r.get("emailAddress") or {}).get("address") for r in (email_data.get("toRecipients") or [])],
            "cc": [(r.get("emailAddress") or {}).get("address") for r in (email_data.get("ccRecipients") or [])],
            "received_at": email_data.get("receivedDateTime"),
            "body": (email_data.get("body") or {}).get("content", ""),
            "body_type": (email_data.get("body") or {}).get("contentType", "html"),
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

            # Check for duplicate attachment by hash
            is_dup, attachment_hash, existing_eloc_id = await check_attachment_duplicate(attachment["content"])
            if is_dup:
                logger.info(f"  ⏭️  Skipping duplicate attachment: {attachment['filename']} (already processed as {existing_eloc_id})")
                structured_log.duplicate_detected(email_id, f"Attachment hash matches {existing_eloc_id}")
                if processing_tracker:
                    await processing_tracker.mark_duplicate(email_id)
                continue

            # Store hash for use when persisting
            attachment["hash"] = attachment_hash

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
                remove_processing_hash(attachment_hash)
                continue

            # Run classification
            classification_result = eloc_workflow.classifier.classify(pdf_text)

            # Handle None classification result
            if classification_result is None:
                classification_result = {"final_classification": "UNKNOWN", "agreement": "error"}

            # Get votes for tracking
            votes = {}
            if classification_result.get("similarity_result"):
                votes["similarity"] = classification_result["similarity_result"].get("classification", "ERROR")
            if classification_result.get("claude_result"):
                votes["claude"] = classification_result["claude_result"].get("classification", "ERROR")
            if classification_result.get("openai_result"):
                votes["openai"] = classification_result["openai_result"].get("classification", "ERROR")

            # Get max similarity score (handle both dual and legacy modes)
            sim_scores = (classification_result.get("similarity_result") or {}).get("scores", {})
            max_similarity = sim_scores.get("max_similarity") or max(
                sim_scores.get("notice_max_similarity", 0),
                sim_scores.get("confirmation_max_similarity", 0)
            )

            # Update tracking with classification result
            if processing_tracker:
                await processing_tracker.set_classification_result(
                    email_id=email_id,
                    result=classification_result.get("final_classification", "UNKNOWN"),
                    votes=votes,
                    agreement=classification_result.get("agreement", "unknown"),
                    confidence=classification_result.get("final_confidence", "UNKNOWN"),
                    similarity_score=max_similarity
                )

            structured_log.classification_result(
                email_id=email_id,
                result=classification_result.get("final_classification", "UNKNOWN"),
                votes=votes,
                agreement=classification_result.get("agreement", "unknown"),
                confidence=classification_result.get("final_confidence", "UNKNOWN"),
                similarity_score=max_similarity
            )

            # Get the final classification result
            final_classification = classification_result.get("final_classification", "UNKNOWN")

            # Set document type for tracking
            if processing_tracker and final_classification in ("PURCHASE_NOTICE", "PURCHASE_CONFIRMATION"):
                await processing_tracker.set_document_type(email_id, final_classification)

            # Handle based on document type
            if final_classification == "NOT_RELEVANT":
                logger.info(f"  Document classified as NOT_RELEVANT - skipping processing")
                remove_processing_hash(attachment_hash)
                continue

            elif final_classification == "PURCHASE_NOTICE":
                # ========== PURCHASE NOTICE WORKFLOW ==========
                # NOTE: Previously had countersigned check here, but it was using the wrong prompt
                # (confirmation_signature prompt for Purchase Notices). Removed to prevent false positives.
                # Purchase Notices normally only have company signature - countersigned detection
                # would require a dedicated prompt that checks for investor signatures on Notices.

                # Extract data fields from the document using dual LLM verification
                if processing_tracker:
                    await processing_tracker.start_extraction(email_id)
                structured_log.extraction_start(email_id)

                logger.info(f"  ✓ Document classified as PURCHASE_NOTICE - starting extraction")

                # Run extraction using verification orchestrator (Claude + OpenAI)
                # Pass PDF bytes for multimodal extraction (vision API)
                extraction_result = await extract_purchase_notice_fields(
                    pdf_text=pdf_text,
                    email_info=email_info,
                    email_id=email_id,
                    pdf_bytes=attachment["content"]
                )

                if extraction_result.get("success"):
                    # Check for duplicate by extracted terms BEFORE persisting
                    eloc_data_svc = getattr(app.state, 'eloc_data_service', None)
                    if eloc_data_svc:
                        all_fields = extraction_result.get("all_fields", {})
                        dup_check_symbol = extraction_result.get("company_symbol", "")
                        dup_check_shares = int(all_fields.get("vwap_purchase_share_amount", 0) or 0)
                        dup_check_date = parse_date_as_utc_noon(all_fields.get("vwap_purchase_exercise_date"))

                        if dup_check_symbol and dup_check_shares:
                            existing_eloc = await eloc_data_svc.check_duplicate_by_terms(
                                company_symbol=dup_check_symbol,
                                share_amount=dup_check_shares,
                                exercise_date=dup_check_date
                            )
                            if existing_eloc:
                                existing_eloc_id = existing_eloc.get("eloc_id", "unknown")
                                logger.info(
                                    f"  ⏭️  Skipping duplicate by terms: {attachment['filename']} "
                                    f"(matches {existing_eloc_id}: {dup_check_symbol}, {dup_check_shares} shares)"
                                )
                                structured_log.duplicate_detected(
                                    email_id, f"Terms match existing ELOC {existing_eloc_id}"
                                )
                                if processing_tracker:
                                    await processing_tracker.mark_duplicate(email_id)
                                remove_processing_hash(attachment_hash)
                                continue

                    # Get confidence summary from extraction result
                    confidence_scores = extraction_result.get("confidence_scores", {})
                    avg_confidence = None
                    if confidence_scores:
                        avg_confidence = sum(confidence_scores.values()) / len(confidence_scores)

                    # Get LLM agreement stats from extraction result
                    llm_agree_count = extraction_result.get("llm_agree_count", 0)
                    llm_total_count = extraction_result.get("llm_total_count", 0)

                    # Update tracking with extraction result including confidence
                    if processing_tracker:
                        await processing_tracker.set_extraction_result(
                            email_id=email_id,
                            eloc_id=extraction_result.get("eloc_id", ""),
                            company_symbol=extraction_result.get("company_symbol", ""),
                            company_name=extraction_result.get("company_name", ""),
                            fields_extracted=extraction_result.get("fields_count", 0),
                            market_data_date=extraction_result.get("market_data_date"),
                            field_confidences=confidence_scores,
                            avg_confidence=avg_confidence,
                            llm_agree_count=llm_agree_count,
                            llm_total_count=llm_total_count
                        )

                    structured_log.extraction_result(
                        email_id=email_id,
                        eloc_id=extraction_result.get("eloc_id", ""),
                        company_symbol=extraction_result.get("company_symbol", ""),
                        company_name=extraction_result.get("company_name", ""),
                        fields_count=extraction_result.get("fields_count", 0),
                        duration_ms=extraction_result.get("duration_ms", 0)
                    )

                    logger.info(
                        f"  Extraction complete: {extraction_result.get('company_symbol')} - "
                        f"{extraction_result.get('fields_count')} fields extracted"
                    )

                    # ========== PERSIST TO MONGODB ==========
                    eloc_data_svc = getattr(app.state, 'eloc_data_service', None)
                    eloc_state_svc = getattr(app.state, 'eloc_state_service', None)

                    eloc_id = extraction_result.get("eloc_id")
                    company_id = extraction_result.get("company_id")

                    if eloc_data_svc and eloc_state_svc and eloc_id and company_id:
                        try:
                            # Build extracted_fields with {value, confidence} pattern
                            all_fields = extraction_result.get("all_fields", {})
                            confidence_scores = extraction_result.get("confidence_scores", {})

                            extracted_fields = ElocDataService.build_extracted_fields(
                                company_symbol=all_fields.get("company_symbol", ""),
                                company_name=all_fields.get("company_name", ""),
                                agreement_date=parse_date_as_utc_noon(all_fields.get("agreement_date")),
                                company_signator=all_fields.get("company_signator", ""),
                                signatory_title=all_fields.get("signatory_title", ""),
                                vwap_purchase_share_amount=int(all_fields.get("vwap_purchase_share_amount", 0) or 0),
                                vwap_purchase_exercise_date=parse_date_as_utc_noon(all_fields.get("vwap_purchase_exercise_date")),
                                vwap_purchase_period_start_date=parse_date_as_utc_noon(all_fields.get("vwap_purchase_period_start_date")),
                                vwap_purchase_period_end_date=parse_date_as_utc_noon(all_fields.get("vwap_purchase_period_end_date")),
                                vwap_purchase_settlement_date=parse_date_as_utc_noon(all_fields.get("vwap_purchase_settlement_date")),
                                aggregate_limit_available=all_fields.get("aggregate_limit_available"),
                                sender_name=all_fields.get("sender_name", ""),
                                sender_emails=all_fields.get("sender_emails", []),
                                email_subject=email_info.get("subject", ""),
                                email_body=email_info.get("body", "")[:1000],  # Truncate body
                                purchase_notice_market_data_date=extraction_result.get("market_data_date"),
                                purchase_notice_company_signature=all_fields.get("purchase_notice_company_signature", False),
                                confidence_scores=confidence_scores
                            )

                            # Get email received_at
                            received_at = None
                            if email_info.get("received_at"):
                                received_at = datetime.fromisoformat(
                                    email_info["received_at"].replace("Z", "+00:00")
                                )

                            # Create eloc_data document
                            await eloc_data_svc.create_eloc_data(
                                eloc_id=eloc_id,
                                extracted_fields=extracted_fields,
                                pdf_bytes=attachment["content"],
                                pdf_filename=attachment["filename"],
                                purchase_notice_market_data_date=extraction_result.get("market_data_date"),
                                received_at=received_at,
                                attachment_hash=attachment.get("hash"),
                                company_id=company_id
                            )
                            logger.info(f"  ✓ Persisted eloc_data: {eloc_id}")

                            # Create eloc_state document
                            await eloc_state_svc.create_eloc_state(
                                eloc_id=eloc_id,
                                company_id=company_id,
                                workflow_step="VerificationOfExtractedFields",
                                status="Pending",
                                include=True
                            )
                            logger.info(f"  ✓ Persisted eloc_state: {eloc_id}")

                        except Exception as persist_error:
                            logger.error(f"  Failed to persist ELOC data: {persist_error}")
                            remove_processing_hash(attachment_hash)
                            # Don't fail the whole workflow for persistence errors
                    else:
                        logger.warning(
                            f"  Skipping persistence: services={bool(eloc_data_svc and eloc_state_svc)}, "
                            f"eloc_id={eloc_id}, company_id={company_id}"
                        )
                        remove_processing_hash(attachment_hash)

                    # Mark completed
                    if processing_tracker:
                        await processing_tracker.mark_completed(email_id)
                    structured_log.processing_complete(email_id, extraction_result.get("eloc_id"))
                else:
                    # Extraction failed
                    error_msg = extraction_result.get("error", "Unknown extraction error")
                    logger.error(f"  Extraction failed: {error_msg}")
                    remove_processing_hash(attachment_hash)
                    if processing_tracker:
                        await processing_tracker.mark_failed(email_id, error_msg, stage="extraction")

            elif final_classification == "PURCHASE_CONFIRMATION":
                # ========== PURCHASE CONFIRMATION WORKFLOW ==========
                # Verify signatures using dual LLM (Claude + OpenAI)
                if processing_tracker:
                    await processing_tracker.start_signature_verification(email_id)

                logger.info(f"  ✓ Document classified as PURCHASE_CONFIRMATION - verifying signatures (dual LLM)")

                # Get signature verification orchestrator
                sig_orchestrator = getattr(app.state, 'signature_verification_orchestrator', None)
                if not sig_orchestrator:
                    logger.error("  ✗ Signature verification orchestrator not initialized")
                    remove_processing_hash(attachment_hash)
                    if processing_tracker:
                        await processing_tracker.mark_failed(
                            email_id, "Signature verification orchestrator not initialized", stage="signature_verification"
                        )
                    continue

                # Run dual LLM signature verification (with multimodal support)
                sig_comparison = await sig_orchestrator.verify_signatures(pdf_text, pdf_bytes=attachment["content"])
                signature_result = sig_comparison.get_merged_fields()

                # Update tracking with signature verification result
                if processing_tracker:
                    await processing_tracker.set_signature_verification_result(
                        email_id=email_id,
                        company_signed=sig_comparison.company_signed,
                        investor_signed=sig_comparison.investor_signed,
                        company_signatory=signature_result.get("company_signatory"),
                        investor_signatory=signature_result.get("investor_signatory"),
                        verification_notes=signature_result.get("verification_notes"),
                        llm_agreement=sig_comparison.all_agree,
                        agreement_details=sig_comparison.agreement_summary
                    )

                # Log verification results
                agreement_status = "AGREE" if sig_comparison.all_agree else "DISAGREE"
                logger.info(
                    f"  Signature verification ({agreement_status}): "
                    f"company={sig_comparison.company_signed}, investor={sig_comparison.investor_signed}, "
                    f"duration={sig_comparison.duration_ms:.0f}ms"
                )

                if not sig_comparison.all_agree:
                    disagreements = sig_comparison.get_disagreements()
                    logger.warning(f"  LLM disagreements: {[d.field_name for d in disagreements]}")

                # Log signature status (informational - does not block persistence)
                if sig_comparison.both_signed:
                    logger.info("  ✓ Both parties signed")
                else:
                    logger.info(f"  ⚠ Signature status: company={sig_comparison.company_signed}, investor={sig_comparison.investor_signed}")

                # Get matching fields from signature result
                company_name = signature_result.get("target_company", "")
                company_symbol = signature_result.get("company_symbol")
                share_amount = signature_result.get("vwap_purchase_share_amount")
                exercise_date = signature_result.get("vwap_purchase_exercise_date")

                logger.info(
                    f"  Matching fields: company={company_name}, symbol={company_symbol}, "
                    f"shares={share_amount}, date={exercise_date}"
                )

                # Look up company_id from PostgreSQL for robust matching
                confirmation_company_id = None
                company_lookup_service = getattr(app.state, 'company_lookup_service', None)
                if company_lookup_service and company_name:
                    try:
                        lookup_result = await company_lookup_service.lookup_by_name(company_name)
                        if lookup_result:
                            confirmation_company_id = lookup_result.company_id
                            logger.info(f"  ✓ Resolved company_id={confirmation_company_id} for confirmation matching (similarity={lookup_result.similarity_score:.2f})")
                    except Exception as lookup_err:
                        logger.warning(f"  Company lookup failed: {lookup_err}")

                # Find matching Purchase Notice in MongoDB
                eloc_data_service = getattr(app.state, 'eloc_data_service', None)
                eloc_state_service = getattr(app.state, 'eloc_state_service', None)

                if eloc_data_service and share_amount:
                    matching_notice = await eloc_data_service.find_matching_purchase_notice(
                        company_name=company_name,
                        share_amount=share_amount,
                        exercise_date=exercise_date,
                        company_symbol=company_symbol,
                        company_id=confirmation_company_id
                    )

                    if matching_notice:
                        eloc_id = matching_notice.get("eloc_id")
                        logger.info(f"  ✓ Found matching Purchase Notice: {eloc_id}")

                        # Save confirmation PDF to the matched eloc_data
                        pdf_bytes = attachment.get("content", b"")
                        if isinstance(pdf_bytes, str):
                            import base64
                            pdf_bytes = base64.b64decode(pdf_bytes)

                        confirmation_added = await eloc_data_service.add_confirmation_pdf(
                            eloc_id=eloc_id,
                            pdf_bytes=pdf_bytes,
                            pdf_filename=attachment["filename"],
                            signature_verification={
                                "purchase_confirmation_investor_signature": signature_result.get("purchase_confirmation_investor_signature"),
                                "purchase_confirmation_company_signature": signature_result.get("purchase_confirmation_company_signature"),
                                "investor_signatory": signature_result.get("investor_signatory"),
                                "company_signatory": signature_result.get("company_signatory"),
                                "investor_company": signature_result.get("investor_company"),
                                "target_company": signature_result.get("target_company"),
                                "vwap_purchase_share_amount": signature_result.get("vwap_purchase_share_amount"),
                                "vwap_purchase_exercise_date": signature_result.get("vwap_purchase_exercise_date"),
                                "verification_notes": signature_result.get("verification_notes"),
                                "both_parties_signed": sig_comparison.both_signed,
                                "llm_agreement": sig_comparison.all_agree
                            }
                        )

                        if confirmation_added:
                            logger.info(f"  ✓ Added confirmation PDF to {eloc_id}")

                            # Update eloc_state workflow step
                            if eloc_state_service:
                                await eloc_state_service.update_workflow_step(
                                    eloc_id=eloc_id,
                                    workflow_step="ReceivedCountersignedVwapNotification",
                                    status="Pending"
                                )
                                logger.info(f"  ✓ Updated eloc_state: {eloc_id} -> ReceivedCountersignedVwapNotification")

                            # Mark completed
                            if processing_tracker:
                                await processing_tracker.mark_completed(email_id)
                            structured_log.processing_complete(email_id, eloc_id)
                        else:
                            logger.error(f"  ✗ Failed to add confirmation PDF to {eloc_id}")
                            remove_processing_hash(attachment_hash)
                            if processing_tracker:
                                await processing_tracker.mark_failed(
                                    email_id, f"Failed to save confirmation PDF to {eloc_id}"
                                )
                    else:
                        failure_reason = (
                            f"No matching Purchase Notice found in database. "
                            f"Looking for: company='{company_name}', symbol='{company_symbol}', "
                            f"shares={share_amount}, exercise_date={exercise_date}. "
                            f"Ensure a Purchase Notice with these values exists before sending the Confirmation."
                        )
                        logger.warning(f"  ✗ {failure_reason}")
                        remove_processing_hash(attachment_hash)
                        if processing_tracker:
                            await processing_tracker.mark_failed(email_id, failure_reason)
                else:
                    failure_reason = (
                        f"Cannot match Purchase Confirmation - missing required fields. "
                        f"share_amount={share_amount}, eloc_data_service={'available' if eloc_data_service else 'unavailable'}"
                    )
                    logger.warning(f"  ✗ {failure_reason}")
                    remove_processing_hash(attachment_hash)
                    if processing_tracker:
                        await processing_tracker.mark_failed(email_id, failure_reason)

            else:
                # UNCERTAIN or ERROR classification
                logger.warning(f"  Document classification uncertain: {final_classification}")
                remove_processing_hash(attachment_hash)
                if processing_tracker:
                    await processing_tracker.mark_failed(email_id, f"Uncertain classification: {final_classification}")

        logger.info(f"✅ Email {email_id} processing complete")

    except Exception as e:
        logger.error(f"❌ Error processing email {email_id}: {str(e)}", exc_info=True)

        # Clean up any hash that was being processed when exception occurred
        try:
            if attachment_hash:
                remove_processing_hash(attachment_hash)
        except NameError:
            pass  # attachment_hash not defined (exception before hash was computed)

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

    # Connect SSE broadcast to logger for real-time dashboard updates
    StructuredLogger.set_sse_broadcast(broadcast_event)
    logger.info("✓ Structured logger initialized (with SSE broadcast)")

    if mongodb_enabled:
        try:
            await mongo_client.connect()
            logger.info("✓ MongoDB connected")

            # Initialize Processing Tracker for dashboard
            processing_tracker = ProcessingTracker(mongo_client.db)
            await processing_tracker.ensure_indexes()
            tracker_module.processing_tracker = processing_tracker
            logger.info("✓ Processing tracker initialized")

            # Initialize ELOC persistence services (stored in app.state)
            app.state.eloc_id_service = ElocIdService(mongo_client.db, PG_CONFIG)
            await app.state.eloc_id_service.ensure_indexes()
            logger.info("✓ ELOC ID service initialized")

            app.state.eloc_data_service = ElocDataService(mongo_client.db)
            await app.state.eloc_data_service.ensure_indexes()
            logger.info("✓ ELOC data service initialized")

            app.state.eloc_state_service = ElocStateService(mongo_client.db)
            logger.info("✓ ELOC state service initialized")

            # Initialize Company Lookup Service (PostgreSQL fuzzy matching)
            app.state.company_lookup_service = CompanyLookupService(PG_CONFIG, similarity_threshold=0.3)
            logger.info("✓ Company lookup service initialized")

            # Initialize Examples Repository for classification
            examples_repository = ExamplesRepository(mongo_client.db)
            example_count = await examples_repository.count()
            logger.info(f"✓ Examples repository initialized ({example_count} examples)")
        except Exception as e:
            logger.warning(f"⚠ MongoDB connection failed: {e} - Running without MongoDB")
            mongodb_enabled = False
    else:
        logger.info("⚠ MongoDB DISABLED - Running in test mode")

    # Initialize Trading Calendar Service
    trading_calendar_service = TradingCalendarService(pg_config=PG_CONFIG)
    logger.info("✓ Trading calendar service initialized")

    # Initialize Verification Orchestrator (dual LLM + trading calendar)
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
    openai_api_key = os.getenv("OPENAI_API_KEY")

    verification_orchestrator = None
    signature_verification_orchestrator = None
    if anthropic_api_key and openai_api_key:
        verification_orchestrator = VerificationOrchestrator(
            anthropic_api_key=anthropic_api_key,
            openai_api_key=openai_api_key,
            trading_calendar_service=trading_calendar_service
        )
        signature_verification_orchestrator = SignatureVerificationOrchestrator(
            anthropic_api_key=anthropic_api_key,
            openai_api_key=openai_api_key
        )
        logger.info("✓ Verification orchestrators initialized (Claude + OpenAI)")
    else:
        logger.warning("⚠ Missing API keys - verification orchestrators disabled")

    # Store services in app state for access in routes
    app.state.trading_calendar_service = trading_calendar_service
    app.state.verification_orchestrator = verification_orchestrator
    app.state.signature_verification_orchestrator = signature_verification_orchestrator

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

    # Start delayed subscription setup (waits 3 seconds for routes to be ready)
    webhook_url = os.getenv("AZURE_WEBHOOK_URL")
    if webhook_url:
        asyncio.create_task(delayed_subscription_setup())
        logger.info("✓ Scheduled delayed subscription setup (3s)")
    else:
        logger.warning("⚠ AZURE_WEBHOOK_URL not set - webhook subscription skipped")

    logger.info("=" * 60)
    logger.info("✅ ELOC EXTRACTION SERVICE - Ready")
    logger.info("=" * 60)

    yield

    # Cleanup
    logger.info("Shutting down...")

    # Cancel subscription renewal task
    if _renewal_task and not _renewal_task.done():
        _renewal_task.cancel()
        try:
            await _renewal_task
        except asyncio.CancelledError:
            pass
        logger.info("✓ Subscription renewal task stopped")

    # Close trading calendar service connection pool
    if hasattr(app.state, 'trading_calendar_service') and app.state.trading_calendar_service:
        await app.state.trading_calendar_service.close()
        logger.info("✓ Trading calendar service closed")
    # Close ELOC ID service PostgreSQL connection pool
    if hasattr(app.state, 'eloc_id_service') and app.state.eloc_id_service:
        await app.state.eloc_id_service.close()
        logger.info("✓ ELOC ID service closed")
    # Close Company Lookup service PostgreSQL connection pool
    if hasattr(app.state, 'company_lookup_service') and app.state.company_lookup_service:
        await app.state.company_lookup_service.close()
        logger.info("✓ Company lookup service closed")
    # await mongo_client.close()
    # mongo_client.close_sync()

    # Stop async file logging (flush remaining logs)
    stop_async_logging()
    logger.info("✓ Shutdown complete")


app = FastAPI(
    title="ELOC Extraction Service",
    description="Extracts data from ELOC documents and sends webhook notifications",
    version="1.0.0",
    lifespan=lifespan
)


async def delayed_subscription_setup():
    """
    Setup Azure webhook subscription after app is fully started.
    Runs as a background task with a short delay to ensure routes are available.
    """
    global _renewal_task

    # Wait for app to be fully ready (routes available)
    await asyncio.sleep(3)

    webhook_url = os.getenv("AZURE_WEBHOOK_URL")
    if webhook_url:
        logger.info("Checking Azure webhook subscription...")
        try:
            subscription_ok = await create_or_renew_subscription()
            if subscription_ok:
                logger.info("✓ Azure webhook subscription active")
            else:
                logger.warning("⚠ Azure webhook subscription failed - emails won't be received")
        except Exception as e:
            logger.error(f"⚠ Subscription check failed: {e}")

        # Start background renewal task
        _renewal_task = asyncio.create_task(subscription_renewal_task())
        logger.info("✓ Subscription auto-renewal task started")
    else:
        logger.warning("⚠ AZURE_WEBHOOK_URL not set - webhook subscription skipped")


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

    # Get deduplication stats
    with cache_lock:
        dedup_cache_size = len(processed_emails_cache)

    return {
        "status": "healthy",
        "mongodb": mongo_status,
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