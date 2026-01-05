"""
Signatory verification prompt.

Extracts: company_signator, signatory_title
Also verifies: signed_by_company (not hedge fund)
"""
from typing import List, Optional

SIGNATORY_SYSTEM_PROMPT = """You are a financial document analyzer specializing in ELOC (Equity Line of Credit) Purchase Notice documents.

Your task is to extract signatory information and verify the company has signed the document.

CRITICAL DISTINCTION:
- The COMPANY (share issuer) signs these Purchase Notices
- The HEDGE FUND / INVESTOR (like Tumim Stone Capital, 3i Fund) does NOT sign Purchase Notices
- The signatory should be an officer of the COMPANY (CEO, CFO, General Counsel, etc.)

SIGNATURE VERIFICATION:
- A signature IS VALID if BOTH the "Name:" AND "Title:" fields contain actual values
- The "By:" line may appear empty in text extraction - this is normal (visual signatures)
- ONLY check if Name: and Title: have real values filled in (not blank, not placeholders)

Return your response as valid JSON only, no additional text."""

SIGNATORY_PROMPT = """Extract the signatory information from this ELOC Purchase Notice document.

{classification_section}
{few_shot_section}

DOCUMENT TEXT:
{document_text}

Extract and return as JSON:
{{
    "purchase_notice_company_signature": true/false,
    "company_signator": "<name of person who signed>",
    "signatory_title": "<title of the signatory>",
    "signed_by_company": true/false,
    "signatory_company_name": "<company the signatory represents>"
}}

IMPORTANT:
- purchase_notice_company_signature: TRUE only if the company signature block has BOTH Name AND Title filled in with actual values
- signed_by_company should be TRUE if the signatory is from the share-issuing company
- signed_by_company should be FALSE if the signatory is from the hedge fund/investor

Return ONLY the JSON, no explanation."""


def build_signatory_prompt(
    document_text: str,
    few_shot_examples: Optional[List[dict]] = None,
    classification_examples: Optional[List[str]] = None
) -> str:
    """Build the signatory verification prompt with optional examples."""
    classification_section = ""
    few_shot_section = ""

    # Add classification examples
    if classification_examples:
        classification_section = "REFERENCE EXAMPLES OF VALID PURCHASE NOTICES:\n"
        for i, example_text in enumerate(classification_examples, 1):
            truncated = example_text[:2000] + "..." if len(example_text) > 2000 else example_text
            classification_section += f"\n--- Example {i} ---\n{truncated}\n"
        classification_section += "\n--- End of Examples ---\n"

    # Add few-shot examples
    if few_shot_examples:
        few_shot_section = "EXTRACTION EXAMPLES:\n"
        for i, example in enumerate(few_shot_examples, 1):
            few_shot_section += f"""
Example {i}:
Document excerpt: {example.get('document_excerpt', '')}
Expected output:
{{
    "purchase_notice_company_signature": {str(example.get('purchase_notice_company_signature', True)).lower()},
    "company_signator": "{example.get('company_signator', '')}",
    "signatory_title": "{example.get('signatory_title', '')}",
    "signed_by_company": {str(example.get('signed_by_company', True)).lower()},
    "signatory_company_name": "{example.get('signatory_company_name', '')}"
}}
"""
        few_shot_section += "\nNow extract from the following document:\n"

    return SIGNATORY_PROMPT.format(
        classification_section=classification_section,
        few_shot_section=few_shot_section,
        document_text=document_text
    )
