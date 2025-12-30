"""
Test script to simulate email processing for dashboard testing.
Tests both PURCHASE_NOTICE and PURCHASE_CONFIRMATION document types.
"""
import asyncio
import uuid
from datetime import datetime, UTC

async def simulate_purchase_notice():
    """Simulate processing a Purchase Notice through the workflow"""
    from services.processing_tracker import ProcessingTracker
    from services.structured_logger import StructuredLogger, get_logger
    from repositories.mongo_client import mongo_client
    from routes.dashboard import broadcast_event

    # Connect to MongoDB
    await mongo_client.connect()

    # Initialize services
    tracker = ProcessingTracker(mongo_client.db)
    await tracker.ensure_indexes()

    logger = StructuredLogger(log_dir="logs", console_output=True)
    StructuredLogger.set_sse_broadcast(broadcast_event)

    # Generate test email ID
    email_id = f"notice-{uuid.uuid4().hex[:8]}"

    print(f"\n{'='*60}")
    print(f"Simulating PURCHASE NOTICE: {email_id}")
    print(f"{'='*60}\n")

    # Step 1: Email received
    print("Step 1: Email received")
    await tracker.start_tracking(
        email_id=email_id,
        internet_message_id=f"<{email_id}@test.local>",
        subject="VWAP Purchase Notice - Acme Corp #42",
        sender="legal@acme.com",
        recipients=["investor@fund.com"],
        received_at=datetime.now(UTC),
        has_attachments=True,
        attachment_count=1
    )
    logger.email_received(
        email_id=email_id,
        subject="VWAP Purchase Notice - Acme Corp #42",
        sender="legal@acme.com",
        has_attachments=True,
        attachment_count=1
    )
    await asyncio.sleep(0.5)

    # Step 2: Classification
    print("Step 2: Starting classification")
    await tracker.start_classification(email_id)
    logger.classification_start(email_id, "purchase_notice.pdf")
    await asyncio.sleep(1)

    # Step 3: Classification result - PURCHASE_NOTICE
    print("Step 3: Classification complete -> PURCHASE_NOTICE")
    votes = {
        "similarity": "PURCHASE_NOTICE",
        "claude": "PURCHASE_NOTICE",
        "openai": "PURCHASE_NOTICE"
    }
    await tracker.set_classification_result(
        email_id=email_id,
        result="PURCHASE_NOTICE",
        votes=votes,
        agreement="unanimous",
        confidence="HIGH",
        similarity_score=0.91
    )
    await tracker.set_document_type(email_id, "PURCHASE_NOTICE")
    logger.classification_result(
        email_id=email_id,
        result="PURCHASE_NOTICE",
        votes=votes,
        agreement="unanimous",
        confidence="HIGH",
        similarity_score=0.91,
        duration_ms=1850
    )
    await asyncio.sleep(0.5)

    # Step 4: Extraction (for Purchase Notices)
    print("Step 4: Starting extraction")
    await tracker.start_extraction(email_id)
    logger.extraction_start(email_id)
    await asyncio.sleep(1)

    # Step 5: Extraction result
    print("Step 5: Extraction complete")
    eloc_id = f"ELOC-ACME-{datetime.now().strftime('%Y%m%d')}-042"
    await tracker.set_extraction_result(
        email_id=email_id,
        eloc_id=eloc_id,
        company_symbol="ACME",
        company_name="Acme Corporation",
        fields_extracted=18,
        market_data_date=datetime.now(UTC)
    )
    logger.extraction_result(
        email_id=email_id,
        eloc_id=eloc_id,
        company_symbol="ACME",
        company_name="Acme Corporation",
        fields_count=18,
        duration_ms=2100
    )
    await asyncio.sleep(0.5)

    # Step 6: Complete
    print("Step 6: Processing complete")
    await tracker.mark_completed(email_id)
    logger.processing_complete(email_id, eloc_id, total_duration_ms=5500)

    print(f"Purchase Notice processed: {eloc_id}")
    return email_id


async def simulate_purchase_confirmation():
    """Simulate processing a Purchase Confirmation through the workflow"""
    from services.processing_tracker import ProcessingTracker
    from services.structured_logger import StructuredLogger, get_logger
    from repositories.mongo_client import mongo_client
    from routes.dashboard import broadcast_event

    # Connect to MongoDB (will reuse existing connection)
    await mongo_client.connect()

    # Initialize services
    tracker = ProcessingTracker(mongo_client.db)

    logger = StructuredLogger(log_dir="logs", console_output=True)
    StructuredLogger.set_sse_broadcast(broadcast_event)

    # Generate test email ID
    email_id = f"confirm-{uuid.uuid4().hex[:8]}"

    print(f"\n{'='*60}")
    print(f"Simulating PURCHASE CONFIRMATION: {email_id}")
    print(f"{'='*60}\n")

    # Step 1: Email received
    print("Step 1: Email received")
    await tracker.start_tracking(
        email_id=email_id,
        internet_message_id=f"<{email_id}@test.local>",
        subject="RE: VWAP Purchase Notice - Acme Corp #42 [COUNTERSIGNED]",
        sender="investor@fund.com",
        recipients=["legal@acme.com"],
        received_at=datetime.now(UTC),
        has_attachments=True,
        attachment_count=1
    )
    logger.email_received(
        email_id=email_id,
        subject="RE: VWAP Purchase Notice - Acme Corp #42 [COUNTERSIGNED]",
        sender="investor@fund.com",
        has_attachments=True,
        attachment_count=1
    )
    await asyncio.sleep(0.5)

    # Step 2: Classification
    print("Step 2: Starting classification")
    await tracker.start_classification(email_id)
    logger.classification_start(email_id, "countersigned_notice.pdf")
    await asyncio.sleep(1)

    # Step 3: Classification result - PURCHASE_CONFIRMATION
    print("Step 3: Classification complete -> PURCHASE_CONFIRMATION")
    votes = {
        "similarity": "PURCHASE_NOTICE",  # Similarity sees similar structure
        "claude": "PURCHASE_CONFIRMATION",
        "openai": "PURCHASE_CONFIRMATION"
    }
    await tracker.set_classification_result(
        email_id=email_id,
        result="PURCHASE_CONFIRMATION",
        votes=votes,
        agreement="majority",
        confidence="HIGH",
        similarity_score=0.88
    )
    await tracker.set_document_type(email_id, "PURCHASE_CONFIRMATION")
    logger.classification_result(
        email_id=email_id,
        result="PURCHASE_CONFIRMATION",
        votes=votes,
        agreement="majority",
        confidence="HIGH",
        similarity_score=0.88,
        duration_ms=1920
    )
    await asyncio.sleep(0.5)

    # Step 4: Signature Verification (for Purchase Confirmations)
    print("Step 4: Starting signature verification")
    await tracker.start_signature_verification(email_id)
    await asyncio.sleep(1)

    # Step 5: Signature verification result
    print("Step 5: Signature verification complete")
    await tracker.set_signature_verification_result(
        email_id=email_id,
        company_signed=True,
        investor_signed=True,
        company_signatory="John Smith, CFO",
        investor_signatory="Jane Doe, Managing Partner",
        verification_notes="Both signatures verified, dated 2025-12-30"
    )
    await asyncio.sleep(0.5)

    # Step 6: Complete
    print("Step 6: Processing complete")
    await tracker.mark_completed(email_id)
    logger.processing_complete(email_id, None, total_duration_ms=4200)

    print(f"Purchase Confirmation processed: {email_id}")
    return email_id


async def main():
    """Run both simulations"""
    print("\n" + "="*70)
    print("DOCUMENT PROCESSING SIMULATION")
    print("="*70)

    # Simulate a Purchase Notice
    notice_id = await simulate_purchase_notice()

    await asyncio.sleep(1)

    # Simulate a Purchase Confirmation
    confirm_id = await simulate_purchase_confirmation()

    print(f"\n{'='*70}")
    print("SIMULATION COMPLETE!")
    print(f"{'='*70}")
    print(f"Purchase Notice ID: {notice_id}")
    print(f"Purchase Confirmation ID: {confirm_id}")
    print(f"{'='*70}\n")

    # Give time for SSE to broadcast
    await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
