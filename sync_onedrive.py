import os
import sys
import json
import asyncio
from dotenv import load_dotenv

load_dotenv()

# We can import chromadb exactly like mcp_server.py
import chromadb
import uuid
import PyPDF2

CHROMA_DIR = os.path.join(os.path.dirname(__file__), "data", "chroma_db")
try:
    chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
    doc_collection = chroma_client.get_or_create_collection(name="documents")
except Exception as e:
    print(f"Warning: Failed to initialize ChromaDB in sync worker: {e}")
    doc_collection = None

# Using the mcp client SDK to talk to the node process directly
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

def _chunk_text(text: str, chunk_size: int = 1000, overlap: int = 100) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start += chunk_size - overlap
    return chunks

async def sync():
    if not doc_collection:
        print("❌ Cannot sync, ChromaDB is unavailable.")
        return

    if not os.getenv("TENANT_ID") or not os.getenv("CLIENT_ID") or not os.getenv("CLIENT_SECRET"):
        print("⚠️ OneDrive API keys missing in .env. Skipping auto-embed sync.")
        return

    print("🔄 Starting OneDrive Auto-Sync Worker...")
    onedrive_dir = os.path.join(os.path.dirname(__file__), "onedrive_mcp")
    index_js = os.path.join(onedrive_dir, "dist", "index.js")
    server_params = StdioServerParameters(command="node", args=[index_js], env=os.environ.copy())
    
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                
                print("Fetching OneDrive file list...")
                result = await session.call_tool("list_files", {"path": "/"})
                
                # result.content contains the tool output
                items_str = result.content[0].text if hasattr(result.content[0], 'text') else str(result.content[0])
                try:
                    # Depending on how bit-onedrivemcp returns it, it might be JSON string
                    files = json.loads(items_str)
                except:
                    print("⚠️ Failed to parse OneDrive files as JSON.")
                    files = []
                    
                if isinstance(files, dict) and "files" in files:
                    files = files["files"]
                elif isinstance(files, dict) and "value" in files:
                    files = files["value"]
                    
                if not files:
                    print("No files found in OneDrive root.")
                    return
                    
                for file_info in files:
                    filename = file_info.get("name", "")
                    item_id = file_info.get("id", "")
                    
                    if not filename or not item_id:
                        continue
                        
                    # Skip unsupported files for embedding
                    ext = filename.lower().split('.')[-1]
                    if ext not in ["txt", "md", "pdf"]:
                        continue
                        
                    # Check if already embedded
                    results = doc_collection.get(where={"file_path": item_id})
                    if results and results["ids"]:
                        print(f"✅ {filename} is already embedded.")
                        continue
                        
                    print(f"📥 Fetching content for {filename}...")
                    file_result = await session.call_tool("get_file", {"item_id": item_id})
                    texts = [c.text for c in file_result.content if hasattr(c, 'text')]
                    text = "\n".join(texts)
                    
                    if not text.strip() or "File not found" in text:
                        print(f"⚠️ Could not extract text from {filename}")
                        continue
                        
                    print(f"🧠 Embedding {filename}...")
                    chunks = _chunk_text(text)
                    ids = [str(uuid.uuid4()) for _ in chunks]
                    metadatas = [{"file_path": item_id, "filename": filename, "source": "onedrive"} for _ in chunks]
                    
                    doc_collection.add(
                        documents=chunks,
                        metadatas=metadatas,
                        ids=ids
                    )
                    print(f"✅ Embedded {filename} successfully ({len(chunks)} chunks)")
                    
    except Exception as e:
        print(f"❌ Auto-sync error: {e}")

if __name__ == "__main__":
    asyncio.run(sync())
