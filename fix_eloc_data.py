"""
Fix eloc_data documents:
1. Show current state of all documents
2. Option to remove confirmation from a specific document
3. Option to backfill company_id

Usage:
    python fix_eloc_data.py                    # Show all documents
    python fix_eloc_data.py --remove-confirm CAPS-00000010  # Remove confirmation from doc
    python fix_eloc_data.py --backfill-company-id           # Backfill company_id for all docs
"""
import asyncio
import sys
import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()


async def show_all_docs():
    mongo_uri = os.getenv('MONGODB_CONNECTION_STRING')
    db_name = os.getenv('MONGODB_DATABASE', 'position_management')
    client = AsyncIOMotorClient(mongo_uri)
    db = client[db_name]

    cursor = db['eloc_data'].find().sort('created_at', -1).limit(20)
    docs = await cursor.to_list(length=20)

    print(f"\n{'='*100}")
    print(f"ELOC_DATA DOCUMENTS ({len(docs)} found)")
    print(f"{'='*100}")
    print(f"{'eloc_id':<20} {'company_id':<12} {'shares':<10} {'has_confirm':<12} {'company_name'}")
    print(f"{'-'*100}")

    for doc in docs:
        extracted = doc.get('extracted_fields', {})
        eloc_id = doc.get('eloc_id', 'N/A')
        company_id = doc.get('company_id', 'NULL')
        shares = extracted.get('vwap_purchase_share_amount', {}).get('value', 'N/A')
        has_confirm = 'YES' if doc.get('countersigned_purchase_confirmation_bytes') else 'NO'
        company_name = extracted.get('company_name', {}).get('value', 'N/A')[:40]

        print(f"{eloc_id:<20} {str(company_id):<12} {str(shares):<10} {has_confirm:<12} {company_name}")

    client.close()


async def remove_confirmation(eloc_id: str):
    mongo_uri = os.getenv('MONGODB_CONNECTION_STRING')
    db_name = os.getenv('MONGODB_DATABASE', 'position_management')
    client = AsyncIOMotorClient(mongo_uri)
    db = client[db_name]

    result = await db['eloc_data'].update_one(
        {'eloc_id': eloc_id},
        {'$unset': {
            'countersigned_purchase_confirmation_bytes': '',
            'countersigned_purchase_confirmation_filename': '',
            'countersigned_purchase_confirmation_content_type': '',
            'countersigned_purchase_confirmation_received_at': '',
            'countersigned_purchase_confirmation_signature_verification': ''
        }}
    )

    if result.modified_count > 0:
        print(f"✓ Removed confirmation from {eloc_id}")
    else:
        print(f"✗ Document not found or no confirmation to remove: {eloc_id}")

    client.close()


async def backfill_company_id():
    """Backfill company_id for documents that don't have it"""
    import asyncpg

    mongo_uri = os.getenv('MONGODB_CONNECTION_STRING')
    db_name = os.getenv('MONGODB_DATABASE', 'position_management')
    client = AsyncIOMotorClient(mongo_uri)
    db = client[db_name]

    # Connect to PostgreSQL
    pg_pool = await asyncpg.create_pool(
        host=os.getenv('POSTGRES_HOST'),
        port=int(os.getenv('POSTGRES_PORT', 5432)),
        user=os.getenv('POSTGRES_USER'),
        password=os.getenv('POSTGRES_PASSWORD'),
        database=os.getenv('POSTGRES_DB')
    )

    # Find all docs without company_id
    cursor = db['eloc_data'].find({'company_id': None})
    docs = await cursor.to_list(length=100)

    print(f"Found {len(docs)} documents without company_id")

    for doc in docs:
        eloc_id = doc.get('eloc_id')
        company_name = doc.get('extracted_fields', {}).get('company_name', {}).get('value')

        if not company_name:
            print(f"  {eloc_id}: No company name, skipping")
            continue

        # Look up company_id from PostgreSQL
        async with pg_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT company_id, symbol, name,
                       similarity(name_normalized, $1) as sim
                FROM company
                WHERE similarity(name_normalized, $1) > 0.3
                ORDER BY sim DESC
                LIMIT 1
            """, company_name.lower())

        if row:
            company_id = row['company_id']
            await db['eloc_data'].update_one(
                {'eloc_id': eloc_id},
                {'$set': {'company_id': company_id}}
            )
            print(f"  {eloc_id}: Set company_id={company_id} (matched '{row['name']}' with sim={row['sim']:.2f})")
        else:
            print(f"  {eloc_id}: No match found for '{company_name}'")

    await pg_pool.close()
    client.close()
    print("\n✓ Backfill complete")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == '--remove-confirm' and len(sys.argv) > 2:
            asyncio.run(remove_confirmation(sys.argv[2]))
        elif sys.argv[1] == '--backfill-company-id':
            asyncio.run(backfill_company_id())
        else:
            print(__doc__)
    else:
        asyncio.run(show_all_docs())
