"""
Verification orchestrator - runs Claude and OpenAI in parallel and compares results.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
from datetime import datetime, UTC

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
class FieldComparison:
    """Comparison result for a single field"""
    field_name: str
    claude_value: Any
    openai_value: Any
    agrees: bool
    category: VerificationCategory


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


class VerificationOrchestrator:
    """Orchestrates dual LLM verification and comparison"""

    def __init__(
        self,
        anthropic_api_key: str,
        openai_api_key: str,
        examples_repository: Optional[ExamplesRepository] = None,
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

        # Log summary
        if comparison.passed:
            logger.info("Verification PASSED - Claude and OpenAI agree on all fields")
        else:
            disagreements = comparison.get_disagreements()
            logger.warning(
                f"Verification FAILED - {len(disagreements)} field(s) disagree: "
                f"{[d.field_name for d in disagreements]}"
            )

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
        # Both None/null
        if value1 is None and value2 is None:
            return True

        # One is None
        if value1 is None or value2 is None:
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


# Global instance (initialized in main.py)
verification_orchestrator: Optional[VerificationOrchestrator] = None
