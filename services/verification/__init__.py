"""
Verification services for ELOC extraction validation.

Uses dual LLM approach (Claude + OpenAI) to verify extracted fields.
Agreement between both models = PASS, disagreement = requires human review.
"""
from services.verification.base import (
    VerificationResult,
    CategoryResult,
    BaseVerificationService,
    VerificationCategory
)
from services.verification.claude_service import ClaudeVerificationService
from services.verification.openai_service import OpenAIVerificationService
from services.verification.orchestrator import (
    VerificationOrchestrator,
    VerificationComparison,
    MarketDataDateInfo,
    FieldComparison,
    CategoryComparison
)
from services.verification.examples_repository import ExamplesRepository, examples_repository

__all__ = [
    "VerificationResult",
    "CategoryResult",
    "BaseVerificationService",
    "VerificationCategory",
    "ClaudeVerificationService",
    "OpenAIVerificationService",
    "VerificationOrchestrator",
    "VerificationComparison",
    "MarketDataDateInfo",
    "FieldComparison",
    "CategoryComparison",
    "ExamplesRepository",
    "examples_repository",
]
