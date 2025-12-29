"""
Prompts repository - Manage AI prompts in MongoDB
"""
from typing import Optional, Dict, List
from datetime import datetime
import logging

from repositories.mongo_client import mongo_client

logger = logging.getLogger(__name__)


class PromptsRepository:
    """Repository for prompt management"""
    
    def __init__(self):
        self.collection_name = "prompts"
    
    @property
    def collection(self):
        return mongo_client.db[self.collection_name]
    
    async def create(self, prompt_data: Dict) -> str:
        """
        Create a new prompt version
        Returns: prompt_id (string)
        """
        prompt_data.update({
            "created_at": datetime.utcnow(),
            "active": True
        })
        
        result = await self.collection.insert_one(prompt_data)
        prompt_id = str(result.inserted_id)
        
        logger.info(f"Created prompt: {prompt_data['name']} v{prompt_data['version']}")
        return prompt_id
    
    async def get_active_prompt(self, name: str) -> Optional[Dict]:
        """
        Get the active prompt by name
        Returns the highest version number that is active
        """
        cursor = self.collection.find({
            "name": name,
            "active": True
        }).sort("version", -1).limit(1)
        
        prompt = await cursor.to_list(length=1)
        
        if prompt:
            prompt = prompt[0]
            prompt["_id"] = str(prompt["_id"])
            return prompt
        
        logger.warning(f"No active prompt found for: {name}")
        return None
    
    async def get_prompt_by_version(self, name: str, version: str) -> Optional[Dict]:
        """Get a specific version of a prompt"""
        prompt = await self.collection.find_one({
            "name": name,
            "version": version
        })
        
        if prompt:
            prompt["_id"] = str(prompt["_id"])
        
        return prompt
    
    async def list_prompts(self, name: Optional[str] = None) -> List[Dict]:
        """List all prompts (optionally filtered by name)"""
        query = {"name": name} if name else {}
        
        cursor = self.collection.find(query).sort([("name", 1), ("version", -1)])
        
        prompts = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            prompts.append(doc)
        
        return prompts
    
    async def deactivate_prompt(self, name: str, version: str):
        """Deactivate a specific prompt version"""
        await self.collection.update_one(
            {"name": name, "version": version},
            {"$set": {"active": False, "deactivated_at": datetime.utcnow()}}
        )
        logger.info(f"Deactivated prompt: {name} v{version}")
    
    async def activate_prompt(self, name: str, version: str):
        """Activate a specific prompt version (deactivates all others)"""
        # Deactivate all versions of this prompt
        await self.collection.update_many(
            {"name": name},
            {"$set": {"active": False}}
        )
        
        # Activate the specified version
        await self.collection.update_one(
            {"name": name, "version": version},
            {"$set": {"active": True, "activated_at": datetime.utcnow()}}
        )
        
        logger.info(f"Activated prompt: {name} v{version}")
    
    async def create_new_version(self, name: str, template: str, 
                                model_config: Optional[Dict] = None,
                                description: Optional[str] = None) -> str:
        """
        Create a new version of an existing prompt
        Auto-increments version number
        """
        # Get latest version
        latest = await self.collection.find_one(
            {"name": name},
            sort=[("version", -1)]
        )
        
        if latest:
            # Parse version (e.g., "1.0" -> 1, 0)
            parts = latest["version"].split(".")
            major = int(parts[0])
            minor = int(parts[1]) if len(parts) > 1 else 0
            
            # Increment minor version
            new_version = f"{major}.{minor + 1}"
        else:
            # First version
            new_version = "1.0"
        
        # Create new prompt
        prompt_data = {
            "name": name,
            "version": new_version,
            "template": template,
            "model_config": model_config or {
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "temperature": 0
            },
            "description": description,
            "active": False  # Don't auto-activate
        }
        
        prompt_id = await self.create(prompt_data)
        
        logger.info(f"Created new version: {name} v{new_version}")
        return prompt_id
    
    async def get_prompt_statistics(self) -> Dict:
        """Get statistics about prompts"""
        pipeline = [
            {
                "$group": {
                    "_id": "$name",
                    "total_versions": {"$sum": 1},
                    "active_version": {
                        "$max": {
                            "$cond": [{"$eq": ["$active", True]}, "$version", None]
                        }
                    }
                }
            }
        ]
        
        cursor = self.collection.aggregate(pipeline)
        stats = {}
        
        async for doc in cursor:
            stats[doc["_id"]] = {
                "total_versions": doc["total_versions"],
                "active_version": doc.get("active_version")
            }
        
        return stats


# Global instance
prompts_repo = PromptsRepository()