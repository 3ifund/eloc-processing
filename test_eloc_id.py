"""Quick test of ELOC ID service"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

async def test_eloc_id_service():
    from services.eloc_id_service import ElocIdService
    from repositories.mongo_client import MongoDBClient, mongo_client

    # Get PostgreSQL config (same as main.py)
    PG_CONFIG = {
        'host': os.getenv('PG_HOST', '10.90.98.123'),
        'port': int(os.getenv('PG_PORT', '5432')),
        'database': os.getenv('PG_DATABASE', 'DealTerms'),
        'user': os.getenv('PG_USER', 'postgres'),
        'password': os.getenv('PG_PASSWORD', 'Drl270!!')
    }

    print(f"PostgreSQL config: {PG_CONFIG['host']}:{PG_CONFIG['port']}/{PG_CONFIG['database']}")

    # Connect to MongoDB
    await mongo_client.connect()
    print(f"MongoDB connected")

    # Create ELOC ID service
    service = ElocIdService(mongo_client.db, PG_CONFIG)
    await service.ensure_indexes()
    print("ELOC ID service initialized")

    # Test company lookup
    print("\n=== Testing company lookup for ZSPC ===")
    try:
        company_info = await service.get_company_info("ZSPC")
        if company_info:
            print(f"  Found: company_id={company_info.company_id}, symbol={company_info.symbol}, name={company_info.company_name}")
        else:
            print("  Company not found!")
    except Exception as e:
        print(f"  Error: {type(e).__name__}: {e}")

    # Test ELOC ID generation
    print("\n=== Testing ELOC ID generation for ZSPC ===")
    try:
        eloc_id, company_id = await service.generate_eloc_id("ZSPC")
        print(f"  Success: eloc_id={eloc_id}, company_id={company_id}")
    except Exception as e:
        print(f"  Error: {type(e).__name__}: {e}")

    # Cleanup
    await service.close()
    await mongo_client.close()
    print("\nDone!")

if __name__ == "__main__":
    asyncio.run(test_eloc_id_service())
