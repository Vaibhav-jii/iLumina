import os
from fastapi import APIRouter
from backend.services.calendar_service import get_calendar_status
from backend.mcp.client import MCP_SESSIONS

router = APIRouter()

@router.get("/api/integrations")
async def get_integrations_status():
    """Return the status of all available integrations."""
    integrations = []
    
    # Google Calendar
    cal_status = get_calendar_status()
    integrations.append({
        "provider": "google_calendar",
        "status": cal_status["status"]
    })
    
    # Google Drive (Natively handled by Chroma/FastMCP)
    integrations.append({
        "provider": "google_drive",
        "status": "connected"
    })
    
    # GitHub MCP
    gh_status = "connected" if "github" in MCP_SESSIONS else "disconnected"
    if gh_status == "disconnected" and not os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN"):
        gh_status = "error" # Token not provided
        
    integrations.append({
        "provider": "github",
        "status": gh_status
    })
    
    # Filesystem MCP
    fs_status = "connected" if "filesystem" in MCP_SESSIONS else "disconnected"
    integrations.append({
        "provider": "filesystem",
        "status": fs_status
    })
    
    # Microsoft 365 MCP
    ms_status = "connected" if "ms365" in MCP_SESSIONS else "disconnected"
    integrations.append({
        "provider": "ms365",
        "status": ms_status
    })
    
    return integrations
