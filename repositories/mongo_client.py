"""
MongoDB connection manager
"""
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket
import gridfs
from pymongo import MongoClient
from typing import Optional
import logging
import os

logger = logging.getLogger(__name__)


class MongoDBClient:
    """Singleton MongoDB client manager"""
    
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
            self.connection_string = os.getenv(
                "MONGODB_CONNECTION_STRING",
                "mongodb://10.90.98.200:27017/"
            )
            self.database_name = os.getenv("MONGODB_DATABASE", "position_management")
            logger.info(f"MongoDB client initialized: {self.database_name}")
    
    async def connect(self):
        """Initialize async MongoDB connection"""
        if self._client is None:
            self._client = AsyncIOMotorClient(self.connection_string)
            # Test connection
            await self._client.admin.command('ping')
            logger.info("✅ MongoDB async connection established")
    
    def connect_sync(self):
        """Initialize sync MongoDB connection (for GridFS)"""
        if self._sync_client is None:
            self._sync_client = MongoClient(self.connection_string)
            # Test connection
            self._sync_client.admin.command('ping')
            logger.info("✅ MongoDB sync connection established")
    
    async def close(self):
        """Close async connection"""
        if self._client:
            self._client.close()
            logger.info("MongoDB async connection closed")
    
    def close_sync(self):
        """Close sync connection"""
        if self._sync_client:
            self._sync_client.close()
            logger.info("MongoDB sync connection closed")
    
    @property
    def db(self):
        """Get async database"""
        if self._client is None:
            raise RuntimeError("MongoDB not connected. Call connect() first.")
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
        return AsyncIOMotorGridFSBucket(self.db)


# Global instance
mongo_client = MongoDBClient()