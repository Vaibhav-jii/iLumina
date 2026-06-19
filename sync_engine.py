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

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from googleapiclient.http import MediaIoBaseDownload

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
        metadatas = [{"source": "onedrive", "item_id": item_id, "filename": name, "filepath": full_path, "last_modified": last_modified, "chunk_index": i} for i in range(len(chunks))]
        
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

async def process_gdrive_file(service, item):
    item_id = item.get('id')
    name = item.get('name')
    last_modified = item.get('modifiedTime', "")
    mime_type = item.get('mimeType', "")
    
    # Check if we already processed this exact version
    existing = doc_collection.get(where={"item_id": item_id})
    if existing and existing.get('metadatas'):
        old_meta = existing['metadatas'][0]
        if old_meta.get('last_modified') == last_modified:
            return # Already up to date
            
        doc_collection.delete(where={"item_id": item_id})
        
    print(f"Downloading and embedding GDrive file: {name}")
    try:
        # Export Google Docs as plain text, download other files directly
        if "vnd.google-apps" in mime_type:
            if mime_type == "application/vnd.google-apps.document":
                request = service.files().export_media(fileId=item_id, mimeType='text/plain')
            else:
                return # Skip other Google-native formats for now
        else:
            request = service.files().get_media(fileId=item_id)
            
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        
        content_bytes = fh.getvalue()
        
        # Parse text
        temp_name = name
        if "vnd.google-apps.document" in mime_type:
            temp_name += ".txt"
        elif mime_type == "application/pdf" and not name.lower().endswith(".pdf"):
            temp_name += ".pdf"
            
        text = await extract_text_from_bytes(content_bytes, temp_name)
        if not text.strip():
            print(f"No text extracted from {name}")
            return
            
        chunks = chunk_text(text)
        ids = [f"{item_id}_chunk_{i}" for i in range(len(chunks))]
        metadatas = [{"source": "gdrive", "item_id": item_id, "filename": name, "filepath": f"Google Drive/{name}", "last_modified": last_modified, "chunk_index": i} for i in range(len(chunks))]
        
        doc_collection.add(documents=chunks, ids=ids, metadatas=metadatas)
        print(f"Successfully embedded {len(chunks)} chunks for Google Drive/{name}")
    except Exception as e:
        print(f"Failed to process GDrive file {name}: {e}")

async def sync_gdrive_cycle():
    while True:
        print("\n--- Starting Google Drive Sync Cycle ---")
        try:
            if not os.path.exists("token.json"):
                print("No token.json found. Skipping Google Drive sync.")
                await asyncio.sleep(300)
                continue
            
            scopes = ['https://www.googleapis.com/auth/drive']
            creds = Credentials.from_authorized_user_file('token.json', scopes)
            service = build('drive', 'v3', credentials=creds)
            
            # Query files (ignore folders, only files owned by me)
            results = service.files().list(
                pageSize=100, fields="nextPageToken, files(id, name, modifiedTime, mimeType)",
                q="mimeType != 'application/vnd.google-apps.folder' and 'me' in owners"
            ).execute()
            
            items = results.get('files', [])
            for item in items:
                await process_gdrive_file(service, item)
                
        except Exception as e:
            print(f"GDrive Sync Error: {e}")
            traceback.print_exc()
            
        print("--- GDrive Sync Cycle Complete. Sleeping for 5 minutes ---")
        await asyncio.sleep(300)

async def main():
    await asyncio.gather(
        run_sync_engine(),
        sync_gdrive_cycle()
    )

if __name__ == "__main__":
    print("🚀 Booting up iLumina Multi-Cloud Sync Engine...")
    asyncio.run(main())
