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
    """Classify documents using multi-reference similarity matching"""

    def __init__(self, references_dir: str = "references"):
        """
        Initialize with reference ELOC documents from local files.

        For MongoDB examples, call load_mongodb_examples() after initialization.

        Args:
            references_dir: Directory containing reference ELOC text files
        """
        self.references_dir = references_dir
        self.reference_examples: List[str] = []
        self.reference_embeddings: List[Any] = []
        self._mongodb_loaded = False

        try:
            from sentence_transformers import SentenceTransformer
            import numpy as np

            self.model = SentenceTransformer('all-MiniLM-L6-v2')
            self.np = np
            self.available = True

            # Load from local files initially
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

    def _compute_embeddings(self):
        """Compute embeddings for all reference examples"""
        if not self.reference_examples:
            self.reference_embeddings = []
            return

        logger.info(f"Computing embeddings for {len(self.reference_examples)} references...")
        self.reference_embeddings = [
            self.model.encode(ref[:2000]) for ref in self.reference_examples  # Truncate for consistency
        ]
        logger.info("Similarity classifier ready")

    async def load_mongodb_examples(self, examples_repository) -> int:
        """
        Load reference examples from MongoDB purchase_notice_examples collection.

        This replaces any previously loaded local file examples.

        Args:
            examples_repository: ExamplesRepository instance

        Returns:
            Number of examples loaded
        """
        if not self.available:
            logger.warning("Similarity classifier not available, cannot load MongoDB examples")
            return 0

        try:
            logger.info("Loading reference examples from MongoDB...")
            example_texts = await examples_repository.get_example_texts()

            if example_texts:
                self.reference_examples = example_texts
                self._compute_embeddings()
                self._mongodb_loaded = True
                logger.info(f"Loaded {len(example_texts)} examples from MongoDB")
                return len(example_texts)
            else:
                logger.warning("No examples found in MongoDB, keeping local files")
                return 0

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
    
    def classify(self, text: str) -> Dict:
        """
        Classify document using similarity to reference ELOCs
        
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
        
        if not self.reference_embeddings:
            logger.warning("No reference embeddings available - using fallback")
            return {
                "classification": "UNCERTAIN",
                "confidence": "NONE",
                "error": "No reference documents loaded"
            }
        
        try:
            # Encode document (use first 2000 chars for speed)
            doc_embedding = self.model.encode(text[:2000])
            
            # Calculate similarities to each reference
            similarities = []
            for i, ref_emb in enumerate(self.reference_embeddings):
                sim = self._cosine_similarity(doc_embedding, ref_emb)
                similarities.append({
                    "reference_id": i + 1,
                    "score": float(sim)
                })
            
            # Aggregate metrics
            scores_list = [s["score"] for s in similarities]
            max_sim = max(scores_list)
            avg_sim = self.np.mean(scores_list)
            top_3_avg = self.np.mean(sorted(scores_list, reverse=True)[:min(3, len(scores_list))])
            
            # Multi-criteria classification
            has_strong_match = max_sim > 0.85
            has_general_similarity = avg_sim > 0.70
            has_multiple_matches = top_3_avg > 0.80

            # Decision logic - similarity is trained on Purchase Notices
            # For Purchase Confirmations, similarity may be lower since they have different content
            if has_strong_match and has_general_similarity:
                classification = DocumentType.PURCHASE_NOTICE.value
                confidence = "HIGH"
            elif has_strong_match or has_multiple_matches:
                classification = DocumentType.PURCHASE_NOTICE.value
                confidence = "MEDIUM"
            elif avg_sim > 0.60:
                # Moderate similarity - could be confirmation or related doc
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
                "method": "similarity_multi_reference"
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
    """Classify documents using Claude API"""
    
    def __init__(self, api_key: str):
        """Initialize with Anthropic API key"""
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
    
    def classify(self, text: str) -> Dict:
        """
        Classify document using Claude API
        
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

Document to classify:
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
    """Classify documents using OpenAI API"""

    def __init__(self, api_key: str):
        """Initialize with OpenAI API key"""
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

    def classify(self, text: str) -> Dict:
        """
        Classify document using OpenAI API

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

Document to classify:
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
        Load reference examples from MongoDB for similarity classification.

        Args:
            examples_repository: ExamplesRepository instance

        Returns:
            Number of examples loaded
        """
        self._examples_repository = examples_repository
        count = await self.similarity.load_mongodb_examples(examples_repository)
        if count > 0:
            logger.info(f"TripleClassifier: Loaded {count} examples from MongoDB")
        return count

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
            "method": "triple_classification"
        }


# Backward compatibility alias
DualClassifier = TripleClassifier