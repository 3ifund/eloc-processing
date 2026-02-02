import os
from dotenv import load_dotenv
from pymongo import MongoClient
from collections import defaultdict

# Load environment variables from the project directory
load_dotenv(r'C:\Users\DarrylKnapp\3iFund\eloc-processing\.env')

# Connect to MongoDB
mongo_uri = os.getenv('MONGODB_CONNECTION_STRING')
db_name = os.getenv('MONGODB_DATABASE', 'position_management')

print(f'Connecting to MongoDB: {mongo_uri}')
print(f'Database: {db_name}')
print('=' * 80)

client = MongoClient(mongo_uri)
db = client[db_name]
collection = db['eloc_data']

# Track confidence scores for averaging
field_scores = defaultdict(list)
doc_count = 0

def extract_confidences(obj, prefix=''):
    """Recursively extract confidence scores from nested structures."""
    results = {}
    if isinstance(obj, dict):
        # Check if this dict has a confidence key
        if 'confidence' in obj:
            return {prefix: obj['confidence']}
        if 'confidence_score' in obj:
            return {prefix: obj['confidence_score']}
        # Otherwise recurse into child keys
        for key, value in obj.items():
            if key in ['confidence', 'confidence_score']:
                continue
            child_prefix = f'{prefix}.{key}' if prefix else key
            results.update(extract_confidences(value, child_prefix))
    return results

# Query all documents
for doc in collection.find():
    doc_count += 1
    eloc_id = doc.get('eloc_id', doc.get('_id', 'Unknown'))
    
    print(f'\nDocument: {eloc_id}')
    print('-' * 40)
    
    confidences = {}
    
    # Check field_confidences at root level
    if 'field_confidences' in doc:
        confidences = doc['field_confidences']
        print('  Source: field_confidences')
    # Check metadata.confidence_scores
    elif 'metadata' in doc and isinstance(doc['metadata'], dict):
        if 'confidence_scores' in doc['metadata']:
            confidences = doc['metadata']['confidence_scores']
            print('  Source: metadata.confidence_scores')
        elif 'field_confidences' in doc['metadata']:
            confidences = doc['metadata']['field_confidences']
            print('  Source: metadata.field_confidences')
    # Check confidence_scores at root level
    elif 'confidence_scores' in doc:
        confidences = doc['confidence_scores']
        print('  Source: confidence_scores')
    # Check extracted_fields for nested confidence values
    elif 'extracted_fields' in doc:
        confidences = extract_confidences(doc['extracted_fields'])
        if confidences:
            print('  Source: extracted_fields (nested confidence values)')
    
    if confidences and isinstance(confidences, dict):
        for field, score in sorted(confidences.items()):
            if isinstance(score, (int, float)):
                if isinstance(score, float):
                    print(f'    {field}: {score:.4f}')
                else:
                    print(f'    {field}: {score}')
                field_scores[field].append(float(score))
            elif isinstance(score, dict) and 'value' in score:
                val = score['value']
                print(f'    {field}: {val}')
                if isinstance(val, (int, float)):
                    field_scores[field].append(float(val))
    else:
        print('  No confidence scores found in this document')
        # Show extracted_fields structure for debugging
        if 'extracted_fields' in doc:
            ef = doc['extracted_fields']
            print(f'  extracted_fields keys: {list(ef.keys())[:10]}')
            # Show first field structure
            if ef:
                first_key = list(ef.keys())[0]
                first_val = ef[first_key]
                print(f'  Sample field structure ({first_key}): {type(first_val).__name__}')
                if isinstance(first_val, dict):
                    print(f'    Sub-keys: {list(first_val.keys())}')

print('\n' + '=' * 80)
print(f'SUMMARY: Processed {doc_count} documents')
print('=' * 80)

if field_scores:
    print('\nAverage Confidence Per Field:')
    print('-' * 40)
    for field, scores in sorted(field_scores.items()):
        avg = sum(scores) / len(scores)
        print(f'  {field}: {avg:.4f} (from {len(scores)} documents)')
else:
    print('\nNo confidence scores found in any documents.')
    print('\nShowing one full document structure for debugging...')
    doc = collection.find_one()
    if doc:
        import json
        # Remove binary fields for display
        doc_copy = {k: v for k, v in doc.items() if not k.endswith('_bytes') and k != '_id'}
        # Limit extracted_fields display
        if 'extracted_fields' in doc_copy and doc_copy['extracted_fields']:
            ef = doc_copy['extracted_fields']
            sample = {k: ef[k] for k in list(ef.keys())[:3]}
            doc_copy['extracted_fields'] = sample
        try:
            print(json.dumps(doc_copy, indent=2, default=str))
        except:
            print(doc_copy)

client.close()
print('\nDone.')
