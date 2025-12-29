"""
Review API endpoints for WPF application
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Dict
from datetime import datetime
import logging

from repositories.workflow_repository import workflow_repo
from repositories.gridfs_repository import gridfs_repo
from api.websocket_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


# ==================== MODELS ====================

class ApprovalRequest(BaseModel):
    reviewer_email: str
    corrections: Optional[Dict] = None
    notes: Optional[str] = None


class RejectionRequest(BaseModel):
    reviewer_email: str
    reason: str


class ReviewSummary(BaseModel):
    workflow_id: str
    email_subject: str
    company_name: Optional[str]
    created_at: str
    age_hours: float
    confidence: Optional[str]
    reason: Optional[str]


# ==================== ENDPOINTS ====================

@router.get("/pending", response_model=List[ReviewSummary])
async def get_pending_reviews():
    """
    Get all reviews awaiting human approval
    Sorted by creation time (oldest first)
    """
    try:
        workflows = await workflow_repo.get_pending_reviews()
        
        reviews = []
        for w in workflows:
            created_at = w.get("created_at")
            age_hours = (datetime.utcnow() - created_at).total_seconds() / 3600 if created_at else 0
            
            reviews.append(ReviewSummary(
                workflow_id=str(w["_id"]),
                email_subject=w.get("email_subject", ""),
                company_name=w.get("extracted_fields", {}).get("company_name"),
                created_at=created_at.isoformat() if created_at else "",
                age_hours=round(age_hours, 1),
                confidence=w.get("signature", {}).get("confidence"),
                reason=w.get("human_review", {}).get("reason")
            ))
        
        logger.info(f"Returned {len(reviews)} pending reviews")
        return reviews
        
    except Exception as e:
        logger.error(f"Error fetching pending reviews: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{workflow_id}")
async def get_review_detail(workflow_id: str):
    """Get complete details for a specific review"""
    try:
        workflow = await workflow_repo.find_by_id(workflow_id)
        
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        return {
            "workflow_id": workflow_id,
            "email_id": workflow.get("email_id"),
            "email_subject": workflow.get("email_subject"),
            "email_sender": workflow.get("email_sender"),
            "email_sender_name": workflow.get("email_sender_name"),
            "email_received_at": workflow.get("email_received_at").isoformat() if workflow.get("email_received_at") else None,
            
            "classification": workflow.get("classification"),
            "signature": workflow.get("signature"),
            "extracted_fields": workflow.get("extracted_fields"),
            
            "attachments": workflow.get("attachments"),
            "eloc_attachment": workflow.get("pdf_word_attachments", [{}])[0] if workflow.get("pdf_word_attachments") else None,
            
            "human_review": workflow.get("human_review"),
            
            "created_at": workflow.get("created_at").isoformat() if workflow.get("created_at") else None,
            "processing_stage": workflow.get("processing_stage")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching review detail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{workflow_id}/document")
async def get_review_document(workflow_id: str):
    """Get the PDF/Word document for a review"""
    try:
        workflow = await workflow_repo.find_by_id(workflow_id)
        
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        # Get the ELOC attachment
        attachments = workflow.get("pdf_word_attachments", [])
        if not attachments:
            raise HTTPException(status_code=404, detail="No document found")
        
        attachment = attachments[0]
        gridfs_id = attachment.get("gridfs_id")
        
        if not gridfs_id:
            raise HTTPException(status_code=404, detail="Document not in storage")
        
        # Retrieve from GridFS
        file_data = gridfs_repo.get_file(gridfs_id)
        
        if not file_data:
            raise HTTPException(status_code=404, detail="Document file not found")
        
        from fastapi.responses import Response
        return Response(
            content=file_data,
            media_type=attachment.get("content_type", "application/pdf"),
            headers={
                "Content-Disposition": f'inline; filename="{attachment.get("filename")}"'
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching document: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{workflow_id}/approve")
async def approve_review(workflow_id: str, approval: ApprovalRequest, background_tasks: BackgroundTasks):
    """
    Approve a review (with optional field corrections)
    Triggers Phase 2 workflow in background
    """
    try:
        # Update MongoDB
        await workflow_repo.approve_review(
            workflow_id,
            approval.reviewer_email,
            approval.corrections
        )
        
        # Notify via WebSocket
        await ws_manager.notify_review_approved(workflow_id, approval.reviewer_email)
        
        # Trigger Phase 2 in background
        background_tasks.add_task(resume_phase2_workflow, workflow_id)
        
        logger.info(f"Review approved: {workflow_id} by {approval.reviewer_email}")
        
        return {
            "status": "approved",
            "workflow_id": workflow_id,
            "reviewer": approval.reviewer_email
        }
        
    except Exception as e:
        logger.error(f"Error approving review: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{workflow_id}/reject")
async def reject_review(workflow_id: str, rejection: RejectionRequest):
    """Reject a review"""
    try:
        # Update MongoDB
        await workflow_repo.reject_review(
            workflow_id,
            rejection.reviewer_email,
            rejection.reason
        )
        
        # Notify via WebSocket
        await ws_manager.notify_review_rejected(workflow_id, rejection.reviewer_email, rejection.reason)
        
        logger.info(f"Review rejected: {workflow_id} by {rejection.reviewer_email}")
        
        return {
            "status": "rejected",
            "workflow_id": workflow_id,
            "reviewer": rejection.reviewer_email
        }
        
    except Exception as e:
        logger.error(f"Error rejecting review: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats/dashboard")
async def get_dashboard_stats():
    """Get statistics for dashboard"""
    try:
        stats = await workflow_repo.get_statistics()
        
        return {
            "pending_reviews": stats.get("awaiting_human_review", 0),
            "approved_today": stats.get("human_approved", 0),
            "completed": stats.get("complete", 0),
            "failed": stats.get("failed", 0),
            "total": sum(stats.values())
        }
        
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== HELPER FUNCTIONS ====================

async def resume_phase2_workflow(workflow_id: str):
    """Resume Phase 2 workflow after approval"""
    try:
        logger.info(f"Resuming Phase 2 for workflow: {workflow_id}")
        
        # Load workflow state
        workflow = await workflow_repo.find_by_id(workflow_id)
        
        if not workflow:
            logger.error(f"Workflow {workflow_id} not found for Phase 2")
            return
        
        # TODO: Implement Phase 2 logic
        # - Call Bloomberg API
        # - Update SharePoint
        # - Mark complete
        
        logger.info(f"Phase 2 completed for workflow: {workflow_id}")
        
        # Notify completion
        await ws_manager.notify_workflow_complete(workflow_id)
        
    except Exception as e:
        logger.error(f"Error in Phase 2 workflow: {e}")