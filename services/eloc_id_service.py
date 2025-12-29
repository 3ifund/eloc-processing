"""
ELOC ID Generation Service

Generates unique eloc_id values in format: {SYMBOL}-{8-digit-sequence}
Example: ZSPC-00000056

Responsibilities:
1. Resolve company symbol (from extracted data or PostgreSQL lookup)
2. Atomic increment of per-company eloc_sequence
3. Return formatted elocId for use in eloc_data and eloc_state
"""
import logging
import re
from typing import Optional, List, Tuple
import asyncpg

logger = logging.getLogger(__name__)

# Common company suffixes to strip for matching
COMPANY_SUFFIXES = [
    r',?\s*inc\.?$',
    r',?\s*incorporated$',
    r',?\s*corp\.?$',
    r',?\s*corporation$',
    r',?\s*llc\.?$',
    r',?\s*l\.l\.c\.?$',
    r',?\s*ltd\.?$',
    r',?\s*limited$',
    r',?\s*co\.?$',
    r',?\s*company$',
    r',?\s*plc\.?$',
    r',?\s*lp\.?$',
    r',?\s*l\.p\.?$',
]

# Minimum similarity threshold for trigram matching
MIN_SIMILARITY_THRESHOLD = 0.3


class ElocIdService:
    """Service for generating unique ELOC identifiers"""

    def __init__(self, pg_connection_string: str):
        """
        Initialize service with PostgreSQL connection

        Args:
            pg_connection_string: PostgreSQL connection string for DealTerms database
        """
        self.pg_connection_string = pg_connection_string
        self._pool: Optional[asyncpg.Pool] = None

    async def _get_pool(self) -> asyncpg.Pool:
        """Get or create connection pool"""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self.pg_connection_string,
                min_size=1,
                max_size=5
            )
            logger.info("PostgreSQL connection pool created")
        return self._pool

    async def close(self):
        """Close connection pool"""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("PostgreSQL connection pool closed")

    async def generate_eloc_id(
        self,
        company_symbol: Optional[str] = None,
        company_name: Optional[str] = None
    ) -> str:
        """
        Generate unique ELOC ID

        Args:
            company_symbol: Extracted company symbol (preferred)
            company_name: Extracted company name (fallback for symbol lookup)

        Returns:
            Formatted eloc_id (e.g., "ZSPC-00000056")

        Raises:
            ValueError: If neither symbol nor name provided, or company not found
        """
        if not company_symbol and not company_name:
            raise ValueError("Either company_symbol or company_name must be provided")

        symbol = company_symbol
        if not symbol:
            symbol = await self.resolve_company_symbol(company_name)
            if not symbol:
                raise ValueError(f"Company not found for name: {company_name}")

        symbol = symbol.upper().strip()
        sequence = await self._increment_sequence(symbol)
        eloc_id = f"{symbol}-{sequence}"

        logger.info(f"Generated ELOC ID: {eloc_id}")
        return eloc_id

    @staticmethod
    def normalize_company_name(name: str) -> str:
        """
        Normalize company name for matching by removing common suffixes

        Args:
            name: Company name to normalize

        Returns:
            Normalized company name

        Examples:
            "zSpace, Inc." -> "zspace"
            "Apple Corporation" -> "apple"
            "Microsoft Corp." -> "microsoft"
        """
        normalized = name.lower().strip()

        for suffix_pattern in COMPANY_SUFFIXES:
            normalized = re.sub(suffix_pattern, '', normalized, flags=re.IGNORECASE)

        normalized = normalized.strip()
        normalized = re.sub(r'\s+', ' ', normalized)

        return normalized

    async def resolve_company_symbol(self, company_name: str) -> Optional[str]:
        """
        Lookup company symbol by name using multiple strategies:
        1. Exact match on normalized name
        2. Trigram similarity on normalized name
        3. Trigram similarity on original name
        4. Partial match (ILIKE)

        Args:
            company_name: Company name to search

        Returns:
            Company symbol or None if not found
        """
        pool = await self._get_pool()

        normalized_input = self.normalize_company_name(company_name)
        original_lower = company_name.lower().strip()

        async with pool.acquire() as conn:
            # Strategy 1: Exact match on normalized name
            row = await conn.fetchrow(
                """
                SELECT symbol, name
                FROM company
                WHERE LOWER(REGEXP_REPLACE(name_normalized, ',?\\s*(inc\\.?|corp\\.?|llc\\.?|ltd\\.?|co\\.?)$', '', 'i')) = $1
                LIMIT 1
                """,
                normalized_input
            )

            if row:
                logger.info(f"Resolved company (exact match): '{company_name}' -> {row['symbol']}")
                return row['symbol']

            # Strategy 2: Trigram similarity on normalized input
            row = await conn.fetchrow(
                """
                SELECT symbol, name,
                       similarity(name_normalized, $1) AS sim,
                       similarity(name_normalized, $2) AS sim_orig
                FROM company
                WHERE name_normalized % $1 OR name_normalized % $2
                ORDER BY GREATEST(similarity(name_normalized, $1), similarity(name_normalized, $2)) DESC
                LIMIT 1
                """,
                normalized_input,
                original_lower
            )

            if row and max(row['sim'] or 0, row['sim_orig'] or 0) >= MIN_SIMILARITY_THRESHOLD:
                best_sim = max(row['sim'] or 0, row['sim_orig'] or 0)
                logger.info(
                    f"Resolved company (trigram): '{company_name}' -> {row['symbol']} "
                    f"(matched: '{row['name']}', similarity: {best_sim:.2f})"
                )
                return row['symbol']

            # Strategy 3: Partial match using ILIKE
            row = await conn.fetchrow(
                """
                SELECT symbol, name
                FROM company
                WHERE name_normalized ILIKE $1 || '%'
                   OR name_normalized ILIKE '%' || $1 || '%'
                ORDER BY LENGTH(name_normalized)
                LIMIT 1
                """,
                normalized_input
            )

            if row:
                logger.info(
                    f"Resolved company (partial match): '{company_name}' -> {row['symbol']} "
                    f"(matched: '{row['name']}')"
                )
                return row['symbol']

            logger.warning(f"Company not found for name: {company_name} (normalized: {normalized_input})")
            return None

    async def search_companies(self, search_term: str, limit: int = 5) -> List[Tuple[str, str, float]]:
        """
        Search for companies by name (for debugging/verification)

        Args:
            search_term: Search term
            limit: Max results

        Returns:
            List of (symbol, name, similarity_score) tuples
        """
        pool = await self._get_pool()
        normalized = self.normalize_company_name(search_term)

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT symbol, name, similarity(name_normalized, $1) AS sim
                FROM company
                WHERE name_normalized % $1 OR name_normalized ILIKE '%' || $1 || '%'
                ORDER BY sim DESC
                LIMIT $2
                """,
                normalized,
                limit
            )

            return [(row['symbol'], row['name'], row['sim'] or 0) for row in rows]

    async def _increment_sequence(self, symbol: str) -> str:
        """
        Atomically increment eloc_sequence for company

        Args:
            symbol: Company symbol

        Returns:
            New 8-digit sequence string (e.g., "00000056")

        Raises:
            ValueError: If company symbol not found
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE company
                SET eloc_sequence = LPAD((CAST(eloc_sequence AS INTEGER) + 1)::TEXT, 8, '0')
                WHERE symbol = $1
                RETURNING eloc_sequence
                """,
                symbol.upper()
            )

            if not row:
                raise ValueError(f"Company not found for symbol: {symbol}")

            return row['eloc_sequence']

    async def get_company_by_symbol(self, symbol: str) -> Optional[dict]:
        """
        Get company details by symbol

        Args:
            symbol: Company symbol

        Returns:
            Company dict or None if not found
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT company_id, symbol, name, eloc_sequence
                FROM company
                WHERE symbol = $1
                """,
                symbol.upper()
            )

            if row:
                return dict(row)
            return None

    async def validate_symbol_exists(self, symbol: str) -> bool:
        """
        Check if company symbol exists in database

        Args:
            symbol: Company symbol to validate

        Returns:
            True if exists, False otherwise
        """
        company = await self.get_company_by_symbol(symbol)
        return company is not None


# Global instance (initialized in main.py)
eloc_id_service: Optional[ElocIdService] = None
