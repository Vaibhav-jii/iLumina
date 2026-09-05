import sqlite3
import json
import uuid
from typing import List, Dict, Any, Optional

from backend.config import DB_PATH
from backend.schemas.actions import ProposedActionCreate, ProposedActionResponse


def init_context_db():
    """Create tables for Actions, Extraction (Document Intelligence), and Memory."""
    with sqlite3.connect(DB_PATH) as conn:
        # --- Actions Framework ---
        conn.execute('''
            CREATE TABLE IF NOT EXISTS proposed_actions (
                id TEXT PRIMARY KEY,
                action_type TEXT NOT NULL,
                provider TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                payload TEXT NOT NULL,
                reason TEXT,
                status TEXT DEFAULT 'pending',
                result TEXT,
                session_id TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                resolved_at DATETIME
            )
        ''')

        # --- Document Intelligence (Phase 2 preview) ---
        conn.execute('''
            CREATE TABLE IF NOT EXISTS extracted_entities (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                value TEXT NOT NULL,
                confidence REAL DEFAULT 0.5,
                evidence TEXT,
                source_page TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS extracted_events (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                title TEXT NOT NULL,
                event_type TEXT NOT NULL,
                start_date TEXT,
                end_date TEXT,
                location TEXT,
                description TEXT,
                confidence REAL DEFAULT 0.5,
                evidence TEXT,
                source_page TEXT,
                status TEXT DEFAULT 'detected',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS extracted_facts (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object TEXT NOT NULL,
                confidence REAL DEFAULT 0.5,
                evidence TEXT,
                source_page TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS document_summaries (
                document_id TEXT PRIMARY KEY,
                summary TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # --- User Memory (Phase 5 preview) ---
        conn.execute('''
            CREATE TABLE IF NOT EXISTS user_memory (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()


# ==========================================
# ACTION CRUD
# ==========================================

def create_action(action: ProposedActionCreate) -> str:
    """Create a new proposed action and return its ID."""
    action_id = str(uuid.uuid4())
    payload_str = json.dumps(action.payload)
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            INSERT INTO proposed_actions 
            (id, action_type, provider, title, description, payload, reason, session_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            action_id, action.action_type, action.provider, action.title, 
            action.description, payload_str, action.reason, action.session_id
        ))
        conn.commit()
    return action_id


def get_action(action_id: str) -> Optional[dict]:
    """Retrieve a single action by ID."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT * FROM proposed_actions WHERE id = ?', (action_id,)).fetchone()
        
        if row:
            d = dict(row)
            d['payload'] = json.loads(d['payload']) if d['payload'] else {}
            return d
    return None


def list_actions(status: Optional[str] = None) -> List[dict]:
    """List actions, optionally filtered by status."""
    query = 'SELECT * FROM proposed_actions'
    params = ()
    
    if status:
        query += ' WHERE status = ?'
        params = (status,)
        
    query += ' ORDER BY created_at DESC'
    
    actions = []
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, params)
        for row in cursor.fetchall():
            d = dict(row)
            d['payload'] = json.loads(d['payload']) if d['payload'] else {}
            actions.append(d)
            
    return actions


def update_action_status(action_id: str, status: str, result: Optional[str] = None):
    """Update an action's status and optionally store the execution result."""
    query = 'UPDATE proposed_actions SET status = ?, resolved_at = CURRENT_TIMESTAMP'
    params = [status]
    
    if result is not None:
        query += ', result = ?'
        params.append(result)
        
    query += ' WHERE id = ?'
    params.append(action_id)
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(query, tuple(params))
        conn.commit()


# ==========================================
# CONTEXT CRUD (Entities, Events, Facts)
# ==========================================

def insert_extracted_entity(entity: dict):
    """Insert a single extracted entity."""
    entity_id = entity.get("id", str(uuid.uuid4()))
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            INSERT INTO extracted_entities
            (id, document_id, entity_type, value, confidence, evidence, source_page)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            entity_id, entity["document_id"], entity["entity_type"], entity["value"],
            entity.get("confidence", 0.5), entity.get("evidence"), entity.get("source_page")
        ))
        conn.commit()
    return entity_id


def insert_extracted_event(event: dict):
    """Insert a single extracted event."""
    event_id = event.get("id", str(uuid.uuid4()))
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            INSERT INTO extracted_events
            (id, document_id, title, event_type, start_date, end_date, location, description, confidence, evidence, source_page)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            event_id, event["document_id"], event["title"], event["event_type"],
            event.get("start_date"), event.get("end_date"), event.get("location"),
            event.get("description"), event.get("confidence", 0.5), event.get("evidence"),
            event.get("source_page")
        ))
        conn.commit()
    return event_id


def clear_document_context(document_id: str):
    """Delete all extracted context for a given document."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('DELETE FROM extracted_entities WHERE document_id = ?', (document_id,))
        conn.execute('DELETE FROM extracted_events WHERE document_id = ?', (document_id,))
        conn.execute('DELETE FROM extracted_facts WHERE document_id = ?', (document_id,))
        conn.commit()


def get_events_by_document(document_id: str) -> List[dict]:
    """Retrieve all events extracted from a specific document."""
    events = []
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute('SELECT * FROM extracted_events WHERE document_id = ?', (document_id,))
        for row in cursor.fetchall():
            events.append(dict(row))
    return events


def get_entities_by_document(document_id: str) -> List[dict]:
    """Retrieve all entities extracted from a specific document."""
    entities = []
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute('SELECT * FROM extracted_entities WHERE document_id = ?', (document_id,))
        for row in cursor.fetchall():
            entities.append(dict(row))
    return entities


def insert_document_summary(document_id: str, summary: str):
    """Insert or replace a document summary."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            INSERT OR REPLACE INTO document_summaries (document_id, summary)
            VALUES (?, ?)
        ''', (document_id, summary))
        conn.commit()


def get_document_summary(document_id: str) -> Optional[str]:
    """Retrieve the summary for a specific document."""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute('SELECT summary FROM document_summaries WHERE document_id = ?', (document_id,)).fetchone()
        if row:
            return row[0]
    return None


# ==========================================
# USER MEMORY CRUD
# ==========================================

def create_memory(content: str, category: str = "general") -> str:
    """Create a new user memory."""
    memory_id = str(uuid.uuid4())
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            INSERT INTO user_memory (id, content, category)
            VALUES (?, ?, ?)
        ''', (memory_id, content, category))
        conn.commit()
    return memory_id


def list_memories() -> List[dict]:
    """Retrieve all user memories."""
    memories = []
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute('SELECT * FROM user_memory ORDER BY created_at DESC')
        for row in cursor.fetchall():
            memories.append(dict(row))
    return memories


def delete_memory(memory_id: str):
    """Delete a memory by ID."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('DELETE FROM user_memory WHERE id = ?', (memory_id,))
        conn.commit()
