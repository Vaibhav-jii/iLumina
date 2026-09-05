from fastmcp import FastMCP
import chromadb
import os
import json

CHROMA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "chroma_db")

mcp = FastMCP("Documents")

@mcp.tool()
def list_embedded_documents() -> str:
    """List all documents embedded in the knowledge base."""
    try:
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        collection = client.get_or_create_collection(name="documents")
        result = collection.get()
        metadatas = result.get('metadatas', [])
        
        import sqlite3
        DB_PATH = os.path.join(os.path.dirname(CHROMA_DIR), "ilumina_chat.db")
        
        unique_files = {}
        with sqlite3.connect(DB_PATH) as conn:
            for meta in metadatas:
                filepath = meta.get('filepath')
                if filepath and filepath not in unique_files:
                    doc_id = meta.get('document_id') or meta.get('item_id') or filepath
                    summary = None
                    try:
                        row = conn.execute('SELECT summary FROM document_summaries WHERE document_id = ?', (doc_id,)).fetchone()
                        if row:
                            summary = row[0]
                    except Exception:
                        pass
                        
                    unique_files[filepath] = {
                        "document_id": doc_id,
                        "name": meta.get('filename'),
                        "last_modified": meta.get('last_modified'),
                        "source": meta.get('source', 'unknown'),
                        "summary": summary
                    }
        
        if not unique_files:
            return "No embedded documents found."
            
        return json.dumps([{"filepath": k, **v} for k, v in unique_files.items()], indent=2)
    except Exception as e:
        return f"Error listing documents: {str(e)}"

@mcp.tool()
def query_documents(query: str, n_results: int = 5, filepath: str = None) -> str:
    """Semantic search across embedded documents. Optional filepath to filter by a specific document."""
    try:
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        collection = client.get_or_create_collection(name="documents")
        
        where = None
        if filepath:
            where = {"filepath": filepath}
            
        results = collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where
        )
        
        if not results['documents'] or not results['documents'][0]:
            return "No matching documents found."
            
        formatted_results = []
        for doc, meta in zip(results['documents'][0], results['metadatas'][0]):
            formatted_results.append({
                "source": meta.get("filepath", "Unknown"),
                "content": doc
            })
            
        return json.dumps(formatted_results, indent=2)
    except Exception as e:
        return f"Error querying documents: {str(e)}"

if __name__ == "__main__":
    mcp.run()
