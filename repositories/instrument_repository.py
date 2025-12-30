"""
Instrument repository - Base class for ELOC, Warrant, Convertible, Preferred
Manages communication history (data) and workflow state (state) documents
"""
from typing import List, Dict, Optional
from datetime import datetime, UTC
import logging
import uuid

from repositories.mongo_client import mongo_client

logger = logging.getLogger(__name__)


class InstrumentRepository:
    """Base repository for instrument data and state management"""
    
    def __init__(self, instrument_type: str):
        """
        Initialize repository for specific instrument type
        Args:
            instrument_type: "eloc", "warrant", "convertible", "preferred"
        """
        self.instrument_type = instrument_type
        self.data_collection_name = f"{instrument_type}_data"
        self.state_collection_name = f"{instrument_type}_state"
        self.id_field = f"{instrument_type}_id"
        
        logger.info(f"Initialized {instrument_type} repository")
    
    @property
    def data_collection(self):
        """Get data collection (communication history)"""
        return mongo_client.db[self.data_collection_name]
    
    @property
    def state_collection(self):
        """Get state collection (workflow state)"""
        return mongo_client.db[self.state_collection_name]
    
    async def create_instrument(self, instrument_id: str, initial_communication: Dict, 
                               initial_state: str, initial_data: Dict) -> bool:
        """
        Create new instrument with first communication and initial state
        
        Args:
            instrument_id: Unique identifier (e.g., "ELOC-2024-001")
            initial_communication: First email/communication data
            initial_state: Initial workflow state (e.g., "notice")
            initial_data: Extracted data from initial document
        
        Returns:
            True if created, False if already exists
        """
        # Check if already exists
        existing = await self.data_collection.find_one({self.id_field: instrument_id})
        if existing:
            logger.warning(f"{self.instrument_type} {instrument_id} already exists")
            return False
        
        # Create data document with first communication
        data_doc = {
            self.id_field: instrument_id,
            "communications": [
                {
                    "sequence": 1,
                    **initial_communication
                }
            ],
            "created_at": datetime.now(UTC),
            "last_updated": datetime.now(UTC)
        }
        
        # Create state document
        state_doc = {
            self.id_field: instrument_id,
            "current_state": initial_state,
            "state_history": [
                {
                    "state": initial_state,
                    "entered_at": datetime.now(UTC),
                    "triggered_by_seq": 1
                }
            ],
            "current_data": initial_data,
            "requires_action": True,
            "created_at": datetime.now(UTC),
            "last_updated": datetime.now(UTC)
        }
        
        # Insert both documents
        await self.data_collection.insert_one(data_doc)
        await self.state_collection.insert_one(state_doc)
        
        logger.info(f"Created {self.instrument_type}: {instrument_id} in state '{initial_state}'")
        return True
    
    async def append_communication(self, instrument_id: str, communication: Dict) -> int:
        """
        Append new communication to existing instrument
        
        Args:
            instrument_id: Instrument identifier
            communication: Communication data (email, attachments, etc.)
        
        Returns:
            Sequence number of added communication
        """
        # Get current data document to determine next sequence number
        data_doc = await self.data_collection.find_one({self.id_field: instrument_id})
        
        if not data_doc:
            raise ValueError(f"{self.instrument_type} {instrument_id} not found")
        
        # Calculate next sequence number
        next_seq = len(data_doc["communications"]) + 1
        
        # Add sequence number to communication
        communication["sequence"] = next_seq
        
        # Append to communications array
        await self.data_collection.update_one(
            {self.id_field: instrument_id},
            {
                "$push": {"communications": communication},
                "$set": {"last_updated": datetime.now(UTC)}
            }
        )
        
        logger.info(f"Appended communication #{next_seq} to {self.instrument_type} {instrument_id}")
        return next_seq
    
    async def update_state(self, instrument_id: str, new_state: str, 
                          updated_data: Optional[Dict] = None,
                          triggered_by_seq: Optional[int] = None) -> bool:
        """
        Update instrument workflow state
        
        Args:
            instrument_id: Instrument identifier
            new_state: New workflow state
            updated_data: Updated extracted data (optional)
            triggered_by_seq: Communication sequence that triggered this change
        
        Returns:
            True if state changed, False if already in that state
        """
        # Get current state
        state_doc = await self.state_collection.find_one({self.id_field: instrument_id})
        
        if not state_doc:
            raise ValueError(f"{self.instrument_type} {instrument_id} not found")
        
        current_state = state_doc["current_state"]
        
        # Check if already in this state
        if current_state == new_state and updated_data is None:
            logger.info(f"{self.instrument_type} {instrument_id} already in state '{new_state}'")
            return False
        
        # Build update document
        update_doc = {
            "last_updated": datetime.now(UTC)
        }
        
        # Update state if changed
        if current_state != new_state:
            update_doc["current_state"] = new_state
            
            # Add to state history
            state_history_entry = {
                "state": new_state,
                "entered_at": datetime.now(UTC),
                "triggered_by_seq": triggered_by_seq
            }
        
        # Update data if provided
        if updated_data:
            update_doc["current_data"] = updated_data
        
        # Perform update
        if current_state != new_state:
            await self.state_collection.update_one(
                {self.id_field: instrument_id},
                {
                    "$set": update_doc,
                    "$push": {"state_history": state_history_entry}
                }
            )
            logger.info(f"{self.instrument_type} {instrument_id}: {current_state} → {new_state}")
        else:
            await self.state_collection.update_one(
                {self.id_field: instrument_id},
                {"$set": update_doc}
            )
            logger.info(f"Updated data for {self.instrument_type} {instrument_id}")
        
        return True
    
    async def get_data(self, instrument_id: str) -> Optional[Dict]:
        """Get complete communication history"""
        data_doc = await self.data_collection.find_one({self.id_field: instrument_id})
        return data_doc
    
    async def get_state(self, instrument_id: str) -> Optional[Dict]:
        """Get current workflow state"""
        state_doc = await self.state_collection.find_one({self.id_field: instrument_id})
        return state_doc
    
    async def get_complete_view(self, instrument_id: str) -> Optional[Dict]:
        """Get both data and state in one call"""
        data_doc = await self.get_data(instrument_id)
        state_doc = await self.get_state(instrument_id)
        
        if not data_doc or not state_doc:
            return None
        
        return {
            "data": data_doc,
            "state": state_doc
        }
    
    async def find_by_state(self, state: str, limit: int = 100) -> List[Dict]:
        """Find all instruments in given state"""
        cursor = self.state_collection.find(
            {"current_state": state}
        ).sort("last_updated", -1).limit(limit)
        
        instruments = []
        async for doc in cursor:
            instruments.append(doc)
        
        return instruments
    
    async def find_requiring_action(self, limit: int = 100) -> List[Dict]:
        """Find all instruments requiring action"""
        cursor = self.state_collection.find(
            {"requires_action": True}
        ).sort("last_updated", -1).limit(limit)
        
        instruments = []
        async for doc in cursor:
            instruments.append(doc)
        
        return instruments
    
    async def set_requires_action(self, instrument_id: str, requires: bool):
        """Set requires_action flag"""
        await self.state_collection.update_one(
            {self.id_field: instrument_id},
            {"$set": {"requires_action": requires, "last_updated": datetime.now(UTC)}}
        )
    
    async def update_assignee(self, instrument_id: str, assignee: str):
        """Update assignee"""
        await self.state_collection.update_one(
            {self.id_field: instrument_id},
            {"$set": {"assignee": assignee, "last_updated": datetime.now(UTC)}}
        )
    
    async def get_statistics(self) -> Dict:
        """Get statistics by state"""
        pipeline = [
            {
                "$group": {
                    "_id": "$current_state",
                    "count": {"$sum": 1}
                }
            }
        ]
        
        cursor = self.state_collection.aggregate(pipeline)
        stats = {}
        
        async for doc in cursor:
            stats[doc["_id"]] = doc["count"]
        
        return stats
    
    async def count_by_state(self, state: str) -> int:
        """Count instruments in given state"""
        return await self.state_collection.count_documents({"current_state": state})
    
    async def get_communication_by_sequence(self, instrument_id: str, sequence: int) -> Optional[Dict]:
        """Get specific communication by sequence number"""
        data_doc = await self.data_collection.find_one({self.id_field: instrument_id})
        
        if not data_doc:
            return None
        
        for comm in data_doc["communications"]:
            if comm["sequence"] == sequence:
                return comm
        
        return None
    
    def generate_unique_id(self) -> str:
        """Generate unique instrument ID"""
        prefix = self.instrument_type.upper()
        year = datetime.now(UTC).year
        unique_part = uuid.uuid4().hex[:8].upper()
        return f"{prefix}-{year}-{unique_part}"


# Specific instrument repositories
class ELOCRepository(InstrumentRepository):
    """Repository for ELOC instruments"""
    def __init__(self):
        super().__init__("eloc")


class WarrantRepository(InstrumentRepository):
    """Repository for Warrant instruments"""
    def __init__(self):
        super().__init__("warrant")


class ConvertibleRepository(InstrumentRepository):
    """Repository for Convertible instruments"""
    def __init__(self):
        super().__init__("convertible")


class PreferredRepository(InstrumentRepository):
    """Repository for Preferred instruments"""
    def __init__(self):
        super().__init__("preferred")


# Global instances
eloc_repo = ELOCRepository()
warrant_repo = WarrantRepository()
convertible_repo = ConvertibleRepository()
preferred_repo = PreferredRepository()