from typing import Optional
from pydantic import BaseModel, Field

class MemoryCreate(BaseModel):
    content: str = Field(..., description="The fact or preference to remember")
    category: str = Field("general", description="e.g. 'preference', 'fact', 'project', 'general'")

class MemoryResponse(MemoryCreate):
    id: str
    created_at: str
    updated_at: str
