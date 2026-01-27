"""
Signatory verification prompt.

Extracts: company_signator, signatory_title
Also verifies: signed_by_company (not hedge fund)

Optimized for multimodal (vision) extraction - LLMs see the PDF as an image.
"""
from typing import List, Optional

SIGNATORY_SYSTEM_PROMPT = """You are a financial document analyzer specializing in ELOC (Equity Line of Credit) Purchase Notice documents.

You are viewing the document as an IMAGE. Use the visual layout to accurately extract signature information.

Your task is to extract signatory information and verify the company has signed the document.

CRITICAL DISTINCTION:
- The COMPANY (share issuer) signs these Purchase Notices
- The HEDGE FUND / INVESTOR (like Tumim Stone Capital, 3i Fund) does NOT sign Purchase Notices
- The signatory should be an officer of the COMPANY (CEO, CFO, COO, General Counsel, etc.)

SIGNATURE VERIFICATION - LOOK AT THE IMAGE:
- You can SEE the actual signature in the document image
- Look for handwritten signatures, typed names, and titles
- Check the signature block area - typically at the bottom right of the document
- The "Name:" and "Title:" fields should have actual values filled in

Return your response as valid JSON only, no additional text."""

SIGNATORY_PROMPT = """Look at this ELOC Purchase Notice document image and extract the signatory information.

{classification_section}
{few_shot_section}

Extract and return as JSON:
{{
    "purchase_notice_company_signature": true/false,
    "company_signator": "<name of person who signed>",
    "signatory_title": "<title of the signatory>",
    "signed_by_company": true/false,
    "signatory_company_name": "<company the signatory represents>"
}}

VISUAL EXTRACTION TIPS:
- Look at the RIGHT side of the document for the company signature block
- The signature block typically has: company name at top, then "By:", "Name:", "Title:", "Address:", "Email:"
- You can see handwritten signatures - note if one is present
- Read the actual Name and Title values from the image
- The LEFT side may have "AGREED AND ACCEPTED" for the investor (Tumim Stone Capital) - ignore this for Purchase Notices

IMPORTANT:
- purchase_notice_company_signature: TRUE if you can see a signature AND the Name/Title fields are filled
- signed_by_company should be TRUE if the signatory is from the share-issuing company (not the hedge fund)

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
        few_shot_section += "\nNow extract from the document image:\n"

    return SIGNATORY_PROMPT.format(
        classification_section=classification_section,
        few_shot_section=few_shot_section,
        document_text=document_text
    )
