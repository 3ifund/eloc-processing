"""
Repository for reading document examples from MongoDB.

Used for few-shot classification of VWAP Purchase Notice and Confirmation documents.
Supports loading examples by document type for dual similarity scoring.
"""
import logging
from typing import Optional, List, Dict, Tuple
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

EXAMPLES_COLLECTION = "purchase_notice_examples"

# Document types
PURCHASE_NOTICE = "PURCHASE_NOTICE"
PURCHASE_CONFIRMATION = "PURCHASE_CONFIRMATION"


class ExamplesRepository:
    """Repository for document example documents (Purchase Notice and Confirmation)"""

    def __init__(self, db: AsyncIOMotorDatabase):
        """
        Initialize repository with MongoDB database

        Args:
            db: Motor async MongoDB database instance
        """
        self.db = db
        self.collection = db[EXAMPLES_COLLECTION]

    async def get_all_examples(self) -> List[Dict]:
        """
        Get all document examples

        Returns:
            List of example documents with filename, pdf_bytes, and document_type
        """
        cursor = self.collection.find({})
        examples = await cursor.to_list(length=100)

        logger.info(f"Loaded {len(examples)} document examples")
        return examples

    async def get_examples_by_type(self, document_type: str) -> List[Dict]:
        """
        Get examples filtered by document type

        Args:
            document_type: PURCHASE_NOTICE or PURCHASE_CONFIRMATION

        Returns:
            List of example documents of the specified type
        """
        cursor = self.collection.find({"document_type": document_type})
        examples = await cursor.to_list(length=100)

        logger.info(f"Loaded {len(examples)} {document_type} examples")
        return examples

    async def get_example_by_filename(self, filename: str) -> Optional[Dict]:
        """
        Get a specific example by filename

        Args:
            filename: The filename to search for

        Returns:
            Example document or None if not found
        """
        doc = await self.collection.find_one({"filename": filename})
        return doc

    async def get_example_texts(self) -> List[str]:
        """
        Get extracted text from all example PDFs (legacy method for backward compatibility)

        Returns:
            List of extracted text strings from each PDF
        """
        texts_with_types = await self.get_example_texts_with_types()
        return [text for text, _ in texts_with_types]

    async def get_example_texts_with_types(self) -> List[Tuple[str, str]]:
        """
        Get extracted text from all example PDFs with their document types

        Returns:
            List of (text, document_type) tuples
        """
        import pdfplumber
        import io

        examples = await self.get_all_examples()
        texts_with_types = []

        for example in examples:
            try:
                pdf_bytes = example.get("pdf_bytes")
                document_type = example.get("document_type", PURCHASE_NOTICE)

                if pdf_bytes:
                    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                        text_parts = []
                        for page in pdf.pages[:10]:  # First 10 pages
                            page_text = page.extract_text()
                            if page_text:
                                text_parts.append(page_text)

                        full_text = "\n".join(text_parts)
                        texts_with_types.append((full_text, document_type))

                        logger.info(
                            f"Extracted {len(full_text)} chars from {example.get('filename')} [{document_type}]"
                        )
            except Exception as e:
                logger.error(f"Failed to extract text from {example.get('filename')}: {e}")

        return texts_with_types

    async def get_texts_by_type(self, document_type: str) -> List[str]:
        """
        Get extracted text from example PDFs of a specific type

        Args:
            document_type: PURCHASE_NOTICE or PURCHASE_CONFIRMATION

        Returns:
            List of extracted text strings for the specified type
        """
        import pdfplumber
        import io

        examples = await self.get_examples_by_type(document_type)
        texts = []

        for example in examples:
            try:
                pdf_bytes = example.get("pdf_bytes")
                if pdf_bytes:
                    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                        text_parts = []
                        for page in pdf.pages[:10]:
                            page_text = page.extract_text()
                            if page_text:
                                text_parts.append(page_text)

                        full_text = "\n".join(text_parts)
                        texts.append(full_text)

                        logger.info(
                            f"Extracted {len(full_text)} chars from {example.get('filename')}"
                        )
            except Exception as e:
                logger.error(f"Failed to extract text from {example.get('filename')}: {e}")

        return texts

    async def get_few_shot_examples(self, max_per_type: int = 1) -> Dict[str, List[str]]:
        """
        Get few-shot examples for LLM classification prompts

        Args:
            max_per_type: Maximum number of examples per document type

        Returns:
            Dict with keys PURCHASE_NOTICE and PURCHASE_CONFIRMATION,
            values are lists of truncated example texts
        """
        result = {
            PURCHASE_NOTICE: [],
            PURCHASE_CONFIRMATION: []
        }

        for doc_type in [PURCHASE_NOTICE, PURCHASE_CONFIRMATION]:
            texts = await self.get_texts_by_type(doc_type)
            # Truncate each example for prompt size management
            truncated = [text[:3000] for text in texts[:max_per_type]]
            result[doc_type] = truncated

        return result

    async def count(self) -> int:
        """
        Get count of examples in collection

        Returns:
            Number of example documents
        """
        return await self.collection.count_documents({})

    async def count_by_type(self, document_type: str) -> int:
        """
        Get count of examples by type

        Args:
            document_type: PURCHASE_NOTICE or PURCHASE_CONFIRMATION

        Returns:
            Number of example documents of the specified type
        """
        return await self.collection.count_documents({"document_type": document_type})


# Global instance (initialized in main.py)
examples_repository: Optional[ExamplesRepository] = None
