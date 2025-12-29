"""
Company identification verification prompt.

Extracts: company_symbol, company_name
"""
from typing import List, Optional

COMPANY_SYSTEM_PROMPT = """You are a financial document analyzer specializing in ELOC (Equity Line of Credit) Purchase Notice documents.

Your task is to extract company identification information from the document.

IMPORTANT:
- The company is the ISSUER of the shares, NOT the hedge fund/investor receiving them
- The company symbol is the stock ticker (e.g., ZSPC, AAPL, MSFT)
- The company name is the legal entity name issuing the shares

Return your response as valid JSON only, no additional text."""

COMPANY_PROMPT = """Extract the company identification from this ELOC Purchase Notice document.

{classification_section}
{few_shot_section}

DOCUMENT TEXT:
{document_text}

Extract and return as JSON:
{{
    "company_symbol": "<stock ticker symbol>",
    "company_name": "<full legal company name>"
}}

Return ONLY the JSON, no explanation."""


def build_company_prompt(
    document_text: str,
    few_shot_examples: Optional[List[dict]] = None,
    classification_examples: Optional[List[str]] = None
) -> str:
    """Build the company verification prompt with optional examples."""
    classification_section = ""
    few_shot_section = ""

    # Add classification examples (full document examples of Purchase Notices)
    if classification_examples:
        classification_section = "REFERENCE EXAMPLES OF VALID PURCHASE NOTICES:\n"
        for i, example_text in enumerate(classification_examples, 1):
            # Truncate to first 2000 chars to keep prompt manageable
            truncated = example_text[:2000] + "..." if len(example_text) > 2000 else example_text
            classification_section += f"\n--- Example {i} ---\n{truncated}\n"
        classification_section += "\n--- End of Examples ---\n"

    # Add few-shot examples with expected outputs
    if few_shot_examples:
        few_shot_section = "EXTRACTION EXAMPLES:\n"
        for i, example in enumerate(few_shot_examples, 1):
            few_shot_section += f"""
Example {i}:
Document excerpt: {example.get('document_excerpt', '')}
Expected output:
{{
    "company_symbol": "{example.get('company_symbol', '')}",
    "company_name": "{example.get('company_name', '')}"
}}
"""
        few_shot_section += "\nNow extract from the following document:\n"

    return COMPANY_PROMPT.format(
        classification_section=classification_section,
        few_shot_section=few_shot_section,
        document_text=document_text
    )
