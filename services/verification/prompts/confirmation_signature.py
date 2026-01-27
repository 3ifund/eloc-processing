"""
Purchase Confirmation signature verification prompt.

Extracts: investor_signed, company_signed, investor_signatory, company_signatory
Also extracts matching fields: company_name, company_symbol, share_amount, exercise_date

Optimized for multimodal (vision) extraction - LLMs see the PDF as an image.
This is especially important for signature verification where visual inspection is critical.
"""
from typing import List, Optional

CONFIRMATION_SIGNATURE_SYSTEM_PROMPT = """You are a financial document analyzer specializing in ELOC (Equity Line of Credit) Purchase Confirmation documents.

You are viewing the document as an IMAGE. This is critical for signature verification - you can SEE the actual signatures.

Your task is to verify signatures on a Purchase Confirmation and extract matching fields to link it to the original Purchase Notice.

DOCUMENT LAYOUT - TWO SIGNATURE BLOCKS:
1. INVESTOR SIGNATURE (typically on the LEFT or at the TOP):
   - The investor company (e.g., "TUMIM STONE CAPITAL, LLC")
   - May have "By: 3i Management LLC, as Manager" underneath
   - Then signature, Name, and Title fields

2. COMPANY SIGNATURE (typically on the RIGHT or under "AGREED AND ACCEPTED:"):
   - The target company name (e.g., "Abundia Global Impact Group, Inc.")
   - Then "By:", signature line, "Name:", "Title:", "Address:", "Email:"

SIGNATURE VALIDATION - LOOK AT THE IMAGE:
- You can SEE handwritten signatures - look for cursive/handwritten marks on signature lines
- A signature IS VALID if you can see:
  * A handwritten signature OR typed name on the "By:" line
  * AND a name in the "Name:" field (or combined with title)
  * AND a title in the "Title:" field (or combined with name)
- Names and titles may be combined (e.g., "Title: Matthew Lipman, CEO" is VALID)

Return your response as valid JSON only, no additional text."""

CONFIRMATION_SIGNATURE_PROMPT = """Look at this VWAP Purchase Confirmation document image and verify the signatures.

{few_shot_section}

Extract and return as JSON:
{{
    "purchase_confirmation_investor_signature": true/false,
    "purchase_confirmation_company_signature": true/false,
    "investor_signatory": "<Name, Title>" or null,
    "company_signatory": "<Name, Title>" or null,
    "investor_company": "<Name of investor company (e.g., Tumim Stone Capital LLC)>",
    "target_company": "<Name of target company (e.g., zSpace, Inc.)>",
    "company_symbol": "<Stock ticker symbol>" or null,
    "vwap_purchase_share_amount": <integer number of shares>,
    "vwap_purchase_exercise_date": "<YYYY-MM-DD format>",
    "verification_notes": "<Brief explanation of what you see in the signature blocks>"
}}

VISUAL EXTRACTION GUIDE:

1. FIND THE TWO SIGNATURE BLOCKS:
   - Investor block: Look for "TUMIM STONE CAPITAL, LLC" or similar investor name
   - Company block: Look for "AGREED AND ACCEPTED:" heading, then company name above signature

2. CHECK EACH SIGNATURE BLOCK FOR:
   - Is there a handwritten signature visible? (cursive marks, initials, etc.)
   - Is the "Name:" field filled in with an actual name?
   - Is the "Title:" field filled in with an actual title (CEO, CFO, COO, etc.)?

3. EXTRACT MATCHING FIELDS FROM THE DOCUMENT BODY:
   - Share amount: Look for "VWAP Purchase Share Amount" row
   - Exercise date: Look for "VWAP Purchase Exercise Date" row
   - Company symbol: May be in parentheses or mentioned with stock/ticker

IMPORTANT:
- purchase_confirmation_investor_signature: TRUE if investor block has signature + name + title
- purchase_confirmation_company_signature: TRUE if company block has signature + name + title
- Share amount must be an integer (remove commas: 200,000 → 200000)
- Exercise date must be in YYYY-MM-DD format (convert from M/D/YYYY if needed)

Return ONLY the JSON, no explanation."""


def build_confirmation_signature_prompt(
    document_text: str,
    few_shot_examples: Optional[List[dict]] = None
) -> str:
    """Build the confirmation signature verification prompt with optional examples."""
    few_shot_section = ""

    if few_shot_examples:
        few_shot_section = "EXTRACTION EXAMPLES:\n"
        for i, example in enumerate(few_shot_examples, 1):
            few_shot_section += f"""
Example {i}:
Document excerpt: {example.get('document_excerpt', '')}
Expected output:
{{
    "purchase_confirmation_investor_signature": {str(example.get('purchase_confirmation_investor_signature', example.get('investor_signed', False))).lower()},
    "purchase_confirmation_company_signature": {str(example.get('purchase_confirmation_company_signature', example.get('company_signed', False))).lower()},
    "investor_signatory": "{example.get('investor_signatory', 'null')}",
    "company_signatory": "{example.get('company_signatory', 'null')}",
    "investor_company": "{example.get('investor_company', '')}",
    "target_company": "{example.get('target_company', '')}",
    "company_symbol": "{example.get('company_symbol', 'null')}",
    "vwap_purchase_share_amount": {example.get('vwap_purchase_share_amount', 0)},
    "vwap_purchase_exercise_date": "{example.get('vwap_purchase_exercise_date', '')}",
    "verification_notes": "{example.get('verification_notes', '')}"
}}
"""
        few_shot_section += "\nNow analyze the document image:\n"

    return CONFIRMATION_SIGNATURE_PROMPT.format(
        few_shot_section=few_shot_section,
        document_text=document_text[:8000]  # Limit document size for text fallback
    )
