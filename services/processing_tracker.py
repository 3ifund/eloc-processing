"""
Processing Tracker Service

Tracks each email through the workflow stages and stores status in MongoDB.
Used by the dashboard to display processing history and statistics.

Collection: eloc_processing_status
"""
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, UTC
from enum import Enum
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

PROCESSING_STATUS_COLLECTION = "eloc_processing_status"


class ProcessingStatus(str, Enum):
    """Email processing status stages"""
    RECEIVED = "RECEIVED"
    DUPLICATE = "DUPLICATE"
    CLASSIFYING = "CLASSIFYING"
    NOT_ELOC = "NOT_ELOC"
    EXTRACTING = "EXTRACTING"
    PERSISTING = "PERSISTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ProcessingTracker:
    """Track email processing through workflow stages"""

    def __init__(self, db: AsyncIOMotorDatabase):
        """
        Initialize tracker with MongoDB database

        Args:
            db: Motor async MongoDB database instance
        """
        self.db = db
        self.collection = db[PROCESSING_STATUS_COLLECTION]

    async def ensure_indexes(self):
        """Create indexes for efficient queries"""
        await self.collection.create_index("email_id", unique=True)
        await self.collection.create_index("internet_message_id")
        await self.collection.create_index("status")
        await self.collection.create_index("received_at")
        await self.collection.create_index([("received_at", -1)])
        logger.info("ProcessingTracker indexes created")

    async def start_tracking(
        self,
        email_id: str,
        internet_message_id: str,
        subject: str,
        sender: str,
        recipients: List[str],
        received_at: Optional[datetime] = None,
        has_attachments: bool = False,
        attachment_count: int = 0
    ) -> str:
        """
        Start tracking a new email

        Args:
            email_id: Microsoft Graph email ID
            internet_message_id: RFC 2822 Message-ID
            subject: Email subject
            sender: Sender email address
            recipients: List of recipient email addresses
            received_at: When email was received
            has_attachments: Whether email has attachments
            attachment_count: Number of attachments

        Returns:
            The email_id of the created tracking record
        """
        now = datetime.now(UTC)

        document = {
            "email_id": email_id,
            "internet_message_id": internet_message_id,
            "subject": subject,
            "sender": sender,
            "recipients": recipients,
            "received_at": received_at or now,
            "has_attachments": has_attachments,
            "attachment_count": attachment_count,
            "status": ProcessingStatus.RECEIVED.value,
            "is_duplicate": False,
            "classification": None,
            "extraction": None,
            "timing": {
                "started_at": now,
                "classification_started_at": None,
                "classification_completed_at": None,
                "extraction_started_at": None,
                "extraction_completed_at": None,
                "completed_at": None,
                "classification_ms": None,
                "extraction_ms": None,
                "total_ms": None
            },
            "error": None,
            "created_at": now,
            "updated_at": now
        }

        try:
            await self.collection.insert_one(document)
            logger.info(f"Started tracking email: {email_id[:20]}... subject: {subject[:50]}")
            return email_id
        except Exception as e:
            # Might be duplicate
            if "duplicate key" in str(e).lower():
                logger.warning(f"Email already tracked: {email_id[:20]}...")
                return email_id
            raise

    async def mark_duplicate(self, email_id: str) -> bool:
        """Mark email as duplicate (already processed)"""
        return await self._update_status(
            email_id,
            ProcessingStatus.DUPLICATE,
            {"is_duplicate": True}
        )

    async def start_classification(self, email_id: str) -> bool:
        """Mark classification started"""
        return await self._update_status(
            email_id,
            ProcessingStatus.CLASSIFYING,
            {"timing.classification_started_at": datetime.now(UTC)}
        )

    async def set_classification_result(
        self,
        email_id: str,
        result: str,
        votes: Dict[str, str],
        agreement: str,
        confidence: str,
        similarity_score: Optional[float] = None
    ) -> bool:
        """
        Set classification result

        Args:
            email_id: Email ID
            result: Final classification (ELOC, NOT_ELOC, UNCERTAIN)
            votes: Dict of classifier votes {similarity, claude, openai}
            agreement: Agreement type (unanimous, majority, split)
            confidence: Confidence level (HIGH, MEDIUM, LOW)
            similarity_score: Max similarity score
        """
        now = datetime.now(UTC)

        # Calculate classification time
        doc = await self.collection.find_one({"email_id": email_id})
        classification_ms = None
        if doc and doc.get("timing", {}).get("classification_started_at"):
            start = doc["timing"]["classification_started_at"]
            classification_ms = int((now - start).total_seconds() * 1000)

        classification_data = {
            "result": result,
            "votes": votes,
            "agreement": agreement,
            "confidence": confidence,
            "similarity_score": similarity_score
        }

        # If NOT_ELOC, mark as final status
        new_status = ProcessingStatus.NOT_ELOC if result == "NOT_ELOC" else None

        update_fields = {
            "classification": classification_data,
            "timing.classification_completed_at": now,
            "timing.classification_ms": classification_ms
        }

        if new_status:
            update_fields["status"] = new_status.value
            update_fields["timing.completed_at"] = now
            # Calculate total time
            if doc and doc.get("timing", {}).get("started_at"):
                total_ms = int((now - doc["timing"]["started_at"]).total_seconds() * 1000)
                update_fields["timing.total_ms"] = total_ms

        return await self._update_fields(email_id, update_fields)

    async def start_extraction(self, email_id: str) -> bool:
        """Mark extraction started"""
        return await self._update_status(
            email_id,
            ProcessingStatus.EXTRACTING,
            {"timing.extraction_started_at": datetime.now(UTC)}
        )

    async def set_extraction_result(
        self,
        email_id: str,
        eloc_id: str,
        company_symbol: str,
        company_name: str,
        fields_extracted: int,
        market_data_date: Optional[datetime] = None
    ) -> bool:
        """
        Set extraction result

        Args:
            email_id: Email ID
            eloc_id: Generated ELOC ID
            company_symbol: Company symbol
            company_name: Company name
            fields_extracted: Number of fields extracted
            market_data_date: Resolved market data date
        """
        now = datetime.now(UTC)

        # Calculate extraction time
        doc = await self.collection.find_one({"email_id": email_id})
        extraction_ms = None
        if doc and doc.get("timing", {}).get("extraction_started_at"):
            start = doc["timing"]["extraction_started_at"]
            extraction_ms = int((now - start).total_seconds() * 1000)

        extraction_data = {
            "eloc_id": eloc_id,
            "company_symbol": company_symbol,
            "company_name": company_name,
            "fields_extracted": fields_extracted,
            "market_data_date": market_data_date
        }

        return await self._update_fields(email_id, {
            "extraction": extraction_data,
            "timing.extraction_completed_at": now,
            "timing.extraction_ms": extraction_ms
        })

    async def start_persistence(self, email_id: str) -> bool:
        """Mark persistence started"""
        return await self._update_status(email_id, ProcessingStatus.PERSISTING)

    async def mark_completed(self, email_id: str) -> bool:
        """Mark email processing as completed"""
        now = datetime.now(UTC)

        # Calculate total time
        doc = await self.collection.find_one({"email_id": email_id})
        total_ms = None
        if doc and doc.get("timing", {}).get("started_at"):
            total_ms = int((now - doc["timing"]["started_at"]).total_seconds() * 1000)

        return await self._update_status(
            email_id,
            ProcessingStatus.COMPLETED,
            {
                "timing.completed_at": now,
                "timing.total_ms": total_ms
            }
        )

    async def mark_failed(self, email_id: str, error: str, stage: str = None) -> bool:
        """
        Mark email processing as failed

        Args:
            email_id: Email ID
            error: Error message
            stage: Stage where failure occurred
        """
        now = datetime.now(UTC)

        doc = await self.collection.find_one({"email_id": email_id})
        total_ms = None
        if doc and doc.get("timing", {}).get("started_at"):
            total_ms = int((now - doc["timing"]["started_at"]).total_seconds() * 1000)

        return await self._update_status(
            email_id,
            ProcessingStatus.FAILED,
            {
                "error": {"message": error, "stage": stage, "occurred_at": now},
                "timing.completed_at": now,
                "timing.total_ms": total_ms
            }
        )

    async def _update_status(
        self,
        email_id: str,
        status: ProcessingStatus,
        extra_fields: Dict[str, Any] = None
    ) -> bool:
        """Update status and optional extra fields"""
        update_fields = {"status": status.value}
        if extra_fields:
            update_fields.update(extra_fields)
        return await self._update_fields(email_id, update_fields)

    async def _update_fields(self, email_id: str, fields: Dict[str, Any]) -> bool:
        """Update fields for an email"""
        fields["updated_at"] = datetime.now(UTC)

        result = await self.collection.update_one(
            {"email_id": email_id},
            {"$set": fields}
        )

        return result.modified_count > 0

    # ==================== Query Methods for Dashboard ====================

    async def get_recent_emails(
        self,
        limit: int = 50,
        offset: int = 0,
        status_filter: Optional[str] = None
    ) -> List[Dict]:
        """
        Get recent emails for dashboard

        Args:
            limit: Max number of results
            offset: Skip first N results
            status_filter: Optional status to filter by

        Returns:
            List of email processing records
        """
        query = {}
        if status_filter:
            query["status"] = status_filter

        cursor = self.collection.find(query).sort("received_at", -1).skip(offset).limit(limit)
        return await cursor.to_list(length=limit)

    async def get_email_by_id(self, email_id: str) -> Optional[Dict]:
        """Get single email processing record"""
        return await self.collection.find_one({"email_id": email_id})

    async def get_statistics(self) -> Dict:
        """
        Get processing statistics for dashboard

        Returns:
            Dict with counts, averages, etc.
        """
        pipeline = [
            {
                "$facet": {
                    "status_counts": [
                        {"$group": {"_id": "$status", "count": {"$sum": 1}}}
                    ],
                    "classification_counts": [
                        {"$match": {"classification.result": {"$exists": True}}},
                        {"$group": {"_id": "$classification.result", "count": {"$sum": 1}}}
                    ],
                    "agreement_counts": [
                        {"$match": {"classification.agreement": {"$exists": True}}},
                        {"$group": {"_id": "$classification.agreement", "count": {"$sum": 1}}}
                    ],
                    "timing_avg": [
                        {"$match": {"timing.total_ms": {"$exists": True, "$ne": None}}},
                        {"$group": {
                            "_id": None,
                            "avg_total_ms": {"$avg": "$timing.total_ms"},
                            "avg_classification_ms": {"$avg": "$timing.classification_ms"},
                            "avg_extraction_ms": {"$avg": "$timing.extraction_ms"}
                        }}
                    ],
                    "total_count": [
                        {"$count": "count"}
                    ],
                    "today_count": [
                        {"$match": {
                            "received_at": {
                                "$gte": datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
                            }
                        }},
                        {"$count": "count"}
                    ]
                }
            }
        ]

        result = await self.collection.aggregate(pipeline).to_list(length=1)
        if not result:
            return {}

        data = result[0]

        # Transform to cleaner format
        status_counts = {item["_id"]: item["count"] for item in data.get("status_counts", [])}
        classification_counts = {item["_id"]: item["count"] for item in data.get("classification_counts", [])}
        agreement_counts = {item["_id"]: item["count"] for item in data.get("agreement_counts", [])}
        timing = data.get("timing_avg", [{}])[0] if data.get("timing_avg") else {}
        total = data.get("total_count", [{}])[0].get("count", 0) if data.get("total_count") else 0
        today = data.get("today_count", [{}])[0].get("count", 0) if data.get("today_count") else 0

        return {
            "total_emails": total,
            "today_emails": today,
            "status_counts": status_counts,
            "classification_counts": classification_counts,
            "agreement_counts": agreement_counts,
            "avg_timing": {
                "total_ms": timing.get("avg_total_ms"),
                "classification_ms": timing.get("avg_classification_ms"),
                "extraction_ms": timing.get("avg_extraction_ms")
            }
        }

    async def search_emails(
        self,
        query: str,
        limit: int = 20
    ) -> List[Dict]:
        """
        Search emails by subject, sender, or ELOC ID

        Args:
            query: Search query
            limit: Max results

        Returns:
            Matching email records
        """
        search_query = {
            "$or": [
                {"subject": {"$regex": query, "$options": "i"}},
                {"sender": {"$regex": query, "$options": "i"}},
                {"extraction.eloc_id": {"$regex": query, "$options": "i"}},
                {"extraction.company_symbol": {"$regex": query, "$options": "i"}}
            ]
        }

        cursor = self.collection.find(search_query).sort("received_at", -1).limit(limit)
        return await cursor.to_list(length=limit)


# Global instance (initialized in main.py)
processing_tracker: Optional[ProcessingTracker] = None
