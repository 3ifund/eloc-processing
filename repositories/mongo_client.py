"""
MongoDB connection manager with auto-reconnect
"""
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket
import gridfs
from pymongo import MongoClient
from typing import Optional, Callable, Awaitable
import logging
import os
import asyncio

logger = logging.getLogger(__name__)

# Reconnect interval in seconds
RECONNECT_INTERVAL = 15


class MongoDBClient:
    """Singleton MongoDB client manager with auto-reconnect"""

    _instance: Optional['MongoDBClient'] = None
    _client: Optional[AsyncIOMotorClient] = None
    _sync_client: Optional[MongoClient] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.initialized = True
            self.connection_string = os.getenv("MONGODB_CONNECTION_STRING")
            if not self.connection_string:
                raise ValueError("MONGODB_CONNECTION_STRING environment variable is required")
            self.database_name = os.getenv("MONGODB_DATABASE", "position_management")
            self._connected = False
            self._reconnect_task: Optional[asyncio.Task] = None
            self._on_reconnect_callback: Optional[Callable[[], Awaitable[None]]] = None
            self._reconnect_enabled = True
            logger.info(f"MongoDB client initialized: {self.database_name}")

    @property
    def is_connected(self) -> bool:
        """Check if MongoDB is connected"""
        return self._connected

    def set_reconnect_callback(self, callback: Callable[[], Awaitable[None]]):
        """Set callback to be called on successful reconnect"""
        self._on_reconnect_callback = callback

    async def connect(self):
        """Initialize async MongoDB connection"""
        if self._client is None:
            self._client = AsyncIOMotorClient(self.connection_string)
        # Test connection (don't log ping)
        await self._client.admin.command('ping')
        if not self._connected:
            logger.info("✅ MongoDB async connection established")
        self._connected = True

    async def _try_reconnect(self) -> bool:
        """Attempt to reconnect to MongoDB. Returns True if successful."""
        try:
            if self._client is None:
                self._client = AsyncIOMotorClient(self.connection_string)
            # Test connection (don't log ping)
            await self._client.admin.command('ping')

            if not self._connected:
                logger.info("✅ MongoDB reconnected successfully")
                self._connected = True

                # Call the reconnect callback to re-initialize services
                if self._on_reconnect_callback:
                    try:
                        await self._on_reconnect_callback()
                    except Exception as cb_err:
                        logger.error(f"Error in reconnect callback: {cb_err}")

            return True
        except Exception:
            if self._connected:
                logger.warning("⚠ MongoDB connection lost")
            self._connected = False
            return False

    async def start_reconnect_loop(self):
        """Start the auto-reconnect background task"""
        if self._reconnect_task is not None:
            return  # Already running

        self._reconnect_task = asyncio.create_task(self._reconnect_loop())
        logger.info(f"✓ MongoDB auto-reconnect enabled (every {RECONNECT_INTERVAL}s)")

    async def _reconnect_loop(self):
        """Background task that attempts to reconnect every RECONNECT_INTERVAL seconds"""
        while self._reconnect_enabled:
            await asyncio.sleep(RECONNECT_INTERVAL)

            if not self._connected:
                await self._try_reconnect()
            else:
                # Verify connection is still alive (don't log ping)
                try:
                    await self._client.admin.command('ping')
                except Exception:
                    logger.warning("⚠ MongoDB connection lost (ping failed)")
                    self._connected = False

    def connect_sync(self):
        """Initialize sync MongoDB connection (for GridFS)"""
        if self._sync_client is None:
            self._sync_client = MongoClient(self.connection_string)
            # Test connection
            self._sync_client.admin.command('ping')
            logger.info("✅ MongoDB sync connection established")

    async def close(self):
        """Close async connection"""
        self._reconnect_enabled = False
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        if self._client:
            self._client.close()
            self._connected = False
            logger.info("MongoDB async connection closed")

    def close_sync(self):
        """Close sync connection"""
        if self._sync_client:
            self._sync_client.close()
            logger.info("MongoDB sync connection closed")

    @property
    def db(self):
        """Get async database (returns None if not connected)"""
        if self._client is None or not self._connected:
            return None
        return self._client[self.database_name]

    @property
    def sync_db(self):
        """Get sync database (for GridFS)"""
        if self._sync_client is None:
            raise RuntimeError("MongoDB sync not connected. Call connect_sync() first.")
        return self._sync_client[self.database_name]

    @property
    def gridfs(self) -> gridfs.GridFS:
        """Get GridFS bucket"""
        return gridfs.GridFS(self.sync_db)

    @property
    def async_gridfs(self) -> AsyncIOMotorGridFSBucket:
        """Get async GridFS bucket"""
        if not self._connected:
            return None
        return AsyncIOMotorGridFSBucket(self.db)


# Global instance
mongo_client = MongoDBClient()