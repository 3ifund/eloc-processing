"""
MongoDB index creation script
Run this once after setting up MongoDB
"""
import asyncio
from repositories.mongo_client import mongo_client
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def create_indexes():
    """Create all necessary MongoDB indexes"""
    
    logger.info("Creating MongoDB indexes...")
    
    # Connect to MongoDB
    await mongo_client.connect()
    db = mongo_client.db
    
    # ==================== WORKFLOWS COLLECTION ====================
    logger.info("Creating indexes for 'workflows' collection...")
    
    await db.workflows.create_index(
        [("workflow_status", 1), ("created_at", 1)],
        name="idx_status_created"
    )
    logger.info("  ✓ Created: idx_status_created")
    
    await db.workflows.create_index(
        "email_id",
        unique=True,
        name="idx_email_id_unique"
    )
    logger.info("  ✓ Created: idx_email_id_unique")
    
    await db.workflows.create_index(
        [("created_at", -1)],
        name="idx_created_desc"
    )
    logger.info("  ✓ Created: idx_created_desc")
    
    await db.workflows.create_index(
        "human_review.reviewed_by",
        name="idx_reviewed_by",
        sparse=True
    )
    logger.info("  ✓ Created: idx_reviewed_by")
    
    await db.workflows.create_index(
        "extracted_fields.company_name",
        name="idx_company_name",
        sparse=True
    )
    logger.info("  ✓ Created: idx_company_name")
    
    await db.workflows.create_index(
        "extracted_fields.vwap_settlement_date",
        name="idx_settlement_date",
        sparse=True
    )
    logger.info("  ✓ Created: idx_settlement_date")
    
    # ==================== WORKFLOW_HISTORY COLLECTION ====================
    logger.info("\nCreating indexes for 'workflow_history' collection...")
    
    await db.workflow_history.create_index(
        [("workflow_id", 1), ("timestamp", 1)],
        name="idx_workflow_timestamp"
    )
    logger.info("  ✓ Created: idx_workflow_timestamp")
    
    # ==================== REFERENCE_EMBEDDINGS COLLECTION ====================
    logger.info("\nCreating indexes for 'reference_embeddings' collection...")
    
    await db.reference_embeddings.create_index(
        "reference_id",
        unique=True,
        name="idx_reference_id_unique"
    )
    logger.info("  ✓ Created: idx_reference_id_unique")
    
    await db.reference_embeddings.create_index(
        "active",
        name="idx_active"
    )
    logger.info("  ✓ Created: idx_active")
    
    # ==================== PROCESSING_COSTS COLLECTION ====================
    logger.info("\nCreating indexes for 'processing_costs' collection...")
    
    await db.processing_costs.create_index(
        "workflow_id",
        name="idx_workflow_id"
    )
    logger.info("  ✓ Created: idx_workflow_id")
    
    await db.processing_costs.create_index(
        [("timestamp", -1)],
        name="idx_timestamp_desc"
    )
    logger.info("  ✓ Created: idx_timestamp_desc")
    
    logger.info("\n✅ All indexes created successfully!")
    
    # Close connection
    await mongo_client.close()


if __name__ == "__main__":
    asyncio.run(create_indexes())