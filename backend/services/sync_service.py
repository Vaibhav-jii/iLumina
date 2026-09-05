import os
import json
import asyncio
import io
import traceback
from datetime import datetime
from typing import Optional

from mcp.client.session import ClientSession
import chromadb

# Try to import document parsers
try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

try:
    import docx
except ImportError:
    docx = None

from backend.db.context_store import get_synced_file, upsert_synced_file
from backend.services.extraction_service import async_run_extraction_for_document

# Initialize ChromaDB client
CHROMA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "chroma_db")
os.makedirs(CHROMA_DIR, exist_ok=True)
try:
    chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
    doc_collection = chroma_client.get_or_create_collection(name="documents")
except Exception as e:
    print(f"Warning: Could not initialize ChromaDB for SyncEngine: {e}")
    doc_collection = None


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


# ==========================================
# ONEDRIVE SYNC
# ==========================================

async def process_onedrive_file(session: ClientSession, drive_id: str, item: dict, full_path: str):
    item_id = item.get("id")
    name = item.get("name")
    file_info = item.get("file", {})
    mime_type = file_info.get("mimeType", "")
    last_modified = item.get("lastModifiedDateTime", "")
    
    # Check if already synced and unchanged
    synced = get_synced_file(item_id)
    if synced and synced["last_modified"] == last_modified:
        return # Skip, already processed
        
    print(f"Syncing OneDrive file: {full_path}")
    try:
        # Fetch file download URL using get-download-url tool
        result = await session.call_tool("get-download-url", {"target": f"/drives/{drive_id}/items/{item_id}"})
        
        if hasattr(result, 'content') and result.content:
            raw_url_res = result.content[0].text
            try:
                download_url = json.loads(raw_url_res).get("downloadUrl")
            except Exception:
                download_url = raw_url_res
                
            if download_url:
                import httpx
                
                # Safely fetch raw uncorrupted bytes
                async with httpx.AsyncClient() as client:
                    response = await client.get(download_url)
                    response.raise_for_status()
                    content_bytes = response.content
            else:
                content_bytes = b""
                
            text = await extract_text_from_bytes(content_bytes, name)
            
            if text and text.strip() and doc_collection:
                chunks = chunk_text(text)
                ids = [f"{item_id}_{i}" for i in range(len(chunks))]
                metadatas = [{"document_id": item_id, "filepath": full_path, "filename": name, "source": "onedrive", "last_modified": last_modified} for _ in chunks]
                
                # Delete old chunks
                doc_collection.delete(where={"filepath": full_path})
                
                doc_collection.add(
                    documents=chunks,
                    metadatas=metadatas,
                    ids=ids
                )
                
                # Extract summary and context using NVIDIA AI ONLY once
                print(f"Extracting context for {name}...")
                await async_run_extraction_for_document(item_id)
                
                upsert_synced_file(item_id, "onedrive", last_modified)
                print(f"✅ Successfully synced {name}")
                
    except Exception as e:
        print(f"Failed to sync {full_path}: {e}")
        traceback.print_exc()


async def crawl_onedrive(session: ClientSession, drive_id: str, item_id: str, path_prefix: str = ""):
    try:
        result = await session.call_tool("list-folder-files", {"driveId": drive_id, "driveItemId": item_id})
        
        if hasattr(result, 'content') and result.content:
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
                            await process_onedrive_file(session, drive_id, item, full_path)
            except json.JSONDecodeError:
                print(f"Could not parse list-folder-files output for {item_id}")
    except Exception as e:
        print(f"Error crawling folder {item_id}: {e}")


async def sync_onedrive_loop(session: ClientSession):
    """Background loop to sync OneDrive files."""
    print("🚀 OneDrive Background Sync Started")
    while True:
        try:
            # Get drives
            result = await session.call_tool("list-drives", {})
            if hasattr(result, 'content') and result.content:
                data = json.loads(result.content[0].text)
                drives = data.get("value", [])
                if drives:
                    drive_id = drives[0].get("id")
                    
                    # Get root folder
                    root_res = await session.call_tool("get-drive-root-item", {"driveId": drive_id})
                    if hasattr(root_res, 'content') and root_res.content:
                        root_data = json.loads(root_res.content[0].text)
                        root_id = root_data.get("id")
                        if root_id:
                            await crawl_onedrive(session, drive_id, root_id)
        except Exception as e:
            print(f"OneDrive sync loop error: {e}")
            
        await asyncio.sleep(300) # 5 minutes


# ==========================================
# GOOGLE DRIVE SYNC
# ==========================================

async def sync_gdrive_loop():
    """Background loop to sync Google Drive files."""
    print("🚀 Google Drive Background Sync Started")
    while True:
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            
            token_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "token.json")
            if os.path.exists(token_path):
                creds = Credentials.from_authorized_user_file(token_path, ['https://www.googleapis.com/auth/drive.readonly'])
                service = build('drive', 'v3', credentials=creds)
                
                # Search for all files owned by user
                results = service.files().list(
                    q="mimeType != 'application/vnd.google-apps.folder' and 'me' in owners",
                    pageSize=100,
                    fields="nextPageToken, files(id, name, mimeType, modifiedTime)"
                ).execute()
                
                items = results.get('files', [])
                for item in items:
                    item_id = item['id']
                    name = item['name']
                    mime_type = item.get('mimeType', '')
                    last_modified = item.get('modifiedTime', '')
                    
                    synced = get_synced_file(item_id)
                    if synced and synced["last_modified"] == last_modified:
                        continue
                        
                    print(f"Syncing Google Drive file: {name}")
                    
                    try:
                        from googleapiclient.http import MediaIoBaseDownload
                        
                        if "vnd.google-apps" in mime_type:
                            if mime_type == "application/vnd.google-apps.document":
                                request = service.files().export_media(fileId=item_id, mimeType='text/plain')
                                temp_name = name + ".txt"
                            else:
                                continue # Skip other google formats
                        else:
                            request = service.files().get_media(fileId=item_id)
                            temp_name = name
                            if mime_type == "application/pdf" and not name.lower().endswith(".pdf"):
                                temp_name += ".pdf"
                                
                        fh = io.BytesIO()
                        downloader = MediaIoBaseDownload(fh, request)
                        done = False
                        while done is False:
                            status, done = downloader.next_chunk()
                        
                        content_bytes = fh.getvalue()
                        text = await extract_text_from_bytes(content_bytes, temp_name)
                        
                        if text and text.strip() and doc_collection:
                            chunks = chunk_text(text)
                            ids = [f"{item_id}_{i}" for i in range(len(chunks))]
                            metadatas = [{"document_id": item_id, "filepath": f"gdrive://{name}", "filename": name, "source": "gdrive", "last_modified": last_modified} for _ in chunks]
                            
                            doc_collection.delete(where={"filepath": f"gdrive://{name}"})
                            doc_collection.add(
                                documents=chunks,
                                metadatas=metadatas,
                                ids=ids
                            )
                            
                            print(f"Extracting context for {name}...")
                            await async_run_extraction_for_document(item_id)
                            upsert_synced_file(item_id, "gdrive", last_modified)
                            print(f"✅ Successfully synced {name}")
                            
                    except Exception as e:
                        print(f"Failed to download/parse GDrive file {name}: {e}")
        except Exception as e:
            # Mute GDrive errors
            pass
            
        await asyncio.sleep(300) # 5 minutes
