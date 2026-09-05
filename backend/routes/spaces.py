import uuid
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List

from backend.db.store import (
    create_space, list_spaces, delete_space, 
    get_space_documents_full, add_document_to_space, remove_document_from_space
)

router = APIRouter()

class SpaceCreate(BaseModel):
    name: str
    document_ids: List[str] = []

class DocumentAttach(BaseModel):
    document_id: str
    filepath: str
    source: str


@router.get("/api/spaces")
async def get_spaces():
    """List all knowledge spaces."""
    spaces = list_spaces()
    return spaces

@router.post("/api/spaces")
async def create_new_space(space: SpaceCreate):
    """Create a new knowledge space and optionally attach documents."""
    space_id = str(uuid.uuid4())
    create_space(space_id, space.name)

    # Auto-attach selected document_ids to the space
    for doc_id in space.document_ids:
        try:
            add_document_to_space(space_id, doc_id, doc_id, "selected")
        except Exception as e:
            print(f"⚠️ Failed to attach doc {doc_id} to space: {e}")

    return {"id": space_id, "name": space.name}

@router.delete("/api/spaces/{space_id}")
async def remove_space(space_id: str):
    """Delete a space."""
    delete_space(space_id)
    return {"status": "ok"}

@router.get("/api/spaces/{space_id}/documents")
async def get_space_docs(space_id: str):
    """List documents in a space."""
    docs = get_space_documents_full(space_id)
    return docs

@router.post("/api/spaces/{space_id}/documents")
async def attach_document(space_id: str, doc: DocumentAttach):
    """Attach a document to a space."""
    add_document_to_space(space_id, doc.document_id, doc.filepath, doc.source)
    return {"status": "ok"}

@router.delete("/api/spaces/{space_id}/documents/{document_id}")
async def detach_document(space_id: str, document_id: str):
    """Detach a document from a space."""
    remove_document_from_space(space_id, document_id)
    return {"status": "ok"}
