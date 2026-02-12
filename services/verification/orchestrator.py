"""
Verification orchestrator - runs Claude and OpenAI in parallel and compares results.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, date, UTC
from typing import Optional, Dict, List, Any, Union

from services.verification.base import (
    VerificationResult,
    VerificationCategory,
    BaseVerificationService
)
from services.verification.claude_service import ClaudeVerificationService
from services.verification.openai_service import OpenAIVerificationService
from services.verification.examples_repository import ExamplesRepository

logger = logging.getLogger(__name__)


@dataclass
class MarketDataDateInfo:
    """Market data date resolution info"""
    exercise_date: date
    market_data_date: date
    was_adjusted: bool
    adjustment_reason: Optional[str]
    tooltip_text: str


@dataclass
class FieldComparison:
    """Comparison result for a single field"""
    field_name: str
    claude_value: Any
    openai_value: Any
    agrees: bool
    category: VerificationCategory
    ner_validated: bool = False
    confidence: float = 0.0


@dataclass
class CategoryComparison:
    """Comparison result for a category"""
    category: VerificationCategory
    fields: List[FieldComparison] = field(default_factory=list)
    claude_error: Optional[str] = None
    openai_error: Optional[str] = None

    @property
    def all_agree(self) -> bool:
        if self.claude_error or self.openai_error:
            return False
        return all(f.agrees for f in self.fields)

    @property
    def agreement_count(self) -> int:
        return sum(1 for f in self.fields if f.agrees)

    @property
    def total_fields(self) -> int:
        return len(self.fields)


@dataclass
class VerificationComparison:
    """Complete comparison between Claude and OpenAI results"""
    claude_result: VerificationResult
    openai_result: VerificationResult
    categories: Dict[VerificationCategory, CategoryComparison] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    market_data_date_info: Optional[MarketDataDateInfo] = None
    ner_applied: bool = False

    @property
    def all_agree(self) -> bool:
        return all(cat.all_agree for cat in self.categories.values())

    @property
    def passed(self) -> bool:
        return self.all_agree

    @property
    def agreement_summary(self) -> Dict[str, Any]:
        """Get summary of agreements per category"""
        summary = {}
        for cat, comparison in self.categories.items():
            summary[cat.value] = {
                "agrees": comparison.all_agree,
                "fields_agreed": comparison.agreement_count,
                "total_fields": comparison.total_fields,
                "claude_error": comparison.claude_error,
                "openai_error": comparison.openai_error
            }
        return summary

    def get_disagreements(self) -> List[FieldComparison]:
        """Get all fields where Claude and OpenAI disagreed"""
        disagreements = []
        for comparison in self.categories.values():
            for field_comp in comparison.fields:
                if not field_comp.agrees:
                    disagreements.append(field_comp)
        return disagreements

    def get_merged_fields(self) -> Dict[str, Any]:
        """
        Get merged extracted fields from all categories.
        Uses Claude values as primary (they agreed if we got here).
        Includes market data date info if available.
        """
        merged = {}
        for cat_result in self.claude_result.categories.values():
            if cat_result.extracted_fields:
                merged.update(cat_result.extracted_fields)

        # Add market data date fields if resolved
        if self.market_data_date_info:
            merged['market_data_date'] = self.market_data_date_info.market_data_date.isoformat()
            merged['market_data_date_adjusted'] = self.market_data_date_info.was_adjusted
            merged['market_data_date_tooltip'] = self.market_data_date_info.tooltip_text
            if self.market_data_date_info.adjustment_reason:
                merged['market_data_date_adjustment_reason'] = self.market_data_date_info.adjustment_reason

        return merged

    def get_field_confidences(self) -> Dict[str, float]:
        """
        Get confidence scores for all fields.

        Confidence formula:
        - If LLMs agree: (100 + NER_score) / 2
        - If LLMs disagree: (0 + NER_score) / 2
        - NER_score = 100 if validated, else 0

        Returns:
            Dict of field_name -> confidence (0-100)
        """
        confidences = {}
        for cat_comparison in self.categories.values():
            for field_comp in cat_comparison.fields:
                confidences[field_comp.field_name] = field_comp.confidence
        return confidences

    def get_field_details(self) -> Dict[str, Dict[str, Any]]:
        """
        Get detailed info for all fields including confidence breakdown.

        Returns:
            Dict of field_name -> {value, confidence, llm_agree, ner_validated}
        """
        details = {}
        for cat_comparison in self.categories.values():
            for field_comp in cat_comparison.fields:
                details[field_comp.field_name] = {
                    "value": field_comp.claude_value,  # Use Claude as primary
                    "confidence": field_comp.confidence,
                    "llm_agree": field_comp.agrees,
                    "ner_validated": field_comp.ner_validated,
                    "claude_value": field_comp.claude_value,
                    "openai_value": field_comp.openai_value
                }
        return details


class VerificationOrchestrator:
    """Orchestrates dual LLM verification and comparison with multimodal support"""

    def __init__(
        self,
        anthropic_api_key: str,
        openai_api_key: str,
        examples_repository: Optional[ExamplesRepository] = None,
        trading_calendar_service: Optional[Any] = None,  # TradingCalendarService
        claude_model: str = "claude-opus-4-6",
        openai_model: str = "gpt-5.2"
    ):
        self.claude_service = ClaudeVerificationService(
            api_key=anthropic_api_key,
            model=claude_model
        )
        self.openai_service = OpenAIVerificationService(
            api_key=openai_api_key,
            model=openai_model
        )
        self.examples_repository = examples_repository
        self.trading_calendar_service = trading_calendar_service
        self._cached_example_texts: Optional[List[str]] = None

    def set_pdf_bytes(self, pdf_bytes: Optional[bytes]) -> bool:
        """
        Set PDF bytes for multimodal extraction on both services.

        Args:
            pdf_bytes: Raw PDF file bytes, or None to clear

        Returns:
            True if images were successfully set on at least one service
        """
        claude_ok = self.claude_service.set_pdf_images(pdf_bytes)
        openai_ok = self.openai_service.set_pdf_images(pdf_bytes)

        if pdf_bytes is not None:
            if claude_ok and openai_ok:
                logger.info("Multimodal mode enabled for both Claude and OpenAI")
            elif claude_ok or openai_ok:
                logger.warning("Multimodal mode partially enabled")
            else:
                logger.warning("Multimodal mode failed - falling back to text extraction")

        return claude_ok or openai_ok

    @property
    def is_multimodal(self) -> bool:
        """Return whether multimodal mode is active"""
        return self.claude_service.is_multimodal or self.openai_service.is_multimodal

    async def _load_example_texts(self) -> List[str]:
        """Load example texts from repository (with caching)"""
        if self._cached_example_texts is not None:
            return self._cached_example_texts

        if self.examples_repository is None:
            return []

        self._cached_example_texts = await self.examples_repository.get_example_texts()
        logger.info(f"Loaded {len(self._cached_example_texts)} example documents for classification")
        return self._cached_example_texts

    def clear_example_cache(self):
        """Clear cached examples (call if examples are updated)"""
        self._cached_example_texts = None

    async def _resolve_market_data_date(
        self,
        company_symbol: Optional[str],
        exercise_date_str: Optional[str]
    ) -> Optional[MarketDataDateInfo]:
        """
        Resolve the market data date for the extracted exercise date.

        Args:
            company_symbol: Extracted company symbol
            exercise_date_str: Extracted exercise date in ISO format (YYYY-MM-DD)

        Returns:
            MarketDataDateInfo or None if resolution not possible
        """
        if not self.trading_calendar_service:
            logger.debug("Trading calendar service not configured, skipping market data date resolution")
            return None

        if not company_symbol or not exercise_date_str:
            logger.warning("Missing company_symbol or exercise_date, cannot resolve market data date")
            return None

        try:
            # Parse the exercise date
            exercise_date = date.fromisoformat(exercise_date_str)

            # Resolve using trading calendar
            result = await self.trading_calendar_service.resolve_market_data_date_by_symbol(
                company_symbol=company_symbol,
                exercise_date=exercise_date
            )

            market_data_info = MarketDataDateInfo(
                exercise_date=result.exercise_date,
                market_data_date=result.market_data_date,
                was_adjusted=result.was_adjusted,
                adjustment_reason=result.adjustment_reason,
                tooltip_text=result.tooltip_text
            )

            if result.was_adjusted:
                logger.info(
                    f"Market data date adjusted: {exercise_date_str} -> {result.market_data_date} "
                    f"({result.adjustment_reason})"
                )
            else:
                logger.info(f"Market data date: {result.market_data_date} (no adjustment needed)")

            return market_data_info

        except ValueError as e:
            logger.warning(f"Failed to resolve market data date: {e}")
            return None
        except Exception as e:
            logger.error(f"Error resolving market data date: {e}")
            return None

    async def verify(
        self,
        document_text: str,
        email_subject: str,
        email_body: str,
        email_sender: str,
        few_shot_examples: Optional[Dict[VerificationCategory, List[Dict]]] = None,
        pdf_bytes: Optional[bytes] = None
    ) -> VerificationComparison:
        """
        Run both LLMs in parallel and compare results.

        Args:
            document_text: The ELOC document text (used as fallback/context)
            email_subject: Email subject line
            email_body: Email body text
            email_sender: Email sender address
            few_shot_examples: Optional few-shot examples per category
            pdf_bytes: Optional raw PDF bytes for multimodal extraction

        Returns:
            VerificationComparison with agreement/disagreement details
        """
        few_shot_examples = few_shot_examples or {}

        # Set up multimodal extraction - REQUIRED, no text fallback
        if pdf_bytes:
            success = self.set_pdf_bytes(pdf_bytes)
            if not self.is_multimodal:
                raise RuntimeError(
                    "Multimodal extraction failed - pdf2image/poppler not installed. "
                    "Install with: pip install pdf2image, and install poppler for Windows."
                )
            logger.info("Verification using multimodal extraction")
        else:
            raise RuntimeError(
                "PDF bytes required for extraction. Multimodal-only mode enabled."
            )

        # Load example texts from repository if available
        example_texts = await self._load_example_texts()

        # Run both services in parallel
        claude_task = self.claude_service.verify_all(
            document_text=document_text,
            email_subject=email_subject,
            email_body=email_body,
            email_sender=email_sender,
            few_shot_examples=few_shot_examples,
            classification_examples=example_texts
        )

        openai_task = self.openai_service.verify_all(
            document_text=document_text,
            email_subject=email_subject,
            email_body=email_body,
            email_sender=email_sender,
            few_shot_examples=few_shot_examples,
            classification_examples=example_texts
        )

        claude_result, openai_result = await asyncio.gather(
            claude_task, openai_task
        )

        # Compare results
        comparison = self._compare_results(claude_result, openai_result)

        # Apply confidence calculation (LLM agreement only, no NER)
        comparison = self._apply_confidence(comparison)

        # Log summary
        if comparison.passed:
            logger.info("Verification PASSED - Claude and OpenAI agree on all fields")
        else:
            disagreements = comparison.get_disagreements()
            logger.warning(
                f"Verification FAILED - {len(disagreements)} field(s) disagree: "
                f"{[d.field_name for d in disagreements]}"
            )

        # Resolve market data date if trading calendar service is configured
        if self.trading_calendar_service and comparison.passed:
            # Extract company_symbol and exercise_date from results
            company_cat = claude_result.categories.get(VerificationCategory.COMPANY)
            transaction_cat = claude_result.categories.get(VerificationCategory.TRANSACTION)

            company_symbol = None
            exercise_date_str = None

            if company_cat and company_cat.extracted_fields:
                company_symbol = company_cat.extracted_fields.get('company_symbol')

            if transaction_cat and transaction_cat.extracted_fields:
                exercise_date_str = transaction_cat.extracted_fields.get('vwap_purchase_exercise_date')

            # Resolve market data date
            market_data_info = await self._resolve_market_data_date(
                company_symbol=company_symbol,
                exercise_date_str=exercise_date_str
            )
            comparison.market_data_date_info = market_data_info

        return comparison

    def _compare_results(
        self,
        claude_result: VerificationResult,
        openai_result: VerificationResult
    ) -> VerificationComparison:
        """Compare Claude and OpenAI results field by field"""
        comparison = VerificationComparison(
            claude_result=claude_result,
            openai_result=openai_result
        )

        for category in VerificationCategory:
            claude_cat = claude_result.categories.get(category)
            openai_cat = openai_result.categories.get(category)

            cat_comparison = CategoryComparison(category=category)

            if claude_cat and claude_cat.error:
                cat_comparison.claude_error = claude_cat.error
            if openai_cat and openai_cat.error:
                cat_comparison.openai_error = openai_cat.error

            if claude_cat and openai_cat and not claude_cat.error and not openai_cat.error:
                # Compare fields
                all_fields = set(claude_cat.extracted_fields.keys()) | set(openai_cat.extracted_fields.keys())

                for field_name in all_fields:
                    claude_value = claude_cat.extracted_fields.get(field_name)
                    openai_value = openai_cat.extracted_fields.get(field_name)

                    agrees = self._values_match(claude_value, openai_value)

                    cat_comparison.fields.append(FieldComparison(
                        field_name=field_name,
                        claude_value=claude_value,
                        openai_value=openai_value,
                        agrees=agrees,
                        category=category
                    ))

            comparison.categories[category] = cat_comparison

        return comparison

    def _values_match(self, value1: Any, value2: Any) -> bool:
        """
        Check if two extracted values match.

        Handles:
        - String comparison (case-insensitive, whitespace-normalized)
        - Numeric comparison
        - Date comparison
        - List comparison
        - None/null handling
        """
        # Treat None and empty string as equivalent
        def is_empty(v):
            return v is None or (isinstance(v, str) and v.strip() == "")

        # Both empty (None or "")
        if is_empty(value1) and is_empty(value2):
            return True

        # One is empty, one has value
        if is_empty(value1) or is_empty(value2):
            return False

        # String comparison
        if isinstance(value1, str) and isinstance(value2, str):
            return self._normalize_string(value1) == self._normalize_string(value2)

        # Numeric comparison (with tolerance for floats)
        if isinstance(value1, (int, float)) and isinstance(value2, (int, float)):
            if isinstance(value1, int) and isinstance(value2, int):
                return value1 == value2
            return abs(float(value1) - float(value2)) < 0.01

        # Boolean comparison
        if isinstance(value1, bool) and isinstance(value2, bool):
            return value1 == value2

        # List comparison
        if isinstance(value1, list) and isinstance(value2, list):
            if len(value1) != len(value2):
                return False
            return all(self._values_match(v1, v2) for v1, v2 in zip(sorted(str(v) for v in value1), sorted(str(v) for v in value2)))

        # Default: string comparison
        return self._normalize_string(str(value1)) == self._normalize_string(str(value2))

    def _normalize_string(self, s: str) -> str:
        """Normalize string for comparison"""
        return " ".join(s.lower().strip().split())

    def _apply_confidence(
        self,
        comparison: VerificationComparison
    ) -> VerificationComparison:
        """
        Apply confidence calculation based on LLM agreement.

        Confidence:
        - LLMs agree: 100%
        - LLMs disagree: 0%

        Args:
            comparison: The comparison result from LLM extraction

        Returns:
            Updated comparison with confidence scores
        """
        field_count = 0
        agree_count = 0

        for cat_comparison in comparison.categories.values():
            for field_comp in cat_comparison.fields:
                field_count += 1
                # LLM agreement only: agree=100%, disagree=0%
                field_comp.confidence = 100.0 if field_comp.agrees else 0.0
                field_comp.ner_validated = False  # NER not used
                if field_comp.agrees:
                    agree_count += 1

        comparison.ner_applied = False
        logger.info(f"Confidence applied - LLM agreement: {agree_count}/{field_count} fields")

        return comparison


@dataclass
class SignatureFieldComparison:
    """Comparison result for a single signature field"""
    field_name: str
    claude_value: Any
    openai_value: Any
    agrees: bool
    confidence: float = 0.0


@dataclass
class SignatureVerificationComparison:
    """Complete comparison between Claude and OpenAI signature verification results"""
    claude_fields: Dict[str, Any]
    openai_fields: Dict[str, Any]
    field_comparisons: List[SignatureFieldComparison] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    claude_error: Optional[str] = None
    openai_error: Optional[str] = None
    duration_ms: float = 0.0

    @property
    def all_agree(self) -> bool:
        """Check if all fields agree"""
        if self.claude_error or self.openai_error:
            return False
        return all(f.agrees for f in self.field_comparisons)

    @property
    def passed(self) -> bool:
        return self.all_agree

    @property
    def investor_signed(self) -> bool:
        """Get purchase_confirmation_investor_signature from merged results (Claude primary)"""
        return self.claude_fields.get("purchase_confirmation_investor_signature", False)

    @property
    def company_signed(self) -> bool:
        """Get purchase_confirmation_company_signature from merged results (Claude primary)"""
        return self.claude_fields.get("purchase_confirmation_company_signature", False)

    @property
    def both_signed(self) -> bool:
        """Check if both parties signed"""
        return self.investor_signed and self.company_signed

    @property
    def agreement_summary(self) -> Dict[str, Any]:
        """Get summary of agreements"""
        agreed = sum(1 for f in self.field_comparisons if f.agrees)
        total = len(self.field_comparisons)
        return {
            "fields_agreed": agreed,
            "total_fields": total,
            "agreement_rate": agreed / total if total > 0 else 0,
            "all_agree": self.all_agree,
            "claude_error": self.claude_error,
            "openai_error": self.openai_error
        }

    def get_disagreements(self) -> List[SignatureFieldComparison]:
        """Get all fields where Claude and OpenAI disagreed"""
        return [f for f in self.field_comparisons if not f.agrees]

    def get_merged_fields(self) -> Dict[str, Any]:
        """Get merged fields using Claude as primary"""
        return dict(self.claude_fields)

    def get_field_confidences(self) -> Dict[str, float]:
        """Get confidence scores for all fields"""
        return {f.field_name: f.confidence for f in self.field_comparisons}


class SignatureVerificationOrchestrator:
    """Orchestrates dual LLM signature verification for Purchase Confirmations with multimodal support"""

    def __init__(
        self,
        anthropic_api_key: str,
        openai_api_key: str,
        claude_model: str = "claude-opus-4-6",
        openai_model: str = "gpt-5.2"
    ):
        self.claude_service = ClaudeVerificationService(
            api_key=anthropic_api_key,
            model=claude_model
        )
        self.openai_service = OpenAIVerificationService(
            api_key=openai_api_key,
            model=openai_model
        )

    def set_pdf_bytes(self, pdf_bytes: Optional[bytes]) -> bool:
        """
        Set PDF bytes for multimodal extraction on both services.

        Args:
            pdf_bytes: Raw PDF file bytes, or None to clear

        Returns:
            True if images were successfully set on at least one service
        """
        claude_ok = self.claude_service.set_pdf_images(pdf_bytes)
        openai_ok = self.openai_service.set_pdf_images(pdf_bytes)
        return claude_ok or openai_ok

    @property
    def is_multimodal(self) -> bool:
        """Return whether multimodal mode is active"""
        return self.claude_service.is_multimodal or self.openai_service.is_multimodal

    async def verify_signatures(
        self,
        document_text: str,
        few_shot_examples: Optional[List[Dict]] = None,
        pdf_bytes: Optional[bytes] = None
    ) -> SignatureVerificationComparison:
        """
        Run both LLMs in parallel to verify signatures on a Purchase Confirmation.

        Args:
            document_text: The Purchase Confirmation document text
            few_shot_examples: Optional few-shot examples for signature verification
            pdf_bytes: Optional raw PDF bytes for multimodal extraction

        Returns:
            SignatureVerificationComparison with agreement/disagreement details
        """
        import time
        start_time = time.time()

        # Set up multimodal extraction - REQUIRED, no text fallback
        if pdf_bytes:
            self.set_pdf_bytes(pdf_bytes)
            if not self.is_multimodal:
                raise RuntimeError(
                    "Multimodal extraction failed - pdf2image/poppler not installed. "
                    "Install with: pip install pdf2image, and install poppler for Windows."
                )
            logger.info("Signature verification using multimodal extraction")
        else:
            raise RuntimeError(
                "PDF bytes required for signature verification. Multimodal-only mode enabled."
            )

        # Run both services in parallel
        claude_task = self.claude_service.verify_confirmation_signature(
            document_text=document_text,
            few_shot_examples=few_shot_examples
        )

        openai_task = self.openai_service.verify_confirmation_signature(
            document_text=document_text,
            few_shot_examples=few_shot_examples
        )

        claude_result, openai_result = await asyncio.gather(
            claude_task, openai_task
        )

        duration_ms = (time.time() - start_time) * 1000

        # Create comparison
        comparison = SignatureVerificationComparison(
            claude_fields=claude_result.extracted_fields,
            openai_fields=openai_result.extracted_fields,
            claude_error=claude_result.error,
            openai_error=openai_result.error,
            duration_ms=duration_ms
        )

        # Compare fields if both succeeded
        if not claude_result.error and not openai_result.error:
            comparison.field_comparisons = self._compare_fields(
                claude_result.extracted_fields,
                openai_result.extracted_fields
            )

        # Log summary
        if comparison.passed:
            logger.info(
                f"Signature verification PASSED - Claude and OpenAI agree "
                f"(investor={comparison.investor_signed}, company={comparison.company_signed}) "
                f"in {duration_ms:.0f}ms"
            )
        else:
            disagreements = comparison.get_disagreements()
            if comparison.claude_error or comparison.openai_error:
                logger.error(
                    f"Signature verification ERROR - Claude: {comparison.claude_error}, "
                    f"OpenAI: {comparison.openai_error}"
                )
            else:
                logger.warning(
                    f"Signature verification DISAGREEMENT - {len(disagreements)} field(s) disagree: "
                    f"{[d.field_name for d in disagreements]} in {duration_ms:.0f}ms"
                )

        return comparison

    def _compare_fields(
        self,
        claude_fields: Dict[str, Any],
        openai_fields: Dict[str, Any]
    ) -> List[SignatureFieldComparison]:
        """Compare Claude and OpenAI fields"""
        comparisons = []

        # Define fields to compare and their importance
        fields_to_compare = [
            "purchase_confirmation_investor_signature",
            "purchase_confirmation_company_signature",
            "investor_signatory",
            "company_signatory",
            "investor_company",
            "target_company",
            "company_symbol",
            "vwap_purchase_share_amount",
            "vwap_purchase_exercise_date",
        ]

        for field_name in fields_to_compare:
            claude_value = claude_fields.get(field_name)
            openai_value = openai_fields.get(field_name)

            agrees = self._values_match(claude_value, openai_value)

            # Calculate confidence: 100% if agree, 0% if disagree
            # (No NER validation for signature fields)
            confidence = 100.0 if agrees else 0.0

            comparisons.append(SignatureFieldComparison(
                field_name=field_name,
                claude_value=claude_value,
                openai_value=openai_value,
                agrees=agrees,
                confidence=confidence
            ))

        return comparisons

    def _values_match(self, value1: Any, value2: Any) -> bool:
        """Check if two extracted values match"""
        # Treat None and empty string as equivalent
        def is_empty(v):
            return v is None or (isinstance(v, str) and v.strip() == "")

        # Both empty
        if is_empty(value1) and is_empty(value2):
            return True

        # One empty, one has value
        if is_empty(value1) or is_empty(value2):
            return False

        # Boolean comparison
        if isinstance(value1, bool) and isinstance(value2, bool):
            return value1 == value2

        # Numeric comparison
        if isinstance(value1, (int, float)) and isinstance(value2, (int, float)):
            if isinstance(value1, int) and isinstance(value2, int):
                return value1 == value2
            return abs(float(value1) - float(value2)) < 0.01

        # String comparison (case-insensitive, whitespace-normalized)
        if isinstance(value1, str) and isinstance(value2, str):
            return self._normalize_string(value1) == self._normalize_string(value2)

        # Default: string comparison
        return self._normalize_string(str(value1)) == self._normalize_string(str(value2))

    def _normalize_string(self, s: str) -> str:
        """Normalize string for comparison"""
        return " ".join(s.lower().strip().split())


# Global instances (initialized in main.py)
verification_orchestrator: Optional[VerificationOrchestrator] = None
signature_verification_orchestrator: Optional[SignatureVerificationOrchestrator] = None
