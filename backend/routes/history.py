"""
Chat history CRUD routes.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.models import ChatTitleUpdate
from backend.db.store import load_session, list_chats, update_title, delete_session, get_session_metadata, get_space_documents_full

router = APIRouter()


@router.get("/api/chats")
async def get_chats(mode: str = "chat"):
    """List all saved chat sessions filtered by mode."""
    return list_chats(mode)


@router.get("/api/chats/{session_id}")
async def get_chat_history(session_id: str):
    """Get full message history for a session."""
    history = load_session(session_id)
    metadata = get_session_metadata(session_id)
    
    # Fetch selected document names if this session has a space
    selected_documents = []
    space_id = metadata.get("space_id")
    if space_id:
        docs = get_space_documents_full(space_id)
        selected_documents = [{"document_id": d["document_id"], "filepath": d.get("filepath", "")} for d in docs]
    
    return {
        "session_id": session_id,
        "messages": history,
        "space_id": space_id,
        "space_name": metadata.get("space_name"),
        "selected_documents": selected_documents,
        "selected_doc_count": len(selected_documents)
    }


@router.put("/api/chats/{session_id}/title")
async def update_chat_title(session_id: str, request: ChatTitleUpdate):
    """Update the title of a chat session."""
    try:
        update_title(session_id, request.title)
        return {"status": "success"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.delete("/api/chats/{session_id}")
async def delete_chat(session_id: str):
    """Delete a specific chat session."""
    try:
        delete_session(session_id)
        return {"status": "success"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
