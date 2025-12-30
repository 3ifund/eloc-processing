"""
Test NER-based confidence calculation on real ELOC documents.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()


async def test_ner_confidence():
    import pdfplumber
    import io
    from repositories.mongo_client import mongo_client
    from services.verification.examples_repository import ExamplesRepository
    from services.verification.orchestrator import VerificationOrchestrator

    print("=" * 70)
    print("NER CONFIDENCE TEST")
    print("=" * 70)
    print("\nConfidence Formula:")
    print("  If LLMs agree:    (100 + NER) / 2")
    print("  If LLMs disagree: (0 + NER) / 2")
    print("  Where NER = 100 if validated, else 0")
    print()
    print("Possible scores:")
    print("  100% = LLMs agree + NER validates")
    print("   50% = LLMs agree + NER doesn't validate (or vice versa)")
    print("    0% = LLMs disagree + NER doesn't validate")
    print("=" * 70)

    # Connect to MongoDB
    print("\n1. Connecting to MongoDB...")
    await mongo_client.connect()
    db = mongo_client.db

    # Initialize orchestrator
    print("\n2. Initializing verification orchestrator...")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    openai_key = os.getenv("OPENAI_API_KEY", "")

    examples_repo = ExamplesRepository(db)
    orchestrator = VerificationOrchestrator(
        anthropic_api_key=anthropic_key,
        openai_api_key=openai_key,
        examples_repository=examples_repo
    )
    print("   Orchestrator ready")

    # Load test documents
    print("\n3. Loading test documents...")
    all_examples = await examples_repo.get_all_examples()

    # Find ZSPC Purchase Notice
    zspc_notice = None
    for ex in all_examples:
        if "ZSPC" in ex.get("filename", "") and "Notice" in ex.get("filename", ""):
            zspc_notice = ex
            break

    if not zspc_notice:
        print("ERROR: ZSPC Purchase Notice not found")
        return

    print(f"   Found: {zspc_notice['filename']}")

    # Extract text from PDF
    print("\n4. Extracting text from PDF...")
    pdf_bytes = zspc_notice.get("pdf_bytes")
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text_parts = []
        for page in pdf.pages[:3]:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
        pdf_text = "\n".join(text_parts)
    print(f"   Extracted {len(pdf_text)} characters")

    # Run verification with NER
    print("\n5. Running dual LLM extraction with NER validation...")
    print("   (This will take ~15-20 seconds)")

    result = await orchestrator.verify(
        document_text=pdf_text,
        email_subject="Test VWAP Purchase Notice",
        email_body="Please see attached.",
        email_sender="legal@company.com"
    )

    # Display results
    print("\n" + "=" * 70)
    print("EXTRACTION RESULTS WITH CONFIDENCE")
    print("=" * 70)

    print(f"\nLLM Agreement: {'PASSED' if result.passed else 'DISAGREEMENT'}")
    print(f"NER Applied: {result.ner_applied}")

    # Get field details
    field_details = result.get_field_details()

    # Group by confidence level
    high_conf = []  # 100%
    medium_conf = []  # 50%
    low_conf = []  # 0%

    for field_name, details in field_details.items():
        conf = details["confidence"]
        if conf == 100:
            high_conf.append((field_name, details))
        elif conf == 50:
            medium_conf.append((field_name, details))
        else:
            low_conf.append((field_name, details))

    print(f"\n{'Field':<35} {'Value':<25} {'Conf':>6} {'LLM':>5} {'NER':>5}")
    print("-" * 80)

    # High confidence (100%)
    if high_conf:
        print("\n[100%] LLMs AGREE + NER VALIDATED:")
        for field_name, details in high_conf:
            value = str(details["value"])[:24] if details["value"] else "None"
            llm = "Yes" if details["llm_agree"] else "No"
            ner = "Yes" if details["ner_validated"] else "No"
            print(f"  {field_name:<33} {value:<25} {details['confidence']:>5.0f}% {llm:>5} {ner:>5}")

    # Medium confidence (50%)
    if medium_conf:
        print("\n[50%] PARTIAL VALIDATION:")
        for field_name, details in medium_conf:
            value = str(details["value"])[:24] if details["value"] else "None"
            llm = "Yes" if details["llm_agree"] else "No"
            ner = "Yes" if details["ner_validated"] else "No"
            reason = ""
            if details["llm_agree"] and not details["ner_validated"]:
                reason = "(LLM agree, no NER type)"
            elif not details["llm_agree"] and details["ner_validated"]:
                reason = "(LLM disagree, NER found)"
            print(f"  {field_name:<33} {value:<25} {details['confidence']:>5.0f}% {llm:>5} {ner:>5} {reason}")

    # Low confidence (0%)
    if low_conf:
        print("\n[0%] LLMs DISAGREE + NER NOT VALIDATED:")
        for field_name, details in low_conf:
            value = str(details["value"])[:24] if details["value"] else "None"
            llm = "Yes" if details["llm_agree"] else "No"
            ner = "Yes" if details["ner_validated"] else "No"
            print(f"  {field_name:<33} {value:<25} {details['confidence']:>5.0f}% {llm:>5} {ner:>5}")
            if not details["llm_agree"]:
                print(f"    Claude: {details['claude_value']}")
                print(f"    OpenAI: {details['openai_value']}")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Total fields: {len(field_details)}")
    print(f"  100% confidence: {len(high_conf)} fields")
    print(f"   50% confidence: {len(medium_conf)} fields")
    print(f"    0% confidence: {len(low_conf)} fields")

    avg_confidence = sum(d["confidence"] for d in field_details.values()) / len(field_details)
    print(f"\n  Average confidence: {avg_confidence:.1f}%")

    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_ner_confidence())
