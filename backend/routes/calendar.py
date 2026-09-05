from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException

from backend.services.calendar_service import get_calendar_status, list_upcoming_events

router = APIRouter()

@router.get("/api/calendar/status")
async def get_status():
    """Check if the Google Calendar integration is connected."""
    return get_calendar_status()

@router.get("/api/calendar/events")
async def get_events(days_ahead: int = 7):
    """Get upcoming Google Calendar events."""
    status = get_calendar_status()
    if status["status"] != "connected":
        raise HTTPException(status_code=403, detail="Google Calendar is not connected")
        
    events = list_upcoming_events(days_ahead)
    return events
