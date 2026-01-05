"""
ELOC Workflow - Document classification and extraction support
"""
import logging

from classifiers import TripleClassifier

logger = logging.getLogger(__name__)


class ELOCWorkflow:
    """
    ELOC workflow providing classification and Claude client for document processing.

    The main email processing logic is in main.py. This class provides:
    - Document classifier (TripleClassifier with similarity + Claude + OpenAI)
    - Claude client for signature verification
    - Verification orchestrator reference (set by main.py)
    """

    def __init__(self, anthropic_api_key: str, openai_api_key: str = None, references_dir: str = "references"):
        """
        Initialize ELOC workflow components.

        Args:
            anthropic_api_key: Anthropic API key (for classification and signature verification)
            openai_api_key: OpenAI API key (for classification)
            references_dir: Directory with reference ELOC documents
        """
        # Document classifier (similarity + Claude + OpenAI triple voting)
        self.classifier = TripleClassifier(anthropic_api_key, openai_api_key, references_dir)

        # Claude client for signature verification
        from anthropic import Anthropic
        self.claude_client = Anthropic(api_key=anthropic_api_key)

        # Verification orchestrator (dual LLM + trading calendar) - set by main.py
        self.verification_orchestrator = None

        logger.info("ELOC workflow initialized")


# Global instance (initialized in main.py)
eloc_workflow = None
