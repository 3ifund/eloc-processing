"""
GridFS repository for file storage
"""
from typing import Optional
from bson import ObjectId
import logging

from repositories.mongo_client import mongo_client

logger = logging.getLogger(__name__)


class GridFSRepository:
    """Repository for file storage using GridFS"""
    
    def __init__(self):
        self.fs = None
    
    def _ensure_connection(self):
        """Ensure GridFS connection"""
        if self.fs is None:
            mongo_client.connect_sync()
            self.fs = mongo_client.gridfs
    
    def store_file(self, file_data: bytes, filename: str, content_type: str, metadata: dict = None) -> str:
        """
        Store file in GridFS
        Returns: file_id (string)
        """
        self._ensure_connection()
        
        file_metadata = metadata or {}
        file_metadata.update({
            "filename": filename,
            "contentType": content_type
        })
        
        file_id = self.fs.put(
            file_data,
            filename=filename,
            content_type=content_type,
            metadata=file_metadata
        )
        
        logger.info(f"Stored file in GridFS: {filename} ({len(file_data)} bytes) - ID: {file_id}")
        return str(file_id)
    
    def get_file(self, file_id: str) -> Optional[bytes]:
        """Retrieve file from GridFS"""
        self._ensure_connection()
        
        try:
            grid_out = self.fs.get(ObjectId(file_id))
            return grid_out.read()
        except Exception as e:
            logger.error(f"Error retrieving file {file_id}: {e}")
            return None
    
    def get_file_info(self, file_id: str) -> Optional[dict]:
        """Get file metadata"""
        self._ensure_connection()
        
        try:
            grid_out = self.fs.get(ObjectId(file_id))
            return {
                "filename": grid_out.filename,
                "content_type": grid_out.content_type,
                "length": grid_out.length,
                "upload_date": grid_out.upload_date,
                "metadata": grid_out.metadata
            }
        except Exception as e:
            logger.error(f"Error getting file info {file_id}: {e}")
            return None
    
    def delete_file(self, file_id: str):
        """Delete file from GridFS"""
        self._ensure_connection()
        
        try:
            self.fs.delete(ObjectId(file_id))
            logger.info(f"Deleted file from GridFS: {file_id}")
        except Exception as e:
            logger.error(f"Error deleting file {file_id}: {e}")
    
    def list_files(self, metadata_filter: dict = None) -> list:
        """List files with optional metadata filter"""
        self._ensure_connection()
        
        try:
            query = {}
            if metadata_filter:
                for key, value in metadata_filter.items():
                    query[f"metadata.{key}"] = value
            
            files = []
            for grid_data in self.fs.find(query):
                files.append({
                    "file_id": str(grid_data._id),
                    "filename": grid_data.filename,
                    "content_type": grid_data.content_type,
                    "length": grid_data.length,
                    "upload_date": grid_data.upload_date,
                    "metadata": grid_data.metadata
                })
            
            return files
        except Exception as e:
            logger.error(f"Error listing files: {e}")
            return []


# Global instance
gridfs_repo = GridFSRepository()