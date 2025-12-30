"""
Debug PostgreSQL connection and trading_calendar query
"""
import asyncio
import asyncpg

# Direct connection params (like your psycopg2 example)
DB_CONFIG = {
    'host': '10.90.98.123',
    'port': 5432,
    'database': 'DealTerms',
    'user': 'postgres',
    'password': 'Drl270!!'
}


async def test_connection():
    print("Testing asyncpg connection...")

    try:
        # Connect using explicit parameters (not connection string)
        conn = await asyncpg.connect(
            host=DB_CONFIG['host'],
            port=DB_CONFIG['port'],
            database=DB_CONFIG['database'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password']
        )

        print("Connected successfully!")

        # Test query - count trading calendar entries
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM trading_calendar"
        )
        print(f"Total trading_calendar entries: {count}")

        # Test query - get ZSPC company
        company = await conn.fetchrow(
            "SELECT company_id, symbol, name FROM company WHERE symbol = 'ZSPC'"
        )
        if company:
            print(f"Company: {company['name']} (ID: {company['company_id']})")

            # Get trading calendar for this company
            calendar_count = await conn.fetchval(
                "SELECT COUNT(*) FROM trading_calendar WHERE company_id = $1",
                company['company_id']
            )
            print(f"Trading calendar entries for ZSPC: {calendar_count}")

            # Get sample entries
            rows = await conn.fetch(
                """
                SELECT trade_date, day_of_week, is_half_day, is_trading_day, note
                FROM trading_calendar
                WHERE company_id = $1
                ORDER BY trade_date DESC
                LIMIT 10
                """,
                company['company_id']
            )

            print(f"\nMost recent 10 trading calendar entries for ZSPC:")
            for row in rows:
                print(f"  {row['trade_date']} ({row['day_of_week']}) - "
                      f"trading={row['is_trading_day']}, half={row['is_half_day']}, "
                      f"note={row['note']}")

        await conn.close()

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_connection())
