"""
Base classes and interfaces for verification services.
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List
from datetime import datetime, UTC

logger = logging.getLogger(__name__)


class VerificationCategory(str, Enum):
    """Categories of verification checks"""
    COMPANY = "company"
    SIGNATORY = "signatory"
    TRANSACTION = "transaction"
    EMAIL_METADATA = "email_metadata"
    CONFIRMATION_SIGNATURE = "confirmation_signature"


@dataclass
class CategoryResult:
    """Result from a single category verification"""
    category: VerificationCategory
    extracted_fields: Dict[str, Any]
    raw_response: str = ""
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None


@dataclass
class VerificationResult:
    """Complete verification result from one LLM"""
    provider: str  # "claude" or "openai"
    categories: Dict[VerificationCategory, CategoryResult] = field(default_factory=dict)
    total_duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def all_successful(self) -> bool:
        return all(cat.success for cat in self.categories.values())

    def get_all_fields(self) -> Dict[str, Any]:
        """Flatten all extracted fields from all categories"""
        all_fields = {}
        for cat_result in self.categories.values():
            all_fields.update(cat_result.extracted_fields)
        return all_fields


class BaseVerificationService(ABC):
    """Abstract base class for LLM verification services"""

    def __init__(self, api_key: str):
        self.api_key = api_key

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return provider name (e.g., 'claude', 'openai')"""
        pass

    @abstractmethod
    async def verify_company(
        self,
        document_text: str,
        few_shot_examples: Optional[List[Dict]] = None,
        classification_examples: Optional[List[str]] = None
    ) -> CategoryResult:
        """
        Extract and verify company identification fields.

        Fields: company_symbol, company_name
        """
        pass

    @abstractmethod
    async def verify_signatory(
        self,
        document_text: str,
        few_shot_examples: Optional[List[Dict]] = None,
        classification_examples: Optional[List[str]] = None
    ) -> CategoryResult:
        """
        Extract and verify signatory fields.

        Fields: company_signator, signatory_title
        Also verifies: signed by company (not hedge fund)
        """
        pass

    @abstractmethod
    async def verify_transaction(
        self,
        document_text: str,
        few_shot_examples: Optional[List[Dict]] = None,
        classification_examples: Optional[List[str]] = None
    ) -> CategoryResult:
        """
        Extract and verify transaction fields.

        Fields: vwap_purchase_share_amount, agreement_date,
                vwap_purchase_exercise_date, vwap_purchase_period_start_date,
                vwap_purchase_period_end_date, vwap_purchase_settlement_date,
                aggregate_limit_available
        """
        pass

    @abstractmethod
    async def verify_email_metadata(
        self,
        email_subject: str,
        email_body: str,
        email_sender: str,
        few_shot_examples: Optional[List[Dict]] = None
    ) -> CategoryResult:
        """
        Extract and verify email metadata fields.

        Fields: sender_name, sender_emails, email_subject
        """
        pass

    async def verify_all(
        self,
        document_text: str,
        email_subject: str,
        email_body: str,
        email_sender: str,
        few_shot_examples: Optional[Dict[VerificationCategory, List[Dict]]] = None,
        classification_examples: Optional[List[str]] = None
    ) -> VerificationResult:
        """
        Run all verification categories and return combined result.

        Args:
            document_text: The document to verify
            email_subject: Email subject line
            email_body: Email body text
            email_sender: Email sender address
            few_shot_examples: Optional examples per category
            classification_examples: Example Purchase Notice texts for classification
        """
        import time
        start_time = time.time()

        few_shot_examples = few_shot_examples or {}
        classification_examples = classification_examples or []

        result = VerificationResult(provider=self.provider_name)

        # Run all categories
        result.categories[VerificationCategory.COMPANY] = await self.verify_company(
            document_text,
            few_shot_examples.get(VerificationCategory.COMPANY),
            classification_examples
        )

        result.categories[VerificationCategory.SIGNATORY] = await self.verify_signatory(
            document_text,
            few_shot_examples.get(VerificationCategory.SIGNATORY),
            classification_examples
        )

        result.categories[VerificationCategory.TRANSACTION] = await self.verify_transaction(
            document_text,
            few_shot_examples.get(VerificationCategory.TRANSACTION),
            classification_examples
        )

        result.categories[VerificationCategory.EMAIL_METADATA] = await self.verify_email_metadata(
            email_subject,
            email_body,
            email_sender,
            few_shot_examples.get(VerificationCategory.EMAIL_METADATA)
        )

        result.total_duration_ms = (time.time() - start_time) * 1000

        logger.info(
            f"{self.provider_name} verification complete: "
            f"{sum(1 for c in result.categories.values() if c.success)}/4 categories successful, "
            f"{result.total_duration_ms:.0f}ms"
        )

        return result
