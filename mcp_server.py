"""
FastMCP Server — Proxy to Playwright MCP over HTTP.

This server exposes @mcp.tool decorated functions that proxy calls
to the Playwright MCP server (running on HTTP transport).

Run: python mcp_server.py
Endpoint: http://localhost:8001/mcp
"""

import os
import asyncio
import json
import base64
import traceback
from typing import Optional

from dotenv import load_dotenv
from fastmcp import FastMCP, Client
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession
from duckduckgo_search import DDGS
import chromadb
import uuid
try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

load_dotenv()

# --- Configuration ---
PLAYWRIGHT_MCP_URL = os.getenv("PLAYWRIGHT_MCP_URL", "http://localhost:9222/mcp")

# --- FastMCP Server Instance ---
mcp = FastMCP("PulseMCP-PlaywrightProxy")

# --- ChromaDB Initialization ---
CHROMA_DIR = os.path.join(os.path.dirname(__file__), "data", "chroma_db")
os.makedirs(CHROMA_DIR, exist_ok=True)
try:
    chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
    doc_collection = chroma_client.get_or_create_collection(name="documents")
except Exception as e:
    print(f"Warning: Failed to initialize ChromaDB: {e}")
    doc_collection = None


def _extract_texts(result) -> list[str]:
    """Extract text content from MCP tool result items."""
    texts = []
    items = result.content if hasattr(result, 'content') else result
    for item in items:
        if hasattr(item, 'text'):
            texts.append(item.text)
        else:
            texts.append(str(item))
    return texts


def _extract_image(result) -> dict | None:
    """Extract image data from MCP tool result items."""
    items = result.content if hasattr(result, 'content') else result
    for item in items:
        if hasattr(item, 'data') and hasattr(item, 'mimeType'):
            return {
                "type": "image",
                "mimeType": item.mimeType,
                "data": item.data,
            }
    return None


@mcp.tool
async def navigate_to(url: str) -> str:
    """Navigate the browser to a specific URL.

    Args:
        url: The URL to navigate to (e.g., 'https://example.com')
    """
    try:
        async with Client(PLAYWRIGHT_MCP_URL) as client:
            result = await client.call_tool("browser_navigate", {"url": url})
            texts = _extract_texts(result)
            return "\n".join(texts) if texts else "Navigation completed."
    except Exception as e:
        return json.dumps({"error": f"navigate_to failed: {str(e)}"})


@mcp.tool
async def take_screenshot() -> str:
    """Take a screenshot of the current browser page.
    Returns the screenshot as a JSON string with base64-encoded PNG data.
    """
    try:
        async with Client(PLAYWRIGHT_MCP_URL) as client:
            # Playwright MCP tool is 'browser_take_screenshot' with required 'type' param
            await asyncio.sleep(1) # wait briefly just in case
            result = await client.call_tool("browser_take_screenshot", {"type": "png", "fullPage": True})
            img = _extract_image(result)
            if img:
                return json.dumps(img)
            texts = _extract_texts(result)
            return "\n".join(texts) if texts else json.dumps({"error": "No screenshot data"})
    except Exception as e:
        return json.dumps({"error": f"take_screenshot failed: {str(e)}"})


@mcp.tool
async def get_page_snapshot() -> str:
    """Get an accessibility snapshot of the current page.
    Returns a text representation of the page content.
    """
    try:
        async with Client(PLAYWRIGHT_MCP_URL) as client:
            result = await client.call_tool("browser_snapshot", {})
            texts = _extract_texts(result)
            return "\n".join(texts) if texts else "No snapshot data."
    except Exception as e:
        return json.dumps({"error": f"get_page_snapshot failed: {str(e)}"})


@mcp.tool
async def navigate_and_summarize(url: str) -> str:
    """Navigate to a URL and get both a screenshot and page summary.
    Use this when the user asks to visit, open, or check a website.

    Args:
        url: The URL to navigate to and analyze
    """
    try:
        async with Client(PLAYWRIGHT_MCP_URL) as client:
            # Step 1: Navigate
            await client.call_tool("browser_navigate", {"url": url})

            # Wait for page to render
            await asyncio.sleep(2)

            # Step 2: Screenshot + Snapshot (sequential to avoid session conflicts)
            screenshot_result = await client.call_tool(
                "browser_take_screenshot", {"type": "png", "fullPage": True}
            )
            snapshot_result = await client.call_tool("browser_snapshot", {})

            # Process screenshot
            screenshot_data = _extract_image(screenshot_result)

            # Process snapshot
            snapshot_texts = _extract_texts(snapshot_result)

            return json.dumps({
                "screenshot": screenshot_data,
                "page_content": "\n".join(snapshot_texts) if snapshot_texts else "No content",
            })
    except Exception as e:
        return json.dumps({"error": f"navigate_and_summarize failed: {str(e)}"})


@mcp.tool
async def browser_click_element(target: str) -> str:
    """Click on a page element using its accessibility ref target.

    Args:
        target: The ref target of the element to click (from browser_snapshot)
    """
    try:
        async with Client(PLAYWRIGHT_MCP_URL) as client:
            result = await client.call_tool("browser_click", {"target": target})
            texts = _extract_texts(result)
            return "\n".join(texts) if texts else "Click performed."
    except Exception as e:
        return json.dumps({"error": f"browser_click failed: {str(e)}"})


@mcp.tool
async def browser_type_text(target: str, text: str, submit: bool = False) -> str:
    """Type text into a page element.

    Args:
        target: The ref target of the element to type into (from browser_snapshot)
        text: Text to type into the element
        submit: Whether to submit the form after typing
    """
    try:
        async with Client(PLAYWRIGHT_MCP_URL) as client:
            result = await client.call_tool("browser_type", {
                "target": target,
                "text": text,
                "submit": submit,
            })
            texts = _extract_texts(result)
            return "\n".join(texts) if texts else "Text typed."
    except Exception as e:
        return json.dumps({"error": f"browser_type failed: {str(e)}"})


def _chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start += chunk_size - overlap
    return chunks

@mcp.tool
def embed_document(file_path: str) -> str:
    """Read a local text or PDF file, generate embeddings, and store them persistently for querying.
    
    Args:
        file_path: The absolute path to the local file (e.g. /path/to/doc.pdf).
    """
    if not doc_collection:
        return json.dumps({"error": "ChromaDB not initialized. Check server logs."})
        
    try:
        # Check if already embedded
        results = doc_collection.get(where={"file_path": file_path})
        if results and results["ids"]:
            return json.dumps({"status": "Document already embedded."})
            
        text = ""
        if file_path.lower().endswith(".pdf"):
            if not PyPDF2:
                return json.dumps({"error": "PyPDF2 is not installed."})
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
        else:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
                
        if not text.strip():
            return json.dumps({"error": "Document is empty or text could not be extracted."})
            
        chunks = _chunk_text(text)
        filename = os.path.basename(file_path)
        
        ids = [str(uuid.uuid4()) for _ in chunks]
        metadatas = [{"file_path": file_path, "filename": filename} for _ in chunks]
        
        doc_collection.add(
            documents=chunks,
            metadatas=metadatas,
            ids=ids
        )
        
        return json.dumps({"status": f"Successfully embedded {len(chunks)} chunks from {filename}."})
    except Exception as e:
        return json.dumps({"error": f"Failed to embed document: {str(e)}"})

@mcp.tool
async def embed_onedrive_document(item_id: str, filename: str) -> str:
    """Read a document from Microsoft OneDrive by its item_id, generate embeddings, and store them persistently."""
    if not doc_collection:
        return json.dumps({"error": "ChromaDB not initialized. Check server logs."})
        
    try:
        # Check if already embedded
        results = doc_collection.get(where={"file_path": item_id})
        if results and results["ids"]:
            return json.dumps({"status": "Document already embedded."})
            
        # Fetch content from OneDrive
        async with stdio_client(get_onedrive_server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("get_file", {"item_id": item_id})
                texts = _extract_texts(result)
                text = "\n".join(texts)
                
        if not text.strip() or "File not found" in text:
            return json.dumps({"error": "Document is empty or could not be read."})
            
        chunks = _chunk_text(text)
        
        ids = [str(uuid.uuid4()) for _ in chunks]
        metadatas = [{"file_path": item_id, "filename": filename, "source": "onedrive"} for _ in chunks]
        
        doc_collection.add(
            documents=chunks,
            metadatas=metadatas,
            ids=ids
        )
        
        return json.dumps({"status": f"Successfully embedded {len(chunks)} chunks from OneDrive: {filename}."})
    except Exception as e:
        return json.dumps({"error": f"Failed to embed OneDrive document: {str(e)}"})

@mcp.tool
def query_documents(query: str, n_results: int = 3) -> str:
    """Search through all previously embedded documents for text relevant to the query.
    
    Args:
        query: The search text or question.
        n_results: Number of relevant chunks to return (default 3).
    """
    if not doc_collection:
        return json.dumps({"error": "ChromaDB not initialized."})
        
    try:
        results = doc_collection.query(
            query_texts=[query],
            n_results=n_results
        )
        
        if not results or not results["documents"] or not results["documents"][0]:
            return json.dumps({"status": "No relevant documents found."})
            
        extracted = []
        for i, doc in enumerate(results["documents"][0]):
            meta = results["metadatas"][0][i] if results["metadatas"] else {}
            filename = meta.get("filename", "Unknown File")
            extracted.append(f"--- From: {filename} ---\n{doc}")
            
        return "\n\n".join(extracted)
    except Exception as e:
        return json.dumps({"error": f"Failed to query documents: {str(e)}"})

@mcp.tool
def list_embedded_documents() -> str:
    """Get a list of all documents that have been embedded and are available for querying."""
    if not doc_collection:
        return json.dumps({"error": "ChromaDB not initialized."})
        
    try:
        data = doc_collection.get(include=["metadatas"])
        if not data or not data["metadatas"]:
            return json.dumps({"files": []})
            
        files = []
        seen = set()
        for meta in data["metadatas"]:
            if "filename" in meta:
                fname = meta["filename"]
                if fname not in seen:
                    seen.add(fname)
                    files.append({
                        "name": fname,
                        "source": meta.get("source", "local")
                    })
                
        return json.dumps({"files": files})
    except Exception as e:
        return json.dumps({"error": f"Failed to list documents: {str(e)}"})


# --- Extra Tools ---
@mcp.tool
def web_search(query: str) -> str:
    """Search the web for real-time information."""
    try:
        results = DDGS().text(query, max_results=5)
        if not results:
            return "No results found."
        formatted = []
        for r in results:
            formatted.append(f"Title: {r.get('title')}\nURL: {r.get('href')}\nSummary: {r.get('body')}\n")
        return "\n".join(formatted)
    except Exception as e:
        return json.dumps({"error": f"Search failed: {str(e)}"})

@mcp.tool
async def store_memory(entity: str, observation: str) -> str:
    """Store a persistent memory fact about a user or topic."""
    server_params = StdioServerParameters(command="npx", args=["-y", "@modelcontextprotocol/server-memory"])
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.call_tool("create_entities", {
                    "entities": [{"name": entity, "entityType": "Concept", "observations": [observation]}]
                })
                return "Memory stored successfully."
    except Exception as e:
        return json.dumps({"error": f"Memory store failed: {str(e)}"})

@mcp.tool
async def read_memory() -> str:
    """Read the full persistent memory graph to recall past facts."""
    server_params = StdioServerParameters(command="npx", args=["-y", "@modelcontextprotocol/server-memory"])
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("read_graph", {})
                texts = _extract_texts(result)
                return "\n".join(texts) if texts else "No memory graph exists yet."
    except Exception as e:
        return json.dumps({"error": f"Memory read failed: {str(e)}"})

@mcp.tool
async def read_local_file(path: str) -> str:
    """Read a file from the local workspace filesystem."""
    server_params = StdioServerParameters(command="npx", args=["-y", "@modelcontextprotocol/server-filesystem", "/Users/vaibhavbansal/.gemini/antigravity/scratch"])
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("read_file", {"path": path})
                texts = _extract_texts(result)
                return "\n".join(texts) if texts else "File empty."
    except Exception as e:
        return json.dumps({"error": f"File read failed: {str(e)}"})

@mcp.tool
async def list_local_directory(path: str) -> str:
    """List contents of a directory in the local workspace."""
    server_params = StdioServerParameters(command="npx", args=["-y", "@modelcontextprotocol/server-filesystem", "/Users/vaibhavbansal/.gemini/antigravity/scratch"])
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("list_directory", {"path": path})
                texts = _extract_texts(result)
                return "\n".join(texts) if texts else "Directory empty."
    except Exception as e:
        return json.dumps({"error": f"Directory list failed: {str(e)}"})

# --- OneDrive MCP Tools ---
def get_onedrive_server_params() -> StdioServerParameters:
    onedrive_dir = os.path.join(os.path.dirname(__file__), "onedrive_mcp")
    index_js = os.path.join(onedrive_dir, "dist", "index.js")
    return StdioServerParameters(command="node", args=[index_js], env=os.environ.copy())

@mcp.tool
async def onedrive_list_files(folder_path: str = "root") -> str:
    """List files and folders in a specific Microsoft OneDrive path. (Default is 'root')"""
    try:
        async with stdio_client(get_onedrive_server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("list_files", {"path": folder_path})
                texts = _extract_texts(result)
                return "\n".join(texts) if texts else "Folder empty."
    except Exception as e:
        return json.dumps({"error": f"OneDrive list failed: {str(e)}"})

@mcp.tool
async def onedrive_search_files(query: str) -> str:
    """Search for files in Microsoft OneDrive by name or content."""
    try:
        async with stdio_client(get_onedrive_server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("search_files", {"query": query})
                texts = _extract_texts(result)
                return "\n".join(texts) if texts else "No files found."
    except Exception as e:
        return json.dumps({"error": f"OneDrive search failed: {str(e)}"})
        
@mcp.tool
async def onedrive_read_file(item_id: str) -> str:
    """Read details or content of a Microsoft OneDrive file by its item_id."""
    try:
        async with stdio_client(get_onedrive_server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("get_file", {"item_id": item_id})
                texts = _extract_texts(result)
                return "\n".join(texts) if texts else "File empty."
    except Exception as e:
        return json.dumps({"error": f"OneDrive read failed: {str(e)}"})
# --- Run the server ---
if __name__ == "__main__":
    port = int(os.getenv("FASTMCP_PORT", "8001"))
    print(f"🚀 Starting FastMCP Playwright Proxy on http://localhost:{port}/mcp")
    print(f"📡 Connecting to Playwright MCP at {PLAYWRIGHT_MCP_URL}")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port, path="/mcp")
