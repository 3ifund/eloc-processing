from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

connection_string = os.getenv('MONGODB_CONNECTION_STRING')
if not connection_string:
    print("Error: MONGODB_CONNECTION_STRING environment variable is required")
    exit(1)
client = MongoClient(connection_string)
db = client[os.getenv('MONGODB_DATABASE', 'position_management')]

# Get last 5 emails from eloc_processing_status
print("=== Recent emails in eloc_processing_status ===\n")
for doc in db["eloc_processing_status"].find().sort("received_at", -1).limit(10):
    eloc_id = doc.get('extraction', {}).get('eloc_id', 'N/A') if doc.get('extraction') else 'N/A'
    print(f"{eloc_id}:")
    print(f"  email_id: {doc.get('email_id', '')[:40]}...")
    print(f"  status: {doc.get('status')}")
    print(f"  document_type: {doc.get('document_type')}")
    print(f"  received_at: {doc.get('received_at')}")
    print()

client.close()
