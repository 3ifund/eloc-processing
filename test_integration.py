"""
Integration test for the dual document type classification in the main workflow.
Tests that PURCHASE_NOTICE and PURCHASE_CONFIRMATION are handled correctly.
"""
import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables from .env
from dotenv import load_dotenv
load_dotenv()


async def test_integration():
    """Test the integration of classifiers into main workflow"""
    import pdfplumber
    import io
    from repositories.mongo_client import mongo_client
    from services.verification.examples_repository import ExamplesRepository
    from services.verification.orchestrator import VerificationOrchestrator
    import services.verification.orchestrator as orchestrator_module
    from workflow import ELOCWorkflow

    print("=" * 70)
    print("INTEGRATION TEST: Classification in Main Workflow")
    print("=" * 70)

    # Connect to MongoDB
    print("\n1. Connecting to MongoDB...")
    await mongo_client.connect()
    db = mongo_client.db

    # Initialize examples repository
    examples_repo = ExamplesRepository(db)

    # Initialize workflow (like main.py does)
    print("\n2. Initializing ELOCWorkflow...")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    openai_key = os.getenv("OPENAI_API_KEY", "")

    workflow = ELOCWorkflow(
        anthropic_api_key=anthropic_key,
        openai_api_key=openai_key
    )

    # Initialize verification orchestrator (for extraction)
    print("\n3. Initializing Verification Orchestrator...")
    orchestrator_module.verification_orchestrator = VerificationOrchestrator(
        anthropic_api_key=anthropic_key,
        openai_api_key=openai_key,
        examples_repository=examples_repo
    )
    print("   Orchestrator initialized")

    # Load MongoDB examples into classifier
    print("\n4. Loading MongoDB examples into classifier...")
    count = await workflow.classifier.load_mongodb_examples(examples_repo)
    print(f"   Loaded {count} examples")
    print(f"   Dual mode: {workflow.classifier.is_dual_mode}")

    # Get test documents from MongoDB
    print("\n5. Loading test documents from MongoDB...")
    all_examples = await examples_repo.get_all_examples()

    # Test each document
    print("\n6. Testing classification on each document...")
    print("-" * 70)

    for example in all_examples:
        filename = example.get("filename", "unknown")
        expected_type = example.get("document_type", "UNKNOWN")
        pdf_bytes = example.get("pdf_bytes")

        print(f"\nFile: {filename}")
        print(f"Expected: {expected_type}")

        if not pdf_bytes:
            print("   ERROR: No PDF bytes found")
            continue

        # Extract text from PDF (like main.py does)
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

        # Classify using workflow's classifier
        result = workflow.classifier.classify(pdf_text)

        classification = result["final_classification"]
        confidence = result["final_confidence"]
        agreement = result["agreement"]
        votes = result["votes"]

        status = "PASS" if classification == expected_type else "FAIL"

        print(f"Result: {classification} ({confidence})")
        print(f"Agreement: {agreement}")
        print(f"Votes: {votes}")

        # Show what would happen in main.py
        if classification == "NOT_RELEVANT":
            print("Action: Would skip processing")
        elif classification == "PURCHASE_NOTICE":
            print("Action: Running extraction workflow...")

            # Test extraction
            from main import extract_purchase_notice_fields
            email_info = {
                "subject": f"VWAP Purchase Notice - {filename}",
                "body": "Please see attached Purchase Notice.",
                "from": "legal@company.com"
            }
            extract_result = await extract_purchase_notice_fields(pdf_text, email_info, f"test-{filename[:8]}")

            if extract_result.get("success"):
                print(f"  ELOC ID: {extract_result.get('eloc_id')}")
                print(f"  Company: {extract_result.get('company_symbol')} ({extract_result.get('company_name')})")
                print(f"  Fields: {extract_result.get('fields_count')}")
                print(f"  Agreement: {'PASSED' if extract_result.get('verification_passed') else 'DISAGREEMENT'}")
                print(f"  Duration: {extract_result.get('duration_ms')}ms")

                # Show key transaction fields
                all_fields = extract_result.get("all_fields", {})
                if all_fields.get("vwap_purchase_exercise_date"):
                    print(f"  Exercise Date: {all_fields.get('vwap_purchase_exercise_date')}")
                if all_fields.get("vwap_purchase_share_amount"):
                    print(f"  Shares: {all_fields.get('vwap_purchase_share_amount')}")
            else:
                print(f"  Extraction FAILED: {extract_result.get('error')}")

        elif classification == "PURCHASE_CONFIRMATION":
            print("Action: Running signature verification...")

            # Test signature verification
            from main import verify_signatures
            sig_result = await verify_signatures(pdf_text, workflow)
            print(f"  Signatures: company={sig_result.get('company_signed')}, investor={sig_result.get('investor_signed')}")
            if sig_result.get('company_signatory'):
                print(f"  Company signatory: {sig_result.get('company_signatory')}")
            if sig_result.get('investor_signatory'):
                print(f"  Investor signatory: {sig_result.get('investor_signatory')}")

        print(f"Status: [{status}]")
        print("-" * 70)

    print("\n" + "=" * 70)
    print("INTEGRATION TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_integration())
