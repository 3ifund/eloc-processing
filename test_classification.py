"""
Test script for dual document type classification.
Tests the updated classifiers with PURCHASE_NOTICE and PURCHASE_CONFIRMATION examples.
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


async def test_classification():
    """Test the classification system with both document types"""
    from repositories.mongo_client import mongo_client
    from services.verification.examples_repository import ExamplesRepository
    from classifiers import TripleClassifier, DocumentType

    print("=" * 70)
    print("DUAL DOCUMENT TYPE CLASSIFICATION TEST")
    print("=" * 70)

    # Connect to MongoDB
    print("\n1. Connecting to MongoDB...")
    await mongo_client.connect()
    db = mongo_client.db

    # Initialize examples repository
    examples_repo = ExamplesRepository(db)

    # Check example counts
    total = await examples_repo.count()
    notice_count = await examples_repo.count_by_type("PURCHASE_NOTICE")
    confirm_count = await examples_repo.count_by_type("PURCHASE_CONFIRMATION")

    print(f"   Examples in database:")
    print(f"   - PURCHASE_NOTICE: {notice_count}")
    print(f"   - PURCHASE_CONFIRMATION: {confirm_count}")
    print(f"   - TOTAL: {total}")

    if total == 0:
        print("\n   ERROR: No examples in database. Run scripts/update_examples_schema.py first.")
        return

    # Initialize classifier
    print("\n2. Initializing TripleClassifier...")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    openai_key = os.getenv("OPENAI_API_KEY", "")

    if not anthropic_key or not openai_key:
        print("   WARNING: API keys not set. LLM classifiers will fail.")
        print("   Set ANTHROPIC_API_KEY and OPENAI_API_KEY environment variables.")

    classifier = TripleClassifier(
        anthropic_api_key=anthropic_key,
        openai_api_key=openai_key
    )

    # Load MongoDB examples
    print("\n3. Loading examples from MongoDB...")
    count = await classifier.load_mongodb_examples(examples_repo)
    print(f"   Loaded {count} examples")
    print(f"   Dual mode: {classifier.is_dual_mode}")
    print(f"   Examples source: {classifier.examples_source}")

    # Test with sample texts
    print("\n4. Testing classification with sample texts...")

    # Sample Purchase Notice text
    purchase_notice_sample = """
    FORM OF VWAP PURCHASE NOTICE

    Reference is made to the Common Stock Purchase Agreement dated January 15, 2025
    between ABC Corporation (the "Company") and Tumim Stone Capital LLC (the "Investor").

    Pursuant to the Agreement, the Company hereby notifies the Investor of the following:

    1. VWAP Purchase Share Amount: 50,000 shares
    2. Pricing Period: January 20, 2025 to January 24, 2025
    3. Settlement Date: January 27, 2025

    ABC CORPORATION

    By: _________________________
    Name: John Smith
    Title: Chief Financial Officer
    Date: January 18, 2025

    AGREED AND ACCEPTED:

    TUMIM STONE CAPITAL LLC

    By: _________________________
    Name:
    Title:
    Date:
    """

    # Sample Purchase Confirmation text
    purchase_confirmation_sample = """
    FORM OF VWAP PURCHASE CONFIRMATION

    Reference is made to the Common Stock Purchase Agreement dated January 15, 2025
    between ABC Corporation (the "Company") and Tumim Stone Capital LLC (the "Investor").

    Pursuant to the Agreement, the Investor confirms the following transaction:

    1. VWAP Purchase Share Amount: 50,000 shares
    2. Pricing Period: January 20, 2025 to January 24, 2025
    3. VWAP Price: $12.45 per share
    4. Total Purchase Price: $622,500.00
    5. Settlement Date: January 27, 2025

    TUMIM STONE CAPITAL LLC

    By: /s/ Jane Doe
    Name: Jane Doe
    Title: Managing Partner
    Date: January 25, 2025

    AGREED AND ACCEPTED:

    ABC CORPORATION

    By: /s/ John Smith
    Name: John Smith
    Title: Chief Financial Officer
    Date: January 25, 2025
    """

    # Sample irrelevant document
    not_relevant_sample = """
    MEETING AGENDA

    Board of Directors Meeting
    Date: January 30, 2025

    1. Call to Order
    2. Approval of Previous Minutes
    3. Financial Report
    4. New Business
    5. Adjournment

    Prepared by Corporate Secretary
    """

    test_cases = [
        ("Purchase Notice", purchase_notice_sample, DocumentType.PURCHASE_NOTICE.value),
        ("Purchase Confirmation", purchase_confirmation_sample, DocumentType.PURCHASE_CONFIRMATION.value),
        ("Meeting Agenda (Not Relevant)", not_relevant_sample, DocumentType.NOT_RELEVANT.value),
    ]

    print("\n" + "-" * 70)

    for name, text, expected in test_cases:
        print(f"\nTest: {name}")
        print(f"Expected: {expected}")

        result = classifier.classify(text)

        classification = result["final_classification"]
        confidence = result["final_confidence"]
        agreement = result["agreement"]
        votes = result["votes"]

        status = "PASS" if classification == expected else "FAIL"
        print(f"Result: {classification} ({confidence})")
        print(f"Agreement: {agreement}")
        print(f"Votes: {votes}")

        # Show similarity scores if in dual mode
        sim_result = result.get("similarity_result", {})
        if sim_result.get("dual_mode"):
            scores = sim_result.get("scores", {})
            print(f"Similarity Scores:")
            print(f"  - Notice: {scores.get('notice_max_similarity', 0):.3f}")
            print(f"  - Confirmation: {scores.get('confirmation_max_similarity', 0):.3f}")

        print(f"Status: [{status}]")
        print("-" * 70)

    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_classification())
