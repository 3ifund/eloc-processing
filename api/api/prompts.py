"""
Prompts API endpoints for managing AI prompts
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import logging

from repositories.prompts_repository import prompts_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


class PromptCreate(BaseModel):
    name: str
    template: str
    description: Optional[str] = None
    model_config: Optional[dict] = None


class PromptUpdate(BaseModel):
    template: Optional[str] = None
    active: Optional[bool] = None


@router.get("")
async def list_prompts(name: Optional[str] = None):
    """List all prompts (optionally filtered by name)"""
    try:
        prompts = await prompts_repo.list_prompts(name)
        return {"prompts": prompts, "count": len(prompts)}
    except Exception as e:
        logger.error(f"Error listing prompts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{name}")
async def get_active_prompt(name: str):
    """Get the active prompt by name"""
    try:
        prompt = await prompts_repo.get_active_prompt(name)
        if not prompt:
            raise HTTPException(status_code=404, detail="Prompt not found")
        return prompt
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting prompt: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{name}/{version}")
async def get_prompt_version(name: str, version: str):
    """Get a specific version of a prompt"""
    try:
        prompt = await prompts_repo.get_prompt_by_version(name, version)
        if not prompt:
            raise HTTPException(status_code=404, detail="Prompt version not found")
        return prompt
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting prompt version: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{name}/version")
async def create_new_version(name: str, prompt_create: PromptCreate):
    """Create a new version of an existing prompt"""
    try:
        prompt_id = await prompts_repo.create_new_version(
            name=name,
            template=prompt_create.template,
            model_config=prompt_create.model_config,
            description=prompt_create.description
        )
        return {"prompt_id": prompt_id, "message": "New version created"}
    except Exception as e:
        logger.error(f"Error creating new version: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{name}/{version}/activate")
async def activate_prompt_version(name: str, version: str):
    """Activate a specific prompt version"""
    try:
        await prompts_repo.activate_prompt(name, version)
        return {"message": f"Activated {name} v{version}"}
    except Exception as e:
        logger.error(f"Error activating prompt: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{name}/{version}/deactivate")
async def deactivate_prompt_version(name: str, version: str):
    """Deactivate a specific prompt version"""
    try:
        await prompts_repo.deactivate_prompt(name, version)
        return {"message": f"Deactivated {name} v{version}"}
    except Exception as e:
        logger.error(f"Error deactivating prompt: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats/overview")
async def get_prompt_statistics():
    """Get prompt statistics"""
    try:
        stats = await prompts_repo.get_prompt_statistics()
        return stats
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))