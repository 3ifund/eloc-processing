"""Quick diagnostic to show eloc_data documents for matching debug."""
import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

async def main():
    mongo_uri = os.getenv('MONGODB_CONNECTION_STRING')
    db_name = os.getenv('MONGODB_DATABASE', 'position_management')
    client = AsyncIOMotorClient(mongo_uri)
    db = client[db_name]

    cursor = db['eloc_data'].find().sort('created_at', -1).limit(10)
    docs = await cursor.to_list(length=10)

    print(f"\n{'='*80}")
    print(f"ELOC_DATA DOCUMENTS ({len(docs)} found)")
    print(f"{'='*80}\n")

    for doc in docs:
        extracted = doc.get('extracted_fields', {})
        print(f"eloc_id: {doc.get('eloc_id')}")
        print(f"  company_id: {doc.get('company_id')}")
        print(f"  company_name: {extracted.get('company_name', {}).get('value')}")
        print(f"  company_symbol: {extracted.get('company_symbol', {}).get('value')}")
        print(f"  shares: {extracted.get('vwap_purchase_share_amount', {}).get('value')}")
        print(f"  exercise_date: {extracted.get('vwap_purchase_exercise_date', {}).get('value')}")
        print(f"  has_confirmation: {doc.get('countersigned_purchase_confirmation_bytes') is not None}")
        print()

    client.close()

if __name__ == "__main__":
    asyncio.run(main())
