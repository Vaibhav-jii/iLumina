import os
import time
import json
import base64
import asyncio
import io
import traceback
from pathlib import Path
from dotenv import load_dotenv

import chromadb
from fastmcp import Client as MCPClient
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

try:
    import docx
except ImportError:
    docx = None

load_dotenv()

CHROMA_DIR = os.path.join(os.path.dirname(__file__), "data", "chroma_db")
os.makedirs(CHROMA_DIR, exist_ok=True)
chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
doc_collection = chroma_client.get_or_create_collection(name="documents")

def chunk_text(text: str, chunk_size=1000, overlap=200):
    chunks = []
    i = 0
    while i < len(text):
        chunks.append(text[i:i + chunk_size])
        i += chunk_size - overlap
    return chunks

async def extract_text_from_bytes(content_bytes: bytes, filename: str) -> str:
    ext = filename.lower().split('.')[-1]
    if ext == 'pdf' and PyPDF2:
        try:
            reader = PyPDF2.PdfReader(io.BytesIO(content_bytes))
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"
            return text
        except Exception as e:
            print(f"Error parsing PDF {filename}: {e}")
            return ""
    elif ext in ['doc', 'docx'] and docx:
        try:
            doc = docx.Document(io.BytesIO(content_bytes))
            return "\n".join([p.text for p in doc.paragraphs])
        except Exception as e:
            print(f"Error parsing Word doc {filename}: {e}")
            return ""
    else:
        # Fallback to UTF-8
        try:
            return content_bytes.decode('utf-8')
        except:
            return ""

async def crawl_onedrive(session: ClientSession, drive_id: str, item_id: str, path_prefix: str = ""):
    print(f"Crawling folder: {path_prefix or '/'}")
    try:
        # list-folder-files takes driveId and driveItemId
        result = await session.call_tool("list-folder-files", {"driveId": drive_id, "driveItemId": item_id})
        
        if hasattr(result, 'content'):
            data_str = result.content[0].text
            try:
                data = json.loads(data_str)
                items = data.get("value", [])
                
                for item in items:
                    name = item.get("name", "")
                    child_id = item.get("id", "")
                    is_folder = "folder" in item
                    
                    full_path = f"{path_prefix}/{name}" if path_prefix else name
                    
                    if is_folder:
                        await crawl_onedrive(session, drive_id, child_id, full_path)
                    else:
                        ext = name.lower().split('.')[-1]
                        if ext in ['pdf', 'doc', 'docx', 'txt', 'md']:
                            await process_file(session, drive_id, item, full_path)
            except json.JSONDecodeError:
                print(f"Could not parse list-folder-files output for {item_id}")
    except Exception as e:
        print(f"Error crawling folder {item_id}: {e}")

async def process_file(session: ClientSession, drive_id: str, item: dict, full_path: str):
    item_id = item.get("id")
    name = item.get("name")
    last_modified = item.get("lastModifiedDateTime", "")
    
    # Check if we already processed this exact version
    existing = doc_collection.get(where={"item_id": item_id})
    if existing and existing.get('metadatas'):
        old_meta = existing['metadatas'][0]
        if old_meta.get('last_modified') == last_modified:
            return # Already up to date
            
        # Delete old chunks first
        doc_collection.delete(where={"item_id": item_id})
        
    print(f"Downloading and embedding: {full_path}")
    
    try:
        # download-bytes tool requires target path
        target = f"/drives/{drive_id}/items/{item_id}/content"
        dl_result = await session.call_tool("download-bytes", {"target": target})
        dl_data = json.loads(dl_result.content[0].text)
        b64_content = dl_data.get("contentBytes", "")
        content_bytes = base64.b64decode(b64_content)
        
        # Parse text
        text = await extract_text_from_bytes(content_bytes, name)
        if not text.strip():
            print(f"No text extracted from {name}")
            return
            
        # Chunk & Embed
        chunks = chunk_text(text)
        ids = [f"{item_id}_chunk_{i}" for i in range(len(chunks))]
        metadatas = [{"item_id": item_id, "filename": name, "filepath": full_path, "last_modified": last_modified, "chunk_index": i} for i in range(len(chunks))]
        
        doc_collection.add(
            documents=chunks,
            ids=ids,
            metadatas=metadatas
        )
        print(f"Successfully embedded {len(chunks)} chunks for {full_path}")
        
    except Exception as e:
        print(f"Failed to process {name}: {e}")

async def run_sync_engine():
    params = StdioServerParameters(command="npx", args=["-y", "@softeria/ms-365-mcp-server"])
    while True:
        print("\n--- Starting OneDrive Sync Cycle ---")
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    
                    # 1. Get personal drive ID via graph-batch
                    drive_result = await session.call_tool("graph-batch", {
                        "body": {
                            "requests": [
                                {
                                    "id": "1",
                                    "method": "GET",
                                    "url": "/me/drive"
                                }
                            ]
                        }
                    })
                    
                    drive_data_raw = json.loads(drive_result.content[0].text)
                    drive_body = drive_data_raw.get("responses", [])[0].get("body", {})
                    drive_id = drive_body.get("id")
                    
                    if not drive_id:
                        print("Failed to get personal driveId")
                        continue
                        
                    # 2. Get root item
                    root_result = await session.call_tool("get-drive-root-item", {"driveId": drive_id})
                    root_data = json.loads(root_result.content[0].text)
                    
                    root_id = root_data.get("id")
                    
                    if root_id and drive_id:
                        await crawl_onedrive(session, drive_id, root_id)
                    else:
                        print("Failed to resolve root drive.")
                        
        except Exception as e:
            print(f"Sync Engine Error: {e}")
            traceback.print_exc()
            
        print("--- Sync Cycle Complete. Sleeping for 5 minutes ---")
        await asyncio.sleep(300)

if __name__ == "__main__":
    print("🚀 Booting up iLumina OneDrive Sync Engine...")
    asyncio.run(run_sync_engine())
