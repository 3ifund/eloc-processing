"""
Test script for the document classifier with MongoDB examples.
Tests similarity-based classification using purchase_notice_examples collection.
"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

# Sample ELOC Purchase Notice text (should be classified as ELOC)
SAMPLE_ELOC_TEXT = """
VWAP PURCHASE NOTICE

Date: December 24, 2025

To: B. Riley Principal Capital II, LLC
    1400 Civic Drive, Suite 200
    Walnut Creek, California 94596

From: zSpace, Inc.
      444 Castro Street, Suite 1200
      Mountain View, CA 94041

Re: Common Stock Purchase Agreement dated September 20, 2024

Dear Sir or Madam:

Reference is made to that certain Common Stock Purchase Agreement, dated as of
September 20, 2024 (the "Agreement"), by and between zSpace, Inc., a Delaware
corporation (the "Company"), and B. Riley Principal Capital II, LLC (the "Investor").

Pursuant to Section 2(a) of the Agreement, the Company hereby delivers this VWAP
Purchase Notice to notify the Investor that the Company elects to exercise its
right to require the Investor to purchase shares of Common Stock.

VWAP PURCHASE DETAILS:

1. VWAP Purchase Share Amount: 150,000 shares of Common Stock

2. VWAP Purchase Exercise Date (Notice Date): December 24, 2025

3. VWAP Purchase Period:
   - Start Date: December 26, 2025
   - End Date: December 30, 2025

4. VWAP Purchase Settlement Date: December 31, 2025

5. Aggregate Limit Available: $4,250,000.00

The Company hereby represents and warrants to the Investor that each of the
conditions set forth in Section 7(b) of the Agreement has been satisfied as of
the date hereof.

Very truly yours,

ZSPACE, INC.

By: ___________________________
Name: Paul Shortino
Title: Chief Financial Officer

Date: December 24, 2025
"""

# Sample NON-ELOC text (general corporate email)
SAMPLE_NON_ELOC_TEXT = """
Subject: Q4 2025 Board Meeting Agenda

Dear Board Members,

Please find below the agenda for our upcoming Q4 2025 board meeting scheduled
for January 15, 2026 at 2:00 PM EST.

AGENDA:

1. Call to Order
2. Approval of Previous Meeting Minutes
3. CEO Report - Business Update
4. CFO Report - Financial Overview
   - Q4 Revenue Summary
   - Operating Expenses
   - Cash Position
5. Strategic Initiatives Update
6. Committee Reports
   - Audit Committee
   - Compensation Committee
7. New Business
8. Executive Session
9. Adjournment

Please confirm your attendance by January 10, 2026.

Best regards,
Corporate Secretary
"""

# Sample invoice text (another non-ELOC type)
SAMPLE_INVOICE_TEXT = """
INVOICE

Invoice Number: INV-2025-12345
Date: December 20, 2025

Bill To:
ABC Corporation
123 Business Avenue
New York, NY 10001

Description                          Qty    Unit Price    Amount
----------------------------------------------------------------
Professional Services - December     80 hrs    $150.00    $12,000.00
Software License (Annual)            1         $5,000.00  $5,000.00
Cloud Hosting Services               1         $2,500.00  $2,500.00
----------------------------------------------------------------
                                              Subtotal:  $19,500.00
                                              Tax (8%):  $1,560.00
                                              TOTAL:     $21,060.00

Payment Terms: Net 30
Due Date: January 19, 2026

Please remit payment to:
Account Name: XYZ Services Inc
Bank: First National Bank
Account: 1234567890
Routing: 021000021

Thank you for your business!
"""


async def test_classifier_with_mongodb(mongo_client, examples_repo):
    """Test the classifier with MongoDB examples loaded"""
    print("\n" + "=" * 60)
    print("Testing TripleClassifier with MongoDB Examples")
    print("=" * 60)

    from classifiers import TripleClassifier

    example_count = await examples_repo.count()
    print(f"\n1. Found {example_count} examples in purchase_notice_examples collection")

    # Initialize classifier
    print("\n2. Initializing TripleClassifier (Similarity + Claude + OpenAI)...")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    if not anthropic_key:
        print("   ERROR: ANTHROPIC_API_KEY not set")
        return
    if not openai_key:
        print("   ERROR: OPENAI_API_KEY not set")
        return

    classifier = TripleClassifier(
        anthropic_api_key=anthropic_key,
        openai_api_key=openai_key,
        references_dir="references"
    )
    print(f"   Initial examples source: {classifier.examples_source}")

    # Load MongoDB examples
    print("\n3. Loading MongoDB examples into classifier...")
    loaded_count = await classifier.load_mongodb_examples(examples_repo)
    print(f"   Loaded {loaded_count} examples")
    print(f"   Examples source now: {classifier.examples_source}")

    # Test classifications
    print("\n" + "=" * 60)
    print("CLASSIFICATION TESTS")
    print("=" * 60)

    # Test 1: ELOC document (should be classified as ELOC)
    print("\n--- Test 1: Sample ELOC Purchase Notice ---")
    result1 = classifier.classify(SAMPLE_ELOC_TEXT)
    print_classification_result(result1, "ELOC")

    # Test 2: Board meeting email (should be NOT_ELOC)
    print("\n--- Test 2: Board Meeting Email (Non-ELOC) ---")
    result2 = classifier.classify(SAMPLE_NON_ELOC_TEXT)
    print_classification_result(result2, "NOT_ELOC")

    # Test 3: Invoice (should be NOT_ELOC)
    print("\n--- Test 3: Invoice Document (Non-ELOC) ---")
    result3 = classifier.classify(SAMPLE_INVOICE_TEXT)
    print_classification_result(result3, "NOT_ELOC")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    tests = [
        ("ELOC Purchase Notice", result1, "ELOC"),
        ("Board Meeting Email", result2, "NOT_ELOC"),
        ("Invoice Document", result3, "NOT_ELOC"),
    ]

    passed = 0
    for name, result, expected in tests:
        actual = result.get("final_classification") or result.get("classification")
        status = "PASS" if actual == expected else "FAIL"
        if actual == expected:
            passed += 1
        print(f"  {status}: {name} - Expected {expected}, Got {actual}")

    print(f"\nResults: {passed}/{len(tests)} tests passed")


def print_classification_result(result: dict, expected: str):
    """Print classification result in readable format"""
    # Get classification from either triple/dual or single classifier format
    classification = result.get("final_classification") or result.get("classification")
    confidence = result.get("final_confidence") or result.get("confidence")
    method = result.get("method", "unknown")
    agreement = result.get("agreement", "n/a")

    print(f"  Classification: {classification}")
    print(f"  Confidence: {confidence}")
    print(f"  Agreement: {agreement}")
    print(f"  Method: {method}")
    print(f"  Expected: {expected}")

    # Show vote counts if available
    if result.get("votes"):
        votes = result["votes"]
        print(f"  Votes: ELOC={votes['eloc']}, NOT_ELOC={votes['not_eloc']}, Total={votes['total']}")

    # Show similarity scores if available
    sim_result = result.get("similarity_result", result)
    if "scores" in sim_result:
        scores = sim_result["scores"]
        print(f"  Similarity Scores:")
        print(f"    - Max: {scores.get('max_similarity', 0):.3f}")
        print(f"    - Avg: {scores.get('avg_similarity', 0):.3f}")
        print(f"    - Top 3 Avg: {scores.get('top_3_avg', 0):.3f}")

    # Show Claude result if used
    if result.get("claude_result"):
        claude = result["claude_result"]
        print(f"  Claude Result:")
        print(f"    - Classification: {claude.get('classification')}")
        print(f"    - Confidence: {claude.get('confidence')}")
        if claude.get("reasoning"):
            print(f"    - Reasoning: {claude.get('reasoning')[:80]}...")

    # Show OpenAI result if used
    if result.get("openai_result"):
        openai = result["openai_result"]
        print(f"  OpenAI Result:")
        print(f"    - Classification: {openai.get('classification')}")
        print(f"    - Confidence: {openai.get('confidence')}")
        if openai.get("reasoning"):
            print(f"    - Reasoning: {openai.get('reasoning')[:80]}...")


async def test_similarity_only(mongo_client, examples_repo):
    """Test just the similarity classifier (no Claude API calls)"""
    print("\n" + "=" * 60)
    print("Testing Similarity Classifier Only (No API Calls)")
    print("=" * 60)

    from classifiers import SimilarityClassifier

    print("\n1. Initializing SimilarityClassifier...")
    classifier = SimilarityClassifier(references_dir="references")

    if not classifier.available:
        print("   ERROR: SimilarityClassifier not available (missing sentence-transformers)")
        return

    print(f"   Classifier available: {classifier.available}")
    print(f"   Initial examples source: {classifier.examples_source}")

    # Load from MongoDB
    print("\n2. Loading MongoDB examples...")
    loaded = await classifier.load_mongodb_examples(examples_repo)
    print(f"   Loaded {loaded} examples")
    print(f"   Examples source: {classifier.examples_source}")

    # Test classifications
    print("\n" + "-" * 40)
    print("Classifying sample documents...")
    print("-" * 40)

    # Test ELOC
    print("\n[ELOC Purchase Notice]")
    result1 = classifier.classify(SAMPLE_ELOC_TEXT)
    print(f"  Classification: {result1['classification']}")
    print(f"  Confidence: {result1['confidence']}")
    if "scores" in result1:
        print(f"  Max Similarity: {result1['scores']['max_similarity']:.3f}")

    # Test non-ELOC
    print("\n[Board Meeting Email]")
    result2 = classifier.classify(SAMPLE_NON_ELOC_TEXT)
    print(f"  Classification: {result2['classification']}")
    print(f"  Confidence: {result2['confidence']}")
    if "scores" in result2:
        print(f"  Max Similarity: {result2['scores']['max_similarity']:.3f}")

    print("\n[Invoice Document]")
    result3 = classifier.classify(SAMPLE_INVOICE_TEXT)
    print(f"  Classification: {result3['classification']}")
    print(f"  Confidence: {result3['confidence']}")
    if "scores" in result3:
        print(f"  Max Similarity: {result3['scores']['max_similarity']:.3f}")


async def main():
    """Run classifier tests"""
    print("\n" + "#" * 60)
    print("# ELOC Classifier Test Suite")
    print("#" * 60)

    # Connect to MongoDB once
    from repositories.mongo_client import mongo_client
    from services.verification.examples_repository import ExamplesRepository

    print("\nConnecting to MongoDB...")
    await mongo_client.connect()
    print("MongoDB connected")

    examples_repo = ExamplesRepository(mongo_client.db)

    try:
        # Test similarity classifier alone first (faster, no API costs)
        await test_similarity_only(mongo_client, examples_repo)

        # Test full dual classifier (includes Claude API calls)
        print("\n\n")
        await test_classifier_with_mongodb(mongo_client, examples_repo)

    finally:
        # Close MongoDB connection
        await mongo_client.close()
        print("\nMongoDB connection closed")

    print("\n" + "#" * 60)
    print("# Tests Complete")
    print("#" * 60)


if __name__ == "__main__":
    asyncio.run(main())
