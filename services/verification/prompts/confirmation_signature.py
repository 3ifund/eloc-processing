"""
Purchase Confirmation signature verification prompt.

Extracts: investor_signed, company_signed, investor_signatory, company_signatory
Also extracts matching fields: company_name, company_symbol, share_amount, exercise_date
"""
from typing import List, Optional

CONFIRMATION_SIGNATURE_SYSTEM_PROMPT = """You are a financial document analyzer specializing in ELOC (Equity Line of Credit) Purchase Confirmation documents.

Your task is to verify signatures on a Purchase Confirmation and extract matching fields to link it to the original Purchase Notice.

CRITICAL UNDERSTANDING:
- A Purchase Confirmation is signed by BOTH parties:
  1. INVESTOR (e.g., Tumim Stone Capital LLC) signs FIRST at the top
  2. COMPANY (e.g., zSpace, Inc.) counter-signs at the bottom under "AGREED AND ACCEPTED:"

SIGNATURE VALIDATION RULES:
- A signature IS VALID if you can identify BOTH a person's name AND their title anywhere in the signature block
- Name and title may appear in DIFFERENT formats - ALL of these are VALID:
  * Separate lines: "Name: John Smith" and "Title: CEO"
  * Combined on Title line: "Title: John Smith, CEO" (VALID - name and title together)
  * Combined on Name line: "Name: John Smith, CEO"
  * On the By line: "By: John Smith" with "Title: CEO"
  * Name field empty but Title has both: "Name:" (empty) "Title: Matthew Lipman, CEO" (VALID)
- The key question is: Can you determine WHO signed and WHAT their role is?
- If yes, the signature is VALID regardless of which fields the info appears in

Return your response as valid JSON only, no additional text."""

CONFIRMATION_SIGNATURE_PROMPT = """Analyze this VWAP Purchase Confirmation document and extract signature verification and matching fields.

{few_shot_section}

DOCUMENT TEXT:
{document_text}

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
    "verification_notes": "<Brief explanation of signature status>"
}}

IMPORTANT:
- purchase_confirmation_investor_signature: TRUE if you can identify the investor signer's name AND title (in any field)
- purchase_confirmation_company_signature: TRUE if you can identify the company signer's name AND title (in any field)
- Name and title may be combined on a single line (e.g., "Title: Matthew Lipman, CEO" counts as BOTH name and title present)
- For signatories, extract the name and title as "Name, Title" format
- Share amount must be an integer (no commas)
- Exercise date must be in YYYY-MM-DD format

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
        few_shot_section += "\nNow extract from the following document:\n"

    return CONFIRMATION_SIGNATURE_PROMPT.format(
        few_shot_section=few_shot_section,
        document_text=document_text[:8000]  # Limit document size
    )
