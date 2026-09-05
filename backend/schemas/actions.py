from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime

class ProposedActionCreate(BaseModel):
    action_type: str = Field(..., description="e.g. 'calendar.create', 'github.create_issue'")
    provider: str = Field(..., description="e.g. 'google_calendar', 'github'")
    title: str = Field(..., description="Short title for the UI")
    description: Optional[str] = Field(None, description="Longer description of what this does")
    payload: Dict[str, Any] = Field(..., description="The actual API arguments")
    reason: Optional[str] = Field(None, description="Why the agent wants to do this")
    session_id: Optional[str] = Field(None, description="Chat session that spawned this action")

class ProposedActionResponse(ProposedActionCreate):
    id: str
    status: str = Field(..., description="'pending', 'approved', 'rejected', 'executed', 'failed'")
    result: Optional[str] = Field(None, description="JSON string of execution result")
    created_at: str
    resolved_at: Optional[str] = None
