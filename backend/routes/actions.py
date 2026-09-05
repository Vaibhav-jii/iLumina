from typing import List, Optional
from fastapi import APIRouter, HTTPException

from backend.schemas.actions import ProposedActionResponse
from backend.db.context_store import get_action, list_actions, update_action_status
from backend.services.calendar_service import execute_calendar_create
from backend.mcp.client import execute_mcp_tool
import json

router = APIRouter()

@router.get("/api/actions", response_model=List[ProposedActionResponse])
async def get_all_actions(status: Optional[str] = None):
    """List actions, optionally filtered by status."""
    actions = list_actions(status=status)
    return actions

@router.get("/api/actions/pending", response_model=List[ProposedActionResponse])
async def get_pending_actions():
    """List all actions pending user approval."""
    actions = list_actions(status='pending')
    return actions

@router.get("/api/actions/{action_id}", response_model=ProposedActionResponse)
async def get_single_action(action_id: str):
    """Get details of a specific action."""
    action = get_action(action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    return action

@router.post("/api/actions/{action_id}/approve")
async def approve_action(action_id: str):
    """Approve a pending action and execute it."""
    action = get_action(action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    if action["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Action cannot be approved because its status is {action['status']}")
    
    # 1. Update status to approved/executing
    update_action_status(action_id, "approved")
    
    # 2. Execute the action
    execution_result_json = "{}"
    try:
        if action["action_type"] == "calendar.create":
            link = execute_calendar_create(action["payload"])
            execution_result_json = json.dumps({"message": "Event created successfully", "link": link})
        elif action["action_type"] == "mcp":
            tool_name = action["payload"].get("tool_name")
            tool_args = action["payload"].get("tool_args", {})
            mcp_result = await execute_mcp_tool(tool_name, tool_args)
            execution_result_json = json.dumps({"message": "MCP Action executed successfully", "result": mcp_result})
        else:
            execution_result_json = json.dumps({"message": f"Action type '{action['action_type']}' not supported for execution."})
            
        update_action_status(action_id, "executed", result=execution_result_json)
        return {"status": "success", "message": "Action approved and executed"}
        
    except Exception as e:
        update_action_status(action_id, "failed", result=json.dumps({"error": str(e)}))
        raise HTTPException(status_code=500, detail=f"Action execution failed: {str(e)}")

@router.post("/api/actions/{action_id}/reject")
async def reject_action(action_id: str):
    """Reject a pending action."""
    action = get_action(action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    if action["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Action cannot be rejected because its status is {action['status']}")
    
    update_action_status(action_id, "rejected")
    return {"status": "success", "message": "Action rejected"}
