"""
Claude verification service implementation with multimodal support.

Supports both text-based and vision-based (PDF as image) extraction.
Vision mode provides better accuracy for documents with complex layouts,
signatures, tables, and multi-column formatting.
"""
import base64
import glob
import io
import json
import logging
import os
import sys
from typing import Optional, List, Dict, Any
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
from services.verification.prompts.confirmation_signature import (
    CONFIRMATION_SIGNATURE_SYSTEM_PROMPT,
    build_confirmation_signature_prompt
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-4-6-20260205"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TEMPERATURE = 0.0

# Cache for poppler path detection
_poppler_path_cache: Optional[str] = None


def find_poppler_path() -> Optional[str]:
    """
    Find the poppler bin directory on Windows.

    Checks in order:
    1. POPPLER_PATH environment variable
    2. Common installation locations
    3. User's Downloads folder (for manual installs)

    Returns:
        Path to poppler bin directory, or None if not found
    """
    global _poppler_path_cache
    if _poppler_path_cache is not None:
        return _poppler_path_cache if _poppler_path_cache != "" else None

    # Not Windows - let pdf2image find it automatically
    if sys.platform != "win32":
        _poppler_path_cache = ""
        return None

    # Check environment variable first
    env_path = os.environ.get("POPPLER_PATH")
    if env_path and os.path.isfile(os.path.join(env_path, "pdftoppm.exe")):
        logger.info(f"Found poppler via POPPLER_PATH: {env_path}")
        _poppler_path_cache = env_path
        return env_path

    # Common installation locations
    common_paths = [
        r"C:\Program Files\poppler\Library\bin",
        r"C:\Program Files\poppler\bin",
        r"C:\poppler\Library\bin",
        r"C:\poppler\bin",
    ]

    for path in common_paths:
        if os.path.isfile(os.path.join(path, "pdftoppm.exe")):
            logger.info(f"Found poppler at: {path}")
            _poppler_path_cache = path
            return path

    # Search in user's Downloads folder (manual install)
    user_home = os.path.expanduser("~")
    downloads_pattern = os.path.join(user_home, "Downloads", "**/poppler*/Library/bin/pdftoppm.exe")
    matches = glob.glob(downloads_pattern, recursive=True)
    if matches:
        path = os.path.dirname(matches[0])
        logger.info(f"Found poppler in Downloads: {path}")
        _poppler_path_cache = path
        return path

    # Also check Downloads for alternative structure
    downloads_pattern2 = os.path.join(user_home, "Downloads", "**/poppler*/bin/pdftoppm.exe")
    matches = glob.glob(downloads_pattern2, recursive=True)
    if matches:
        path = os.path.dirname(matches[0])
        logger.info(f"Found poppler in Downloads: {path}")
        _poppler_path_cache = path
        return path

    logger.warning("Poppler not found - PDF to image conversion may fail")
    _poppler_path_cache = ""
    return None


def convert_pdf_to_images(pdf_bytes: bytes, max_pages: int = 5) -> List[str]:
    """
    Convert PDF bytes to base64-encoded PNG images.

    Args:
        pdf_bytes: Raw PDF file bytes
        max_pages: Maximum number of pages to convert (default 5)

    Returns:
        List of base64-encoded PNG image strings
    """
    try:
        from pdf2image import convert_from_bytes

        # Find poppler path for Windows
        poppler_path = find_poppler_path()

        # Convert PDF to images (150 DPI is good balance of quality/size)
        images = convert_from_bytes(
            pdf_bytes,
            dpi=150,
            first_page=1,
            last_page=max_pages,
            poppler_path=poppler_path
        )

        base64_images = []
        for img in images:
            # Convert to PNG bytes
            img_buffer = io.BytesIO()
            img.save(img_buffer, format='PNG', optimize=True)
            img_buffer.seek(0)

            # Encode to base64
            b64_str = base64.standard_b64encode(img_buffer.getvalue()).decode('utf-8')
            base64_images.append(b64_str)

        logger.info(f"Converted PDF to {len(base64_images)} images")
        return base64_images

    except ImportError:
        logger.error("pdf2image not installed - pip install pdf2image")
        logger.error("Also requires poppler: https://github.com/osber/poppler-windows/releases")
        return []
    except Exception as e:
        logger.error(f"Failed to convert PDF to images: {e}")
        return []


def build_multimodal_content(
    images: List[str],
    prompt: str,
    include_text: bool = True,
    document_text: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Build multimodal message content with images and text prompt.

    Args:
        images: List of base64-encoded image strings
        prompt: Text prompt for extraction
        include_text: Whether to include extracted text as backup
        document_text: Optional extracted text (for context)

    Returns:
        List of content blocks for Claude API
    """
    content = []

    # Add images first
    for i, img_b64 in enumerate(images):
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": img_b64
            }
        })

    # Add the extraction prompt
    prompt_text = prompt
    if include_text and document_text:
        # Include extracted text as backup context
        prompt_text += f"\n\n[Extracted text for reference - use the images as primary source]\n{document_text[:3000]}"

    content.append({
        "type": "text",
        "text": prompt_text
    })

    return content


class ClaudeVerificationService(BaseVerificationService):
    """Claude-based verification service with multimodal support"""

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
        self._pdf_images: Optional[List[str]] = None

    def set_pdf_images(self, pdf_bytes: Optional[bytes]) -> bool:
        """
        Set PDF images for multimodal extraction.

        Args:
            pdf_bytes: Raw PDF file bytes, or None to clear

        Returns:
            True if images were successfully converted
        """
        if pdf_bytes is None:
            self._pdf_images = None
            return True

        self._pdf_images = convert_pdf_to_images(pdf_bytes)
        if self._pdf_images:
            logger.info(f"Claude service: PDF images set ({len(self._pdf_images)} pages)")
            return True
        else:
            logger.warning("Claude service: Failed to convert PDF to images, will use text extraction")
            return False

    @property
    def is_multimodal(self) -> bool:
        """Return whether multimodal mode is active"""
        return self._pdf_images is not None and len(self._pdf_images) > 0

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

    def _build_message_content(
        self,
        prompt: str,
        document_text: Optional[str] = None
    ) -> Any:
        """
        Build message content - multimodal if images available, otherwise text.

        Args:
            prompt: The extraction prompt
            document_text: Optional text for fallback/context

        Returns:
            Message content (string or list of content blocks)
        """
        if self._pdf_images:
            # Multimodal mode - send images with prompt
            return build_multimodal_content(
                images=self._pdf_images,
                prompt=prompt,
                include_text=True,
                document_text=document_text
            )
        else:
            # Text-only mode
            return prompt

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

            # Use multimodal content if images are available
            content = self._build_message_content(prompt, document_text)

            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=COMPANY_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}]
            )

            raw_response = response.content[0].text
            extracted = self._parse_json_response(raw_response)

            mode = "multimodal" if self.is_multimodal else "text"
            logger.info(f"Claude company extraction ({mode}): {extracted}")

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

            # Use multimodal content if images are available
            content = self._build_message_content(prompt, document_text)

            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=SIGNATORY_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}]
            )

            raw_response = response.content[0].text
            extracted = self._parse_json_response(raw_response)

            mode = "multimodal" if self.is_multimodal else "text"
            logger.info(f"Claude signatory extraction ({mode}): {extracted}")

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

            # Use multimodal content if images are available
            content = self._build_message_content(prompt, document_text)

            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=TRANSACTION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}]
            )

            raw_response = response.content[0].text
            extracted = self._parse_json_response(raw_response)

            mode = "multimodal" if self.is_multimodal else "text"
            logger.info(f"Claude transaction extraction ({mode}): {extracted}")

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

    async def verify_confirmation_signature(
        self,
        document_text: str,
        few_shot_examples: Optional[List[Dict]] = None
    ) -> CategoryResult:
        """
        Verify signatures on a Purchase Confirmation document.

        Fields: investor_signed, company_signed, investor_signatory, company_signatory,
                investor_company, target_company, company_symbol, vwap_purchase_share_amount,
                vwap_purchase_exercise_date, verification_notes
        """
        try:
            prompt = build_confirmation_signature_prompt(
                document_text,
                few_shot_examples
            )

            # Use multimodal content if images are available
            content = self._build_message_content(prompt, document_text)

            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=CONFIRMATION_SIGNATURE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}]
            )

            raw_response = response.content[0].text
            extracted = self._parse_json_response(raw_response)

            mode = "multimodal" if self.is_multimodal else "text"
            logger.info(f"Claude confirmation signature extraction ({mode}): {extracted}")

            return CategoryResult(
                category=VerificationCategory.CONFIRMATION_SIGNATURE,
                extracted_fields=extracted,
                raw_response=raw_response
            )

        except Exception as e:
            logger.error(f"Claude confirmation signature verification failed: {e}")
            return CategoryResult(
                category=VerificationCategory.CONFIRMATION_SIGNATURE,
                extracted_fields={},
                error=str(e)
            )
