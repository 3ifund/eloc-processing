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
from services.verification.ner_service import NERVerificationService, get_ner_service

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
    """Orchestrates dual LLM verification and comparison"""

    def __init__(
        self,
        anthropic_api_key: str,
        openai_api_key: str,
        examples_repository: Optional[ExamplesRepository] = None,
        trading_calendar_service: Optional[Any] = None,  # TradingCalendarService
        claude_model: str = "claude-sonnet-4-20250514",
        openai_model: str = "gpt-4o"
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
        few_shot_examples: Optional[Dict[VerificationCategory, List[Dict]]] = None
    ) -> VerificationComparison:
        """
        Run both LLMs in parallel and compare results.

        Args:
            document_text: The ELOC document text
            email_subject: Email subject line
            email_body: Email body text
            email_sender: Email sender address
            few_shot_examples: Optional few-shot examples per category

        Returns:
            VerificationComparison with agreement/disagreement details
        """
        few_shot_examples = few_shot_examples or {}

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

        # Apply NER validation for confidence calculation
        comparison = self._apply_ner_validation(comparison, document_text)

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

    def _apply_ner_validation(
        self,
        comparison: VerificationComparison,
        document_text: str
    ) -> VerificationComparison:
        """
        Apply NER validation to calculate field confidences.

        Confidence formula:
        - If LLMs agree: (100 + NER_score) / 2
        - If LLMs disagree: (0 + NER_score) / 2
        - NER_score = 100 if value found with >0.9 confidence, else 0

        Args:
            comparison: The comparison result from LLM extraction
            document_text: Original document text for NER

        Returns:
            Updated comparison with NER validation and confidence scores
        """
        try:
            ner_service = get_ner_service()

            # Get all extracted fields for NER validation
            merged_fields = comparison.get_merged_fields()

            # Run NER extraction once
            ner_results = ner_service.validate_extraction(merged_fields, document_text)

            # Update each field comparison with NER validation and confidence
            for cat_comparison in comparison.categories.values():
                for field_comp in cat_comparison.fields:
                    ner_result = ner_results.get(field_comp.field_name)

                    # Check if NER validated this field
                    ner_validated = False
                    if ner_result and ner_result.found_in_ner:
                        ner_validated = True

                    # Calculate confidence using the simple formula
                    llm_score = 100 if field_comp.agrees else 0
                    ner_score = 100 if ner_validated else 0
                    confidence = (llm_score + ner_score) / 2

                    # Update field comparison
                    field_comp.ner_validated = ner_validated
                    field_comp.confidence = confidence

            comparison.ner_applied = True
            logger.info(
                f"NER validation applied - Fields validated: "
                f"{sum(1 for c in comparison.categories.values() for f in c.fields if f.ner_validated)}"
            )

        except Exception as e:
            logger.warning(f"NER validation failed: {e} - using LLM agreement only")
            # Fall back to LLM agreement only
            for cat_comparison in comparison.categories.values():
                for field_comp in cat_comparison.fields:
                    # Without NER: agree=50%, disagree=0%
                    field_comp.confidence = 50.0 if field_comp.agrees else 0.0
                    field_comp.ner_validated = False

        return comparison


# Global instance (initialized in main.py)
verification_orchestrator: Optional[VerificationOrchestrator] = None
