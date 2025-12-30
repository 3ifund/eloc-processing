"""
Test classification with real PDF documents from MongoDB.
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


async def test_real_pdfs():
    """Test classification with actual PDFs from MongoDB"""
    import pdfplumber
    import io
    from repositories.mongo_client import mongo_client
    from services.verification.examples_repository import ExamplesRepository
    from classifiers import TripleClassifier, DocumentType

    print("=" * 70)
    print("REAL PDF CLASSIFICATION TEST")
    print("=" * 70)

    # Connect to MongoDB
    print("\n1. Connecting to MongoDB...")
    await mongo_client.connect()
    db = mongo_client.db

    # Initialize examples repository
    examples_repo = ExamplesRepository(db)

    # Initialize classifier
    print("\n2. Initializing TripleClassifier...")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    openai_key = os.getenv("OPENAI_API_KEY", "")

    classifier = TripleClassifier(
        anthropic_api_key=anthropic_key,
        openai_api_key=openai_key
    )

    # Load MongoDB examples
    print("\n3. Loading examples from MongoDB...")
    count = await classifier.load_mongodb_examples(examples_repo)
    print(f"   Loaded {count} examples (dual_mode={classifier.is_dual_mode})")

    # Get all examples from MongoDB
    print("\n4. Loading PDF documents for testing...")
    all_examples = await examples_repo.get_all_examples()

    print(f"   Found {len(all_examples)} documents:")
    for ex in all_examples:
        print(f"   - {ex.get('filename')} [{ex.get('document_type', 'UNKNOWN')}]")

    # Test each PDF
    print("\n5. Testing classification on each PDF...")
    print("-" * 70)

    results = []
    for example in all_examples:
        filename = example.get("filename", "unknown")
        expected_type = example.get("document_type", "UNKNOWN")
        pdf_bytes = example.get("pdf_bytes")

        print(f"\nFile: {filename}")
        print(f"Expected: {expected_type}")

        if not pdf_bytes:
            print("   ERROR: No PDF bytes found")
            continue

        # Extract text from PDF
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                text_parts = []
                for page in pdf.pages[:10]:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
                text = "\n".join(text_parts)
                print(f"   Extracted {len(text)} characters from {len(pdf.pages)} pages")
        except Exception as e:
            print(f"   ERROR extracting text: {e}")
            continue

        # Classify
        result = classifier.classify(text)

        classification = result["final_classification"]
        confidence = result["final_confidence"]
        agreement = result["agreement"]
        votes = result["votes"]

        status = "PASS" if classification == expected_type else "FAIL"

        print(f"Result: {classification} ({confidence})")
        print(f"Agreement: {agreement}")
        print(f"Votes: {votes}")

        # Show similarity scores
        sim_result = result.get("similarity_result", {})
        if sim_result.get("dual_mode"):
            scores = sim_result.get("scores", {})
            print(f"Similarity: notice={scores.get('notice_max_similarity', 0):.3f}, confirm={scores.get('confirmation_max_similarity', 0):.3f}")

        # Show LLM reasoning
        claude_reasoning = result.get("claude_result", {}).get("reasoning", "")
        openai_reasoning = result.get("openai_result", {}).get("reasoning", "")
        if claude_reasoning:
            print(f"Claude: {claude_reasoning[:100]}...")
        if openai_reasoning:
            print(f"OpenAI: {openai_reasoning[:100]}...")

        print(f"Status: [{status}]")
        print("-" * 70)

        results.append({
            "filename": filename,
            "expected": expected_type,
            "actual": classification,
            "status": status
        })

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")

    for r in results:
        print(f"[{r['status']}] {r['filename']}: expected={r['expected']}, actual={r['actual']}")

    print(f"\nTotal: {passed} passed, {failed} failed out of {len(results)}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_real_pdfs())
