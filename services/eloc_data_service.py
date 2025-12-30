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

    async def create_eloc_data(
        self,
        eloc_id: str,
        extracted_fields: Dict[str, Any],
        pdf_bytes: bytes,
        pdf_filename: str,
        pdf_content_type: str = "application/pdf",
        received_at: Optional[datetime] = None,
        source: str = "Email"
    ) -> str:
        """
        Create new eloc_data document

        Args:
            eloc_id: Unique ELOC identifier (e.g., "ZSPC-00000056")
            extracted_fields: Dict with extracted fields in {value, confidence} format
            pdf_bytes: Raw PDF file bytes
            pdf_filename: Original PDF filename
            pdf_content_type: MIME type (default: application/pdf)
            received_at: When the email was received (default: now)
            source: Source of the data (default: "Email")

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
            "extracted_fields": extracted_fields,
            "purchase_notice_bytes": Binary(pdf_bytes),
            "purchase_notice_filename": pdf_filename,
            "purchase_notice_content_type": pdf_content_type,
            "received_at": received_at,
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
        default_confidence = 0.95
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
