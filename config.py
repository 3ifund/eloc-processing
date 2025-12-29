"""
Configuration management for ELOC Processing API
"""
from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    """Application settings"""
    
    # ==================== ENVIRONMENT ====================
    environment: str = "development"
    
    # ==================== MICROSOFT GRAPH ====================
    tenant_id: str
    client_id: str
    client_secret: str
    mailbox_object_id: str
    mailbox_email: str
    
    # ==================== ANTHROPIC ====================
    anthropic_api_key: str
    
    # ==================== MONGODB ====================
    mongodb_connection_string: str = "mongodb://localhost:27017/"
    mongodb_database: str = "eloc_processing"

    # ==================== POSTGRESQL (DealTerms) ====================
    postgres_connection_string: str = "postgresql://localhost:5432/dealterms"
    
    # ==================== APPLICATION ====================
    log_level: str = "INFO"
    log_file: str = "logs/webhook.log"
    
    # Human Review
    enable_human_review: bool = True
    human_handler_email: str = "eloc-review@3ifund.com"
    
    # WebSocket
    websocket_ping_interval: int = 30
    websocket_timeout: int = 300
    
    # ==================== FILE STORAGE ====================
    temp_attachments_dir: str = "C:/temp/attachments"
    references_dir: str = "references"
    
    # ==================== BLOOMBERG (Phase 2) ====================
    bloomberg_api_key: Optional[str] = None
    bloomberg_endpoint: Optional[str] = None
    
    # ==================== SHAREPOINT (Phase 2) ====================
    sharepoint_site_url: Optional[str] = None
    sharepoint_client_id: Optional[str] = None
    sharepoint_client_secret: Optional[str] = None
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()