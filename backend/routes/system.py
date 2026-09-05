"""
System routes — health checks, tool listing, and document tree.
"""

import json

import chromadb
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from fastmcp import Client as MCPClient

from backend.config import FASTMCP_URL, GROQ_API_KEY, GOOGLE_API_KEY, CHROMA_DIR

router = APIRouter()

# ChromaDB client for document tree queries
try:
    _chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
    _doc_collection = _chroma_client.get_or_create_collection(name="documents")
except Exception as e:
    print(f"Warning: Failed to initialize ChromaDB in system routes: {e}")
    _doc_collection = None


@router.get("/api/health")
async def health():
    """Health check endpoint."""
    mcp_status = "unknown"
    try:
        async with MCPClient(FASTMCP_URL) as client:
            await client.list_tools()
            mcp_status = "connected"
    except Exception:
        mcp_status = "disconnected"

    return {
        "status": "ok",
        "mcp_server": mcp_status,
        "groq_configured": bool(GROQ_API_KEY),
        "gemini_configured": bool(GOOGLE_API_KEY),
    }


@router.get("/api/tools")
async def list_tools():
    """List available MCP tools from the FastMCP server."""
    try:
        async with MCPClient(FASTMCP_URL) as client:
            tools = await client.list_tools()
            return [{"name": t.name, "description": t.description or ""} for t in tools]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Could not connect to MCP server: {str(e)}"})


@router.get("/api/documents")
async def list_documents():
    """List embedded documents from the MCP server."""
    from backend.mcp.client import MCP_SESSIONS
    try:
        if "documents" in MCP_SESSIONS:
            session = MCP_SESSIONS["documents"]["session"]
            result = await session.call_tool("list_embedded_documents", {})
            texts = []
            items = result.content if hasattr(result, 'content') else result
            for item in items:
                if hasattr(item, 'text'):
                    texts.append(item.text)
                else:
                    texts.append(str(item))
            res_str = "\n".join(texts)
            try:
                return json.loads(res_str)
            except Exception:
                return {"files": []}
        return {"files": []}
    except Exception:
        return {"files": []}


@router.get("/api/documents/tree")
async def get_document_tree():
    """Return a nested JSON tree of all embedded documents categorized by source."""
    if not _doc_collection:
        return {"onedrive": {}, "gdrive": {}, "local": {}}

    result = _doc_collection.get()
    metadatas = result.get('metadatas', [])

    unique_files = {}
    for meta in metadatas:
        filepath = meta.get('filepath')
        if filepath and filepath not in unique_files:
            unique_files[filepath] = {
                "document_id": meta.get('document_id') or meta.get('item_id') or filepath,
                "name": meta.get('filename'),
                "last_modified": meta.get('last_modified'),
                "source": meta.get('source', 'onedrive')
            }

    trees = {"onedrive": {}, "gdrive": {}, "local": {}}
    for filepath, details in unique_files.items():
        source = details["source"]
        if source not in trees:
            trees[source] = {}

        parts = filepath.split('/')
        current_node = trees[source]
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                current_node[part] = {"_type": "file", "path": filepath, "details": details}
            else:
                if part not in current_node:
                    current_node[part] = {"_type": "directory", "children": {}}
                current_node = current_node[part]["children"]

    return trees
