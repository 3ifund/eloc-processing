"""
Standalone test script for signature verification in both document types.

Tests:
1. Purchase Notice - Signatory extraction (single company signature)
2. Purchase Confirmation - Dual signature verification (investor + company)

Usage:
    python test_signature_verification.py
"""
import asyncio
import os
import sys
import json
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pdfplumber
from dotenv import load_dotenv

load_dotenv()

# Test document paths
PURCHASE_NOTICE_DOCS = [
    r"C:\Users\Darryl Knapp\Downloads\BGL Tumim VWAP Purchase Notice - 12 Nov.pdf",
    r"C:\Users\Darryl Knapp\Downloads\ZSPC Tumim VWAP Purchase Notice #51_11172025.pdf",
]

PURCHASE_CONFIRMATION_DOCS = [
    r"C:\Users\Darryl Knapp\Downloads\ZSPC Tumim VWAP Purchase Confirmation #58 12.01.2025 Executed.pdf",
    r"C:\Users\Darryl Knapp\Downloads\BGL Tumim VWAP Purchase Confirmation #9 12.28.2025 countersigned.pdf",
]


def extract_pdf_text(pdf_path: str, max_pages: int = 10) -> str:
    """Extract text from PDF file."""
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[:max_pages]:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text


def print_separator(title: str, char: str = "=", width: int = 80):
    """Print a section separator."""
    print(f"\n{char * width}")
    print(f" {title}")
    print(f"{char * width}\n")


def print_field_comparison(field_name: str, claude_value, openai_value, agrees: bool):
    """Print a single field comparison."""
    status = "AGREE" if agrees else "DISAGREE"
    status_color = "\033[92m" if agrees else "\033[91m"  # Green or Red
    reset = "\033[0m"

    print(f"  {field_name}:")
    print(f"    Claude:  {claude_value}")
    print(f"    OpenAI:  {openai_value}")
    print(f"    Status:  {status_color}{status}{reset}")
    print()


async def test_purchase_notice_signatory(pdf_path: str):
    """Test signatory extraction from a Purchase Notice."""
    from services.verification.orchestrator import VerificationOrchestrator

    print_separator(f"PURCHASE NOTICE: {os.path.basename(pdf_path)}", "=")

    # Extract PDF text
    print("Extracting PDF text...")
    pdf_text = extract_pdf_text(pdf_path)
    print(f"  Extracted {len(pdf_text)} characters from PDF\n")

    # Initialize orchestrator
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    if not anthropic_key or not openai_key:
        print("ERROR: Missing ANTHROPIC_API_KEY or OPENAI_API_KEY")
        return

    orchestrator = VerificationOrchestrator(
        anthropic_api_key=anthropic_key,
        openai_api_key=openai_key
    )

    # Run signatory verification (part of the broader extraction)
    print("Running dual LLM signatory extraction...")
    print("  (Claude + OpenAI in parallel)\n")

    start_time = datetime.now()

    # Get results from both services
    claude_result = await orchestrator.claude_service.verify_signatory(pdf_text)
    openai_result = await orchestrator.openai_service.verify_signatory(pdf_text)

    duration_ms = (datetime.now() - start_time).total_seconds() * 1000

    # Display results
    print_separator("CLAUDE RESULT", "-", 60)
    print(json.dumps(claude_result.extracted_fields, indent=2))

    print_separator("OPENAI RESULT", "-", 60)
    print(json.dumps(openai_result.extracted_fields, indent=2))

    # Compare fields
    print_separator("FIELD COMPARISON", "-", 60)

    claude_fields = claude_result.extracted_fields
    openai_fields = openai_result.extracted_fields

    fields_to_compare = [
        "purchase_notice_company_signature",
        "company_signator",
        "signatory_title",
        "signed_by_company",
        "signatory_company_name"
    ]

    agreements = 0
    total = 0

    for field in fields_to_compare:
        claude_val = claude_fields.get(field)
        openai_val = openai_fields.get(field)

        # Normalize for comparison
        claude_norm = str(claude_val).lower().strip() if claude_val else ""
        openai_norm = str(openai_val).lower().strip() if openai_val else ""

        agrees = claude_norm == openai_norm
        if agrees:
            agreements += 1
        total += 1

        print_field_comparison(field, claude_val, openai_val, agrees)

    # Summary
    print_separator("SUMMARY", "-", 60)
    agreement_rate = (agreements / total * 100) if total > 0 else 0
    print(f"  Fields Agreed: {agreements}/{total} ({agreement_rate:.0f}%)")
    print(f"  Duration: {duration_ms:.0f}ms")
    print()

    # Signature verification status
    claude_sig = claude_fields.get("purchase_notice_company_signature", False)
    openai_sig = openai_fields.get("purchase_notice_company_signature", False)
    sig_agree = claude_sig == openai_sig
    sig_status = "\033[92mYES\033[0m" if claude_sig else "\033[93mNO\033[0m"
    print(f"  Company Signature Present: {sig_status}")
    if not sig_agree:
        print(f"    (DISAGREEMENT: Claude={claude_sig}, OpenAI={openai_sig})")

    if claude_result.error:
        print(f"  Claude Error: {claude_result.error}")
    if openai_result.error:
        print(f"  OpenAI Error: {openai_result.error}")


async def test_purchase_confirmation_signature(pdf_path: str):
    """Test signature verification on a Purchase Confirmation."""
    from services.verification.orchestrator import SignatureVerificationOrchestrator

    print_separator(f"PURCHASE CONFIRMATION: {os.path.basename(pdf_path)}", "=")

    # Extract PDF text
    print("Extracting PDF text...")
    pdf_text = extract_pdf_text(pdf_path)
    print(f"  Extracted {len(pdf_text)} characters from PDF\n")

    # Initialize orchestrator
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    if not anthropic_key or not openai_key:
        print("ERROR: Missing ANTHROPIC_API_KEY or OPENAI_API_KEY")
        return

    orchestrator = SignatureVerificationOrchestrator(
        anthropic_api_key=anthropic_key,
        openai_api_key=openai_key
    )

    # Run dual LLM signature verification
    print("Running dual LLM signature verification...")
    print("  (Claude + OpenAI in parallel)\n")

    comparison = await orchestrator.verify_signatures(pdf_text)

    # Display results
    print_separator("CLAUDE RESULT", "-", 60)
    print(json.dumps(comparison.claude_fields, indent=2))

    print_separator("OPENAI RESULT", "-", 60)
    print(json.dumps(comparison.openai_fields, indent=2))

    # Field-by-field comparison
    print_separator("FIELD COMPARISON", "-", 60)

    for field_comp in comparison.field_comparisons:
        print_field_comparison(
            field_comp.field_name,
            field_comp.claude_value,
            field_comp.openai_value,
            field_comp.agrees
        )

    # Summary
    print_separator("SUMMARY", "-", 60)
    summary = comparison.agreement_summary

    all_agree_status = "\033[92mYES\033[0m" if comparison.all_agree else "\033[91mNO\033[0m"
    both_signed_status = "\033[92mYES\033[0m" if comparison.both_signed else "\033[93mNO\033[0m"

    print(f"  All Fields Agree: {all_agree_status}")
    print(f"  Fields Agreed: {summary['fields_agreed']}/{summary['total_fields']} ({summary['agreement_rate']*100:.0f}%)")
    print(f"  Duration: {comparison.duration_ms:.0f}ms")
    print()
    print(f"  Investor Signed: {comparison.investor_signed}")
    print(f"  Company Signed: {comparison.company_signed}")
    print(f"  Both Parties Signed: {both_signed_status}")

    if comparison.claude_error:
        print(f"  Claude Error: {comparison.claude_error}")
    if comparison.openai_error:
        print(f"  OpenAI Error: {comparison.openai_error}")

    # Show disagreements if any
    disagreements = comparison.get_disagreements()
    if disagreements:
        print_separator("DISAGREEMENTS", "-", 60)
        for d in disagreements:
            print(f"  {d.field_name}: Claude='{d.claude_value}' vs OpenAI='{d.openai_value}'")


async def main():
    """Run all tests."""
    print("\n" + "=" * 80)
    print(" ELOC SIGNATURE VERIFICATION TEST")
    print(" Testing dual LLM (Claude + OpenAI) signature extraction")
    print("=" * 80)

    # Test Purchase Notices
    print("\n\n" + "#" * 80)
    print(" PART 1: PURCHASE NOTICE - SIGNATORY EXTRACTION")
    print("#" * 80)

    for pdf_path in PURCHASE_NOTICE_DOCS:
        try:
            await test_purchase_notice_signatory(pdf_path)
        except Exception as e:
            print(f"ERROR testing {pdf_path}: {e}")
        print("\n")

    # Test Purchase Confirmations
    print("\n\n" + "#" * 80)
    print(" PART 2: PURCHASE CONFIRMATION - SIGNATURE VERIFICATION")
    print("#" * 80)

    for pdf_path in PURCHASE_CONFIRMATION_DOCS:
        try:
            await test_purchase_confirmation_signature(pdf_path)
        except Exception as e:
            print(f"ERROR testing {pdf_path}: {e}")
        print("\n")

    print("\n" + "=" * 80)
    print(" TEST COMPLETE")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
