"""
Transaction details verification prompt.

Extracts: vwap_purchase_share_amount, agreement_date, vwap_purchase_exercise_date,
          vwap_purchase_period_start_date, vwap_purchase_period_end_date,
          vwap_purchase_settlement_date, aggregate_limit_available

Optimized for multimodal (vision) extraction - LLMs see the PDF as an image.
"""
from typing import List, Optional

TRANSACTION_SYSTEM_PROMPT = """You are a financial document analyzer specializing in ELOC (Equity Line of Credit) Purchase Notice documents.

You are viewing the document as an IMAGE. Use the visual layout to accurately extract transaction details.

Your task is to extract transaction details including dates and amounts.

DATE DEFINITIONS:
- agreement_date: Date of the underlying Purchase Agreement (NOT the exercise date). Look in the introductory paragraph for phrases like "Common Stock Purchase Agreement dated as of [DATE]" or "Agreement dated [DATE]". This is the original agreement date, typically months or years before the exercise.
- vwap_purchase_exercise_date: Date the VWAP purchase right is being exercised (usually today's date or recent)
- vwap_purchase_period_start_date: First day of the VWAP calculation period
- vwap_purchase_period_end_date: Last day of the VWAP calculation period
- vwap_purchase_settlement_date: Date when shares will be delivered/settled

AMOUNT DEFINITIONS:
- vwap_purchase_share_amount: Number of shares being purchased (integer, e.g., 200,000)
- aggregate_limit_available: Remaining dollar amount available under the agreement

Return all dates in ISO format (YYYY-MM-DD).
Return your response as valid JSON only, no additional text."""

TRANSACTION_PROMPT = """Look at this ELOC Purchase Notice document image and extract the transaction details.

{classification_section}
{few_shot_section}

Extract and return as JSON:
{{
    "vwap_purchase_share_amount": <integer number of shares>,
    "agreement_date": "<YYYY-MM-DD>",
    "vwap_purchase_exercise_date": "<YYYY-MM-DD>",
    "vwap_purchase_period_start_date": "<YYYY-MM-DD>",
    "vwap_purchase_period_end_date": "<YYYY-MM-DD>",
    "vwap_purchase_settlement_date": "<YYYY-MM-DD>",
    "aggregate_limit_available": <decimal dollar amount or null if not found>
}}

VISUAL EXTRACTION TIPS:
- Look for a TABLE or FORM layout in the middle of the document with labeled rows
- Common labels: "VWAP Purchase Share Amount", "VWAP Purchase Exercise Date", etc.
- The values are typically on the RIGHT side of each row, often with underlines
- IMPORTANT for agreement_date: Read the INTRODUCTORY PARAGRAPH at the top. Look for "Purchase Agreement dated as of [DATE]" or similar phrasing. This date is typically from months/years ago (e.g., "July 8, 2025").
- Dollar amounts may have "$" prefix and commas (e.g., $94,985,090.61)
- Share amounts are integers, may have commas (e.g., 200,000)

DATE FORMAT CONVERSION:
- If you see "1/27/2026" convert to "2026-01-27"
- If you see "January 27, 2026" convert to "2026-01-27"

Return ONLY the JSON, no explanation."""


def build_transaction_prompt(
    document_text: str,
    few_shot_examples: Optional[List[dict]] = None,
    classification_examples: Optional[List[str]] = None
) -> str:
    """Build the transaction verification prompt with optional examples."""
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
    "vwap_purchase_share_amount": {example.get('vwap_purchase_share_amount', 0)},
    "agreement_date": "{example.get('agreement_date', '')}",
    "vwap_purchase_exercise_date": "{example.get('vwap_purchase_exercise_date', '')}",
    "vwap_purchase_period_start_date": "{example.get('vwap_purchase_period_start_date', '')}",
    "vwap_purchase_period_end_date": "{example.get('vwap_purchase_period_end_date', '')}",
    "vwap_purchase_settlement_date": "{example.get('vwap_purchase_settlement_date', '')}",
    "aggregate_limit_available": {example.get('aggregate_limit_available', 'null')}
}}
"""
        few_shot_section += "\nNow extract from the document image:\n"

    return TRANSACTION_PROMPT.format(
        classification_section=classification_section,
        few_shot_section=few_shot_section,
        document_text=document_text
    )
