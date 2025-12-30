"""
Test script for ELOC extraction with sample document text.
Tests the dual LLM verification (Claude + OpenAI) directly.
"""
import asyncio
import os
import json
from dotenv import load_dotenv

load_dotenv()

# PostgreSQL config for trading calendar
PG_CONFIG = {
    'host': '10.90.98.123',
    'port': 5432,
    'database': 'DealTerms',
    'user': 'postgres',
    'password': 'Drl270!!'
}

# Sample ELOC Purchase Notice text (simulated)
# Using 2025-12-24 (Christmas Eve) to test market data date adjustment
SAMPLE_ELOC_TEXT = """
VWAP PURCHASE NOTICE

Date: December 24, 2025

To: B. Riley Principal Capital II, LLC
    1400 Civic Drive, Suite 200
    Walnut Creek, California 94596

From: zSpace, Inc.
      444 Castro Street, Suite 1200
      Mountain View, CA 94041

Re: Common Stock Purchase Agreement dated September 20, 2024

Dear Sir or Madam:

Reference is made to that certain Common Stock Purchase Agreement, dated as of
September 20, 2024 (the "Agreement"), by and between zSpace, Inc., a Delaware
corporation (the "Company"), and B. Riley Principal Capital II, LLC (the "Investor").

Pursuant to Section 2(a) of the Agreement, the Company hereby delivers this VWAP
Purchase Notice to notify the Investor that the Company elects to exercise its
right to require the Investor to purchase shares of Common Stock.

VWAP PURCHASE DETAILS:

1. VWAP Purchase Share Amount: 150,000 shares of Common Stock

2. VWAP Purchase Exercise Date (Notice Date): December 24, 2025

3. VWAP Purchase Period:
   - Start Date: December 26, 2025
   - End Date: December 30, 2025

4. VWAP Purchase Settlement Date: December 31, 2025

5. Aggregate Limit Available: $4,250,000.00

The Company hereby represents and warrants to the Investor that each of the
conditions set forth in Section 7(b) of the Agreement has been satisfied as of
the date hereof.

Very truly yours,

ZSPACE, INC.

By: ___________________________
Name: Paul Shortino
Title: Chief Financial Officer

Date: December 24, 2025
"""

SAMPLE_EMAIL_SUBJECT = "VWAP Purchase Notice - zSpace, Inc. - December 24, 2025"
SAMPLE_EMAIL_BODY = """
Hi Team,

Please find attached the VWAP Purchase Notice for zSpace, Inc.

This notice is for 150,000 shares with a settlement date of December 31, 2025.

Let me know if you have any questions.

Best regards,
Paul Shortino
CFO, zSpace, Inc.
"""
SAMPLE_EMAIL_SENDER = "paul.shortino@zspace.com"


async def test_claude_verification():
    """Test Claude verification service"""
    print("\n" + "="*60)
    print("Testing Claude Verification Service")
    print("="*60)

    from services.verification.claude_service import ClaudeVerificationService

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set")
        return None

    service = ClaudeVerificationService(api_key)

    # Test each category
    print("\n1. Company Verification:")
    company_result = await service.verify_company(SAMPLE_ELOC_TEXT)
    print(f"   Extracted: {json.dumps(company_result.extracted_fields, indent=6)}")

    print("\n2. Signatory Verification:")
    signatory_result = await service.verify_signatory(SAMPLE_ELOC_TEXT)
    print(f"   Extracted: {json.dumps(signatory_result.extracted_fields, indent=6)}")

    print("\n3. Transaction Verification:")
    transaction_result = await service.verify_transaction(SAMPLE_ELOC_TEXT)
    print(f"   Extracted: {json.dumps(transaction_result.extracted_fields, indent=6)}")

    print("\n4. Email Metadata Verification:")
    email_result = await service.verify_email_metadata(
        SAMPLE_EMAIL_SUBJECT, SAMPLE_EMAIL_BODY, SAMPLE_EMAIL_SENDER
    )
    print(f"   Extracted: {json.dumps(email_result.extracted_fields, indent=6)}")

    return {
        "company": company_result,
        "signatory": signatory_result,
        "transaction": transaction_result,
        "email_metadata": email_result
    }


async def test_openai_verification():
    """Test OpenAI verification service"""
    print("\n" + "="*60)
    print("Testing OpenAI Verification Service")
    print("="*60)

    from services.verification.openai_service import OpenAIVerificationService

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set")
        return None

    service = OpenAIVerificationService(api_key)

    # Test each category
    print("\n1. Company Verification:")
    company_result = await service.verify_company(SAMPLE_ELOC_TEXT)
    print(f"   Extracted: {json.dumps(company_result.extracted_fields, indent=6)}")

    print("\n2. Signatory Verification:")
    signatory_result = await service.verify_signatory(SAMPLE_ELOC_TEXT)
    print(f"   Extracted: {json.dumps(signatory_result.extracted_fields, indent=6)}")

    print("\n3. Transaction Verification:")
    transaction_result = await service.verify_transaction(SAMPLE_ELOC_TEXT)
    print(f"   Extracted: {json.dumps(transaction_result.extracted_fields, indent=6)}")

    print("\n4. Email Metadata Verification:")
    email_result = await service.verify_email_metadata(
        SAMPLE_EMAIL_SUBJECT, SAMPLE_EMAIL_BODY, SAMPLE_EMAIL_SENDER
    )
    print(f"   Extracted: {json.dumps(email_result.extracted_fields, indent=6)}")

    return {
        "company": company_result,
        "signatory": signatory_result,
        "transaction": transaction_result,
        "email_metadata": email_result
    }


async def test_orchestrator():
    """Test the verification orchestrator (runs both LLMs) with trading calendar integration"""
    print("\n" + "="*60)
    print("Testing Verification Orchestrator (Dual LLM + Trading Calendar)")
    print("="*60)

    from services.verification.orchestrator import VerificationOrchestrator
    from services.trading_calendar_service import TradingCalendarService

    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    if not anthropic_key or not openai_key:
        print("ERROR: Both ANTHROPIC_API_KEY and OPENAI_API_KEY must be set")
        return None

    # Initialize trading calendar service
    trading_calendar = TradingCalendarService(pg_config=PG_CONFIG)

    # Initialize orchestrator with trading calendar
    orchestrator = VerificationOrchestrator(
        anthropic_api_key=anthropic_key,
        openai_api_key=openai_key,
        trading_calendar_service=trading_calendar
    )

    print("\nRunning dual verification (Claude + OpenAI in parallel)...")
    print("Exercise date in document: December 24, 2025 (Christmas Eve - half day)")

    result = await orchestrator.verify(
        document_text=SAMPLE_ELOC_TEXT,
        email_subject=SAMPLE_EMAIL_SUBJECT,
        email_body=SAMPLE_EMAIL_BODY,
        email_sender=SAMPLE_EMAIL_SENDER
    )

    print(f"\n{'='*60}")
    print("VERIFICATION RESULTS")
    print(f"{'='*60}")
    print(f"\nOverall Pass: {result.passed}")
    print(f"All Fields Agree: {result.all_agree}")

    print(f"\n--- Agreement Summary ---")
    for category, summary in result.agreement_summary.items():
        print(f"\n{category.upper()}:")
        print(f"  Agrees: {summary['agrees']}")
        print(f"  Fields Agreed: {summary['fields_agreed']}/{summary['total_fields']}")
        if summary['claude_error']:
            print(f"  Claude Error: {summary['claude_error']}")
        if summary['openai_error']:
            print(f"  OpenAI Error: {summary['openai_error']}")

    # Show any disagreements
    disagreements = result.get_disagreements()
    if disagreements:
        print(f"\n--- Disagreements ({len(disagreements)}) ---")
        for d in disagreements:
            print(f"\n  Field: {d.field_name} ({d.category.value})")
            print(f"    Claude: {d.claude_value}")
            print(f"    OpenAI: {d.openai_value}")

    # Show market data date info
    print(f"\n{'='*60}")
    print("MARKET DATA DATE RESOLUTION")
    print(f"{'='*60}")
    if result.market_data_date_info:
        info = result.market_data_date_info
        print(f"\n  Exercise Date (extracted): {info.exercise_date}")
        print(f"  Market Data Date (for queries): {info.market_data_date}")
        print(f"  Was Adjusted: {info.was_adjusted}")
        if info.adjustment_reason:
            print(f"  Adjustment Reason: {info.adjustment_reason}")
        print(f"\n  Tooltip Text:")
        for line in info.tooltip_text.split('\n'):
            print(f"    {line}")
    else:
        print("\n  Market data date not resolved (service not configured or error)")

    # Show merged fields with market data date
    print(f"\n{'='*60}")
    print("MERGED EXTRACTED FIELDS")
    print(f"{'='*60}")
    merged = result.get_merged_fields()
    print(json.dumps(merged, indent=2, default=str))

    # Cleanup
    await trading_calendar.close()

    return result


async def main():
    """Run all tests"""
    print("\n" + "#"*60)
    print("# ELOC Extraction Test Suite")
    print("#"*60)

    # Test individual services
    claude_results = await test_claude_verification()
    openai_results = await test_openai_verification()

    # Test orchestrator (dual verification)
    if claude_results and openai_results:
        orchestrator_results = await test_orchestrator()

    print("\n" + "#"*60)
    print("# Tests Complete")
    print("#"*60)


if __name__ == "__main__":
    asyncio.run(main())
