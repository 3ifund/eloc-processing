"""
Transaction details verification prompt.

Extracts: vwap_purchase_share_amount, agreement_date, vwap_purchase_exercise_date,
          vwap_purchase_period_start_date, vwap_purchase_period_end_date,
          vwap_purchase_settlement_date, aggregate_limit_available
"""
from typing import List, Optional

TRANSACTION_SYSTEM_PROMPT = """You are a financial document analyzer specializing in ELOC (Equity Line of Credit) Purchase Notice documents.

Your task is to extract transaction details including dates and amounts.

DATE DEFINITIONS:
- agreement_date: Date the Purchase Notice was created/dated
- vwap_purchase_exercise_date: Date the VWAP purchase right is being exercised (Notice Date)
- vwap_purchase_period_start_date: First day of the VWAP calculation period
- vwap_purchase_period_end_date: Last day of the VWAP calculation period
- vwap_purchase_settlement_date: Date when shares will be delivered/settled

AMOUNT DEFINITIONS:
- vwap_purchase_share_amount: Number of shares being purchased (integer)
- aggregate_limit_available: Remaining dollar amount available under the agreement

Return all dates in ISO format (YYYY-MM-DD).
Return your response as valid JSON only, no additional text."""

TRANSACTION_PROMPT = """Extract the transaction details from this ELOC Purchase Notice document.

{classification_section}
{few_shot_section}

DOCUMENT TEXT:
{document_text}

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
        few_shot_section += "\nNow extract from the following document:\n"

    return TRANSACTION_PROMPT.format(
        classification_section=classification_section,
        few_shot_section=few_shot_section,
        document_text=document_text
    )
