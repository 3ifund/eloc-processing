"""
Database setup script - WITH COMPREHENSIVE PROMPTS
"""
import asyncio
from repositories.mongo_client import mongo_client
from repositories.prompts_repository import prompts_repo
from datetime import datetime, UTC
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def setup_prompts():
    """Create initial prompts in MongoDB"""
    logger.info("\n" + "=" * 60)
    logger.info("Creating AI Prompts...")
    logger.info("=" * 60)
    
    prompts = [
        {
            "name": "signature_verification",
            "version": "1.0",
            "description": "Verifies if VWAP Purchase Notice has been signed by the company",
            "template": """You are verifying if a VWAP Purchase Notice has been signed by the COMPANY (not the investor).

CRITICAL: We only care about the COMPANY signature block, NOT the Tumim Stone Capital/3i Management investor signature.

Document text:
{eloc_text}

Look for the COMPANY signature block. This is typically:
- NOT labeled "Tumim Stone Capital" or "3i Management"
- Usually has a company name like "zSpace, Inc." or "[Company Name], Inc."
- Contains fields: By:, Name:, Title:, Address:, Email:

Check if the COMPANY signature block is COMPLETE:
1. Name field has an actual person's name (not "Name:" or blank or "_____")
2. Title field has an actual corporate title (not "Title:" or blank) - like "CFO", "CEO", "President", "Officer"
3. At least one of: email address or physical address is present

Respond with JSON only:
{{
  "signature_status": "SIGNED" or "UNSIGNED" or "UNCERTAIN",
  "confidence": "HIGH" or "MEDIUM" or "LOW",
  "company_name": "company name" or null,
  "signatory_name": "person's name" or null,
  "signatory_title": "title" or null,
  "reasoning": "brief explanation of your determination"
}}

IMPORTANT:
- If Name or Title fields appear to be template/placeholder text, return UNSIGNED
- If you cannot clearly identify the company signature block, return UNCERTAIN
- Be VERY conservative - when in doubt, return UNSIGNED or UNCERTAIN (false negative is OK, false positive is NOT)""",
            "model_config": {
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 500,
                "temperature": 0
            },
            "active": True
        },
        {
            "name": "field_extraction",
            "version": "1.0",
            "description": "Extracts structured fields from VWAP Purchase Notice",
            "template": """Extract structured data from this VWAP Purchase Notice document.

Document:
{eloc_text}

Extract ALL of these fields (use null if not found):

{{
  "vwap_purchase_share_amount": "number of shares as string",
  "vwap_purchase_exercise_date": "date as string",
  "vwap_purchase_period_start": "date as string",
  "vwap_purchase_period_end": "date as string",
  "vwap_settlement_date": "date as string",
  "dollar_amount_available": "dollar amount as string with $ and commas",
  
  "company_name": "full company name",
  "company_signatory_name": "person who signed for company",
  "company_signatory_title": "their title",
  "company_address": "physical address if present",
  "company_email": "email if present",
  
  "investor_name": "typically Tumim Stone Capital LLC",
  "investor_manager": "typically 3i Management LLC",
  
  "agreement_date": "date of original agreement if mentioned"
}}

Respond with ONLY valid JSON, no other text.""",
            "model_config": {
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "temperature": 0
            },
            "active": True
        }
    ]
    
    for prompt in prompts:
        existing = await prompts_repo.collection.find_one({"name": prompt["name"], "version": prompt["version"]})
        if existing:
            logger.info(f"  ✓ Prompt '{prompt['name']}' v{prompt['version']} already exists")
        else:
            await prompts_repo.create(prompt)
            logger.info(f"  ✓ Created prompt: '{prompt['name']}' v{prompt['version']}")


async def setup_database():
    """Setup MongoDB database with collections and initial data"""
    
    logger.info("=" * 60)
    logger.info("ELOC Processing - Database Setup")
    logger.info("=" * 60)
    
    # Connect to MongoDB
    await mongo_client.connect()
    mongo_client.connect_sync()
    db = mongo_client.db
    
    # ==================== CREATE COLLECTIONS ====================
    logger.info("\n1. Creating collections...")
    
    collections = [
        "workflows",
        "workflow_history",
        "reference_embeddings",
        "processing_costs",
        "prompts"
    ]
    
    existing_collections = await db.list_collection_names()
    
    for collection_name in collections:
        if collection_name in existing_collections:
            logger.info(f"  ✓ Collection '{collection_name}' already exists")
        else:
            await db.create_collection(collection_name)
            logger.info(f"  ✓ Created collection: '{collection_name}'")
    
    # ==================== CREATE INDEXES ====================
    logger.info("\n2. Creating indexes...")
    
    # Workflows indexes
    await db.workflows.create_index(
        [("workflow_status", 1), ("created_at", 1)],
        name="idx_status_created"
    )
    
    await db.workflows.create_index(
        "email_id",
        unique=True,
        name="idx_email_id_unique"
    )
    
    # Prompts indexes
    await db.prompts.create_index(
        [("name", 1), ("version", -1)],
        name="idx_name_version"
    )
    
    await db.prompts.create_index(
        [("name", 1), ("active", 1)],
        name="idx_name_active"
    )
    
    logger.info("  ✓ All indexes created")
    
    # ==================== LOAD PROMPTS ====================
    await setup_prompts()
    
    # ==================== LOAD REFERENCE EMBEDDINGS ====================
    logger.info("\n3. Loading reference embeddings...")
    
    from pathlib import Path
    references_dir = Path("references")
    
    if not references_dir.exists():
        logger.warning(f"  ⚠️ References directory not found: {references_dir}")
        logger.info(f"  Creating {references_dir}...")
        references_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"  Please add reference ELOC .txt files to {references_dir}")
    else:
        try:
            from sentence_transformers import SentenceTransformer
            
            model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("  ✓ Loaded embedding model")
            
            ref_files = list(references_dir.glob("*.txt"))
            
            if not ref_files:
                logger.warning(f"  ⚠️ No .txt files found in {references_dir}")
                logger.info(f"  Please add reference ELOC .txt files")
            else:
                for i, ref_file in enumerate(ref_files, 1):
                    with open(ref_file, 'r', encoding='utf-8') as f:
                        text = f.read()
                    
                    # Compute embedding
                    embedding = model.encode(text).tolist()
                    
                    # Check if already exists
                    existing = await db.reference_embeddings.find_one({
                        "reference_id": f"eloc_{i}"
                    })
                    
                    if existing:
                        logger.info(f"  ✓ Reference {i} already exists: {ref_file.name}")
                    else:
                        # Insert
                        await db.reference_embeddings.insert_one({
                            "reference_id": f"eloc_{i}",
                            "reference_name": ref_file.stem,
                            "text": text,
                            "embedding": embedding,
                            "created_at": datetime.now(UTC),
                            "active": True
                        })
                        logger.info(f"  ✓ Loaded reference {i}: {ref_file.name}")
        
        except ImportError:
            logger.warning("  ⚠️ sentence-transformers not installed")
            logger.info("  Install: pip install sentence-transformers")
    
    # ==================== SUMMARY ====================
    logger.info("\n" + "=" * 60)
    logger.info("✅ Database setup complete!")
    logger.info("=" * 60)
    logger.info(f"\nDatabase: {mongo_client.database_name}")
    logger.info(f"Collections: {len(collections)}")
    logger.info(f"Connection: {mongo_client.connection_string}")
    
    # Close connections
    await mongo_client.close()
    mongo_client.close_sync()


if __name__ == "__main__":
    asyncio.run(setup_database())