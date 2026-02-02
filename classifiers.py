"""
Document classification classes - LLM-based (Claude + OpenAI)

Classifies documents into three types:
- PURCHASE_NOTICE: VWAP Purchase Notice (requires extraction)
- PURCHASE_CONFIRMATION: Countersigned confirmation (requires signature verification)
- NOT_RELEVANT: Neither of the above

Uses dual LLM classification with Claude and OpenAI for robust results.
"""
from typing import Dict, List, Optional, Any
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class DocumentType(str, Enum):
    """Document classification types"""
    PURCHASE_NOTICE = "PURCHASE_NOTICE"
    PURCHASE_CONFIRMATION = "PURCHASE_CONFIRMATION"
    NOT_RELEVANT = "NOT_RELEVANT"
    UNCERTAIN = "UNCERTAIN"
    ERROR = "ERROR"


class ClaudeClassifier:
    """Classify documents using Claude API with few-shot examples"""

    def __init__(self, api_key: str):
        """Initialize with Anthropic API key"""
        self.few_shot_examples: Dict[str, List[str]] = {}
        try:
            from anthropic import Anthropic
            self.client = Anthropic(api_key=api_key)
            self.available = True
            logger.info("Claude classifier initialized")
        except ImportError:
            logger.error("anthropic not installed - pip install anthropic")
            self.available = False
        except Exception as e:
            logger.error(f"Failed to initialize Claude: {e}")
            self.available = False

    async def load_few_shot_examples(self, examples_repository) -> int:
        """
        Load few-shot examples from MongoDB for improved classification.

        Args:
            examples_repository: ExamplesRepository instance

        Returns:
            Total number of examples loaded
        """
        try:
            self.few_shot_examples = await examples_repository.get_few_shot_examples(max_per_type=1)
            total = sum(len(v) for v in self.few_shot_examples.values())
            logger.info(f"Claude classifier: loaded {total} few-shot examples")
            return total
        except Exception as e:
            logger.error(f"Failed to load few-shot examples for Claude: {e}")
            return 0

    def _build_few_shot_section(self) -> str:
        """Build the few-shot examples section for the prompt"""
        if not self.few_shot_examples:
            return ""

        sections = []

        notice_examples = self.few_shot_examples.get("PURCHASE_NOTICE", [])
        if notice_examples:
            sections.append("=== EXAMPLE PURCHASE_NOTICE DOCUMENT ===")
            for i, ex in enumerate(notice_examples, 1):
                sections.append(f"[Example {i} - truncated for brevity]")
                sections.append(ex[:1500])  # Truncate for prompt size
            sections.append("")

        confirm_examples = self.few_shot_examples.get("PURCHASE_CONFIRMATION", [])
        if confirm_examples:
            sections.append("=== EXAMPLE PURCHASE_CONFIRMATION DOCUMENT ===")
            for i, ex in enumerate(confirm_examples, 1):
                sections.append(f"[Example {i} - truncated for brevity]")
                sections.append(ex[:1500])
            sections.append("")

        return "\n".join(sections)

    def classify(self, text: str) -> Dict:
        """
        Classify document using Claude API with few-shot examples

        Returns:
            dict with classification, confidence, and reasoning
        """
        if not self.available:
            logger.error("Claude classifier not available")
            return {
                "classification": "ERROR",
                "confidence": "NONE",
                "error": "Classifier not available"
            }

        try:
            # Truncate text for classification (use first 3000 tokens ≈ 12000 chars)
            text_sample = text[:12000]

            # Build few-shot examples section
            few_shot_section = self._build_few_shot_section()
            few_shot_intro = ""
            if few_shot_section:
                few_shot_intro = """
Below are REAL examples from our database. Use these to understand the exact format and style of each document type.

"""

            prompt = f"""You are a document classifier for a financial services company.

Classify the following document into one of three categories:
- PURCHASE_NOTICE
- PURCHASE_CONFIRMATION
- NOT_RELEVANT

**MANDATORY FIRST STEP**: Look at the FIRST LINE of the document. The document title determines the classification:

- Title contains "CONFIRMATION" → PURCHASE_CONFIRMATION (even if it looks like a notice)
- Title contains "NOTICE" (and NOT "CONFIRMATION") → PURCHASE_NOTICE

=== PURCHASE_CONFIRMATION ===
TITLE: "VWAP Purchase Confirmation" or "Form of VWAP Purchase Confirmation"
- The title/header says "Confirmation" - this OVERRIDES all other signals
- Issued BY THE INVESTOR (Tumim Stone Capital) TO the company
- Text says "Investor hereby issues this VWAP Purchase Confirmation"
- Typically has signatures from BOTH investor and company

=== PURCHASE_NOTICE ===
TITLE: "VWAP Purchase Notice" or "Form of VWAP Purchase Notice"
- The title/header says "Notice" (NOT "Confirmation")
- Issued BY THE COMPANY TO the investor
- Text says "Company hereby delivers this VWAP Purchase Notice"
- Typically has signature from company only

=== NOT_RELEVANT ===
- No "Purchase Notice" or "Purchase Confirmation" in the title
- General emails, announcements, other documents
{few_shot_intro}{few_shot_section}
=== DOCUMENT TO CLASSIFY ===
{text_sample}

STEP 1: What is the EXACT title on the first line?
STEP 2: Does it contain "CONFIRMATION" or "NOTICE"?
STEP 3: Classify based on the title.

Respond with JSON only:
{{
  "classification": "PURCHASE_NOTICE" or "PURCHASE_CONFIRMATION" or "NOT_RELEVANT",
  "confidence": "HIGH" or "MEDIUM" or "LOW",
  "reasoning": "The title says [exact title] which contains [CONFIRMATION/NOTICE]"
}}"""

            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}]
            )

            import json
            result_text = response.content[0].text.strip()

            # Remove markdown code blocks if present
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
                result_text = result_text.strip()

            result = json.loads(result_text)

            logger.info(f"Claude classification: {result['classification']} ({result['confidence']})")

            result["method"] = "claude_api"
            result["few_shot_used"] = bool(few_shot_section)
            return result

        except Exception as e:
            logger.error(f"Claude classification error: {e}")
            return {
                "classification": "ERROR",
                "confidence": "NONE",
                "error": str(e),
                "method": "claude_api"
            }


class OpenAIClassifier:
    """Classify documents using OpenAI API with few-shot examples"""

    def __init__(self, api_key: str):
        """Initialize with OpenAI API key"""
        self.few_shot_examples: Dict[str, List[str]] = {}
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key)
            self.available = True
            logger.info("OpenAI classifier initialized")
        except ImportError:
            logger.error("openai not installed - pip install openai")
            self.available = False
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI: {e}")
            self.available = False

    async def load_few_shot_examples(self, examples_repository) -> int:
        """
        Load few-shot examples from MongoDB for improved classification.

        Args:
            examples_repository: ExamplesRepository instance

        Returns:
            Total number of examples loaded
        """
        try:
            self.few_shot_examples = await examples_repository.get_few_shot_examples(max_per_type=1)
            total = sum(len(v) for v in self.few_shot_examples.values())
            logger.info(f"OpenAI classifier: loaded {total} few-shot examples")
            return total
        except Exception as e:
            logger.error(f"Failed to load few-shot examples for OpenAI: {e}")
            return 0

    def _build_few_shot_section(self) -> str:
        """Build the few-shot examples section for the prompt"""
        if not self.few_shot_examples:
            return ""

        sections = []

        notice_examples = self.few_shot_examples.get("PURCHASE_NOTICE", [])
        if notice_examples:
            sections.append("=== EXAMPLE PURCHASE_NOTICE DOCUMENT ===")
            for i, ex in enumerate(notice_examples, 1):
                sections.append(f"[Example {i} - truncated for brevity]")
                sections.append(ex[:1500])
            sections.append("")

        confirm_examples = self.few_shot_examples.get("PURCHASE_CONFIRMATION", [])
        if confirm_examples:
            sections.append("=== EXAMPLE PURCHASE_CONFIRMATION DOCUMENT ===")
            for i, ex in enumerate(confirm_examples, 1):
                sections.append(f"[Example {i} - truncated for brevity]")
                sections.append(ex[:1500])
            sections.append("")

        return "\n".join(sections)

    def classify(self, text: str) -> Dict:
        """
        Classify document using OpenAI API with few-shot examples

        Returns:
            dict with classification, confidence, and reasoning
        """
        if not self.available:
            logger.error("OpenAI classifier not available")
            return {
                "classification": "ERROR",
                "confidence": "NONE",
                "error": "Classifier not available"
            }

        try:
            # Truncate text for classification
            text_sample = text[:12000]

            # Build few-shot examples section
            few_shot_section = self._build_few_shot_section()
            few_shot_intro = ""
            if few_shot_section:
                few_shot_intro = """
Below are REAL examples from our database. Use these to understand the exact format and style of each document type.

"""

            prompt = f"""You are a document classifier for a financial services company.

Classify the following document into one of three categories:
- PURCHASE_NOTICE
- PURCHASE_CONFIRMATION
- NOT_RELEVANT

**MANDATORY FIRST STEP**: Look at the FIRST LINE of the document. The document title determines the classification:

- Title contains "CONFIRMATION" → PURCHASE_CONFIRMATION (even if it looks like a notice)
- Title contains "NOTICE" (and NOT "CONFIRMATION") → PURCHASE_NOTICE

=== PURCHASE_CONFIRMATION ===
TITLE: "VWAP Purchase Confirmation" or "Form of VWAP Purchase Confirmation"
- The title/header says "Confirmation" - this OVERRIDES all other signals
- Issued BY THE INVESTOR (Tumim Stone Capital) TO the company
- Text says "Investor hereby issues this VWAP Purchase Confirmation"
- Typically has signatures from BOTH investor and company

=== PURCHASE_NOTICE ===
TITLE: "VWAP Purchase Notice" or "Form of VWAP Purchase Notice"
- The title/header says "Notice" (NOT "Confirmation")
- Issued BY THE COMPANY TO the investor
- Text says "Company hereby delivers this VWAP Purchase Notice"
- Typically has signature from company only

=== NOT_RELEVANT ===
- No "Purchase Notice" or "Purchase Confirmation" in the title
- General emails, announcements, other documents
{few_shot_intro}{few_shot_section}
=== DOCUMENT TO CLASSIFY ===
{text_sample}

STEP 1: What is the EXACT title on the first line?
STEP 2: Does it contain "CONFIRMATION" or "NOTICE"?
STEP 3: Classify based on the title.

Respond with JSON only:
{{
  "classification": "PURCHASE_NOTICE" or "PURCHASE_CONFIRMATION" or "NOT_RELEVANT",
  "confidence": "HIGH" or "MEDIUM" or "LOW",
  "reasoning": "The title says [exact title] which contains [CONFIRMATION/NOTICE]"
}}"""

            response = self.client.chat.completions.create(
                model="gpt-4o",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}]
            )

            import json
            result_text = response.choices[0].message.content.strip()

            # Remove markdown code blocks if present
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
                result_text = result_text.strip()

            result = json.loads(result_text)

            logger.info(f"OpenAI classification: {result['classification']} ({result['confidence']})")

            result["method"] = "openai_api"
            result["few_shot_used"] = bool(few_shot_section)
            return result

        except Exception as e:
            logger.error(f"OpenAI classification error: {e}")
            return {
                "classification": "ERROR",
                "confidence": "NONE",
                "error": str(e),
                "method": "openai_api"
            }


class DualLLMClassifier:
    """Combine Claude and OpenAI classifiers for robust classification (no similarity)"""

    def __init__(self, anthropic_api_key: str, openai_api_key: str, references_dir: str = "references"):
        """Initialize both LLM classifiers"""
        self.claude = ClaudeClassifier(anthropic_api_key)
        self.openai = OpenAIClassifier(openai_api_key)
        self._examples_repository = None
        logger.info("Dual LLM classifier initialized (Claude + OpenAI)")

    async def load_mongodb_examples(self, examples_repository) -> int:
        """
        Load few-shot examples from MongoDB for both LLM classifiers.

        Args:
            examples_repository: ExamplesRepository instance

        Returns:
            Number of examples loaded
        """
        self._examples_repository = examples_repository

        # Load few-shot examples for LLM classifiers
        claude_count = await self.claude.load_few_shot_examples(examples_repository)
        openai_count = await self.openai.load_few_shot_examples(examples_repository)

        total = claude_count + openai_count
        logger.info(f"DualLLMClassifier: Few-shot examples loaded - Claude: {claude_count}, OpenAI: {openai_count}")

        return total

    @property
    def is_dual_mode(self) -> bool:
        """Return True (always dual LLM mode)"""
        return True

    @property
    def examples_source(self) -> str:
        """Return the source of loaded examples"""
        if self._examples_repository:
            return "mongodb"
        return "none"

    def classify(self, text: str) -> Dict:
        """
        Classify using both LLMs: Claude and OpenAI.

        Uses consensus voting for final classification among:
        - PURCHASE_NOTICE
        - PURCHASE_CONFIRMATION
        - NOT_RELEVANT

        Returns:
            dict with final classification and details from both classifiers
        """
        logger.info("Starting dual LLM classification (Claude + OpenAI)...")

        # Call both LLMs for classification
        claude_result = self.claude.classify(text)
        openai_result = self.openai.classify(text)

        # Collect votes (excluding ERROR results)
        votes = {}
        if claude_result["classification"] not in ["ERROR"]:
            votes["claude"] = claude_result["classification"]
        if openai_result["classification"] not in ["ERROR"]:
            votes["openai"] = openai_result["classification"]

        # Count votes by category
        vote_counts = {
            DocumentType.PURCHASE_NOTICE.value: 0,
            DocumentType.PURCHASE_CONFIRMATION.value: 0,
            DocumentType.NOT_RELEVANT.value: 0
        }
        for classifier, vote in votes.items():
            if vote in vote_counts:
                vote_counts[vote] += 1

        total_votes = len(votes)

        # Determine final classification
        if total_votes == 0:
            final_classification = DocumentType.ERROR.value
            final_confidence = "NONE"
            agreement = "none"
            logger.error("Both classifiers failed")
        elif total_votes == 1:
            # Only one classifier succeeded - use its result with low confidence
            final_classification = list(votes.values())[0]
            final_confidence = "LOW"
            agreement = "single"
            logger.warning(f"Only one classifier succeeded: {list(votes.keys())[0]}")
        else:
            # Both LLMs voted
            if claude_result["classification"] == openai_result["classification"]:
                # Full agreement
                final_classification = claude_result["classification"]
                final_confidence = "HIGH"
                agreement = "unanimous"
            else:
                # Disagreement - flag as uncertain
                final_classification = DocumentType.UNCERTAIN.value
                final_confidence = "LOW"
                agreement = "split"
                logger.warning(
                    f"LLM disagreement: Claude={claude_result['classification']}, "
                    f"OpenAI={openai_result['classification']}"
                )

        # Log voting details
        vote_summary = ", ".join([f"{name}={vote}" for name, vote in votes.items()])
        logger.info(f"Votes: {vote_summary}")
        logger.info(f"Final: {final_classification} ({final_confidence}) - {agreement}")

        return {
            "final_classification": final_classification,
            "final_confidence": final_confidence,
            "similarity_result": None,  # No similarity - backward compat
            "claude_result": claude_result,
            "openai_result": openai_result,
            "votes": votes,
            "vote_counts": vote_counts,
            "agreement": agreement,
            "method": "dual_llm_classification",
            "dual_mode": True
        }


# Backward compatibility aliases
TripleClassifier = DualLLMClassifier
DualClassifier = DualLLMClassifier