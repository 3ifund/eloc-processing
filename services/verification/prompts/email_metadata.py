"""
Email metadata verification prompt.

Extracts: sender_name, sender_emails, email_subject
"""

EMAIL_METADATA_SYSTEM_PROMPT = """You are an email analyzer specializing in financial communications.

Your task is to extract sender information and subject from ELOC-related emails.

The sender is typically a company officer (CFO, CEO, General Counsel) sending a Purchase Notice.

Return your response as valid JSON only, no additional text."""

EMAIL_METADATA_PROMPT = """Extract the email metadata from this email.

{few_shot_section}

EMAIL SUBJECT:
{email_subject}

EMAIL SENDER:
{email_sender}

EMAIL BODY:
{email_body}

Extract and return as JSON:
{{
    "sender_name": "<full name of the sender>",
    "sender_emails": ["<email1>", "<email2>"],
    "email_subject": "<the email subject line>"
}}

NOTES:
- sender_name should be extracted from the email body signature if possible
- sender_emails should include all email addresses associated with the sender
- email_subject should be the exact subject line

Return ONLY the JSON, no explanation."""


def build_email_metadata_prompt(
    email_subject: str,
    email_body: str,
    email_sender: str,
    few_shot_examples: list = None
) -> str:
    """Build the email metadata verification prompt with optional few-shot examples."""
    few_shot_section = ""

    if few_shot_examples:
        few_shot_section = "EXAMPLES:\n"
        for i, example in enumerate(few_shot_examples, 1):
            emails_str = '", "'.join(example.get('sender_emails', []))
            few_shot_section += f"""
Example {i}:
Subject: {example.get('email_subject', '')}
Sender: {example.get('email_sender', '')}
Body excerpt: {example.get('email_body_excerpt', '')}
Expected output:
{{
    "sender_name": "{example.get('sender_name', '')}",
    "sender_emails": ["{emails_str}"],
    "email_subject": "{example.get('email_subject', '')}"
}}
"""
        few_shot_section += "\nNow extract from the following email:\n"

    return EMAIL_METADATA_PROMPT.format(
        few_shot_section=few_shot_section,
        email_subject=email_subject,
        email_sender=email_sender,
        email_body=email_body
    )
