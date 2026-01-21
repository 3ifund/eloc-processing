"""
ELOC State Persistence Service

Persists ELOC workflow state to MongoDB eloc_state collection.

Schema (snake_case):
- eloc_id: Unique identifier (e.g., "ZSPC-00000056")
- workflow_step: Current workflow step (e.g., "VerificationOfExtractedFields")
- status: Current status (e.g., "Pending")
- include: Whether to include in processing (default: True)
- created_at: Creation timestamp
- modified_at: Last modification timestamp
"""
import logging
from typing import Optional, Dict, List
from datetime import datetime, timedelta, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

# Eastern timezone (UTC-5)
EASTERN_TZ = timezone(timedelta(hours=-5))

ELOC_STATE_COLLECTION = "eloc_state"

# Default values for new ELOC state
DEFAULT_WORKFLOW_STEP = "VerificationOfExtractedFields"
DEFAULT_STATUS = "Pending"
DEFAULT_INCLUDE = True


class ElocStateService:
    """Service for persisting ELOC workflow state to MongoDB"""

    def __init__(self, db: AsyncIOMotorDatabase):
        """
        Initialize service with MongoDB database

        Args:
            db: Motor async MongoDB database instance
        """
        self.db = db
        self.collection = db[ELOC_STATE_COLLECTION]

    async def create_eloc_state(
        self,
        eloc_id: str,
        company_id: int,
        workflow_step: str = DEFAULT_WORKFLOW_STEP,
        status: str = DEFAULT_STATUS,
        include: bool = DEFAULT_INCLUDE
    ) -> str:
        """
        Create new eloc_state document

        Args:
            eloc_id: Unique ELOC identifier (e.g., "ZSPC-00000056")
            company_id: Company ID from PostgreSQL database
            workflow_step: Initial workflow step (default: "VerificationOfExtractedFields")
            status: Initial status (default: "Pending")
            include: Include in processing (default: True)

        Returns:
            The eloc_id of the created document

        Raises:
            ValueError: If eloc_id already exists
        """
        now = datetime.now(EASTERN_TZ)

        existing = await self.collection.find_one({"eloc_id": eloc_id})
        if existing:
            raise ValueError(f"ELOC state already exists: {eloc_id}")

        document = {
            "eloc_id": eloc_id,
            "company_id": company_id,
            "workflow_step": workflow_step,
            "status": status,
            "include": include,
            "created_at": now,
            "modified_at": now
        }

        await self.collection.insert_one(document)
        logger.info(f"Created eloc_state document: {eloc_id}")

        return eloc_id

    async def get_eloc_state(self, eloc_id: str) -> Optional[Dict]:
        """
        Get eloc_state document by ID

        Args:
            eloc_id: ELOC identifier

        Returns:
            Document dict or None if not found
        """
        doc = await self.collection.find_one({"eloc_id": eloc_id})
        return doc

    async def update_workflow_step(
        self,
        eloc_id: str,
        workflow_step: str,
        status: Optional[str] = None
    ) -> bool:
        """
        Update workflow step (and optionally status)

        Args:
            eloc_id: ELOC identifier
            workflow_step: New workflow step
            status: New status (optional)

        Returns:
            True if updated, False if not found
        """
        now = datetime.now(EASTERN_TZ)

        update_doc = {
            "$set": {
                "workflow_step": workflow_step,
                "modified_at": now
            }
        }

        if status is not None:
            update_doc["$set"]["status"] = status

        result = await self.collection.update_one(
            {"eloc_id": eloc_id},
            update_doc
        )

        if result.modified_count > 0:
            logger.info(f"Updated eloc_state: {eloc_id} -> {workflow_step}")
            return True

        return False

    async def update_status(self, eloc_id: str, status: str) -> bool:
        """
        Update status only

        Args:
            eloc_id: ELOC identifier
            status: New status

        Returns:
            True if updated, False if not found
        """
        now = datetime.now(EASTERN_TZ)

        result = await self.collection.update_one(
            {"eloc_id": eloc_id},
            {
                "$set": {
                    "status": status,
                    "modified_at": now
                }
            }
        )

        if result.modified_count > 0:
            logger.info(f"Updated eloc_state status: {eloc_id} -> {status}")
            return True

        return False

    async def set_include(self, eloc_id: str, include: bool) -> bool:
        """
        Set include flag

        Args:
            eloc_id: ELOC identifier
            include: Include flag value

        Returns:
            True if updated, False if not found
        """
        now = datetime.now(EASTERN_TZ)

        result = await self.collection.update_one(
            {"eloc_id": eloc_id},
            {
                "$set": {
                    "include": include,
                    "modified_at": now
                }
            }
        )

        if result.modified_count > 0:
            logger.info(f"Updated eloc_state include: {eloc_id} -> {include}")
            return True

        return False

    async def delete_eloc_state(self, eloc_id: str) -> bool:
        """
        Delete eloc_state document

        Args:
            eloc_id: ELOC identifier

        Returns:
            True if deleted, False if not found
        """
        result = await self.collection.delete_one({"eloc_id": eloc_id})

        if result.deleted_count > 0:
            logger.info(f"Deleted eloc_state document: {eloc_id}")
            return True

        return False

    async def find_by_status(self, status: str, limit: int = 100) -> List[Dict]:
        """
        Find all ELOCs with given status

        Args:
            status: Status to filter by
            limit: Max results

        Returns:
            List of eloc_state documents
        """
        cursor = self.collection.find(
            {"status": status}
        ).sort("created_at", -1).limit(limit)

        return await cursor.to_list(length=limit)

    async def find_by_workflow_step(self, workflow_step: str, limit: int = 100) -> List[Dict]:
        """
        Find all ELOCs at given workflow step

        Args:
            workflow_step: Workflow step to filter by
            limit: Max results

        Returns:
            List of eloc_state documents
        """
        cursor = self.collection.find(
            {"workflow_step": workflow_step}
        ).sort("created_at", -1).limit(limit)

        return await cursor.to_list(length=limit)

    async def find_pending(self, limit: int = 100) -> List[Dict]:
        """
        Find all pending ELOCs (status=Pending, include=True)

        Args:
            limit: Max results

        Returns:
            List of eloc_state documents
        """
        cursor = self.collection.find(
            {"status": "Pending", "include": True}
        ).sort("created_at", -1).limit(limit)

        return await cursor.to_list(length=limit)

    async def get_statistics(self) -> Dict:
        """
        Get statistics by status and workflow_step

        Returns:
            Dict with counts by status and workflow_step
        """
        pipeline_status = [
            {"$group": {"_id": "$status", "count": {"$sum": 1}}}
        ]

        pipeline_step = [
            {"$group": {"_id": "$workflow_step", "count": {"$sum": 1}}}
        ]

        status_cursor = self.collection.aggregate(pipeline_status)
        step_cursor = self.collection.aggregate(pipeline_step)

        status_stats = {doc["_id"]: doc["count"] async for doc in status_cursor}
        step_stats = {doc["_id"]: doc["count"] async for doc in step_cursor}

        return {
            "by_status": status_stats,
            "by_workflow_step": step_stats
        }


# Global instance (initialized in main.py)
eloc_state_service: Optional[ElocStateService] = None
