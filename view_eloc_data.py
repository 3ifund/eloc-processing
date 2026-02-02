"""
View extracted fields from eloc_data MongoDB collection.

Usage:
    python view_eloc_data.py              # View most recent
    python view_eloc_data.py CAPS-00000004  # View specific ELOC
    python view_eloc_data.py --all        # View all ELOCs
"""
import asyncio
import sys
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()


async def view_eloc_data(eloc_id: str = None, show_all: bool = False):
    mongo_uri = os.getenv('MONGODB_CONNECTION_STRING')
    db_name = os.getenv('MONGODB_DATABASE', 'position_management')
    client = AsyncIOMotorClient(mongo_uri)
    db = client[db_name]

    if show_all:
        cursor = db['eloc_data'].find().sort('created_at', -1).limit(20)
        docs = await cursor.to_list(length=20)
        print(f"\n{'='*60}")
        print(f"RECENT ELOC DATA DOCUMENTS ({len(docs)} found)")
        print(f"{'='*60}\n")
        for doc in docs:
            print_eloc_summary(doc)
    elif eloc_id:
        doc = await db['eloc_data'].find_one({'eloc_id': eloc_id})
        if doc:
            print_eloc_detail(doc)
        else:
            print(f"ELOC not found: {eloc_id}")
    else:
        doc = await db['eloc_data'].find_one(sort=[('created_at', -1)])
        if doc:
            print_eloc_detail(doc)
        else:
            print("No eloc_data documents found")
            colls = await db.list_collection_names()
            print(f"Collections in {db_name}: {colls}")

    client.close()


def print_eloc_summary(doc):
    extracted = doc.get('extracted_fields', {})
    symbol = extracted.get('company_symbol', {}).get('value', 'N/A')
    shares = extracted.get('vwap_purchase_share_amount', {}).get('value', 0)
    exercise = extracted.get('vwap_purchase_exercise_date', {}).get('value', 'N/A')

    print(f"  {doc.get('eloc_id'):20} | {symbol:6} | {shares:>10,} shares | Exercise: {format_date(exercise)}")


def print_eloc_detail(doc):
    print(f"\n{'='*60}")
    print(f"ELOC DATA: {doc.get('eloc_id')}")
    print(f"{'='*60}")
    print(f"  Created: {doc.get('created_at')}")
    print(f"  Filename: {doc.get('purchase_notice_filename')}")
    print(f"  company_id: {doc.get('company_id')}")
    print(f"  Has Confirmation: {doc.get('countersigned_purchase_confirmation_bytes') is not None}")
    print()
    print(f"{'='*60}")
    print("EXTRACTED FIELDS")
    print(f"{'='*60}")

    extracted = doc.get('extracted_fields', {})

    # Define field display order and labels
    field_order = [
        ('company_symbol', 'Company Symbol'),
        ('company_name', 'Company Name'),
        ('vwap_purchase_share_amount', 'Share Amount'),
        ('vwap_purchase_exercise_date', 'Exercise Date'),
        ('vwap_purchase_period_start_date', 'Period Start'),
        ('vwap_purchase_period_end_date', 'Period End'),
        ('vwap_purchase_settlement_date', 'Settlement Date'),
        ('aggregate_limit_available', 'Aggregate Limit'),
        ('company_signator', 'Signatory'),
        ('signatory_title', 'Signatory Title'),
        ('agreement_date', 'Agreement Date'),
        ('purchase_notice_company_signature', 'Company Signed'),
    ]

    for field_name, label in field_order:
        field_data = extracted.get(field_name, {})
        if isinstance(field_data, dict) and 'value' in field_data:
            val = field_data.get('value')
            conf = field_data.get('confidence', 0)

            # Format value
            if 'date' in field_name.lower() and val:
                val = format_date(val)
            elif field_name == 'vwap_purchase_share_amount' and val:
                val = f"{int(val):,}"
            elif field_name == 'aggregate_limit_available' and val:
                val = f"${int(float(str(val))):,}"

            print(f"  {label:25} {str(val):30} ({conf:.0f}%)")

    print()


def format_date(val):
    if val is None:
        return 'N/A'
    if isinstance(val, datetime):
        return val.strftime('%Y-%m-%d')
    if isinstance(val, str):
        return val[:10] if len(val) >= 10 else val
    return str(val)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == '--all':
            asyncio.run(view_eloc_data(show_all=True))
        else:
            asyncio.run(view_eloc_data(eloc_id=sys.argv[1]))
    else:
        asyncio.run(view_eloc_data())
