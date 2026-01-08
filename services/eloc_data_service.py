"""
ELOC Data Persistence Service

Persists extracted ELOC data to MongoDB eloc_data collection.

Schema (snake_case):
- eloc_id: Unique identifier (e.g., "ZSPC-00000056")
- extracted_fields: Nested object with {value, confidence} pattern
  - includes purchase_notice_market_data_date (resolved date for market data queries)
- purchase_notice_bytes: Binary PDF data
- purchase_notice_filename: Original filename
- purchase_notice_content_type: MIME type
- received_at, created_at, created_by, modified_at, modified_by, source
"""
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, UTC
from bson import Binary
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

ELOC_DATA_COLLECTION = "eloc_data"


class ElocDataService:
    """Service for persisting ELOC data to MongoDB"""

    def __init__(self, db: AsyncIOMotorDatabase):
        """
        Initialize service with MongoDB database

        Args:
            db: Motor async MongoDB database instance
        """
        self.db = db
        self.collection = db[ELOC_DATA_COLLECTION]

    async def ensure_indexes(self):
        """Create indexes for efficient queries"""
        await self.collection.create_index("eloc_id", unique=True)
        await self.collection.create_index("attachment_hash")
        logger.info("ElocDataService indexes created")

    async def create_eloc_data(
        self,
        eloc_id: str,
        extracted_fields: Dict[str, Any],
        pdf_bytes: bytes,
        pdf_filename: str,
        purchase_notice_market_data_date: Optional[datetime] = None,
        pdf_content_type: str = "application/pdf",
        received_at: Optional[datetime] = None,
        source: str = "Email",
        attachment_hash: Optional[str] = None
    ) -> str:
        """
        Create new eloc_data document

        Args:
            eloc_id: Unique ELOC identifier (e.g., "ZSPC-00000056")
            extracted_fields: Dict with extracted fields in {value, confidence} format
            pdf_bytes: Raw PDF file bytes
            pdf_filename: Original PDF filename
            purchase_notice_market_data_date: Resolved market data date (top-level field)
            pdf_content_type: MIME type (default: application/pdf)
            received_at: When the email was received (default: now)
            source: Source of the data (default: "Email")
            attachment_hash: SHA256 hash of PDF bytes for deduplication

        Returns:
            The eloc_id of the created document

        Raises:
            ValueError: If eloc_id already exists
        """
        now = datetime.now(UTC)
        received_at = received_at or now

        existing = await self.collection.find_one({"eloc_id": eloc_id})
        if existing:
            raise ValueError(f"ELOC already exists: {eloc_id}")

        document = {
            "eloc_id": eloc_id,
            "received_at": received_at,
            "purchase_notice_market_data_date": purchase_notice_market_data_date,
            "extracted_fields": extracted_fields,
            "purchase_notice_bytes": Binary(pdf_bytes),
            "purchase_notice_filename": pdf_filename,
            "purchase_notice_content_type": pdf_content_type,
            "attachment_hash": attachment_hash,
            "created_at": now,
            "created_by": "LLM_Extraction",
            "modified_at": now,
            "modified_by": "LLM_Extraction",
            "source": source
        }

        await self.collection.insert_one(document)
        logger.info(f"Created eloc_data document: {eloc_id}")

        return eloc_id

    async def get_eloc_data(self, eloc_id: str) -> Optional[Dict]:
        """
        Get eloc_data document by ID

        Args:
            eloc_id: ELOC identifier

        Returns:
            Document dict or None if not found
        """
        doc = await self.collection.find_one({"eloc_id": eloc_id})
        return doc

    async def update_extracted_fields(
        self,
        eloc_id: str,
        updated_fields: Dict[str, Any],
        modified_by: str = "LLM_Extraction"
    ) -> bool:
        """
        Update extracted fields (partial update)

        Args:
            eloc_id: ELOC identifier
            updated_fields: Fields to update (will merge with existing)
            modified_by: Who made the modification

        Returns:
            True if updated, False if not found
        """
        now = datetime.now(UTC)

        update_doc = {
            "$set": {
                "modified_at": now,
                "modified_by": modified_by
            }
        }

        for field_name, field_value in updated_fields.items():
            update_doc["$set"][f"extracted_fields.{field_name}"] = field_value

        result = await self.collection.update_one(
            {"eloc_id": eloc_id},
            update_doc
        )

        if result.modified_count > 0:
            logger.info(f"Updated eloc_data fields: {eloc_id}")
            return True

        return False

    async def delete_eloc_data(self, eloc_id: str) -> bool:
        """
        Delete eloc_data document

        Args:
            eloc_id: ELOC identifier

        Returns:
            True if deleted, False if not found
        """
        result = await self.collection.delete_one({"eloc_id": eloc_id})

        if result.deleted_count > 0:
            logger.info(f"Deleted eloc_data document: {eloc_id}")
            return True

        return False

    async def eloc_exists(self, eloc_id: str) -> bool:
        """
        Check if ELOC exists

        Args:
            eloc_id: ELOC identifier

        Returns:
            True if exists, False otherwise
        """
        doc = await self.collection.find_one({"eloc_id": eloc_id}, {"_id": 1})
        return doc is not None

    async def find_by_company_symbol(self, company_symbol: str, limit: int = 100) -> List[Dict]:
        """
        Find all ELOCs for a company symbol

        Args:
            company_symbol: Company symbol to filter by
            limit: Max results

        Returns:
            List of eloc_data documents
        """
        cursor = self.collection.find(
            {"extracted_fields.company_symbol.value": company_symbol}
        ).sort("created_at", -1).limit(limit)

        return await cursor.to_list(length=limit)

    async def find_matching_purchase_notice(
        self,
        company_name: str,
        share_amount: int,
        exercise_date: str,
        company_symbol: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Find a matching Purchase Notice by company name, share amount, and exercise date.

        Args:
            company_name: Company name (will use case-insensitive regex match)
            share_amount: Number of shares (exact match)
            exercise_date: Exercise date in YYYY-MM-DD format (exact match)
            company_symbol: Optional company symbol for faster matching

        Returns:
            Matching eloc_data document or None if not found
        """
        import re
        from datetime import datetime

        # Convert exercise_date string to datetime if needed for comparison
        if isinstance(exercise_date, str):
            try:
                exercise_date_dt = datetime.fromisoformat(exercise_date.replace("Z", "+00:00"))
            except:
                exercise_date_dt = None
        else:
            exercise_date_dt = exercise_date

        # Build query - first try with company_symbol if provided
        if company_symbol:
            # Exact match on symbol is faster
            doc = await self.collection.find_one({
                "extracted_fields.company_symbol.value": company_symbol.upper(),
                "extracted_fields.vwap_purchase_share_amount.value": share_amount,
                "countersigned_purchase_confirmation_bytes": {"$exists": False}  # Not already matched
            })
            if doc:
                logger.info(f"Found matching Purchase Notice by symbol: {doc.get('eloc_id')}")
                return doc

        # Fuzzy match on company name using case-insensitive regex
        # Extract key words from company name for matching
        name_pattern = re.escape(company_name.split(",")[0].split("Inc")[0].strip())
        if len(name_pattern) < 3:
            name_pattern = re.escape(company_name[:20])

        query = {
            "extracted_fields.company_name.value": {"$regex": name_pattern, "$options": "i"},
            "extracted_fields.vwap_purchase_share_amount.value": share_amount,
            "countersigned_purchase_confirmation_bytes": {"$exists": False}  # Not already matched
        }

        # Try to match with exercise date
        if exercise_date_dt:
            # First try exact date match
            query_with_date = {
                **query,
                "extracted_fields.vwap_purchase_exercise_date.value": exercise_date_dt
            }
            doc = await self.collection.find_one(query_with_date)
            if doc:
                logger.info(f"Found matching Purchase Notice: {doc.get('eloc_id')}")
                return doc

        # Fallback: match without date (rely on company + shares)
        doc = await self.collection.find_one(query)
        if doc:
            logger.info(f"Found matching Purchase Notice (by company+shares): {doc.get('eloc_id')}")
            return doc

        logger.warning(
            f"No matching Purchase Notice found for company={company_name}, "
            f"shares={share_amount}, date={exercise_date}"
        )
        return None

    async def add_confirmation_pdf(
        self,
        eloc_id: str,
        pdf_bytes: bytes,
        pdf_filename: str,
        pdf_content_type: str = "application/pdf",
        signature_verification: Optional[Dict] = None
    ) -> bool:
        """
        Add Purchase Confirmation PDF to an existing eloc_data document.

        Args:
            eloc_id: ELOC identifier
            pdf_bytes: Raw PDF file bytes
            pdf_filename: Original PDF filename
            pdf_content_type: MIME type (default: application/pdf)
            signature_verification: Optional dict with signature verification results

        Returns:
            True if updated, False if not found
        """
        now = datetime.now(UTC)

        update_doc = {
            "$set": {
                "countersigned_purchase_confirmation_bytes": Binary(pdf_bytes),
                "countersigned_purchase_confirmation_filename": pdf_filename,
                "countersigned_purchase_confirmation_content_type": pdf_content_type,
                "countersigned_purchase_confirmation_received_at": now,
                "modified_at": now,
                "modified_by": "LLM_Extraction"
            }
        }

        if signature_verification:
            update_doc["$set"]["countersigned_purchase_confirmation_signature_verification"] = signature_verification

        result = await self.collection.update_one(
            {"eloc_id": eloc_id},
            update_doc
        )

        if result.modified_count > 0:
            logger.info(f"Added confirmation PDF to eloc_data: {eloc_id}")
            return True

        logger.warning(f"Failed to add confirmation PDF - ELOC not found: {eloc_id}")
        return False

    @staticmethod
    def build_extracted_fields(
        company_symbol: str,
        company_name: str,
        agreement_date: Optional[datetime],
        company_signator: str,
        signatory_title: str,
        vwap_purchase_share_amount: int,
        vwap_purchase_exercise_date: Optional[datetime],
        vwap_purchase_period_start_date: Optional[datetime],
        vwap_purchase_period_end_date: Optional[datetime],
        vwap_purchase_settlement_date: Optional[datetime],
        aggregate_limit_available: Optional[float],
        sender_name: str,
        sender_emails: list,
        email_subject: str,
        email_body: str,
        purchase_notice_market_data_date: Optional[datetime] = None,
        purchase_notice_company_signature: bool = False,
        confidence_scores: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """
        Build extracted_fields dict with {value, confidence} pattern (snake_case)

        Args:
            All the extracted field values
            purchase_notice_market_data_date: Resolved market data date (may differ from exercise date
                                              if exercise date falls on half day or non-trading day)
            confidence_scores: Optional dict of field_name -> confidence

        Returns:
            Properly formatted extracted_fields dict
        """
        default_confidence = 95  # 0-100 scale to match orchestrator confidence scores
        scores = confidence_scores or {}

        def field(value, field_name):
            return {
                "value": value,
                "confidence": scores.get(field_name, default_confidence)
            }

        extracted = {
            "company_symbol": field(company_symbol, "company_symbol"),
            "company_name": field(company_name, "company_name"),
            "agreement_date": field(agreement_date, "agreement_date"),
            "company_signator": field(company_signator, "company_signator"),
            "signatory_title": field(signatory_title, "signatory_title"),
            "purchase_notice_company_signature": field(purchase_notice_company_signature, "purchase_notice_company_signature"),
            "vwap_purchase_share_amount": field(vwap_purchase_share_amount, "vwap_purchase_share_amount"),
            "vwap_purchase_exercise_date": field(vwap_purchase_exercise_date, "vwap_purchase_exercise_date"),
            "vwap_purchase_period_start_date": field(vwap_purchase_period_start_date, "vwap_purchase_period_start_date"),
            "vwap_purchase_period_end_date": field(vwap_purchase_period_end_date, "vwap_purchase_period_end_date"),
            "vwap_purchase_settlement_date": field(vwap_purchase_settlement_date, "vwap_purchase_settlement_date"),
            "aggregate_limit_available": field(aggregate_limit_available, "aggregate_limit_available"),
            "purchase_notice_market_data_date": field(purchase_notice_market_data_date, "purchase_notice_market_data_date"),
            "sender_name": field(sender_name, "sender_name"),
            "sender_emails": [field(email, "sender_emails") for email in sender_emails],
            "email_subject": field(email_subject, "email_subject"),
            "email_body": field(email_body, "email_body")
        }

        return extracted


# Global instance (initialized in main.py)
eloc_data_service: Optional[ElocDataService] = None
