import sqlite3
from typing import List, Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks

from backend.schemas.context import ExtractedEntity, ExtractedEvent, ExtractedFact
from backend.services.extraction_service import async_run_extraction_for_document
from backend.db.store import get_space_documents
from backend.config import DB_PATH

router = APIRouter()

@router.post("/api/context/extract/{document_id}")
async def trigger_extraction(document_id: str, background_tasks: BackgroundTasks):
    """
    Trigger the AI extractor to process a document.
    Runs asynchronously in the background.
    """
    # Define wrapper for background execution
    async def bg_extract(doc_id: str):
        print(f"Starting background extraction for {doc_id}...")
        results = await async_run_extraction_for_document(doc_id)
        print(f"Background extraction complete: {results}")

    background_tasks.add_task(bg_extract, document_id)
    return {"status": "success", "message": f"Extraction triggered in background for {document_id}"}


@router.get("/api/context/events", response_model=List[ExtractedEvent])
async def get_events(space_id: Optional[str] = None):
    """Retrieve extracted events. Optionally filter by space_id."""
    events = []
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        
        if space_id:
            allowed_docs = get_space_documents(space_id)
            if not allowed_docs:
                return []
            
            # SQLite safe parameterization for IN clause
            placeholders = ', '.join(['?'] * len(allowed_docs))
            query = f'SELECT * FROM extracted_events WHERE document_id IN ({placeholders})'
            cursor = conn.execute(query, allowed_docs)
        else:
            cursor = conn.execute('SELECT * FROM extracted_events')
            
        for row in cursor.fetchall():
            events.append(dict(row))
            
    return events


@router.get("/api/context/entities", response_model=List[ExtractedEntity])
async def get_entities(space_id: Optional[str] = None, type: Optional[str] = None):
    """Retrieve extracted entities. Optionally filter by space_id and/or entity type."""
    entities = []
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        
        query_parts = []
        params = []
        
        if space_id:
            allowed_docs = get_space_documents(space_id)
            if not allowed_docs:
                return []
            placeholders = ', '.join(['?'] * len(allowed_docs))
            query_parts.append(f'document_id IN ({placeholders})')
            params.extend(allowed_docs)
            
        if type:
            query_parts.append('entity_type = ?')
            params.append(type)
            
        query = 'SELECT * FROM extracted_entities'
        if query_parts:
            query += ' WHERE ' + ' AND '.join(query_parts)
            
        cursor = conn.execute(query, tuple(params))
            
        for row in cursor.fetchall():
            entities.append(dict(row))
            
    return entities
