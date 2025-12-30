"""
ELOC ID Generation Service

Generates unique ELOC IDs in format "{SYMBOL}-{SEQUENCE}" (e.g., "ZSPC-00000056")
Looks up company_id from PostgreSQL company table.
Maintains sequence counters per company in MongoDB.
"""
import logging
from typing import Optional, Tuple, Dict, Union
from dataclasses import dataclass
import asyncpg
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

SEQUENCE_COLLECTION = "eloc_sequences"


@dataclass
class CompanyInfo:
    """Company lookup result"""
    company_id: int
    symbol: str
    company_name: Optional[str] = None


class ElocIdService:
    """Service for generating ELOC IDs and looking up company info"""

    def __init__(
        self,
        mongo_db: AsyncIOMotorDatabase,
        pg_config: Optional[Dict[str, Union[str, int]]] = None
    ):
        """
        Initialize service with MongoDB and PostgreSQL connections

        Args:
            mongo_db: Motor async MongoDB database instance (for sequence tracking)
            pg_config: Dict with host, port, database, user, password for PostgreSQL
        """
        self.mongo_db = mongo_db
        self.pg_config = pg_config
        self._pg_pool: Optional[asyncpg.Pool] = None
        self.sequence_collection = mongo_db[SEQUENCE_COLLECTION]

    async def _get_pg_pool(self) -> asyncpg.Pool:
        """Get or create PostgreSQL connection pool"""
        if self._pg_pool is None:
            if not self.pg_config:
                raise RuntimeError("PostgreSQL config not provided")

            self._pg_pool = await asyncpg.create_pool(
                host=self.pg_config.get('host'),
                port=self.pg_config.get('port', 5432),
                database=self.pg_config.get('database'),
                user=self.pg_config.get('user'),
                password=self.pg_config.get('password'),
                min_size=1,
                max_size=3
            )
            logger.info("ElocIdService: PostgreSQL connection pool created")
        return self._pg_pool

    async def close(self):
        """Close PostgreSQL connection pool"""
        if self._pg_pool:
            await self._pg_pool.close()
            self._pg_pool = None
            logger.info("ElocIdService: PostgreSQL connection pool closed")

    async def get_company_info(self, company_symbol: str) -> Optional[CompanyInfo]:
        """
        Look up company info from PostgreSQL company table

        Args:
            company_symbol: Company stock symbol (e.g., "ZSPC")

        Returns:
            CompanyInfo with company_id, symbol, and name, or None if not found
        """
        pool = await self._get_pg_pool()

        async with pool.acquire() as conn:
            # First try to get the company with name if available
            row = await conn.fetchrow(
                """
                SELECT company_id, symbol,
                       COALESCE(name, symbol) as company_name
                FROM company
                WHERE UPPER(symbol) = $1
                """,
                company_symbol.upper()
            )

            if not row:
                logger.warning(f"Company not found for symbol: {company_symbol}")
                return None

            return CompanyInfo(
                company_id=row['company_id'],
                symbol=row['symbol'],
                company_name=row['company_name']
            )

    async def get_company_id(self, company_symbol: str) -> Optional[int]:
        """
        Look up company_id from company symbol

        Args:
            company_symbol: Company stock symbol (e.g., "ZSPC")

        Returns:
            company_id or None if not found
        """
        info = await self.get_company_info(company_symbol)
        return info.company_id if info else None

    async def get_next_sequence(self, company_symbol: str) -> int:
        """
        Get and increment the next sequence number for a company

        Uses MongoDB findAndModify with upsert to atomically get and increment.

        Args:
            company_symbol: Company stock symbol (e.g., "ZSPC")

        Returns:
            Next sequence number (1-indexed)
        """
        symbol_upper = company_symbol.upper()

        # Atomic increment with upsert
        result = await self.sequence_collection.find_one_and_update(
            {"symbol": symbol_upper},
            {"$inc": {"sequence": 1}},
            upsert=True,
            return_document=True  # Return document after update
        )

        next_seq = result.get("sequence", 1)
        logger.info(f"Next ELOC sequence for {symbol_upper}: {next_seq}")
        return next_seq

    async def generate_eloc_id(self, company_symbol: str) -> Tuple[str, int]:
        """
        Generate a new unique ELOC ID for a company

        Format: "{SYMBOL}-{8-digit sequence}" (e.g., "ZSPC-00000056")

        Args:
            company_symbol: Company stock symbol (e.g., "ZSPC")

        Returns:
            Tuple of (eloc_id, company_id)

        Raises:
            ValueError: If company not found
        """
        # Look up company to verify it exists and get company_id
        company_info = await self.get_company_info(company_symbol)
        if not company_info:
            raise ValueError(f"Company not found for symbol: {company_symbol}")

        # Get next sequence number
        sequence = await self.get_next_sequence(company_symbol)

        # Format ELOC ID: SYMBOL-00000XXX
        eloc_id = f"{company_info.symbol.upper()}-{sequence:08d}"

        logger.info(f"Generated ELOC ID: {eloc_id} (company_id={company_info.company_id})")

        return eloc_id, company_info.company_id

    async def get_current_sequence(self, company_symbol: str) -> int:
        """
        Get current sequence number without incrementing

        Args:
            company_symbol: Company stock symbol

        Returns:
            Current sequence number (0 if no ELOCs exist for company)
        """
        symbol_upper = company_symbol.upper()
        doc = await self.sequence_collection.find_one({"symbol": symbol_upper})
        return doc.get("sequence", 0) if doc else 0

    async def ensure_indexes(self):
        """Create necessary MongoDB indexes"""
        await self.sequence_collection.create_index(
            "symbol",
            unique=True,
            name="idx_symbol_unique"
        )
        logger.info("ElocIdService: MongoDB indexes created")


# Global instance (initialized in main.py)
eloc_id_service: Optional[ElocIdService] = None
