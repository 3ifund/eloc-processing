"""
Company Lookup Service

Uses PostgreSQL pg_trgm extension for fuzzy matching company names.
Provides validation and enrichment for extracted company data.
"""
import logging
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
import asyncpg

logger = logging.getLogger(__name__)


@dataclass
class CompanyMatch:
    """Result of a company lookup"""
    company_id: int
    symbol: str
    name: str
    name_normalized: str
    similarity_score: float
    is_exact_match: bool


class CompanyLookupService:
    """
    Fuzzy company name lookup using PostgreSQL trigram similarity.

    Uses pg_trgm extension for fast fuzzy matching against the company table.
    """

    def __init__(self, pg_config: Dict[str, Any], similarity_threshold: float = 0.3):
        """
        Initialize the company lookup service.

        Args:
            pg_config: PostgreSQL connection config dict
            similarity_threshold: Minimum similarity score to consider a match (0-1)
        """
        self.pg_config = pg_config
        self.similarity_threshold = similarity_threshold
        self._pool: Optional[asyncpg.Pool] = None

    async def _ensure_pool(self):
        """Ensure connection pool exists"""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                host=self.pg_config['host'],
                port=self.pg_config['port'],
                database=self.pg_config['database'],
                user=self.pg_config['user'],
                password=self.pg_config['password'],
                min_size=1,
                max_size=5
            )
            logger.info("CompanyLookupService: PostgreSQL pool created")

    async def close(self):
        """Close the connection pool"""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("CompanyLookupService: PostgreSQL pool closed")

    async def lookup_by_name(self, company_name: str) -> Optional[CompanyMatch]:
        """
        Look up a company by name using fuzzy matching.

        Args:
            company_name: The company name to search for

        Returns:
            CompanyMatch if found above threshold, None otherwise
        """
        if not company_name or not company_name.strip():
            return None

        await self._ensure_pool()

        company_name = company_name.strip()

        async with self._pool.acquire() as conn:
            # First try exact match on normalized name
            exact = await conn.fetchrow('''
                SELECT company_id, symbol, name, name_normalized
                FROM company
                WHERE LOWER(name) = LOWER($1)
                   OR LOWER(name_normalized) = LOWER($1)
                LIMIT 1
            ''', company_name)

            if exact:
                return CompanyMatch(
                    company_id=exact['company_id'],
                    symbol=exact['symbol'],
                    name=exact['name'],
                    name_normalized=exact['name_normalized'] or '',
                    similarity_score=1.0,
                    is_exact_match=True
                )

            # Fuzzy match using trigram similarity
            fuzzy = await conn.fetchrow('''
                SELECT company_id, symbol, name, name_normalized,
                       GREATEST(
                           similarity(name, $1),
                           similarity(name_normalized, $1)
                       ) as score
                FROM company
                WHERE similarity(name, $1) > $2
                   OR similarity(name_normalized, $1) > $2
                ORDER BY score DESC
                LIMIT 1
            ''', company_name, self.similarity_threshold)

            if fuzzy:
                return CompanyMatch(
                    company_id=fuzzy['company_id'],
                    symbol=fuzzy['symbol'],
                    name=fuzzy['name'],
                    name_normalized=fuzzy['name_normalized'] or '',
                    similarity_score=float(fuzzy['score']),
                    is_exact_match=False
                )

            logger.warning(f"No company match found for: {company_name}")
            return None

    async def lookup_by_symbol(self, symbol: str) -> Optional[CompanyMatch]:
        """
        Look up a company by symbol (exact match).

        Args:
            symbol: The company symbol to search for

        Returns:
            CompanyMatch if found, None otherwise
        """
        if not symbol or not symbol.strip():
            return None

        await self._ensure_pool()

        symbol = symbol.strip().upper()

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow('''
                SELECT company_id, symbol, name, name_normalized
                FROM company
                WHERE UPPER(symbol) = $1
                LIMIT 1
            ''', symbol)

            if row:
                return CompanyMatch(
                    company_id=row['company_id'],
                    symbol=row['symbol'],
                    name=row['name'],
                    name_normalized=row['name_normalized'] or '',
                    similarity_score=1.0,
                    is_exact_match=True
                )

            return None

    async def validate_and_enrich(
        self,
        extracted_symbol: Optional[str],
        extracted_name: Optional[str]
    ) -> Dict[str, Any]:
        """
        Validate extracted company data against the database and enrich if needed.

        Logic:
        1. If symbol provided, validate it exists
        2. If name provided, fuzzy match to find/validate company
        3. If symbol missing but name matches, populate symbol from DB
        4. Return validation status and enriched data

        Args:
            extracted_symbol: Company symbol from extraction (may be None)
            extracted_name: Company name from extraction (may be None)

        Returns:
            Dict with:
                - validated: bool - whether company was found in DB
                - symbol: str - validated/enriched symbol
                - name: str - validated name from DB
                - company_id: int - company ID from DB
                - similarity_score: float - match confidence (1.0 for exact)
                - enriched_symbol: bool - True if symbol was populated from DB
                - match_source: str - 'symbol', 'name', or None
        """
        result = {
            'validated': False,
            'symbol': extracted_symbol,
            'name': extracted_name,
            'company_id': None,
            'similarity_score': 0.0,
            'enriched_symbol': False,
            'match_source': None
        }

        # Try symbol lookup first (most reliable)
        if extracted_symbol:
            match = await self.lookup_by_symbol(extracted_symbol)
            if match:
                result['validated'] = True
                result['symbol'] = match.symbol
                result['name'] = match.name
                result['company_id'] = match.company_id
                result['similarity_score'] = 1.0
                result['match_source'] = 'symbol'
                logger.info(f"Company validated by symbol: {match.symbol} -> {match.name}")
                return result

        # Try name lookup (fuzzy match)
        if extracted_name:
            match = await self.lookup_by_name(extracted_name)
            if match:
                result['validated'] = True
                result['name'] = match.name
                result['company_id'] = match.company_id
                result['similarity_score'] = match.similarity_score
                result['match_source'] = 'name'

                # Enrich symbol if not extracted
                if not extracted_symbol:
                    result['symbol'] = match.symbol
                    result['enriched_symbol'] = True
                    logger.info(
                        f"Company validated by name (score={match.similarity_score:.3f}): "
                        f"'{extracted_name}' -> {match.symbol} ({match.name}), "
                        f"symbol enriched from DB"
                    )
                else:
                    result['symbol'] = match.symbol
                    logger.info(
                        f"Company validated by name (score={match.similarity_score:.3f}): "
                        f"'{extracted_name}' -> {match.name}"
                    )
                return result

        logger.warning(
            f"Company not validated - symbol: {extracted_symbol}, name: {extracted_name}"
        )
        return result


# Global instance (initialized in main.py)
company_lookup_service: Optional[CompanyLookupService] = None
