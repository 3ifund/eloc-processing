"""
Script to update MongoDB examples with document_type field and add Purchase Confirmation examples.
"""
import asyncio
import os
import sys
from datetime import datetime, UTC
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

async def update_examples():
    """Update existing examples and add new Purchase Confirmation examples"""
    from repositories.mongo_client import mongo_client

    # Connect to MongoDB
    await mongo_client.connect()
    db = mongo_client.db
    collection = db["purchase_notice_examples"]

    print("="*60)
    print("UPDATING DOCUMENT EXAMPLES SCHEMA")
    print("="*60)

    # Step 1: Add document_type to existing Purchase Notice examples
    print("\n1. Updating existing Purchase Notice examples with document_type field...")
    result = await collection.update_many(
        {"document_type": {"$exists": False}},
        {"$set": {"document_type": "PURCHASE_NOTICE"}}
    )
    print(f"   Updated {result.modified_count} existing examples")

    # Step 2: Add Purchase Confirmation examples
    print("\n2. Adding Purchase Confirmation examples...")

    confirmation_files = [
        r"C:\Users\Darryl Knapp\Downloads\ZSPC Tumim VWAP Purchase Confirmation #58 12.01.2025 Executed.pdf",
        r"C:\Users\Darryl Knapp\Downloads\BGL Tumim VWAP Purchase Confirmation #9 12.28.2025 countersigned.pdf"
    ]

    added_count = 0
    for filepath in confirmation_files:
        path = Path(filepath)
        if not path.exists():
            print(f"   WARNING: File not found: {filepath}")
            continue

        filename = path.name

        # Check if already exists
        existing = await collection.find_one({"filename": filename})
        if existing:
            print(f"   Skipping {filename} - already exists")
            # Update document_type if not set
            if existing.get("document_type") != "PURCHASE_CONFIRMATION":
                await collection.update_one(
                    {"filename": filename},
                    {"$set": {"document_type": "PURCHASE_CONFIRMATION"}}
                )
                print(f"   Updated document_type for {filename}")
            continue

        # Read PDF bytes
        with open(path, "rb") as f:
            pdf_bytes = f.read()

        # Insert new document
        doc = {
            "filename": filename,
            "pdf_bytes": pdf_bytes,
            "document_type": "PURCHASE_CONFIRMATION",
            "created_at": datetime.now(UTC),
            "source": "manual_upload"
        }

        await collection.insert_one(doc)
        print(f"   Added: {filename}")
        added_count += 1

    print(f"   Added {added_count} new Purchase Confirmation examples")

    # Step 3: Verify the results
    print("\n3. Verification - Current examples by type:")

    notice_count = await collection.count_documents({"document_type": "PURCHASE_NOTICE"})
    confirmation_count = await collection.count_documents({"document_type": "PURCHASE_CONFIRMATION"})
    total_count = await collection.count_documents({})

    print(f"   PURCHASE_NOTICE: {notice_count}")
    print(f"   PURCHASE_CONFIRMATION: {confirmation_count}")
    print(f"   TOTAL: {total_count}")

    # List all examples
    print("\n4. All examples:")
    cursor = collection.find({}, {"filename": 1, "document_type": 1})
    async for doc in cursor:
        print(f"   - {doc.get('filename')} [{doc.get('document_type', 'UNKNOWN')}]")

    print("\n" + "="*60)
    print("SCHEMA UPDATE COMPLETE")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(update_examples())
