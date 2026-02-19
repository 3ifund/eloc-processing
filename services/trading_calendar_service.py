"""
Trading Calendar Service

Handles trading day lookups for Market Data queries.
If the exercise date is not a full trading day, finds the most recent prior full trading day.

A full trading day = is_trading_day = true AND is_half_day = false
"""
import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional, Union, Dict
import asyncpg

logger = logging.getLogger(__name__)


@dataclass
class MarketDataDateResult:
    """Result of market data date resolution"""
    exercise_date: date                    # Original extracted date
    market_data_date: date                 # Date to use for market data queries
    was_adjusted: bool                     # True if market_data_date differs from exercise_date
    adjustment_reason: Optional[str]       # Reason for adjustment (if any)
    original_date_info: Optional[str]      # Info about why original date wasn't used

    @property
    def tooltip_text(self) -> str:
        """Generate tooltip text explaining the market data date"""
        if not self.was_adjusted:
            return f"Market Data as of: {self.market_data_date.strftime('%B %d, %Y')}"

        return (
            f"Market Data as of: {self.market_data_date.strftime('%B %d, %Y')}\n"
            f"(Exercise date {self.exercise_date.strftime('%B %d, %Y')} {self.original_date_info})"
        )


class TradingCalendarService:
    """Service for trading calendar lookups and market data date resolution"""

    def __init__(
        self,
        pg_connection_string: Optional[str] = None,
        pg_config: Optional[Dict[str, Union[str, int]]] = None
    ):
        """
        Initialize service with PostgreSQL connection

        Args:
            pg_connection_string: PostgreSQL connection string (optional)
            pg_config: Dict with host, port, database, user, password (preferred)

        Note: pg_config is preferred over pg_connection_string to avoid
        URL encoding issues with special characters in passwords.
        """
        self.pg_connection_string = pg_connection_string
        self.pg_config = pg_config
        self._pool: Optional[asyncpg.Pool] = None

    async def _get_pool(self) -> asyncpg.Pool:
        """Get or create connection pool"""
        if self._pool is None:
            if self.pg_config:
                # Use explicit connection parameters (handles special chars in password)
                self._pool = await asyncpg.create_pool(
                    host=self.pg_config.get('host'),
                    port=self.pg_config.get('port', 5432),
                    database=self.pg_config.get('database'),
                    user=self.pg_config.get('user'),
                    password=self.pg_config.get('password'),
                    min_size=1,
                    max_size=5
                )
            else:
                # Fallback to connection string
                self._pool = await asyncpg.create_pool(
                    self.pg_connection_string,
                    min_size=1,
                    max_size=5
                )
            logger.info("TradingCalendarService: PostgreSQL connection pool created")
        return self._pool

    async def close(self):
        """Close connection pool"""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("TradingCalendarService: PostgreSQL connection pool closed")

    async def is_full_trading_day(
        self,
        company_id: int,
        check_date: date
    ) -> tuple[bool, Optional[str]]:
        """
        Check if a date is a full trading day for a company

        Args:
            company_id: Company ID from company table
            check_date: Date to check

        Returns:
            Tuple of (is_full_trading_day, reason_if_not)
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT is_trading_day, is_half_day, note
                FROM trading_calendar
                WHERE company_id = $1 AND trade_date = $2
                """,
                company_id,
                check_date
            )

            if not row:
                # No calendar entry - assume it's not a trading day
                return False, "no calendar entry found"

            if not row['is_trading_day']:
                note = row['note'] or "non-trading day"
                return False, f"was a {note}"

            if row['is_half_day']:
                note = row['note'] or "half trading day"
                return False, f"was a {note}"

            return True, None

    async def get_most_recent_full_trading_day(
        self,
        company_id: int,
        before_date: date
    ) -> Optional[date]:
        """
        Find the most recent full trading day before a given date

        Args:
            company_id: Company ID from company table
            before_date: Find trading day before this date

        Returns:
            Most recent full trading day, or None if not found
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT trade_date
                FROM trading_calendar
                WHERE company_id = $1
                  AND trade_date < $2
                  AND is_trading_day = true
                  AND is_half_day = false
                ORDER BY trade_date DESC
                LIMIT 1
                """,
                company_id,
                before_date
            )

            if row:
                return row['trade_date']
            return None

    async def resolve_market_data_date(
        self,
        company_id: int,
        exercise_date: date
    ) -> MarketDataDateResult:
        """
        Resolve the market data date for a given exercise date.

        If the exercise date is a full trading day, use it.
        Otherwise, find the most recent prior full trading day.

        Args:
            company_id: Company ID from company table
            exercise_date: The extracted VWAP purchase exercise date

        Returns:
            MarketDataDateResult with resolved date and metadata
        """
        # Check if exercise date is a full trading day
        is_full_day, reason = await self.is_full_trading_day(company_id, exercise_date)

        if is_full_day:
            logger.info(
                f"Exercise date {exercise_date} is a full trading day for company {company_id}"
            )
            return MarketDataDateResult(
                exercise_date=exercise_date,
                market_data_date=exercise_date,
                was_adjusted=False,
                adjustment_reason=None,
                original_date_info=None
            )

        # Find the most recent full trading day
        prior_trading_day = await self.get_most_recent_full_trading_day(
            company_id,
            exercise_date
        )

        if prior_trading_day is None:
            logger.error(
                f"No prior trading day found for company {company_id} before {exercise_date}"
            )
            raise ValueError(
                f"No prior trading day found in calendar before {exercise_date}"
            )

        logger.info(
            f"Exercise date {exercise_date} {reason} for company {company_id}. "
            f"Using prior trading day: {prior_trading_day}"
        )

        return MarketDataDateResult(
            exercise_date=exercise_date,
            market_data_date=prior_trading_day,
            was_adjusted=True,
            adjustment_reason=f"Exercise date {reason}",
            original_date_info=reason
        )

    async def resolve_market_data_date_by_symbol(
        self,
        company_symbol: str,
        exercise_date: date
    ) -> MarketDataDateResult:
        """
        Resolve market data date using company symbol instead of ID.

        Convenience method that looks up company_id first.

        Args:
            company_symbol: Company stock symbol (e.g., "ZSPC")
            exercise_date: The extracted VWAP purchase exercise date

        Returns:
            MarketDataDateResult with resolved date and metadata

        Raises:
            ValueError: If company symbol not found
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT company_id
                FROM company
                WHERE symbol = $1
                """,
                company_symbol.upper()
            )

            if not row:
                raise ValueError(f"Company not found for symbol: {company_symbol}")

            company_id = row['company_id']

        return await self.resolve_market_data_date(company_id, exercise_date)

    async def get_trading_days_between(
        self,
        company_id: int,
        start_date: date,
        end_date: date
    ) -> list[date]:
        """
        Get all full trading days between two dates (inclusive)

        Args:
            company_id: Company ID
            start_date: Start date
            end_date: End date

        Returns:
            List of trading dates
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT trade_date
                FROM trading_calendar
                WHERE company_id = $1
                  AND trade_date >= $2
                  AND trade_date <= $3
                  AND is_trading_day = true
                  AND is_half_day = false
                ORDER BY trade_date
                """,
                company_id,
                start_date,
                end_date
            )

            return [row['trade_date'] for row in rows]

    async def count_trading_days_between(
        self,
        company_id: int,
        start_date: date,
        end_date: date
    ) -> int:
        """
        Count full trading days between two dates (inclusive)

        Args:
            company_id: Company ID
            start_date: Start date
            end_date: End date

        Returns:
            Number of full trading days
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COUNT(*) as count
                FROM trading_calendar
                WHERE company_id = $1
                  AND trade_date >= $2
                  AND trade_date <= $3
                  AND is_trading_day = true
                  AND is_half_day = false
                """,
                company_id,
                start_date,
                end_date
            )

            return row['count']

    async def get_date_n_trading_days_ago(
        self,
        company_id: int,
        from_date: date,
        n_days: int
    ) -> Optional[date]:
        """
        Get the date that is N trading days before a given date.

        Args:
            company_id: Company ID
            from_date: Reference date (typically today)
            n_days: Number of trading days to go back

        Returns:
            The date that is N trading days before from_date, or None if not found
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT trade_date
                FROM trading_calendar
                WHERE company_id = $1
                  AND trade_date < $2
                  AND is_trading_day = true
                  AND is_half_day = false
                ORDER BY trade_date DESC
                LIMIT 1 OFFSET $3
                """,
                company_id,
                from_date,
                n_days - 1  # OFFSET is 0-based, so for 7 days ago we offset by 6
            )

            if row:
                return row['trade_date']
            return None


# Global instance (initialized in main.py)
trading_calendar_service: Optional[TradingCalendarService] = None
