"""
Test Hugging Face NER on ZSPC Purchase Notice
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()


async def test_ner():
    import pdfplumber
    import io
    from transformers import pipeline
    from repositories.mongo_client import mongo_client
    from services.verification.examples_repository import ExamplesRepository

    print("=" * 70)
    print("NER TEST: Hugging Face BERT on ZSPC Purchase Notice")
    print("=" * 70)

    # Connect to MongoDB and get the document
    print("\n1. Loading document from MongoDB...")
    await mongo_client.connect()
    db = mongo_client.db
    examples_repo = ExamplesRepository(db)

    all_examples = await examples_repo.get_all_examples()
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
    print("\n2. Extracting text from PDF...")
    pdf_bytes = zspc_notice.get("pdf_bytes")
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text_parts = []
        for page in pdf.pages[:3]:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
        pdf_text = "\n".join(text_parts)

    print(f"   Extracted {len(pdf_text)} characters")

    # Load NER model
    print("\n3. Loading NER model (dslim/bert-base-NER)...")
    ner = pipeline(
        "ner",
        model="dslim/bert-base-NER",
        aggregation_strategy="simple"
    )
    print("   Model loaded")

    # Run NER
    print("\n4. Running NER extraction...")
    entities = ner(pdf_text)
    print(f"   Found {len(entities)} entities")

    # Group by type
    by_type = {}
    for ent in entities:
        label = ent["entity_group"]
        if label not in by_type:
            by_type[label] = []
        by_type[label].append({
            "text": ent["word"],
            "score": ent["score"],
            "start": ent["start"],
            "end": ent["end"]
        })

    # Display results
    print("\n" + "=" * 70)
    print("NER RESULTS")
    print("=" * 70)

    for label in sorted(by_type.keys()):
        entities_list = by_type[label]
        print(f"\n{label} ({len(entities_list)} found):")
        print("-" * 50)

        # Sort by score descending, show top 10
        sorted_ents = sorted(entities_list, key=lambda x: x["score"], reverse=True)
        for ent in sorted_ents[:15]:
            score_bar = "#" * int(ent["score"] * 20)
            print(f"  {ent['score']:.3f} [{score_bar:<20}] {ent['text']}")

    # Compare with what we expect to find
    print("\n" + "=" * 70)
    print("EXPECTED FIELDS vs NER")
    print("=" * 70)

    expected = {
        "Company": "zSpace, Inc.",
        "Signatory": "Erick DeOliveira",
        "Title": "Chief Financial Officer",
        "Investor": "Tumim Stone Capital LLC",
        "Manager": "3i Management LLC"
    }

    print("\nSearching for expected values in NER output...")
    for field, expected_value in expected.items():
        found = False
        best_match = None
        best_score = 0

        for label, ents in by_type.items():
            for ent in ents:
                # Check if expected value is in NER output or vice versa
                if (expected_value.lower() in ent["text"].lower() or
                    ent["text"].lower() in expected_value.lower()):
                    if ent["score"] > best_score:
                        found = True
                        best_match = ent["text"]
                        best_score = ent["score"]

        status = "[FOUND]" if found else "[NOT FOUND]"
        if found:
            print(f"  {status} {field}: '{expected_value}'")
            print(f"           NER: '{best_match}' (score: {best_score:.3f})")
        else:
            print(f"  {status} {field}: '{expected_value}'")

    # Test with OntoNotes model (has DATE, MONEY)
    print("\n" + "=" * 70)
    print("TESTING WITH OntoNotes MODEL (includes DATE, MONEY)")
    print("=" * 70)

    print("\nLoading tner/roberta-large-ontonotes5...")
    try:
        ner_onto = pipeline(
            "ner",
            model="tner/roberta-large-ontonotes5",
            aggregation_strategy="simple"
        )
        print("Model loaded")

        entities_onto = ner_onto(pdf_text[:5000])  # Limit text for speed

        by_type_onto = {}
        for ent in entities_onto:
            label = ent["entity_group"]
            if label not in by_type_onto:
                by_type_onto[label] = []
            by_type_onto[label].append({
                "text": ent["word"],
                "score": ent["score"]
            })

        for label in sorted(by_type_onto.keys()):
            entities_list = by_type_onto[label]
            print(f"\n{label} ({len(entities_list)} found):")
            sorted_ents = sorted(entities_list, key=lambda x: x["score"], reverse=True)
            for ent in sorted_ents[:10]:
                print(f"  {ent['score']:.3f} - {ent['text']}")

    except Exception as e:
        print(f"OntoNotes model failed: {e}")

    print("\n" + "=" * 70)
    print("NER TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_ner())
