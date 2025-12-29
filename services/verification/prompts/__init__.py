"""
Verification prompts organized by category.

Each category has a focused prompt for extracting specific fields.
"""
from services.verification.prompts.company import COMPANY_PROMPT, COMPANY_SYSTEM_PROMPT
from services.verification.prompts.signatory import SIGNATORY_PROMPT, SIGNATORY_SYSTEM_PROMPT
from services.verification.prompts.transaction import TRANSACTION_PROMPT, TRANSACTION_SYSTEM_PROMPT
from services.verification.prompts.email_metadata import EMAIL_METADATA_PROMPT, EMAIL_METADATA_SYSTEM_PROMPT

__all__ = [
    "COMPANY_PROMPT",
    "COMPANY_SYSTEM_PROMPT",
    "SIGNATORY_PROMPT",
    "SIGNATORY_SYSTEM_PROMPT",
    "TRANSACTION_PROMPT",
    "TRANSACTION_SYSTEM_PROMPT",
    "EMAIL_METADATA_PROMPT",
    "EMAIL_METADATA_SYSTEM_PROMPT",
]
