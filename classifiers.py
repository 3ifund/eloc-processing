"""
Document classification classes - LLM-based (Claude + OpenAI)

Classifies documents into three types:
- PURCHASE_NOTICE: VWAP Purchase Notice (requires extraction)
- PURCHASE_CONFIRMATION: Countersigned confirmation (requires signature verification)
- NOT_RELEVANT: Neither of the above

Uses dual LLM classification with Claude and OpenAI for robust results.
Supports vision-based classification for PDFs with handwritten content.
"""
from typing import Dict, List, Optional, Any
import logging
import base64
import io
import re
import json
from enum import Enum

logger = logging.getLogger(__name__)


def extract_json_from_response(text: str) -> str:
    """
    Extract JSON from LLM response that may contain additional text.

    Handles cases where the LLM adds explanatory text before/after the JSON,
    or wraps JSON in markdown code blocks.

    Args:
        text: Raw LLM response text

    Returns:
        Extracted JSON string ready for parsing
    """
    if not text:
        return ""

    text = text.strip()

    # Try to find JSON in markdown code blocks first (```json ... ``` or ``` ... ```)
    # This pattern handles the case where Claude adds text before the code block
    code_block_pattern = r'```(?:json)?\s*(\{[\s\S]*?\})\s*```'
    match = re.search(code_block_pattern, text)
    if match:
        return match.group(1).strip()

    # If response starts with ```, handle it (legacy behavior)
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            json_part = parts[1]
            if json_part.startswith("json"):
                json_part = json_part[4:]
            return json_part.strip()

    # Try to find a JSON object anywhere in the text
    # Look for { ... } pattern that could be valid JSON
    brace_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
    matches = re.findall(brace_pattern, text)
    for potential_json in matches:
        try:
            json.loads(potential_json)
            return potential_json
        except json.JSONDecodeError:
            continue

    # Last resort: return the original text and let json.loads handle the error
    return text


def convert_pdf_to_images(pdf_bytes: bytes, max_pages: int = 2) -> List[str]:
    """
    Convert PDF bytes to base64-encoded PNG images for vision classification.

    Args:
        pdf_bytes: Raw PDF file bytes
        max_pages: Maximum number of pages to convert (default 2 for classification)

    Returns:
        List of base64-encoded PNG image strings
    """
    try:
        from pdf2image import convert_from_bytes
        import sys
        import os
        import glob

        # Find poppler path for Windows
        poppler_path = None
        if sys.platform == "win32":
            # Check environment variable first
            env_path = os.environ.get("POPPLER_PATH")
            if env_path and os.path.isfile(os.path.join(env_path, "pdftoppm.exe")):
                poppler_path = env_path
            else:
                # Common installation locations
                common_paths = [
                    r"C:\Program Files\poppler\Library\bin",
                    r"C:\Program Files\poppler\bin",
                    r"C:\poppler\Library\bin",
                    r"C:\poppler\bin",
                ]
                for path in common_paths:
                    if os.path.isfile(os.path.join(path, "pdftoppm.exe")):
                        poppler_path = path
                        break

                # Search in Downloads folder
                if not poppler_path:
                    user_home = os.path.expanduser("~")
                    for pattern in [
                        os.path.join(user_home, "Downloads", "**/poppler*/Library/bin/pdftoppm.exe"),
                        os.path.join(user_home, "Downloads", "**/poppler*/bin/pdftoppm.exe")
                    ]:
                        matches = glob.glob(pattern, recursive=True)
                        if matches:
                            poppler_path = os.path.dirname(matches[0])
                            break

        # Convert PDF to images (150 DPI for good balance of quality/size)
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

        logger.info(f"Converted PDF to {len(base64_images)} images for classification")
        return base64_images

    except ImportError:
        logger.error("pdf2image not installed - pip install pdf2image")
        logger.error("Also requires poppler: https://github.com/osber/poppler-windows/releases")
        return []
    except Exception as e:
        logger.error(f"Failed to convert PDF to images: {e}")
        return []


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

    def _get_classification_prompt(self, include_document: bool = True, text_sample: str = "") -> str:
        """Build the classification prompt"""
        few_shot_section = self._build_few_shot_section()
        few_shot_intro = ""
        if few_shot_section:
            few_shot_intro = """
Below are REAL examples from our database. Use these to understand the exact format and style of each document type.

"""

        document_section = ""
        if include_document and text_sample:
            document_section = f"""
=== DOCUMENT TO CLASSIFY ===
{text_sample}
"""

        return f"""You are a document classifier for a financial services company.

Classify the document into one of three categories:
- PURCHASE_NOTICE
- PURCHASE_CONFIRMATION
- NOT_RELEVANT

**MANDATORY FIRST STEP**: Look at the TITLE/HEADER AREA (top of the document). The document title determines the classification.

IMPORTANT: Document titles may span multiple lines, for example:
  "EXHIBIT A TO THE
   COMMON STOCK PURCHASE AGREEMENT
   FORM OF VWAP PURCHASE NOTICE"
In this case, look for "NOTICE" or "CONFIRMATION" anywhere in the header area.

- Header contains "PURCHASE CONFIRMATION" → PURCHASE_CONFIRMATION
- Header contains "PURCHASE NOTICE" (and NOT "CONFIRMATION") → PURCHASE_NOTICE

=== PURCHASE_CONFIRMATION ===
TITLE: Contains "VWAP Purchase Confirmation" or "Form of VWAP Purchase Confirmation"
- The title/header says "Confirmation" - this OVERRIDES all other signals
- Issued BY THE INVESTOR (Tumim Stone Capital) TO the company
- Text says "Investor hereby issues this VWAP Purchase Confirmation"
- Typically has signatures from BOTH investor and company

=== PURCHASE_NOTICE ===
TITLE: Contains "VWAP Purchase Notice" or "Form of VWAP Purchase Notice"
- The title/header says "Notice" (NOT "Confirmation")
- Issued BY THE COMPANY TO the investor
- Text says "Company hereby delivers this VWAP Purchase Notice"
- Typically has signature from company only
- May start with "EXHIBIT A TO THE..." before the actual title

=== NOT_RELEVANT ===
- No "Purchase Notice" or "Purchase Confirmation" anywhere in the header/title area
- General emails, announcements, other documents
{few_shot_intro}{few_shot_section}{document_section}
Think through these steps internally, then respond with ONLY valid JSON (no other text):
1. Scan the header/title area for the document title
2. Check if it contains "PURCHASE CONFIRMATION" or "PURCHASE NOTICE"
3. Classify based on what you find

{{
  "classification": "PURCHASE_NOTICE" or "PURCHASE_CONFIRMATION" or "NOT_RELEVANT",
  "confidence": "HIGH" or "MEDIUM" or "LOW",
  "reasoning": "Header contains [what you found] - classified as [type]"
}}"""

    def classify_with_vision(self, pdf_images: List[str], fallback_text: str = "") -> Dict:
        """
        Classify document using Claude vision API with PDF images.

        Args:
            pdf_images: List of base64-encoded PNG images of PDF pages
            fallback_text: Optional extracted text as fallback context

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

        if not pdf_images:
            logger.warning("No PDF images provided, falling back to text classification")
            return self.classify(fallback_text) if fallback_text else {
                "classification": "ERROR",
                "confidence": "NONE",
                "error": "No images or text provided",
                "error_type": "NO_INPUT",
                "method": "claude_vision"
            }

        try:
            import json

            # Build multimodal content with images
            content = []

            # Add images first (Claude processes them in order)
            for i, img_b64 in enumerate(pdf_images):
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": img_b64
                    }
                })

            # Add the classification prompt
            prompt = self._get_classification_prompt(include_document=False)
            content.append({
                "type": "text",
                "text": prompt
            })

            logger.info(f"Claude vision classification with {len(pdf_images)} image(s)")

            response = self.client.messages.create(
                model="claude-opus-4-5-20251101",
                max_tokens=300,
                messages=[{"role": "user", "content": content}]
            )

            # Parse response
            raw_content = response.content
            if not raw_content or len(raw_content) == 0:
                logger.error(f"Claude vision returned empty content. Stop reason: {response.stop_reason}")
                return {
                    "classification": "ERROR",
                    "confidence": "NONE",
                    "error": f"Claude returned empty response (stop_reason: {response.stop_reason})",
                    "error_type": "EMPTY_RESPONSE",
                    "method": "claude_vision"
                }

            result_text = response.content[0].text.strip()

            if not result_text:
                logger.error(f"Claude vision returned empty text. Stop reason: {response.stop_reason}")
                return {
                    "classification": "ERROR",
                    "confidence": "NONE",
                    "error": f"Claude returned empty text (stop_reason: {response.stop_reason})",
                    "error_type": "EMPTY_RESPONSE",
                    "method": "claude_vision"
                }

            # Extract JSON from response (handles markdown blocks and extra text)
            json_text = extract_json_from_response(result_text)
            result = json.loads(json_text)

            logger.info(f"Claude vision classification: {result['classification']} ({result['confidence']})")

            result["method"] = "claude_vision"
            result["pages_analyzed"] = len(pdf_images)
            return result

        except json.JSONDecodeError as e:
            error_msg = f"JSON parsing error - Claude vision returned invalid JSON: {e}"
            logger.error(f"Claude vision classification error: {error_msg}")
            logger.error(f"Claude raw response (first 500 chars): {result_text[:500] if 'result_text' in dir() else 'N/A'}")
            return {
                "classification": "ERROR",
                "confidence": "NONE",
                "error": error_msg,
                "error_type": "JSON_PARSE_ERROR",
                "method": "claude_vision"
            }
        except Exception as e:
            error_str = str(e).lower()
            if "rate" in error_str and "limit" in error_str:
                error_type = "RATE_LIMIT"
                error_msg = f"API rate limit exceeded: {e}"
            elif "timeout" in error_str or "timed out" in error_str:
                error_type = "TIMEOUT"
                error_msg = f"API request timed out: {e}"
            elif "connection" in error_str or "network" in error_str:
                error_type = "NETWORK_ERROR"
                error_msg = f"Network/connection error: {e}"
            elif "authentication" in error_str or "api key" in error_str or "unauthorized" in error_str:
                error_type = "AUTH_ERROR"
                error_msg = f"Authentication error: {e}"
            else:
                error_type = "UNKNOWN"
                error_msg = f"Unexpected error: {e}"

            logger.error(f"Claude vision classification error [{error_type}]: {error_msg}")
            return {
                "classification": "ERROR",
                "confidence": "NONE",
                "error": error_msg,
                "error_type": error_type,
                "method": "claude_vision"
            }

    def classify(self, text: str) -> Dict:
        """
        Classify document using Claude API with few-shot examples (text-based)

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
            prompt = self._get_classification_prompt(include_document=True, text_sample=text_sample)

            response = self.client.messages.create(
                model="claude-opus-4-5-20251101",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}]
            )

            import json

            # Log raw response for debugging
            raw_content = response.content
            if not raw_content or len(raw_content) == 0:
                logger.error(f"Claude returned empty content array. Stop reason: {response.stop_reason}")
                return {
                    "classification": "ERROR",
                    "confidence": "NONE",
                    "error": f"Claude returned empty response (stop_reason: {response.stop_reason})",
                    "error_type": "EMPTY_RESPONSE",
                    "method": "claude_api"
                }

            result_text = response.content[0].text.strip()

            # Log if response is empty or very short
            if not result_text:
                logger.error(f"Claude returned empty text. Stop reason: {response.stop_reason}, Content type: {response.content[0].type}")
                return {
                    "classification": "ERROR",
                    "confidence": "NONE",
                    "error": f"Claude returned empty text (stop_reason: {response.stop_reason})",
                    "error_type": "EMPTY_RESPONSE",
                    "method": "claude_api"
                }

            # Extract JSON from response (handles markdown blocks and extra text)
            json_text = extract_json_from_response(result_text)
            result = json.loads(json_text)

            logger.info(f"Claude classification: {result['classification']} ({result['confidence']})")

            result["method"] = "claude_api"
            result["few_shot_used"] = bool(few_shot_section)
            return result

        except json.JSONDecodeError as e:
            # Log the actual text that failed to parse
            error_msg = f"JSON parsing error - Claude returned invalid JSON: {e}"
            logger.error(f"Claude classification error: {error_msg}")
            logger.error(f"Claude raw response (first 500 chars): {result_text[:500] if 'result_text' in dir() else 'N/A'}")
            return {
                "classification": "ERROR",
                "confidence": "NONE",
                "error": error_msg,
                "error_type": "JSON_PARSE_ERROR",
                "method": "claude_api"
            }
        except Exception as e:
            # Categorize the error
            error_str = str(e).lower()
            if "rate" in error_str and "limit" in error_str:
                error_type = "RATE_LIMIT"
                error_msg = f"API rate limit exceeded: {e}"
            elif "timeout" in error_str or "timed out" in error_str:
                error_type = "TIMEOUT"
                error_msg = f"API request timed out: {e}"
            elif "connection" in error_str or "network" in error_str:
                error_type = "NETWORK_ERROR"
                error_msg = f"Network/connection error: {e}"
            elif "authentication" in error_str or "api key" in error_str or "unauthorized" in error_str:
                error_type = "AUTH_ERROR"
                error_msg = f"Authentication error: {e}"
            elif "invalid" in error_str and "request" in error_str:
                error_type = "INVALID_REQUEST"
                error_msg = f"Invalid request error: {e}"
            else:
                error_type = "UNKNOWN"
                error_msg = f"Unexpected error: {e}"

            logger.error(f"Claude classification error [{error_type}]: {error_msg}")
            return {
                "classification": "ERROR",
                "confidence": "NONE",
                "error": error_msg,
                "error_type": error_type,
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

    def _get_classification_prompt(self, include_document: bool = True, text_sample: str = "") -> str:
        """Build the classification prompt"""
        few_shot_section = self._build_few_shot_section()
        few_shot_intro = ""
        if few_shot_section:
            few_shot_intro = """
Below are REAL examples from our database. Use these to understand the exact format and style of each document type.

"""

        document_section = ""
        if include_document and text_sample:
            document_section = f"""
=== DOCUMENT TO CLASSIFY ===
{text_sample}
"""

        return f"""You are a document classifier for a financial services company.

Classify the document into one of three categories:
- PURCHASE_NOTICE
- PURCHASE_CONFIRMATION
- NOT_RELEVANT

**MANDATORY FIRST STEP**: Look at the TITLE/HEADER AREA (top of the document). The document title determines the classification.

IMPORTANT: Document titles may span multiple lines, for example:
  "EXHIBIT A TO THE
   COMMON STOCK PURCHASE AGREEMENT
   FORM OF VWAP PURCHASE NOTICE"
In this case, look for "NOTICE" or "CONFIRMATION" anywhere in the header area.

- Header contains "PURCHASE CONFIRMATION" → PURCHASE_CONFIRMATION
- Header contains "PURCHASE NOTICE" (and NOT "CONFIRMATION") → PURCHASE_NOTICE

=== PURCHASE_CONFIRMATION ===
TITLE: Contains "VWAP Purchase Confirmation" or "Form of VWAP Purchase Confirmation"
- The title/header says "Confirmation" - this OVERRIDES all other signals
- Issued BY THE INVESTOR (Tumim Stone Capital) TO the company
- Text says "Investor hereby issues this VWAP Purchase Confirmation"
- Typically has signatures from BOTH investor and company

=== PURCHASE_NOTICE ===
TITLE: Contains "VWAP Purchase Notice" or "Form of VWAP Purchase Notice"
- The title/header says "Notice" (NOT "Confirmation")
- Issued BY THE COMPANY TO the investor
- Text says "Company hereby delivers this VWAP Purchase Notice"
- Typically has signature from company only
- May start with "EXHIBIT A TO THE..." before the actual title

=== NOT_RELEVANT ===
- No "Purchase Notice" or "Purchase Confirmation" anywhere in the header/title area
- General emails, announcements, other documents
{few_shot_intro}{few_shot_section}{document_section}
Think through these steps internally, then respond with ONLY valid JSON (no other text):
1. Scan the header/title area for the document title
2. Check if it contains "PURCHASE CONFIRMATION" or "PURCHASE NOTICE"
3. Classify based on what you find

{{
  "classification": "PURCHASE_NOTICE" or "PURCHASE_CONFIRMATION" or "NOT_RELEVANT",
  "confidence": "HIGH" or "MEDIUM" or "LOW",
  "reasoning": "Header contains [what you found] - classified as [type]"
}}"""

    def classify_with_vision(self, pdf_images: List[str], fallback_text: str = "") -> Dict:
        """
        Classify document using OpenAI vision API with PDF images.

        Args:
            pdf_images: List of base64-encoded PNG images of PDF pages
            fallback_text: Optional extracted text as fallback context

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

        if not pdf_images:
            logger.warning("No PDF images provided, falling back to text classification")
            return self.classify(fallback_text) if fallback_text else {
                "classification": "ERROR",
                "confidence": "NONE",
                "error": "No images or text provided",
                "error_type": "NO_INPUT",
                "method": "openai_vision"
            }

        try:
            import json

            # Build multimodal content for OpenAI
            content = []

            # Add images first
            for i, img_b64 in enumerate(pdf_images):
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{img_b64}",
                        "detail": "high"
                    }
                })

            # Add the classification prompt
            prompt = self._get_classification_prompt(include_document=False)
            content.append({
                "type": "text",
                "text": prompt
            })

            logger.info(f"OpenAI vision classification with {len(pdf_images)} image(s)")

            response = self.client.chat.completions.create(
                model="gpt-4o",
                max_tokens=300,
                messages=[{"role": "user", "content": content}]
            )

            result_text = response.choices[0].message.content.strip()

            # Extract JSON from response (handles markdown blocks and extra text)
            json_text = extract_json_from_response(result_text)
            result = json.loads(json_text)

            logger.info(f"OpenAI vision classification: {result['classification']} ({result['confidence']})")

            result["method"] = "openai_vision"
            result["pages_analyzed"] = len(pdf_images)
            return result

        except json.JSONDecodeError as e:
            error_msg = f"JSON parsing error - OpenAI vision returned invalid JSON: {e}"
            logger.error(f"OpenAI vision classification error: {error_msg}")
            return {
                "classification": "ERROR",
                "confidence": "NONE",
                "error": error_msg,
                "error_type": "JSON_PARSE_ERROR",
                "method": "openai_vision"
            }
        except Exception as e:
            error_str = str(e).lower()
            if "rate" in error_str and "limit" in error_str:
                error_type = "RATE_LIMIT"
                error_msg = f"API rate limit exceeded: {e}"
            elif "timeout" in error_str or "timed out" in error_str:
                error_type = "TIMEOUT"
                error_msg = f"API request timed out: {e}"
            elif "connection" in error_str or "network" in error_str:
                error_type = "NETWORK_ERROR"
                error_msg = f"Network/connection error: {e}"
            elif "authentication" in error_str or "api key" in error_str or "unauthorized" in error_str:
                error_type = "AUTH_ERROR"
                error_msg = f"Authentication error: {e}"
            else:
                error_type = "UNKNOWN"
                error_msg = f"Unexpected error: {e}"

            logger.error(f"OpenAI vision classification error [{error_type}]: {error_msg}")
            return {
                "classification": "ERROR",
                "confidence": "NONE",
                "error": error_msg,
                "error_type": error_type,
                "method": "openai_vision"
            }

    def classify(self, text: str) -> Dict:
        """
        Classify document using OpenAI API with few-shot examples (text-based)

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
            prompt = self._get_classification_prompt(include_document=True, text_sample=text_sample)

            response = self.client.chat.completions.create(
                model="gpt-4o",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}]
            )

            result_text = response.choices[0].message.content.strip()

            # Extract JSON from response (handles markdown blocks and extra text)
            json_text = extract_json_from_response(result_text)
            result = json.loads(json_text)

            logger.info(f"OpenAI classification: {result['classification']} ({result['confidence']})")

            result["method"] = "openai_api"
            result["few_shot_used"] = bool(self.few_shot_examples)
            return result

        except json.JSONDecodeError as e:
            error_msg = f"JSON parsing error - OpenAI returned invalid JSON: {e}"
            logger.error(f"OpenAI classification error: {error_msg}")
            return {
                "classification": "ERROR",
                "confidence": "NONE",
                "error": error_msg,
                "error_type": "JSON_PARSE_ERROR",
                "method": "openai_api"
            }
        except Exception as e:
            # Categorize the error
            error_str = str(e).lower()
            if "rate" in error_str and "limit" in error_str:
                error_type = "RATE_LIMIT"
                error_msg = f"API rate limit exceeded: {e}"
            elif "timeout" in error_str or "timed out" in error_str:
                error_type = "TIMEOUT"
                error_msg = f"API request timed out: {e}"
            elif "connection" in error_str or "network" in error_str:
                error_type = "NETWORK_ERROR"
                error_msg = f"Network/connection error: {e}"
            elif "authentication" in error_str or "api key" in error_str or "unauthorized" in error_str:
                error_type = "AUTH_ERROR"
                error_msg = f"Authentication error: {e}"
            elif "invalid" in error_str and "request" in error_str:
                error_type = "INVALID_REQUEST"
                error_msg = f"Invalid request error: {e}"
            else:
                error_type = "UNKNOWN"
                error_msg = f"Unexpected error: {e}"

            logger.error(f"OpenAI classification error [{error_type}]: {error_msg}")
            return {
                "classification": "ERROR",
                "confidence": "NONE",
                "error": error_msg,
                "error_type": error_type,
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

    def classify_with_vision(self, pdf_bytes: bytes, fallback_text: str = "") -> Dict:
        """
        Classify using both LLMs with vision (PDF images).

        Converts PDF to images and uses multimodal classification for better
        accuracy with handwritten content, signatures, and complex layouts.

        Args:
            pdf_bytes: Raw PDF file bytes
            fallback_text: Optional extracted text as fallback

        Returns:
            dict with final classification and details from both classifiers
        """
        logger.info("Starting dual LLM VISION classification (Claude + OpenAI)...")

        # Convert PDF to images
        pdf_images = convert_pdf_to_images(pdf_bytes, max_pages=2)

        if not pdf_images:
            logger.warning("PDF to image conversion failed, falling back to text classification")
            return self.classify(fallback_text) if fallback_text else {
                "final_classification": DocumentType.ERROR.value,
                "final_confidence": "NONE",
                "error": "PDF conversion failed and no fallback text",
                "agreement": "none",
                "method": "dual_llm_vision"
            }

        # Call both LLMs with vision
        claude_result = self.claude.classify_with_vision(pdf_images, fallback_text)
        openai_result = self.openai.classify_with_vision(pdf_images, fallback_text)

        return self._aggregate_results(claude_result, openai_result, method="dual_llm_vision")

    def classify(self, text: str) -> Dict:
        """
        Classify using both LLMs: Claude and OpenAI (text-based).

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

        return self._aggregate_results(claude_result, openai_result, method="dual_llm_classification")

    def _aggregate_results(self, claude_result: Dict, openai_result: Dict, method: str = "dual_llm") -> Dict:
        """
        Aggregate results from both classifiers using consensus voting.

        Args:
            claude_result: Result from Claude classifier
            openai_result: Result from OpenAI classifier
            method: Classification method name

        Returns:
            dict with final classification and details
        """

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
            "method": method,
            "dual_mode": True
        }


# Backward compatibility aliases
TripleClassifier = DualLLMClassifier
DualClassifier = DualLLMClassifier