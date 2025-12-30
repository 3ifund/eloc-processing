"""
Webhook sender for notifying external processing service
"""
import logging
import httpx
import hashlib
import hmac
import json
from typing import Dict, Optional
from datetime import datetime, UTC
import asyncio

logger = logging.getLogger(__name__)


class WebhookSender:
    """
    Sends webhook notifications to external processing service
    """
    
    def __init__(self, webhook_url: str, webhook_secret: Optional[str] = None,
                 timeout: int = 30, max_retries: int = 3):
        """
        Initialize webhook sender
        
        Args:
            webhook_url: URL to send webhooks to
            webhook_secret: Secret for HMAC signature (optional)
            timeout: Request timeout in seconds
            max_retries: Number of retry attempts
        """
        self.webhook_url = webhook_url
        self.webhook_secret = webhook_secret
        self.timeout = timeout
        self.max_retries = max_retries
        
        logger.info(f"Webhook sender initialized: {webhook_url}")
    
    async def send_extraction_complete(self, workflow_data: Dict) -> Dict:
        """
        Send extraction complete webhook
        
        Args:
            workflow_data: Complete workflow document from MongoDB
        
        Returns:
            Webhook delivery status
        """
        logger.info(f"Sending extraction complete webhook for {workflow_data['workflow_id']}")
        
        # Build webhook payload with summary data
        payload = {
            "workflow_id": workflow_data["workflow_id"],
            "event": "extraction_complete",
            "timestamp": datetime.now(UTC).isoformat() + "Z",
            
            # Summary data for routing decisions
            "summary": {
                "is_eloc": workflow_data.get("classification", {}).get("is_eloc", False),
                "email_subject": workflow_data.get("email", {}).get("subject", ""),
                "email_sender": workflow_data.get("email", {}).get("sender_email", ""),
                "company_name": workflow_data.get("extracted_fields", {}).get(
                    "vwap_purchase_share_amount", {}
                ).get("value", "Unknown"),
                "share_amount": workflow_data.get("extracted_fields", {}).get(
                    "vwap_purchase_share_amount", {}
                ).get("value", None),
                "has_questions": len(workflow_data.get("email_analysis", {}).get("questions", [])) > 0,
                "question_count": len(workflow_data.get("email_analysis", {}).get("questions", [])),
                "has_personal_comments": len(workflow_data.get("email_analysis", {}).get("personal_comments", [])) > 0
            },
            
            # Database connection info
            "database": {
                "collection": "workflows",
                "query": {"workflow_id": workflow_data["workflow_id"]}
            }
        }
        
        # Send webhook with retries
        return await self._send_with_retry(payload)
    
    async def send_extraction_failed(self, workflow_id: str, error: str) -> Dict:
        """
        Send extraction failed webhook
        
        Args:
            workflow_id: Workflow ID that failed
            error: Error message
        
        Returns:
            Webhook delivery status
        """
        logger.info(f"Sending extraction failed webhook for {workflow_id}")
        
        payload = {
            "workflow_id": workflow_id,
            "event": "extraction_failed",
            "timestamp": datetime.now(UTC).isoformat() + "Z",
            "error": error,
            
            # Database connection info
            "database": {
                "collection": "workflows",
                "query": {"workflow_id": workflow_id}
            }
        }
        
        return await self._send_with_retry(payload)
    
    async def _send_with_retry(self, payload: Dict) -> Dict:
        """
        Send webhook with retry logic
        
        Args:
            payload: Webhook payload
        
        Returns:
            Delivery status
        """
        payload_json = json.dumps(payload)
        
        # Generate HMAC signature if secret provided
        headers = {"Content-Type": "application/json"}
        if self.webhook_secret:
            signature = hmac.new(
                self.webhook_secret.encode(),
                payload_json.encode(),
                hashlib.sha256
            ).hexdigest()
            headers["X-Webhook-Signature"] = signature
        
        # Try sending with retries
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        self.webhook_url,
                        content=payload_json,
                        headers=headers
                    )
                    
                    if response.status_code in [200, 201, 202, 204]:
                        logger.info(
                            f"Webhook delivered successfully (attempt {attempt}): "
                            f"{payload['workflow_id']}"
                        )
                        return {
                            "delivered": True,
                            "attempt": attempt,
                            "status_code": response.status_code,
                            "response": response.text
                        }
                    else:
                        logger.warning(
                            f"Webhook delivery failed (attempt {attempt}): "
                            f"Status {response.status_code}"
                        )
                        last_error = f"HTTP {response.status_code}: {response.text}"
                
            except httpx.TimeoutException as e:
                logger.warning(f"Webhook timeout (attempt {attempt}): {e}")
                last_error = f"Timeout: {str(e)}"
            
            except Exception as e:
                logger.warning(f"Webhook error (attempt {attempt}): {e}")
                last_error = str(e)
            
            # Wait before retry (exponential backoff)
            if attempt < self.max_retries:
                wait_time = 2 ** attempt  # 2, 4, 8 seconds
                logger.info(f"Retrying webhook in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
        
        # All retries failed
        logger.error(
            f"Webhook delivery failed after {self.max_retries} attempts: "
            f"{payload['workflow_id']}"
        )
        return {
            "delivered": False,
            "attempts": self.max_retries,
            "last_error": last_error
        }


# Global instance (initialized in main.py)
webhook_sender = None