"""
Repository for reading purchase notice examples from MongoDB.

Used for few-shot classification of ELOC Purchase Notice documents.
"""
import logging
from typing import Optional, List, Dict
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

EXAMPLES_COLLECTION = "purchase_notice_examples"


class ExamplesRepository:
    """Repository for purchase notice example documents"""

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
        Get all purchase notice examples

        Returns:
            List of example documents with filename and pdf_bytes
        """
        cursor = self.collection.find({})
        examples = await cursor.to_list(length=100)

        logger.info(f"Loaded {len(examples)} purchase notice examples")
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
        Get extracted text from all example PDFs

        Returns:
            List of extracted text strings from each PDF
        """
        import pdfplumber
        import io

        examples = await self.get_all_examples()
        texts = []

        for example in examples:
            try:
                pdf_bytes = example.get("pdf_bytes")
                if pdf_bytes:
                    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                        text_parts = []
                        for page in pdf.pages[:10]:  # First 10 pages
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

    async def count(self) -> int:
        """
        Get count of examples in collection

        Returns:
            Number of example documents
        """
        return await self.collection.count_documents({})


# Global instance (initialized in main.py)
examples_repository: Optional[ExamplesRepository] = None
