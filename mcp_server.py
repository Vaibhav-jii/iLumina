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

# --- Persistent Playwright Browser Session ---
# All browser tools share this single client so navigate→click→snapshot
# all operate on the SAME browser tab (fixes session isolation bug).
_playwright_client = None
_playwright_lock = asyncio.Lock()

async def get_browser_client():
    """Get or create a persistent Playwright MCP client session."""
    global _playwright_client
    async with _playwright_lock:
        if _playwright_client is None:
            _playwright_client = Client(PLAYWRIGHT_MCP_URL)
            await _playwright_client.__aenter__()
        return _playwright_client

async def reset_browser_client():
    """Reset the persistent client if it becomes stale."""
    global _playwright_client
    async with _playwright_lock:
        if _playwright_client is not None:
            try:
                await _playwright_client.__aexit__(None, None, None)
            except Exception:
                pass
            _playwright_client = None

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
        client = await get_browser_client()
        result = await client.call_tool("browser_navigate", {"url": url})
        texts = _extract_texts(result)
        return "\n".join(texts) if texts else "Navigation completed."
    except Exception as e:
        await reset_browser_client()
        return json.dumps({"error": f"navigate_to failed: {str(e)}"})


@mcp.tool
async def take_screenshot() -> str:
    """Take a screenshot of the current browser page.
    Returns the screenshot as a JSON string with base64-encoded PNG data.
    """
    try:
        client = await get_browser_client()
        await asyncio.sleep(1)
        result = await client.call_tool("browser_take_screenshot", {"type": "png", "fullPage": True})
        img = _extract_image(result)
        if img:
            return json.dumps(img)
        texts = _extract_texts(result)
        return "\n".join(texts) if texts else json.dumps({"error": "No screenshot data"})
    except Exception as e:
        await reset_browser_client()
        return json.dumps({"error": f"take_screenshot failed: {str(e)}"})


@mcp.tool
async def get_page_snapshot() -> str:
    """Get an accessibility snapshot of the current page.
    Returns a text representation of the page content.
    """
    try:
        client = await get_browser_client()
        result = await client.call_tool("browser_snapshot", {})
        texts = _extract_texts(result)
        return "\n".join(texts) if texts else "No snapshot data."
    except Exception as e:
        await reset_browser_client()
        return json.dumps({"error": f"get_page_snapshot failed: {str(e)}"})


@mcp.tool
async def navigate_and_summarize(url: str) -> str:
    """Navigate to a URL and get both a screenshot and page summary.
    Use this when the user asks to visit, open, or check a website.

    Args:
        url: The URL to navigate to and analyze
    """
    try:
        client = await get_browser_client()
        # Step 1: Navigate
        await client.call_tool("browser_navigate", {"url": url})

        # Wait for page to render
        await asyncio.sleep(2)

        # Step 2: Screenshot + Snapshot
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
        await reset_browser_client()
        return json.dumps({"error": f"navigate_and_summarize failed: {str(e)}"})


@mcp.tool
async def browser_click_element(target: str) -> str:
    """Click on a page element using its exact text or accessibility ref target.
    This tool captures page state BEFORE and AFTER clicking to verify the click actually worked.
    Returns: status, state_changed (bool), url_before, url_after, page_content (post-click snapshot).
    
    Args:
        target: The exact text of the element or the ref target ID.
    """
    try:
        # Auto-format bare text into Playwright text selectors
        if not target.isdigit() and not target.startswith("text=") and target.find("=") == -1 and not target.startswith("#") and not target.startswith("."):
            if '"' not in target:
                target = f'text="{target}"'
            else:
                target = f"text={target}"
                
        client = await get_browser_client()
        
        # --- BEFORE state ---
        try:
            before_snapshot = await client.call_tool("browser_snapshot", {})
            before_texts = _extract_texts(before_snapshot)
            before_text = "\n".join(before_texts) if before_texts else ""
            # Extract URL and title from the snapshot header
            before_url = ""
            before_title = ""
            for line in before_texts[:5]:
                if "url:" in line.lower():
                    before_url = line.split(":", 1)[-1].strip()
                if "title:" in line.lower():
                    before_title = line.split(":", 1)[-1].strip()
        except Exception:
            before_url = "unknown"
            before_title = "unknown"
            before_text = ""
        
        # --- CLICK ---
        try:
            result = await client.call_tool("browser_click", {"target": target})
            texts = _extract_texts(result)
            result_text_str = " ".join(texts).lower() if texts else ""
            if "failed" in result_text_str or "not found" in result_text_str or "error" in result_text_str:
                return json.dumps({
                    "error": f"Playwright could not find or click '{target}'. Try clicking a different TEXT substring or a CSS selector instead!",
                    "playwright_output": result_text_str
                })
        except Exception as e:
            return json.dumps({"error": f"Failed to click '{target}'. Try using a valid CSS selector or different TEXT! Error: {str(e)}"})
        
        # Wait for navigation/animation/network
        await asyncio.sleep(2)
        
        # --- AFTER state ---
        screenshot_result = await client.call_tool("browser_take_screenshot", {"type": "png", "fullPage": True})
        after_snapshot = await client.call_tool("browser_snapshot", {})
        
        screenshot_data = _extract_image(screenshot_result)
        after_texts = _extract_texts(after_snapshot)
        after_text = "\n".join(after_texts) if after_texts else "No content"
        
        after_url = ""
        after_title = ""
        for line in after_texts[:5]:
            if "url:" in line.lower():
                after_url = line.split(":", 1)[-1].strip()
            if "title:" in line.lower():
                after_title = line.split(":", 1)[-1].strip()
        
        # --- Compare states ---
        state_changed = (before_url != after_url) or (before_title != after_title) or (before_text[:500] != after_text[:500])
        
        return json.dumps({
            "status": f"Clicked '{target}'",
            "state_changed": state_changed,
            "url_before": before_url,
            "url_after": after_url,
            "title_before": before_title,
            "title_after": after_title,
            "screenshot": screenshot_data,
            "page_content": after_text
        })
    except Exception as e:
        await reset_browser_client()
        return json.dumps({"error": f"browser_click_element failed completely: {str(e)}"})


@mcp.tool
async def browser_type_text(target: str, text: str, submit: bool = False) -> str:
    """Type text into a page element.
    This tool automatically takes a screenshot and returns the new page snapshot after typing!

    Args:
        target: The exact text of the input field or its ref target ID.
        text: Text to type into the element
        submit: Whether to submit the form after typing
    """
    try:
        client = await get_browser_client()
        try:
            await client.call_tool("browser_type", {
                "target": target,
                "text": text,
                "submit": submit,
            })
        except Exception as e:
            return json.dumps({"error": f"Failed to type into '{target}'. Error: {str(e)}"})
        
        # Wait for any potential navigation or UI updates
        await asyncio.sleep(1.5)
        
        # Automatically grab new state
        screenshot_result = await client.call_tool("browser_take_screenshot", {"type": "png", "fullPage": True})
        snapshot_result = await client.call_tool("browser_snapshot", {})
        
        screenshot_data = _extract_image(screenshot_result)
        snapshot_texts = _extract_texts(snapshot_result)
        
        return json.dumps({
            "status": f"Successfully typed into '{target}'",
            "screenshot": screenshot_data,
            "page_content": "\n".join(snapshot_texts) if snapshot_texts else "No content"
        })
    except Exception as e:
        await reset_browser_client()
        return json.dumps({"error": f"browser_type_text failed completely: {str(e)}"})


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
def query_documents(query: str, n_results: int = 5, filename_filter: str = None) -> str:
    """Search through all previously embedded documents for text relevant to the query.
    
    Args:
        query: The search text or question.
        n_results: Number of relevant chunks to return (default 5).
        filename_filter: If provided, restricts the search to a specific filename (exact match) to avoid mixing up different documents.
    """
    if not doc_collection:
        return json.dumps({"error": "ChromaDB not initialized."})
        
    try:
        kwargs = {
            "query_texts": [query],
            "n_results": n_results
        }
        if filename_filter:
            kwargs["where"] = {"filename": filename_filter}
            
        results = doc_collection.query(**kwargs)
        
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


# --- Run the server ---
if __name__ == "__main__":
    port = int(os.getenv("FASTMCP_PORT", "8001"))
    print(f"🚀 Starting FastMCP Playwright Proxy on http://localhost:{port}/mcp")
    print(f"📡 Connecting to Playwright MCP at {PLAYWRIGHT_MCP_URL}")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port, path="/mcp")
