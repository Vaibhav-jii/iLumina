from typing import List
from fastapi import APIRouter, HTTPException

from backend.schemas.memory import MemoryCreate, MemoryResponse
from backend.db.context_store import create_memory, list_memories, delete_memory

router = APIRouter()

@router.get("/api/memory", response_model=List[MemoryResponse])
async def get_memories():
    """List all permanent user memories."""
    return list_memories()


@router.post("/api/memory", response_model=dict)
async def add_memory(memory: MemoryCreate):
    """Manually add a memory (or called via Agent)."""
    memory_id = create_memory(memory.content, memory.category)
    return {"status": "success", "id": memory_id}


@router.delete("/api/memory/{memory_id}")
async def remove_memory(memory_id: str):
    """Delete a user memory."""
    delete_memory(memory_id)
    return {"status": "success"}
