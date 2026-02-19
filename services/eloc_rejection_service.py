"""
ELOC Rejection Service

Handles storage of rejected Purchase Notices and Purchase Confirmations
in the eloc_rejection MongoDB collection.

Rejections are tracked so the upstream C# app can be notified via
MongoDB Change Streams and handle them appropriately.
"""
from datetime import datetime, UTC
from enum import Enum
from typing import Optional, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import Binary
import logging

logger = logging.getLogger(__name__)


class RejectionReason(str, Enum):
    """
    Reasons for rejecting a classified Purchase Notice or Purchase Confirmation.

    This enum is shared with the upstream C# app - keep in sync.
    """
    # Purchase Notice rejections
    INVESTOR_COUNTERSIGNED = "INVESTOR_COUNTERSIGNED"  # Hedge fund already signed
    DUPLICATE_ATTACHMENT = "DUPLICATE_ATTACHMENT"      # Same PDF already processed
    EXERCISE_DATE_TOO_OLD = "EXERCISE_DATE_TOO_OLD"    # >7 trading days in past
    COMPANY_NOT_SIGNED = "COMPANY_NOT_SIGNED"          # Company hasn't signed
    EXTRACTION_FAILED = "EXTRACTION_FAILED"            # LLM extraction error

    # Purchase Confirmation rejections
    BOTH_PARTIES_NOT_SIGNED = "BOTH_PARTIES_NOT_SIGNED"  # Missing signatures
    NO_MATCHING_NOTICE = "NO_MATCHING_NOTICE"            # No Purchase Notice found
    MISSING_REQUIRED_FIELDS = "MISSING_REQUIRED_FIELDS"  # Can't match without fields


class DocumentType(str, Enum):
    """Document types that can be rejected"""
    PURCHASE_NOTICE = "PURCHASE_NOTICE"
    PURCHASE_CONFIRMATION = "PURCHASE_CONFIRMATION"


class ElocRejectionService:
    """
    Service for managing rejected ELOC documents.

    Stores rejections in the eloc_rejection collection with the PDF
    and metadata so upstream apps can handle them.
    """

    def __init__(self, db: AsyncIOMotorDatabase, eloc_id_service):
        """
        Initialize the rejection service.

        Args:
            db: MongoDB database instance
            eloc_id_service: Service for generating ELOC IDs (shared sequence)
        """
        self.db = db
        self.collection = db["eloc_rejection"]
        self.eloc_id_service = eloc_id_service

    async def ensure_indexes(self):
        """Create indexes for the eloc_rejection collection"""
        await self.collection.create_index("rejection_id", unique=True)
        await self.collection.create_index("rejection_processed")
        await self.collection.create_index("company_id")
        await self.collection.create_index([("rejected_at", -1)])
        logger.info("✓ ELOC rejection indexes ensured")

    async def create_rejection(
        self,
        email_id: str,
        document_type: DocumentType,
        rejection_reason: RejectionReason,
        rejection_reason_detail: str,
        company_symbol: str,
        pdf_bytes: bytes,
        pdf_filename: str,
        company_name: Optional[str] = None,
        exercise_date: Optional[str] = None,
        share_amount: Optional[int] = None,
        email_subject: Optional[str] = None,
        email_sender: Optional[str] = None,
        email_received_at: Optional[datetime] = None,
        pdf_content_type: str = "application/pdf",
        rejection_id: Optional[str] = None,
        company_id: Optional[int] = None
    ) -> Optional[str]:
        """
        Create a rejection record for a classified document.

        Args:
            email_id: Microsoft Graph email ID
            document_type: PURCHASE_NOTICE or PURCHASE_CONFIRMATION
            rejection_reason: Enum value for the rejection type
            rejection_reason_detail: Human-readable explanation
            company_symbol: Company stock symbol (required for ID generation if rejection_id not provided)
            pdf_bytes: The PDF file content
            pdf_filename: Original PDF filename
            company_name: Company name if extracted
            exercise_date: Exercise date if extracted (ISO format string)
            share_amount: Share amount if extracted
            email_subject: Email subject for context
            email_sender: Email sender for context
            email_received_at: When email was received
            pdf_content_type: MIME type (default: application/pdf)
            rejection_id: Pre-generated ELOC ID (e.g., from extraction attempt). If not provided, generates new one.
            company_id: Company ID if known (avoids extra lookup)

        Returns:
            The rejection_id (e.g., "ZSPC-00000040") or None if failed
        """
        try:
            # Use pre-generated ID or generate new one using shared sequence
            if rejection_id is None:
                rejection_id, company_id = await self.eloc_id_service.generate_eloc_id(company_symbol)
            elif company_id is None:
                # Have ID but need company_id
                company_id = await self.eloc_id_service.get_company_id(company_symbol)

            now = datetime.now(UTC)

            doc = {
                "rejection_id": rejection_id,
                "company_id": company_id,
                "email_id": email_id,
                "document_type": document_type.value,

                # Rejection details
                "rejection_reason": rejection_reason.value,
                "rejection_reason_detail": rejection_reason_detail,

                # PDF storage
                "pdf_bytes": Binary(pdf_bytes),
                "pdf_filename": pdf_filename,
                "pdf_content_type": pdf_content_type,

                # Extracted info (if available)
                "company_symbol": company_symbol,
                "company_name": company_name,
                "exercise_date": exercise_date,
                "share_amount": share_amount,

                # Email metadata
                "email_subject": email_subject,
                "email_sender": email_sender,
                "email_received_at": email_received_at,

                # Processing status
                "rejected_at": now,
                "rejection_processed": False,
                "processed_at": None,
                "processed_by": None,

                # Audit
                "created_at": now,
                "created_by": "LLM_Extraction"
            }

            await self.collection.insert_one(doc)

            logger.info(
                f"Created rejection {rejection_id}: {rejection_reason.value} - "
                f"{document_type.value} for {company_symbol}"
            )

            return rejection_id

        except Exception as e:
            logger.error(f"Failed to create rejection record: {e}")
            return None

    async def get_unprocessed_rejections(self, limit: int = 100) -> list:
        """
        Get rejections that haven't been processed by upstream app.

        Args:
            limit: Maximum number to return

        Returns:
            List of rejection documents (without pdf_bytes for efficiency)
        """
        cursor = self.collection.find(
            {"rejection_processed": False},
            {"pdf_bytes": 0}  # Exclude large binary field
        ).sort("rejected_at", -1).limit(limit)

        return await cursor.to_list(length=limit)

    async def mark_processed(
        self,
        rejection_id: str,
        processed_by: str = "upstream_app"
    ) -> bool:
        """
        Mark a rejection as processed by upstream app.

        Args:
            rejection_id: The rejection ID to mark
            processed_by: Who/what processed it

        Returns:
            True if updated, False if not found
        """
        result = await self.collection.update_one(
            {"rejection_id": rejection_id},
            {
                "$set": {
                    "rejection_processed": True,
                    "processed_at": datetime.now(UTC),
                    "processed_by": processed_by
                }
            }
        )

        return result.modified_count > 0

    async def get_rejection(self, rejection_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a single rejection by ID.

        Args:
            rejection_id: The rejection ID

        Returns:
            Rejection document or None
        """
        return await self.collection.find_one({"rejection_id": rejection_id})

    async def get_rejection_pdf(self, rejection_id: str) -> Optional[bytes]:
        """
        Get just the PDF bytes for a rejection.

        Args:
            rejection_id: The rejection ID

        Returns:
            PDF bytes or None
        """
        doc = await self.collection.find_one(
            {"rejection_id": rejection_id},
            {"pdf_bytes": 1}
        )

        if doc and "pdf_bytes" in doc:
            return bytes(doc["pdf_bytes"])
        return None
