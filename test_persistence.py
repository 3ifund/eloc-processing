"""
Test script for ELOC persistence services.
Tests ElocIdService, ElocDataService, and ElocStateService with real MongoDB data.
"""
import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime, UTC

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables from .env
from dotenv import load_dotenv
load_dotenv()

# PostgreSQL config (same as main.py)
PG_CONFIG = {
    'host': os.getenv('PG_HOST', '10.90.98.123'),
    'port': int(os.getenv('PG_PORT', '5432')),
    'database': os.getenv('PG_DATABASE', 'DealTerms'),
    'user': os.getenv('PG_USER', 'postgres'),
    'password': os.getenv('PG_PASSWORD', 'Drl270!!')
}


async def test_persistence():
    """Test the persistence services"""
    import pdfplumber
    import io
    from repositories.mongo_client import mongo_client
    from services.eloc_id_service import ElocIdService
    from services.eloc_data_service import ElocDataService
    from services.eloc_state_service import ElocStateService
    from services.verification.examples_repository import ExamplesRepository

    print("=" * 70)
    print("PERSISTENCE TEST: ElocIdService, ElocDataService, ElocStateService")
    print("=" * 70)

    # Connect to MongoDB
    print("\n1. Connecting to MongoDB...")
    await mongo_client.connect()
    db = mongo_client.db
    print("   [OK] MongoDB connected")

    # Initialize services
    print("\n2. Initializing services...")
    eloc_id_service = ElocIdService(db, PG_CONFIG)
    await eloc_id_service.ensure_indexes()
    print("   [OK] ElocIdService initialized")

    eloc_data_service = ElocDataService(db)
    print("   [OK] ElocDataService initialized")

    eloc_state_service = ElocStateService(db)
    print("   [OK] ElocStateService initialized")

    # Test company lookup
    print("\n3. Testing company lookup...")
    test_symbols = ["ZSPC", "BGL", "INVALID"]
    for symbol in test_symbols:
        company_info = await eloc_id_service.get_company_info(symbol)
        if company_info:
            print(f"   {symbol}: company_id={company_info.company_id}, name={company_info.company_name}")
        else:
            print(f"   {symbol}: NOT FOUND")

    # Test ELOC ID generation
    print("\n4. Testing ELOC ID generation...")
    for symbol in ["ZSPC", "BGL"]:
        try:
            current_seq = await eloc_id_service.get_current_sequence(symbol)
            print(f"   {symbol} current sequence: {current_seq}")

            eloc_id, company_id = await eloc_id_service.generate_eloc_id(symbol)
            print(f"   Generated: {eloc_id} (company_id={company_id})")
        except ValueError as e:
            print(f"   {symbol}: ERROR - {e}")

    # Load test documents from MongoDB examples
    print("\n5. Loading test documents from MongoDB...")
    examples_repo = ExamplesRepository(db)
    all_examples = await examples_repo.get_all_examples()
    print(f"   Found {len(all_examples)} example documents")

    # Test persistence with a Purchase Notice
    print("\n6. Testing persistence with Purchase Notice...")
    for example in all_examples:
        doc_type = example.get("document_type", "UNKNOWN")
        if doc_type != "PURCHASE_NOTICE":
            continue

        filename = example.get("filename", "unknown")
        pdf_bytes = example.get("pdf_bytes")

        if not pdf_bytes:
            print(f"   {filename}: No PDF bytes, skipping")
            continue

        print(f"\n   Processing: {filename}")

        # Extract text from PDF
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                text_parts = []
                for page in pdf.pages[:10]:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
                pdf_text = "\n".join(text_parts)
        except Exception as e:
            print(f"   ERROR extracting text: {e}")
            continue

        # Determine company symbol from filename
        # Filenames like "ZSPC Tumim VWAP Purchase Notice..." or "BGL Tumim..."
        # Extract the first word as the company symbol
        company_symbol = filename.split()[0].upper() if " " in filename else filename.split("_")[0].upper()
        # Validate it's a known symbol
        if company_symbol not in ["ZSPC", "BGL"]:
            print(f"   Unknown company symbol: {company_symbol}, skipping")
            continue

        # Generate ELOC ID
        try:
            eloc_id, company_id = await eloc_id_service.generate_eloc_id(company_symbol)
            print(f"   ELOC ID: {eloc_id}")
            print(f"   Company ID: {company_id}")
        except ValueError as e:
            print(f"   ERROR generating ID: {e}")
            continue

        # Build extracted fields (mock data for test)
        extracted_fields = ElocDataService.build_extracted_fields(
            company_symbol=company_symbol,
            company_name=f"Test Company {company_symbol}",
            agreement_date=None,
            company_signator="Test Signatory",
            signatory_title="CFO",
            vwap_purchase_share_amount=50000,
            vwap_purchase_exercise_date=datetime.now(UTC),
            vwap_purchase_period_start_date=datetime.now(UTC),
            vwap_purchase_period_end_date=datetime.now(UTC),
            vwap_purchase_settlement_date=datetime.now(UTC),
            aggregate_limit_available=1000000.0,
            sender_name="test@example.com",
            sender_emails=["test@example.com"],
            email_subject="Test Purchase Notice",
            email_body="Test email body",
            purchase_notice_market_data_date=datetime.now(UTC),
            confidence_scores={"company_symbol": 0.98, "company_name": 0.95}
        )

        # Test eloc_data persistence
        try:
            await eloc_data_service.create_eloc_data(
                eloc_id=eloc_id,
                extracted_fields=extracted_fields,
                pdf_bytes=pdf_bytes,
                pdf_filename=filename,
                purchase_notice_market_data_date=datetime.now(UTC),
                received_at=datetime.now(UTC)
            )
            print(f"   [OK] eloc_data created")
        except ValueError as e:
            print(f"   SKIP eloc_data (already exists): {e}")

        # Test eloc_state persistence
        try:
            await eloc_state_service.create_eloc_state(
                eloc_id=eloc_id,
                company_id=company_id,
                workflow_step="VerificationOfExtractedFields",
                status="Pending",
                include=True
            )
            print(f"   [OK] eloc_state created")
        except ValueError as e:
            print(f"   SKIP eloc_state (already exists): {e}")

        # Verify persistence
        print("\n   Verifying persistence...")
        eloc_data = await eloc_data_service.get_eloc_data(eloc_id)
        if eloc_data:
            print(f"   [OK] eloc_data retrieved")
            print(f"     - received_at: {eloc_data.get('received_at')}")
            print(f"     - market_data_date: {eloc_data.get('purchase_notice_market_data_date')}")
            ef = eloc_data.get("extracted_fields", {})
            print(f"     - company_symbol: {ef.get('company_symbol', {}).get('value')}")
            print(f"     - share_amount: {ef.get('vwap_purchase_share_amount', {}).get('value')}")
        else:
            print(f"   ERROR: eloc_data not found!")

        eloc_state = await eloc_state_service.get_eloc_state(eloc_id)
        if eloc_state:
            print(f"   [OK] eloc_state retrieved")
            print(f"     - company_id: {eloc_state.get('company_id')}")
            print(f"     - workflow_step: {eloc_state.get('workflow_step')}")
            print(f"     - status: {eloc_state.get('status')}")
            print(f"     - include: {eloc_state.get('include')}")
        else:
            print(f"   ERROR: eloc_state not found!")

        # Only test one document
        break

    # Show current state statistics
    print("\n7. Current state statistics...")
    stats = await eloc_state_service.get_statistics()
    print(f"   By status: {stats.get('by_status', {})}")
    print(f"   By workflow_step: {stats.get('by_workflow_step', {})}")

    # Cleanup
    print("\n8. Cleaning up...")
    await eloc_id_service.close()
    print("   [OK] ElocIdService closed")

    print("\n" + "=" * 70)
    print("PERSISTENCE TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_persistence())
