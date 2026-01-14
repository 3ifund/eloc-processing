"""
Script to add a PDF document as a reference example to MongoDB.

Usage:
    python add_example.py <pdf_path> <document_type>

Example:
    python add_example.py "C:\path\to\doc.pdf" PURCHASE_CONFIRMATION
"""
import asyncio
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

async def add_example(pdf_path: str, document_type: str):
    """Add a PDF as a reference example to MongoDB"""
    from motor.motor_asyncio import AsyncIOMotorClient
    from bson import Binary

    # Validate document type
    valid_types = ["PURCHASE_NOTICE", "PURCHASE_CONFIRMATION"]
    if document_type not in valid_types:
        print(f"Error: document_type must be one of {valid_types}")
        return False

    # Read PDF file
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        print(f"Error: File not found: {pdf_path}")
        return False

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    print(f"Read {len(pdf_bytes)} bytes from {pdf_path.name}")

    # Connect to MongoDB
    mongo_uri = os.getenv("MONGODB_URI")
    if not mongo_uri:
        print("Error: MONGODB_URI not set in .env")
        return False

    client = AsyncIOMotorClient(mongo_uri)
    db = client.get_default_database()
    collection = db["purchase_notice_examples"]

    # Check if already exists
    existing = await collection.find_one({"filename": pdf_path.name})
    if existing:
        print(f"Warning: Example with filename '{pdf_path.name}' already exists")
        response = input("Overwrite? (y/n): ")
        if response.lower() != 'y':
            print("Aborted")
            return False
        await collection.delete_one({"filename": pdf_path.name})

    # Insert document
    doc = {
        "filename": pdf_path.name,
        "pdf_bytes": Binary(pdf_bytes),
        "document_type": document_type
    }

    result = await collection.insert_one(doc)
    print(f"✓ Added example: {pdf_path.name} as {document_type}")
    print(f"  MongoDB _id: {result.inserted_id}")

    # Show current counts
    notice_count = await collection.count_documents({"document_type": "PURCHASE_NOTICE"})
    confirm_count = await collection.count_documents({"document_type": "PURCHASE_CONFIRMATION"})
    print(f"\nCurrent examples: {notice_count} PURCHASE_NOTICE, {confirm_count} PURCHASE_CONFIRMATION")

    client.close()
    return True


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        print("\nDocument types: PURCHASE_NOTICE, PURCHASE_CONFIRMATION")
        sys.exit(1)

    pdf_path = sys.argv[1]
    document_type = sys.argv[2].upper()

    success = asyncio.run(add_example(pdf_path, document_type))
    sys.exit(0 if success else 1)
