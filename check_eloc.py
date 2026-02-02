from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

# Connect to MongoDB using env settings
connection_string = os.getenv('MONGODB_CONNECTION_STRING', 'mongodb://10.90.98.123:27017/?replicaSet=rs0')
database_name = os.getenv('MONGODB_DATABASE', 'position_management')

print(f"Connecting to: {connection_string}")
print(f"Database: {database_name}")

client = MongoClient(connection_string)
db = client[database_name]

# List all collections
print('=== Collections ===')
print(db.list_collection_names())

# Count documents in each collection
print('\n=== Document Counts ===')
print(f"  eloc_data: {db['eloc_data'].count_documents({})}")
print(f"  eloc_state: {db['eloc_state'].count_documents({})}")
print(f"  eloc_processing_status: {db['eloc_processing_status'].count_documents({})}")

# Check eloc_processing_status - show recent with eloc_ids
print('\n=== eloc_processing_status (recent) ===')
for doc in db['eloc_processing_status'].find().sort('received_at', -1).limit(5):
    eloc_id = doc.get('extraction', {}).get('eloc_id', 'N/A') if doc.get('extraction') else 'N/A'
    print(f"  eloc_id={eloc_id}, status={doc.get('status')}")

# Check if those eloc_ids exist in eloc_data
print('\n=== Checking if ELOCs exist in eloc_data ===')
for doc in db['eloc_processing_status'].find().sort('received_at', -1).limit(5):
    eloc_id = doc.get('extraction', {}).get('eloc_id') if doc.get('extraction') else None
    if eloc_id:
        exists = db['eloc_data'].find_one({'eloc_id': eloc_id})
        print(f"  {eloc_id}: {'EXISTS' if exists else 'MISSING'}")

client.close()
