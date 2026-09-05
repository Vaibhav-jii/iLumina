import chromadb
from typing import List, Dict, Any

from backend.config import CHROMA_DIR
from backend.core.context.extractor import extract_context_from_text
from backend.db.context_store import (
    clear_document_context, 
    insert_extracted_entity, 
    insert_extracted_event
)

def run_extraction_for_document(document_id: str) -> Dict[str, int]:
    """
    Fetch document text from ChromaDB, run it through the AI extractor,
    and persist the results into SQLite.
    
    Returns the number of entities and events extracted.
    """
    try:
        chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
        doc_collection = chroma_client.get_or_create_collection(name="documents")
    except Exception as e:
        print(f"Extraction Service Error: Could not connect to ChromaDB: {e}")
        return {"entities": 0, "events": 0}

    # Fetch chunks for this document
    results = doc_collection.get(where={"document_id": document_id}, include=["documents", "metadatas"])
    
    if not results or not results["documents"]:
        print(f"Extraction Service: No document chunks found for document_id {document_id}")
        return {"entities": 0, "events": 0}
        
    documents = results["documents"]
    metadatas = results.get("metadatas", [])
    
    if not documents:
        return {"entities": 0, "events": 0}
        
    # Get filename from first chunk's metadata
    filename = "unknown_document"
    if metadatas and metadatas[0] and "filename" in metadatas[0]:
        filename = metadatas[0]["filename"]

    # Combine text. Limit to first ~30,000 characters to avoid huge payload for now.
    # In a full implementation, we would process chunk-by-chunk or use an overlap strategy.
    full_text = "\n\n".join(documents)
    if len(full_text) > 30000:
        full_text = full_text[:30000]
        
    import asyncio
    try:
        # Run async extraction from sync context
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    if loop.is_running():
        # If we are already in an event loop (e.g. FastAPI route), run it as a coroutine
        # But this function is sync, so we should really provide an async version.
        # For simplicity, we'll assume it's awaited by an async caller, so let's make this async.
        raise RuntimeError("run_extraction_for_document must be called asynchronously or converted to async.")
        
    raise RuntimeError("Use async_run_extraction_for_document instead.")

async def async_run_extraction_for_document(document_id: str) -> Dict[str, int]:
    """
    Async version: Fetch document text from ChromaDB, run it through the AI extractor,
    and persist the results into SQLite.
    """
    try:
        chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
        doc_collection = chroma_client.get_or_create_collection(name="documents")
    except Exception as e:
        print(f"Extraction Service Error: Could not connect to ChromaDB: {e}")
        return {"entities": 0, "events": 0}

    results = doc_collection.get(where={"document_id": document_id}, include=["documents", "metadatas"])
    
    if not results or not results["documents"]:
        return {"entities": 0, "events": 0}
        
    documents = results["documents"]
    metadatas = results.get("metadatas", [])
    
    if not documents:
        return {"entities": 0, "events": 0}
        
    filename = "unknown_document"
    if metadatas and metadatas[0] and "filename" in metadatas[0]:
        filename = metadatas[0]["filename"]

    full_text = "\n\n".join(documents)
    if len(full_text) > 30000:
        full_text = full_text[:30000]
        
    # Run the extractor
    extracted_data = await extract_context_from_text(full_text, document_id, filename)
    
    # Persist to SQLite
    # 1. Clear existing context for this document to avoid duplicates
    clear_document_context(document_id)
    
    from backend.db.context_store import insert_document_summary
    
    # 2. Insert new summary if present
    summary = extracted_data.get("summary", "")
    if summary:
        insert_document_summary(document_id, summary)
    
    # 3. Insert new entities
    entities_count = 0
    for entity in extracted_data.get("entities", []):
        insert_extracted_entity(entity)
        entities_count += 1
        
    # 4. Insert new events
    events_count = 0
    for event in extracted_data.get("events", []):
        insert_extracted_event(event)
        events_count += 1
        
    return {"entities": entities_count, "events": events_count}
