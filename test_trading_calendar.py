"""
Test script for TradingCalendarService
"""
import asyncio
import os
from datetime import date
from dotenv import load_dotenv

load_dotenv()

# Explicit connection config (avoids URL encoding issues with special chars)
PG_CONFIG = {
    'host': '10.90.98.123',
    'port': 5432,
    'database': 'DealTerms',
    'user': 'postgres',
    'password': 'Drl270!!'
}


async def test_trading_calendar_service():
    """Test the trading calendar service"""
    from services.trading_calendar_service import TradingCalendarService

    print("=" * 60)
    print("Testing TradingCalendarService")
    print("=" * 60)

    service = TradingCalendarService(pg_config=PG_CONFIG)

    try:
        # Test 1: Look up a company by symbol to get company_id
        print("\n1. Looking up company ZSPC...")
        pool = await service._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT company_id, symbol, name FROM company WHERE symbol = 'ZSPC'"
            )
            if row:
                company_id = row['company_id']
                print(f"   Found: {row['name']} (ID: {company_id})")
            else:
                print("   ZSPC not found. Using company_id = 1 for testing.")
                company_id = 1

            # Check date range of calendar data
            date_range = await conn.fetchrow(
                """
                SELECT MIN(trade_date) as min_date, MAX(trade_date) as max_date
                FROM trading_calendar WHERE company_id = $1
                """,
                company_id
            )
            print(f"   Calendar date range: {date_range['min_date']} to {date_range['max_date']}")

        # Test 2: Check if a weekday is a full trading day (using 2025 date)
        test_date = date(2025, 12, 15)  # Monday in 2025
        print(f"\n2. Checking if {test_date} is a full trading day...")
        is_full, reason = await service.is_full_trading_day(company_id, test_date)
        print(f"   Is full trading day: {is_full}")
        if reason:
            print(f"   Reason: {reason}")

        # Test 3: Check Christmas Eve (half day)
        christmas_eve = date(2025, 12, 24)
        print(f"\n3. Checking if {christmas_eve} (Christmas Eve) is a full trading day...")
        is_full, reason = await service.is_full_trading_day(company_id, christmas_eve)
        print(f"   Is full trading day: {is_full}")
        if reason:
            print(f"   Reason: {reason}")

        # Test 4: Get most recent trading day before Christmas Eve
        print(f"\n4. Getting most recent full trading day before {christmas_eve}...")
        prior_day = await service.get_most_recent_full_trading_day(company_id, christmas_eve)
        if prior_day:
            print(f"   Most recent trading day: {prior_day}")
        else:
            print("   No prior trading day found")

        # Test 5: Resolve market data date for Christmas Eve (the main use case)
        print(f"\n5. Resolving market data date for exercise date {christmas_eve}...")
        try:
            result = await service.resolve_market_data_date(company_id, christmas_eve)
            print(f"   Exercise date: {result.exercise_date}")
            print(f"   Market data date: {result.market_data_date}")
            print(f"   Was adjusted: {result.was_adjusted}")
            if result.adjustment_reason:
                print(f"   Adjustment reason: {result.adjustment_reason}")
            print(f"\n   Tooltip text:")
            for line in result.tooltip_text.split('\n'):
                print(f"   {line}")
        except ValueError as e:
            print(f"   Error: {e}")

        # Test 6: Resolve market data date for a regular weekday
        print(f"\n6. Resolving market data date for exercise date {test_date} (regular Monday)...")
        try:
            result = await service.resolve_market_data_date(company_id, test_date)
            print(f"   Exercise date: {result.exercise_date}")
            print(f"   Market data date: {result.market_data_date}")
            print(f"   Was adjusted: {result.was_adjusted}")
            print(f"\n   Tooltip text:")
            print(f"   {result.tooltip_text}")
        except ValueError as e:
            print(f"   Error: {e}")

        # Test 7: Count trading days in December 2025
        start = date(2025, 12, 1)
        end = date(2025, 12, 31)
        print(f"\n7. Counting trading days in December 2025...")
        count = await service.count_trading_days_between(company_id, start, end)
        print(f"   Full trading days: {count}")

        # Test 8: List trading days in Christmas week
        week_start = date(2025, 12, 22)
        week_end = date(2025, 12, 26)
        print(f"\n8. Trading days from {week_start} to {week_end} (Christmas week)...")
        trading_days = await service.get_trading_days_between(company_id, week_start, week_end)
        for td in trading_days:
            print(f"   {td} ({td.strftime('%A')})")
        if not trading_days:
            print("   (none found)")

        # Test 9: Test by symbol convenience method
        print(f"\n9. Testing resolve_market_data_date_by_symbol('ZSPC', {christmas_eve})...")
        try:
            result = await service.resolve_market_data_date_by_symbol('ZSPC', christmas_eve)
            print(f"   Market data date: {result.market_data_date}")
            print(f"   Was adjusted: {result.was_adjusted}")
        except ValueError as e:
            print(f"   Error: {e}")

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()

    finally:
        await service.close()
        print("\n" + "=" * 60)
        print("Test complete")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_trading_calendar_service())
