"""
WebSocket manager for real-time notifications to WPF app
"""
from fastapi import WebSocket, WebSocketDisconnect
from typing import List, Dict
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections and broadcasts"""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.client_info: Dict[WebSocket, Dict] = {}
    
    async def connect(self, websocket: WebSocket, client_id: str = None):
        """Accept and register a new WebSocket connection"""
        await websocket.accept()
        self.active_connections.append(websocket)
        
        self.client_info[websocket] = {
            "client_id": client_id or "unknown",
            "connected_at": datetime.utcnow(),
            "ip": websocket.client.host if websocket.client else "unknown"
        }
        
        logger.info(f"WebSocket client connected: {client_id} ({len(self.active_connections)} total)")
        
        # Send welcome message
        await self.send_personal_message({
            "type": "connected",
            "message": "Connected to ELOC processing server",
            "timestamp": datetime.utcnow().isoformat()
        }, websocket)
    
    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection"""
        if websocket in self.active_connections:
            client_info = self.client_info.get(websocket, {})
            client_id = client_info.get("client_id", "unknown")
            
            self.active_connections.remove(websocket)
            del self.client_info[websocket]
            
            logger.info(f"WebSocket client disconnected: {client_id} ({len(self.active_connections)} remaining)")
    
    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """Send message to a specific client"""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Error sending personal message: {e}")
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients"""
        if not self.active_connections:
            logger.debug("No active WebSocket connections to broadcast to")
            return
        
        logger.info(f"Broadcasting to {len(self.active_connections)} clients: {message.get('type')}")
        
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to client: {e}")
                disconnected.append(connection)
        
        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)
    
    async def notify_new_review(self, workflow_id: str, workflow_data: dict):
        """Notify about new review available"""
        await self.broadcast({
            "type": "new_review",
            "workflow_id": workflow_id,
            "company_name": workflow_data.get("extracted_fields", {}).get("company_name"),
            "email_subject": workflow_data.get("email_subject"),
            "created_at": workflow_data.get("created_at").isoformat() if workflow_data.get("created_at") else None,
            "confidence": workflow_data.get("signature", {}).get("confidence"),
            "timestamp": datetime.utcnow().isoformat()
        })
    
    async def notify_review_approved(self, workflow_id: str, reviewer: str):
        """Notify about review approval"""
        await self.broadcast({
            "type": "review_approved",
            "workflow_id": workflow_id,
            "reviewer": reviewer,
            "timestamp": datetime.utcnow().isoformat()
        })
    
    async def notify_review_rejected(self, workflow_id: str, reviewer: str, reason: str):
        """Notify about review rejection"""
        await self.broadcast({
            "type": "review_rejected",
            "workflow_id": workflow_id,
            "reviewer": reviewer,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat()
        })
    
    async def notify_workflow_complete(self, workflow_id: str):
        """Notify about workflow completion"""
        await self.broadcast({
            "type": "workflow_complete",
            "workflow_id": workflow_id,
            "timestamp": datetime.utcnow().isoformat()
        })
    
    def get_connection_count(self) -> int:
        """Get number of active connections"""
        return len(self.active_connections)
    
    def get_clients_info(self) -> List[Dict]:
        """Get information about all connected clients"""
        return [
            {
                "client_id": info.get("client_id"),
                "connected_at": info.get("connected_at").isoformat(),
                "ip": info.get("ip")
            }
            for info in self.client_info.values()
        ]


# Global instance
ws_manager = WebSocketManager()