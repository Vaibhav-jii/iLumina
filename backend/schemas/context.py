from typing import Optional
from pydantic import BaseModel, Field

class ExtractedEntity(BaseModel):
    id: str
    document_id: str
    entity_type: str = Field(..., description="'person', 'organization', 'location', 'technology', 'project'")
    value: str
    confidence: float
    evidence: str
    source_page: Optional[str] = None
    created_at: Optional[str] = None

class ExtractedEvent(BaseModel):
    id: str
    document_id: str
    title: str
    event_type: str = Field(..., description="'interview', 'meeting', 'deadline', 'exam', 'submission', 'appointment'")
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    confidence: float
    evidence: str
    source_page: Optional[str] = None
    status: str = "detected"
    created_at: Optional[str] = None

class ExtractedFact(BaseModel):
    id: str
    document_id: str
    subject: str
    predicate: str
    object: str
    confidence: float
    evidence: str
    source_page: Optional[str] = None
    created_at: Optional[str] = None
