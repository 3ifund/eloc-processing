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


def ensure_tz_aware(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware (UTC)"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class ProcessingStatus(str, Enum):
    """Email processing status stages"""
    RECEIVED = "RECEIVED"
    DUPLICATE = "DUPLICATE"
    CLASSIFYING = "CLASSIFYING"
    NOT_RELEVANT = "NOT_RELEVANT"  # Neither Purchase Notice nor Confirmation
    EXTRACTING = "EXTRACTING"  # For Purchase Notices
    VERIFYING_SIGNATURES = "VERIFYING_SIGNATURES"  # For Purchase Confirmations
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

    async def mark_not_relevant(self, email_id: str, reason: str = None) -> bool:
        """Mark email as not relevant (e.g., countersigned Purchase Notice)"""
        extra_fields = {}
        if reason:
            extra_fields["not_relevant_reason"] = reason
        return await self._update_status(
            email_id,
            ProcessingStatus.NOT_RELEVANT,
            extra_fields
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
        similarity_score: Optional[float] = None,
        classification_errors: Optional[Dict[str, Dict[str, str]]] = None
    ) -> bool:
        """
        Set classification result

        Args:
            email_id: Email ID
            result: Final classification (PURCHASE_NOTICE, PURCHASE_CONFIRMATION, NOT_RELEVANT, UNCERTAIN)
            votes: Dict of classifier votes {similarity, claude, openai}
            agreement: Agreement type (unanimous, majority, split)
            confidence: Confidence level (HIGH, MEDIUM, LOW)
            similarity_score: Max similarity score
            classification_errors: Dict of classifier errors {claude: {error, error_type}, openai: {error, error_type}}
        """
        now = datetime.now(UTC)

        # Calculate classification time
        doc = await self.collection.find_one({"email_id": email_id})
        classification_ms = None
        if doc and doc.get("timing", {}).get("classification_started_at"):
            start = ensure_tz_aware(doc["timing"]["classification_started_at"])
            classification_ms = int((now - start).total_seconds() * 1000)

        classification_data = {
            "result": result,
            "votes": votes,
            "agreement": agreement,
            "confidence": confidence,
            "similarity_score": similarity_score
        }

        # Include classification errors if any occurred
        if classification_errors:
            classification_data["errors"] = classification_errors

        # If NOT_RELEVANT, mark as final status (no further processing needed)
        new_status = ProcessingStatus.NOT_RELEVANT if result == "NOT_RELEVANT" else None

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
                started = ensure_tz_aware(doc["timing"]["started_at"])
                total_ms = int((now - started).total_seconds() * 1000)
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
        market_data_date: Optional[datetime] = None,
        field_confidences: Optional[Dict[str, float]] = None,
        avg_confidence: Optional[float] = None,
        llm_agree_count: Optional[int] = None,
        llm_total_count: Optional[int] = None
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
            field_confidences: Dict of field_name -> confidence (0-100)
            avg_confidence: Average confidence across all fields
            llm_agree_count: Number of fields where both LLMs agreed
            llm_total_count: Total number of fields compared
        """
        now = datetime.now(UTC)

        # Calculate extraction time
        doc = await self.collection.find_one({"email_id": email_id})
        extraction_ms = None
        if doc and doc.get("timing", {}).get("extraction_started_at"):
            start = ensure_tz_aware(doc["timing"]["extraction_started_at"])
            extraction_ms = int((now - start).total_seconds() * 1000)

        extraction_data = {
            "eloc_id": eloc_id,
            "company_symbol": company_symbol,
            "company_name": company_name,
            "fields_extracted": fields_extracted,
            "market_data_date": market_data_date,
            "field_confidences": field_confidences,
            "avg_confidence": avg_confidence,
            "llm_agree_count": llm_agree_count,
            "llm_total_count": llm_total_count
        }

        return await self._update_fields(email_id, {
            "extraction": extraction_data,
            "timing.extraction_completed_at": now,
            "timing.extraction_ms": extraction_ms
        })

    async def start_signature_verification(self, email_id: str) -> bool:
        """Mark signature verification started (for Purchase Confirmations)"""
        return await self._update_status(
            email_id,
            ProcessingStatus.VERIFYING_SIGNATURES,
            {"timing.verification_started_at": datetime.now(UTC)}
        )

    async def set_signature_verification_result(
        self,
        email_id: str,
        company_signed: bool,
        investor_signed: bool,
        company_signatory: Optional[str] = None,
        investor_signatory: Optional[str] = None,
        verification_notes: Optional[str] = None,
        llm_agreement: Optional[bool] = None,
        agreement_details: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Set signature verification result (for Purchase Confirmations)

        Args:
            email_id: Email ID
            company_signed: Whether company signature is present
            investor_signed: Whether investor signature is present
            company_signatory: Name of company signatory
            investor_signatory: Name of investor signatory
            verification_notes: Additional verification notes
            llm_agreement: Whether both LLMs (Claude and OpenAI) agreed on results
            agreement_details: Dict with per-field agreement info from dual LLM verification
        """
        now = datetime.now(UTC)

        # Calculate verification time
        doc = await self.collection.find_one({"email_id": email_id})
        verification_ms = None
        if doc and doc.get("timing", {}).get("verification_started_at"):
            start = ensure_tz_aware(doc["timing"]["verification_started_at"])
            verification_ms = int((now - start).total_seconds() * 1000)

        verification_data = {
            "company_signed": company_signed,
            "investor_signed": investor_signed,
            "both_signed": company_signed and investor_signed,
            "company_signatory": company_signatory,
            "investor_signatory": investor_signatory,
            "notes": verification_notes,
            "llm_agreement": llm_agreement,
            "agreement_details": agreement_details
        }

        return await self._update_fields(email_id, {
            "signature_verification": verification_data,
            "timing.verification_completed_at": now,
            "timing.verification_ms": verification_ms
        })

    async def set_document_type(self, email_id: str, document_type: str) -> bool:
        """Set the document type after classification"""
        return await self._update_fields(email_id, {"document_type": document_type})

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
            started = ensure_tz_aware(doc["timing"]["started_at"])
            total_ms = int((now - started).total_seconds() * 1000)

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
            started = ensure_tz_aware(doc["timing"]["started_at"])
            total_ms = int((now - started).total_seconds() * 1000)

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
                    "document_type_counts": [
                        {"$match": {"document_type": {"$exists": True, "$ne": None}}},
                        {"$group": {"_id": "$document_type", "count": {"$sum": 1}}}
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
                            "avg_extraction_ms": {"$avg": "$timing.extraction_ms"},
                            "avg_verification_ms": {"$avg": "$timing.verification_ms"}
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
                    ],
                    # Signature verification stats (for Purchase Confirmations)
                    "signature_verification_counts": [
                        {"$match": {"signature_verification": {"$exists": True}}},
                        {"$group": {
                            "_id": {
                                "$cond": [
                                    "$signature_verification.both_signed", "both_signed",
                                    {"$cond": [
                                        "$signature_verification.investor_signed", "investor_only",
                                        {"$cond": [
                                            "$signature_verification.company_signed", "company_only",
                                            "neither"
                                        ]}
                                    ]}
                                ]
                            },
                            "count": {"$sum": 1}
                        }}
                    ],
                    "signature_llm_agreement_counts": [
                        {"$match": {"signature_verification.llm_agreement": {"$exists": True}}},
                        {"$group": {
                            "_id": {"$cond": ["$signature_verification.llm_agreement", "agree", "disagree"]},
                            "count": {"$sum": 1}
                        }}
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
        document_type_counts = {item["_id"]: item["count"] for item in data.get("document_type_counts", [])}
        classification_counts = {item["_id"]: item["count"] for item in data.get("classification_counts", [])}
        agreement_counts = {item["_id"]: item["count"] for item in data.get("agreement_counts", [])}
        timing = data.get("timing_avg", [{}])[0] if data.get("timing_avg") else {}
        total = data.get("total_count", [{}])[0].get("count", 0) if data.get("total_count") else 0
        today = data.get("today_count", [{}])[0].get("count", 0) if data.get("today_count") else 0

        # Signature verification stats
        sig_verification_counts = {
            item["_id"]: item["count"]
            for item in data.get("signature_verification_counts", [])
        }
        sig_llm_agreement_counts = {
            item["_id"]: item["count"]
            for item in data.get("signature_llm_agreement_counts", [])
        }

        return {
            "total_emails": total,
            "today_emails": today,
            "status_counts": status_counts,
            "document_type_counts": document_type_counts,
            "classification_counts": classification_counts,
            "agreement_counts": agreement_counts,
            "avg_timing": {
                "total_ms": timing.get("avg_total_ms"),
                "classification_ms": timing.get("avg_classification_ms"),
                "extraction_ms": timing.get("avg_extraction_ms"),
                "verification_ms": timing.get("avg_verification_ms")
            },
            "signature_verification_counts": sig_verification_counts,
            "signature_llm_agreement_counts": sig_llm_agreement_counts
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
