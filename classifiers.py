"""
Document classification classes - Similarity and LLM-based

Classifies documents into three types:
- PURCHASE_NOTICE: VWAP Purchase Notice (requires extraction)
- PURCHASE_CONFIRMATION: Countersigned confirmation (requires signature verification)
- NOT_RELEVANT: Neither of the above

Supports loading reference documents from:
1. MongoDB purchase_notice_examples collection (preferred)
2. Local text files in references directory (fallback)
"""
from typing import Dict, List, Optional, Any
import logging
from pathlib import Path
import os
from enum import Enum

logger = logging.getLogger(__name__)


class DocumentType(str, Enum):
    """Document classification types"""
    PURCHASE_NOTICE = "PURCHASE_NOTICE"
    PURCHASE_CONFIRMATION = "PURCHASE_CONFIRMATION"
    NOT_RELEVANT = "NOT_RELEVANT"
    UNCERTAIN = "UNCERTAIN"
    ERROR = "ERROR"


class SimilarityClassifier:
    """Classify documents using dual similarity scoring against typed examples"""

    def __init__(self, references_dir: str = "references"):
        """
        Initialize with reference ELOC documents from local files.

        For MongoDB examples with type-based scoring, call load_mongodb_examples() after initialization.

        Args:
            references_dir: Directory containing reference ELOC text files
        """
        self.references_dir = references_dir
        # Legacy: single list for backward compatibility
        self.reference_examples: List[str] = []
        self.reference_embeddings: List[Any] = []

        # New: type-separated examples and embeddings for dual scoring
        self.notice_examples: List[str] = []
        self.notice_embeddings: List[Any] = []
        self.confirmation_examples: List[str] = []
        self.confirmation_embeddings: List[Any] = []

        self._mongodb_loaded = False
        self._dual_mode = False  # True when type-separated examples are loaded

        try:
            from sentence_transformers import SentenceTransformer
            import numpy as np

            self.model = SentenceTransformer('all-MiniLM-L6-v2')
            self.np = np
            self.available = True

            # Load from local files initially (legacy mode)
            logger.info("Loading reference ELOC documents...")
            self.reference_examples = self._load_references(references_dir)

            if not self.reference_examples:
                logger.warning(f"No reference documents found in {references_dir}")
                self.reference_embeddings = []
            else:
                self._compute_embeddings()

        except ImportError:
            logger.error("sentence-transformers not installed - pip install sentence-transformers")
            self.available = False

    def _extract_text_for_embedding(self, text: str, max_chars: int = 3000) -> str:
        """
        Extract text for embedding, including both beginning and end of document.

        Signatures are typically at the bottom, so we need to capture both:
        - Beginning: Title, headers, document type indicators
        - End: Signature blocks, "AGREED AND ACCEPTED" sections

        Args:
            text: Full document text
            max_chars: Maximum characters to use (default 3000)

        Returns:
            Combined text from beginning and end of document
        """
        if len(text) <= max_chars:
            return text

        # Split: 60% from beginning (title, headers), 40% from end (signatures)
        begin_chars = int(max_chars * 0.6)  # 1800 chars
        end_chars = max_chars - begin_chars  # 1200 chars

        beginning = text[:begin_chars]
        ending = text[-end_chars:]

        # Combine with separator to avoid word joining
        return beginning + "\n...\n" + ending

    def _compute_embeddings(self):
        """Compute embeddings for all reference examples (legacy single-list mode)"""
        if not self.reference_examples:
            self.reference_embeddings = []
            return

        logger.info(f"Computing embeddings for {len(self.reference_examples)} references...")
        self.reference_embeddings = [
            self.model.encode(self._extract_text_for_embedding(ref)) for ref in self.reference_examples
        ]
        logger.info("Similarity classifier ready")

    def _compute_typed_embeddings(self):
        """Compute embeddings for type-separated examples (dual mode)"""
        if self.notice_examples:
            logger.info(f"Computing embeddings for {len(self.notice_examples)} PURCHASE_NOTICE examples...")
            self.notice_embeddings = [
                self.model.encode(self._extract_text_for_embedding(ref)) for ref in self.notice_examples
            ]
        else:
            self.notice_embeddings = []

        if self.confirmation_examples:
            logger.info(f"Computing embeddings for {len(self.confirmation_examples)} PURCHASE_CONFIRMATION examples...")
            self.confirmation_embeddings = [
                self.model.encode(self._extract_text_for_embedding(ref)) for ref in self.confirmation_examples
            ]
        else:
            self.confirmation_embeddings = []

        logger.info("Dual similarity classifier ready")

    async def load_mongodb_examples(self, examples_repository) -> int:
        """
        Load reference examples from MongoDB with type separation for dual scoring.

        This loads examples by document type (PURCHASE_NOTICE, PURCHASE_CONFIRMATION)
        and enables dual similarity scoring mode.

        Args:
            examples_repository: ExamplesRepository instance

        Returns:
            Total number of examples loaded
        """
        if not self.available:
            logger.warning("Similarity classifier not available, cannot load MongoDB examples")
            return 0

        try:
            logger.info("Loading reference examples from MongoDB by type...")

            # Load examples with their types
            texts_with_types = await examples_repository.get_example_texts_with_types()

            if not texts_with_types:
                logger.warning("No examples found in MongoDB, keeping local files")
                return 0

            # Separate by type
            self.notice_examples = []
            self.confirmation_examples = []

            for text, doc_type in texts_with_types:
                if doc_type == DocumentType.PURCHASE_NOTICE.value:
                    self.notice_examples.append(text)
                elif doc_type == DocumentType.PURCHASE_CONFIRMATION.value:
                    self.confirmation_examples.append(text)

            # Also keep combined list for backward compatibility
            self.reference_examples = [text for text, _ in texts_with_types]

            # Compute type-separated embeddings
            self._compute_typed_embeddings()
            # Also compute combined embeddings for backward compatibility
            self._compute_embeddings()

            self._mongodb_loaded = True
            self._dual_mode = len(self.notice_examples) > 0 and len(self.confirmation_examples) > 0

            logger.info(
                f"Loaded {len(self.notice_examples)} PURCHASE_NOTICE, "
                f"{len(self.confirmation_examples)} PURCHASE_CONFIRMATION examples from MongoDB"
            )
            logger.info(f"Dual mode: {self._dual_mode}")

            return len(texts_with_types)

        except Exception as e:
            logger.error(f"Failed to load MongoDB examples: {e}")
            return 0

    @property
    def examples_source(self) -> str:
        """Return the source of loaded examples"""
        if self._mongodb_loaded:
            return "mongodb"
        elif self.reference_examples:
            return "local_files"
        else:
            return "none"

    @property
    def is_dual_mode(self) -> bool:
        """Return whether dual scoring mode is enabled"""
        return self._dual_mode
    
    def _load_references(self, references_dir: str) -> List[str]:
        """Load reference ELOC documents from directory"""
        ref_path = Path(references_dir)
        
        if not ref_path.exists():
            logger.warning(f"References directory not found: {references_dir}")
            ref_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created {references_dir} - please add reference ELOC files")
            return []
        
        references = []
        for ref_file in ref_path.glob("*.txt"):
            try:
                with open(ref_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if content.strip():
                        references.append(content)
                        logger.info(f"Loaded reference: {ref_file.name}")
            except Exception as e:
                logger.error(f"Failed to load {ref_file.name}: {e}")
        
        return references
    
    def _compute_type_similarity(self, doc_embedding, embeddings: List[Any]) -> Dict:
        """
        Compute similarity metrics against a set of embeddings.

        Returns:
            dict with max_similarity, avg_similarity, and individual scores
        """
        if not embeddings:
            return {
                "max_similarity": 0.0,
                "avg_similarity": 0.0,
                "scores": []
            }

        scores = []
        for i, emb in enumerate(embeddings):
            sim = self._cosine_similarity(doc_embedding, emb)
            scores.append({"reference_id": i + 1, "score": float(sim)})

        scores_list = [s["score"] for s in scores]
        return {
            "max_similarity": float(max(scores_list)),
            "avg_similarity": float(self.np.mean(scores_list)),
            "scores": scores
        }

    def classify(self, text: str) -> Dict:
        """
        Classify document using dual similarity scoring.

        In dual mode, computes separate similarity scores against:
        - PURCHASE_NOTICE examples
        - PURCHASE_CONFIRMATION examples

        Classification is based on which type has higher similarity,
        with fallback to NOT_RELEVANT if both are low.

        Returns:
            dict with classification, confidence, and detailed scores
        """
        if not self.available:
            logger.error("Similarity classifier not available")
            return {
                "classification": "ERROR",
                "confidence": "NONE",
                "error": "Classifier not available"
            }

        # Check if we have any embeddings
        has_dual = self._dual_mode and (self.notice_embeddings or self.confirmation_embeddings)
        has_legacy = bool(self.reference_embeddings)

        if not has_dual and not has_legacy:
            logger.warning("No reference embeddings available - using fallback")
            return {
                "classification": "UNCERTAIN",
                "confidence": "NONE",
                "error": "No reference documents loaded"
            }

        try:
            # Encode document (include beginning + end to capture signatures)
            doc_embedding = self.model.encode(self._extract_text_for_embedding(text))

            if self._dual_mode:
                # DUAL MODE: Score against each document type separately
                notice_metrics = self._compute_type_similarity(doc_embedding, self.notice_embeddings)
                confirm_metrics = self._compute_type_similarity(doc_embedding, self.confirmation_embeddings)

                notice_max = notice_metrics["max_similarity"]
                confirm_max = confirm_metrics["max_similarity"]

                # Thresholds for classification
                STRONG_THRESHOLD = 0.82
                MODERATE_THRESHOLD = 0.70
                WEAK_THRESHOLD = 0.55

                # Decision logic based on dual scores
                if notice_max >= STRONG_THRESHOLD and notice_max > confirm_max + 0.05:
                    classification = DocumentType.PURCHASE_NOTICE.value
                    confidence = "HIGH"
                elif confirm_max >= STRONG_THRESHOLD and confirm_max > notice_max + 0.05:
                    classification = DocumentType.PURCHASE_CONFIRMATION.value
                    confidence = "HIGH"
                elif notice_max >= MODERATE_THRESHOLD and notice_max > confirm_max:
                    classification = DocumentType.PURCHASE_NOTICE.value
                    confidence = "MEDIUM"
                elif confirm_max >= MODERATE_THRESHOLD and confirm_max > notice_max:
                    classification = DocumentType.PURCHASE_CONFIRMATION.value
                    confidence = "MEDIUM"
                elif max(notice_max, confirm_max) >= WEAK_THRESHOLD:
                    # Similar to both - could be either, let LLMs decide
                    if notice_max > confirm_max:
                        classification = DocumentType.PURCHASE_NOTICE.value
                    else:
                        classification = DocumentType.PURCHASE_CONFIRMATION.value
                    confidence = "LOW"
                else:
                    classification = DocumentType.NOT_RELEVANT.value
                    confidence = "HIGH"

                logger.info(
                    f"Dual similarity: {classification} ({confidence}) - "
                    f"notice={notice_max:.3f}, confirm={confirm_max:.3f}"
                )

                return {
                    "classification": classification,
                    "confidence": confidence,
                    "scores": {
                        "notice_max_similarity": notice_max,
                        "notice_avg_similarity": notice_metrics["avg_similarity"],
                        "confirmation_max_similarity": confirm_max,
                        "confirmation_avg_similarity": confirm_metrics["avg_similarity"],
                        "max_similarity": max(notice_max, confirm_max),  # For backward compat
                    },
                    "notice_detail": notice_metrics["scores"],
                    "confirmation_detail": confirm_metrics["scores"],
                    "method": "similarity_dual_type",
                    "dual_mode": True
                }

            else:
                # LEGACY MODE: Single similarity score (backward compatibility)
                similarities = []
                for i, ref_emb in enumerate(self.reference_embeddings):
                    sim = self._cosine_similarity(doc_embedding, ref_emb)
                    similarities.append({
                        "reference_id": i + 1,
                        "score": float(sim)
                    })

                scores_list = [s["score"] for s in similarities]
                max_sim = max(scores_list)
                avg_sim = self.np.mean(scores_list)
                top_3_avg = self.np.mean(sorted(scores_list, reverse=True)[:min(3, len(scores_list))])

                # Multi-criteria classification
                has_strong_match = max_sim > 0.85
                has_general_similarity = avg_sim > 0.70
                has_multiple_matches = top_3_avg > 0.80

                if has_strong_match and has_general_similarity:
                    classification = DocumentType.PURCHASE_NOTICE.value
                    confidence = "HIGH"
                elif has_strong_match or has_multiple_matches:
                    classification = DocumentType.PURCHASE_NOTICE.value
                    confidence = "MEDIUM"
                elif avg_sim > 0.60:
                    classification = DocumentType.UNCERTAIN.value
                    confidence = "LOW"
                else:
                    classification = DocumentType.NOT_RELEVANT.value
                    confidence = "HIGH"

                logger.info(f"Similarity classification: {classification} ({confidence}) - max_sim: {max_sim:.3f}")

                return {
                    "classification": classification,
                    "confidence": confidence,
                    "scores": {
                        "max_similarity": float(max_sim),
                        "avg_similarity": float(avg_sim),
                        "top_3_avg": float(top_3_avg)
                    },
                    "criteria": {
                        "strong_match": has_strong_match,
                        "general_similarity": has_general_similarity,
                        "multiple_matches": has_multiple_matches
                    },
                    "detail": similarities,
                    "method": "similarity_multi_reference",
                    "dual_mode": False
                }

        except Exception as e:
            logger.error(f"Similarity classification error: {e}")
            return {
                "classification": "ERROR",
                "confidence": "NONE",
                "error": str(e)
            }
    
    def _cosine_similarity(self, emb1, emb2):
        """Calculate cosine similarity between two embeddings"""
        return self.np.dot(emb1, emb2) / (
            self.np.linalg.norm(emb1) * self.np.linalg.norm(emb2)
        )


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

=== PURCHASE_NOTICE ===
A "VWAP Purchase Notice" document with these characteristics:
- Document type: "VWAP Purchase Notice" or similar title
- References a "Common Stock Purchase Agreement" between a company and an investor
- Contains VWAP purchase details (share amount, dates, settlement)
- May have signature from ONE party only (usually the company/sender)
- Often contains "AGREED AND ACCEPTED" section waiting for countersignature

=== PURCHASE_CONFIRMATION ===
A countersigned/confirmation document with these characteristics:
- Similar structure to Purchase Notice BUT has signatures from BOTH parties
- Contains "AGREED AND ACCEPTED" section that is COMPLETED (both signatures present)
- May be titled "Purchase Confirmation" or be a signed copy of the Purchase Notice
- Key indicator: Both Company AND Investor signatures are present

=== NOT_RELEVANT ===
- General corporate emails, announcements, meeting agendas
- Invoices, purchase orders, or payment documents
- Stock option grants or employee equity plans
- Other financial documents unrelated to VWAP purchase notices
{few_shot_intro}{few_shot_section}
=== DOCUMENT TO CLASSIFY ===
{text_sample}

Respond with JSON only:
{{
  "classification": "PURCHASE_NOTICE" or "PURCHASE_CONFIRMATION" or "NOT_RELEVANT",
  "confidence": "HIGH" or "MEDIUM" or "LOW",
  "reasoning": "brief explanation including signature status if applicable"
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

=== PURCHASE_NOTICE ===
A "VWAP Purchase Notice" document with these characteristics:
- Document type: "VWAP Purchase Notice" or similar title
- References a "Common Stock Purchase Agreement" between a company and an investor
- Contains VWAP purchase details (share amount, dates, settlement)
- May have signature from ONE party only (usually the company/sender)
- Often contains "AGREED AND ACCEPTED" section waiting for countersignature

=== PURCHASE_CONFIRMATION ===
A countersigned/confirmation document with these characteristics:
- Similar structure to Purchase Notice BUT has signatures from BOTH parties
- Contains "AGREED AND ACCEPTED" section that is COMPLETED (both signatures present)
- May be titled "Purchase Confirmation" or be a signed copy of the Purchase Notice
- Key indicator: Both Company AND Investor signatures are present

=== NOT_RELEVANT ===
- General corporate emails, announcements, meeting agendas
- Invoices, purchase orders, or payment documents
- Stock option grants or employee equity plans
- Other financial documents unrelated to VWAP purchase notices
{few_shot_intro}{few_shot_section}
=== DOCUMENT TO CLASSIFY ===
{text_sample}

Respond with JSON only:
{{
  "classification": "PURCHASE_NOTICE" or "PURCHASE_CONFIRMATION" or "NOT_RELEVANT",
  "confidence": "HIGH" or "MEDIUM" or "LOW",
  "reasoning": "brief explanation including signature status if applicable"
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


class TripleClassifier:
    """Combine Similarity, Claude, and OpenAI classifiers for robust classification"""

    def __init__(self, anthropic_api_key: str, openai_api_key: str, references_dir: str = "references"):
        """Initialize all three classifiers"""
        self.similarity = SimilarityClassifier(references_dir)
        self.claude = ClaudeClassifier(anthropic_api_key)
        self.openai = OpenAIClassifier(openai_api_key)
        self._examples_repository = None
        logger.info("Triple classifier initialized (Similarity + Claude + OpenAI)")

    async def load_mongodb_examples(self, examples_repository) -> int:
        """
        Load reference examples from MongoDB for all classifiers.

        This loads:
        - Type-separated embeddings for dual similarity scoring
        - Few-shot examples for Claude and OpenAI classifiers

        Args:
            examples_repository: ExamplesRepository instance

        Returns:
            Number of examples loaded for similarity
        """
        self._examples_repository = examples_repository

        # Load similarity embeddings (dual mode)
        sim_count = await self.similarity.load_mongodb_examples(examples_repository)
        if sim_count > 0:
            logger.info(f"TripleClassifier: Loaded {sim_count} examples for similarity (dual_mode={self.similarity.is_dual_mode})")

        # Load few-shot examples for LLM classifiers
        claude_count = await self.claude.load_few_shot_examples(examples_repository)
        openai_count = await self.openai.load_few_shot_examples(examples_repository)

        logger.info(f"TripleClassifier: Few-shot examples loaded - Claude: {claude_count}, OpenAI: {openai_count}")

        return sim_count

    @property
    def is_dual_mode(self) -> bool:
        """Return whether dual similarity scoring mode is enabled"""
        return self.similarity.is_dual_mode

    @property
    def examples_source(self) -> str:
        """Return the source of loaded examples"""
        return self.similarity.examples_source

    def classify(self, text: str) -> Dict:
        """
        Classify using all three methods: Similarity, Claude, and OpenAI.

        Uses majority voting for final classification among:
        - PURCHASE_NOTICE
        - PURCHASE_CONFIRMATION
        - NOT_RELEVANT

        Returns:
            dict with final classification and details from all classifiers
        """
        logger.info("Starting triple classification (Similarity + Claude + OpenAI)...")

        # Step 1: Fast similarity check
        sim_result = self.similarity.classify(text)
        max_sim = sim_result.get("scores", {}).get("max_similarity", 0)

        # Step 2: Call both LLMs for classification
        logger.info("Calling Claude and OpenAI for classification...")
        claude_result = self.claude.classify(text)
        openai_result = self.openai.classify(text)

        # Collect votes (excluding ERROR results)
        votes = {}
        if sim_result["classification"] not in ["ERROR", "UNCERTAIN"]:
            votes["similarity"] = sim_result["classification"]
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

        # Determine final classification by majority
        if total_votes == 0:
            final_classification = DocumentType.ERROR.value
            final_confidence = "NONE"
            agreement = "none"
            logger.error("All classifiers failed")
        else:
            # Find the category with most votes
            max_votes = max(vote_counts.values())
            winners = [cat for cat, count in vote_counts.items() if count == max_votes]

            if len(winners) == 1:
                final_classification = winners[0]
                if max_votes == total_votes:
                    final_confidence = "HIGH"
                    agreement = "unanimous"
                else:
                    final_confidence = "MEDIUM"
                    agreement = "majority"
            else:
                # Tie - use LLM consensus (Claude and OpenAI agree)
                if claude_result["classification"] == openai_result["classification"]:
                    final_classification = claude_result["classification"]
                    final_confidence = "MEDIUM"
                    agreement = "llm_consensus"
                else:
                    # True split - flag as uncertain
                    final_classification = DocumentType.UNCERTAIN.value
                    final_confidence = "LOW"
                    agreement = "split"

        # Log voting details
        vote_summary = ", ".join([f"{name}={vote}" for name, vote in votes.items()])
        logger.info(f"Votes: {vote_summary}")
        logger.info(f"Final: {final_classification} ({final_confidence}) - {agreement}")

        return {
            "final_classification": final_classification,
            "final_confidence": final_confidence,
            "similarity_result": sim_result,
            "claude_result": claude_result,
            "openai_result": openai_result,
            "votes": votes,
            "vote_counts": vote_counts,
            "agreement": agreement,
            "method": "triple_classification",
            "dual_mode": self.similarity.is_dual_mode
        }


# Backward compatibility alias
DualClassifier = TripleClassifier