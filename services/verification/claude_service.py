"""
Claude verification service implementation.
"""
import json
import logging
from typing import Optional, List, Dict
from anthropic import Anthropic

from services.verification.base import (
    BaseVerificationService,
    CategoryResult,
    VerificationCategory
)
from services.verification.prompts.company import (
    COMPANY_SYSTEM_PROMPT,
    build_company_prompt
)
from services.verification.prompts.signatory import (
    SIGNATORY_SYSTEM_PROMPT,
    build_signatory_prompt
)
from services.verification.prompts.transaction import (
    TRANSACTION_SYSTEM_PROMPT,
    build_transaction_prompt
)
from services.verification.prompts.email_metadata import (
    EMAIL_METADATA_SYSTEM_PROMPT,
    build_email_metadata_prompt
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TEMPERATURE = 0.0


class ClaudeVerificationService(BaseVerificationService):
    """Claude-based verification service"""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE
    ):
        super().__init__(api_key)
        self.client = Anthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    @property
    def provider_name(self) -> str:
        return "claude"

    def _parse_json_response(self, response_text: str) -> Dict:
        """Parse JSON from response, handling markdown code blocks."""
        text = response_text.strip()

        if text.startswith("```"):
            lines = text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```") and not in_block:
                    in_block = True
                    continue
                elif line.startswith("```") and in_block:
                    break
                elif in_block:
                    json_lines.append(line)
            text = "\n".join(json_lines)

        return json.loads(text)

    async def verify_company(
        self,
        document_text: str,
        few_shot_examples: Optional[List[Dict]] = None,
        classification_examples: Optional[List[str]] = None
    ) -> CategoryResult:
        """Extract company identification fields."""
        try:
            prompt = build_company_prompt(
                document_text,
                few_shot_examples,
                classification_examples
            )

            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=COMPANY_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )

            raw_response = response.content[0].text
            extracted = self._parse_json_response(raw_response)

            logger.info(f"Claude company extraction: {extracted}")

            return CategoryResult(
                category=VerificationCategory.COMPANY,
                extracted_fields=extracted,
                raw_response=raw_response
            )

        except Exception as e:
            logger.error(f"Claude company verification failed: {e}")
            return CategoryResult(
                category=VerificationCategory.COMPANY,
                extracted_fields={},
                error=str(e)
            )

    async def verify_signatory(
        self,
        document_text: str,
        few_shot_examples: Optional[List[Dict]] = None,
        classification_examples: Optional[List[str]] = None
    ) -> CategoryResult:
        """Extract signatory fields."""
        try:
            prompt = build_signatory_prompt(
                document_text,
                few_shot_examples,
                classification_examples
            )

            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=SIGNATORY_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )

            raw_response = response.content[0].text
            extracted = self._parse_json_response(raw_response)

            logger.info(f"Claude signatory extraction: {extracted}")

            return CategoryResult(
                category=VerificationCategory.SIGNATORY,
                extracted_fields=extracted,
                raw_response=raw_response
            )

        except Exception as e:
            logger.error(f"Claude signatory verification failed: {e}")
            return CategoryResult(
                category=VerificationCategory.SIGNATORY,
                extracted_fields={},
                error=str(e)
            )

    async def verify_transaction(
        self,
        document_text: str,
        few_shot_examples: Optional[List[Dict]] = None,
        classification_examples: Optional[List[str]] = None
    ) -> CategoryResult:
        """Extract transaction fields."""
        try:
            prompt = build_transaction_prompt(
                document_text,
                few_shot_examples,
                classification_examples
            )

            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=TRANSACTION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )

            raw_response = response.content[0].text
            extracted = self._parse_json_response(raw_response)

            logger.info(f"Claude transaction extraction: {extracted}")

            return CategoryResult(
                category=VerificationCategory.TRANSACTION,
                extracted_fields=extracted,
                raw_response=raw_response
            )

        except Exception as e:
            logger.error(f"Claude transaction verification failed: {e}")
            return CategoryResult(
                category=VerificationCategory.TRANSACTION,
                extracted_fields={},
                error=str(e)
            )

    async def verify_email_metadata(
        self,
        email_subject: str,
        email_body: str,
        email_sender: str,
        few_shot_examples: Optional[List[Dict]] = None
    ) -> CategoryResult:
        """Extract email metadata fields."""
        try:
            prompt = build_email_metadata_prompt(
                email_subject, email_body, email_sender, few_shot_examples
            )

            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=EMAIL_METADATA_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )

            raw_response = response.content[0].text
            extracted = self._parse_json_response(raw_response)

            logger.info(f"Claude email metadata extraction: {extracted}")

            return CategoryResult(
                category=VerificationCategory.EMAIL_METADATA,
                extracted_fields=extracted,
                raw_response=raw_response
            )

        except Exception as e:
            logger.error(f"Claude email metadata verification failed: {e}")
            return CategoryResult(
                category=VerificationCategory.EMAIL_METADATA,
                extracted_fields={},
                error=str(e)
            )
