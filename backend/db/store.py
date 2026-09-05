"""
SQLite persistence layer for chat sessions and messages.
Includes an in-memory cache for fast reads.
"""

import os
import sqlite3

from backend.config import DB_PATH


# In-memory cache for fast reads
CHAT_CACHE: dict[str, list[dict]] = {}


def init_db():
    """Create tables and indexes if they don't exist."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT,
                mode TEXT DEFAULT 'chat'
            )
        ''')
        # Migration: add mode and space_id column if they don't exist (for existing DBs)
        try:
            conn.execute('ALTER TABLE sessions ADD COLUMN mode TEXT DEFAULT "chat"')
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute('ALTER TABLE sessions ADD COLUMN space_id TEXT')
        except sqlite3.OperationalError:
            pass

        # Phase 2: Knowledge Spaces
        conn.execute('''
            CREATE TABLE IF NOT EXISTS spaces (
                space_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS space_documents (
                space_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                filepath TEXT,
                source TEXT,
                PRIMARY KEY (space_id, document_id),
                FOREIGN KEY (space_id) REFERENCES spaces(space_id) ON DELETE CASCADE
            )
        ''')

        conn.execute('CREATE INDEX IF NOT EXISTS idx_session_id ON messages(session_id)')
        conn.commit()


def load_session(session_id: str) -> list[dict]:
    """Load session from cache, falling back to SQLite."""
    if session_id in CHAT_CACHE:
        return [dict(msg) for msg in CHAT_CACHE[session_id]]

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            'SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC',
            (session_id,)
        )
        history = [{"role": row[0], "content": row[1]} for row in cursor.fetchall()]
        CHAT_CACHE[session_id] = [dict(msg) for msg in history]
        return history


def append_message(session_id: str, role: str, content: str, mode: str = "chat", space_id: str = None):
    """Atomically append a message to both cache and SQLite."""
    if session_id not in CHAT_CACHE:
        load_session(session_id)
    CHAT_CACHE[session_id].append({"role": role, "content": content})

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            'INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)',
            (session_id, role, content)
        )
        conn.execute(
            'INSERT OR IGNORE INTO sessions (session_id, mode, space_id) VALUES (?, ?, ?)',
            (session_id, mode, space_id)
        )
        # Update space_id if the session already existed but space_id was null
        if space_id:
            conn.execute('UPDATE sessions SET space_id = ? WHERE session_id = ? AND space_id IS NULL', (space_id, session_id))
        conn.commit()


def list_chats(mode: str = "chat") -> list[dict]:
    """List all chat sessions for a given mode, ordered by latest activity."""
    sessions = []
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute('''
            SELECT m.session_id, MAX(m.timestamp), s.title, s.space_id, sp.name
            FROM messages m
            LEFT JOIN sessions s ON m.session_id = s.session_id
            LEFT JOIN spaces sp ON s.space_id = sp.space_id
            WHERE COALESCE(s.mode, 'chat') = ?
            GROUP BY m.session_id
            ORDER BY MAX(m.timestamp) DESC
        ''', (mode,))
        for row in cursor.fetchall():
            sid = row[0]
            title = row[2]
            space_id = row[3]
            space_name = row[4]

            if title:
                preview = title
            else:
                cursor2 = conn.execute(
                    'SELECT content FROM messages WHERE session_id = ? AND role = "user" ORDER BY id ASC LIMIT 1',
                    (sid,)
                )
                first_user = cursor2.fetchone()
                preview = "Empty chat"
                if first_user:
                    msg_content = first_user[0]
                    preview = msg_content[:60] + "..." if len(msg_content) > 60 else msg_content

            sessions.append({"id": sid, "preview": preview, "space_id": space_id, "space_name": space_name, "title": title})

    return sessions


def get_session_metadata(session_id: str) -> dict:
    """Fetch space_id and space_name for a given session."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute('''
            SELECT s.space_id, sp.name 
            FROM sessions s
            LEFT JOIN spaces sp ON s.space_id = sp.space_id
            WHERE s.session_id = ?
        ''', (session_id,))
        row = cursor.fetchone()
        if row:
            return {"space_id": row[0], "space_name": row[1]}
    return {}


def update_title(session_id: str, title: str):
    """Update or create a session title."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('UPDATE sessions SET title = ? WHERE session_id = ?', (title, session_id))
        if conn.execute('SELECT changes()').fetchone()[0] == 0:
            conn.execute(
                'INSERT INTO sessions (session_id, title) VALUES (?, ?)',
                (session_id, title)
            )
        conn.commit()


def delete_session(session_id: str):
    """Delete a chat session from both cache and SQLite."""
    CHAT_CACHE.pop(session_id, None)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('DELETE FROM messages WHERE session_id = ?', (session_id,))
        conn.execute('DELETE FROM sessions WHERE session_id = ?', (session_id,))
        conn.commit()

    # Clean up legacy JSON file if it exists
    json_path = os.path.join(os.path.dirname(DB_PATH), "chats", f"{session_id}.json")
    if os.path.exists(json_path):
        os.remove(json_path)


# --- Knowledge Spaces CRUD ---

def create_space(space_id: str, name: str):
    """Create a new knowledge space."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('INSERT INTO spaces (space_id, name) VALUES (?, ?)', (space_id, name))
        conn.commit()


def list_spaces() -> list[dict]:
    """List all knowledge spaces with their document counts."""
    spaces = []
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute('''
            SELECT s.space_id, s.name, s.created_at, COUNT(sd.document_id) as doc_count
            FROM spaces s
            LEFT JOIN space_documents sd ON s.space_id = sd.space_id
            GROUP BY s.space_id
            ORDER BY s.created_at DESC
        ''')
        for row in cursor.fetchall():
            spaces.append({
                "id": row[0],
                "name": row[1],
                "created_at": row[2],
                "doc_count": row[3]
            })
    return spaces


def delete_space(space_id: str):
    """Delete a space and its document associations (cascade handled by foreign key)."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('PRAGMA foreign_keys = ON')
        conn.execute('DELETE FROM spaces WHERE space_id = ?', (space_id,))
        conn.commit()


def get_space_documents(space_id: str) -> list[str]:
    """Get a list of allowed document_ids for a given space."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute('SELECT document_id FROM space_documents WHERE space_id = ?', (space_id,))
        return [row[0] for row in cursor.fetchall()]


def get_space_documents_full(space_id: str) -> list[dict]:
    """Get full document info for a given space."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute('SELECT document_id, filepath, source FROM space_documents WHERE space_id = ?', (space_id,))
        return [{"document_id": row[0], "filepath": row[1], "source": row[2]} for row in cursor.fetchall()]


def add_document_to_space(space_id: str, document_id: str, filepath: str, source: str):
    """Attach a document to a space."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            'INSERT OR IGNORE INTO space_documents (space_id, document_id, filepath, source) VALUES (?, ?, ?, ?)',
            (space_id, document_id, filepath, source)
        )
        conn.commit()


def remove_document_from_space(space_id: str, document_id: str):
    """Detach a document from a space."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            'DELETE FROM space_documents WHERE space_id = ? AND document_id = ?',
            (space_id, document_id)
        )
        conn.commit()

