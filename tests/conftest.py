"""
conftest.py — Pytest fixtures for iLumina backend tests.

Redirects ALL database and storage paths to temp directories
so tests never touch production data.
"""

import os
import pytest
import tempfile

# ─── IMPORTANT: Patch config BEFORE any backend module is imported ───
# This must happen at conftest load time, before test collection triggers imports.

_test_tmp = tempfile.mkdtemp(prefix="ilumina_test_")

os.environ["ILUMINA_TEST_DB"] = os.path.join(_test_tmp, "test.db")

import backend.config as cfg
cfg.DB_PATH = os.path.join(_test_tmp, "test.db")
cfg.CHROMA_DIR = os.path.join(_test_tmp, "chroma")
cfg.DATA_DIR = os.path.join(_test_tmp, "data")
cfg.FRONTEND_DIR = os.path.join(_test_tmp, "frontend")
cfg.SCREENSHOTS_DIR = os.path.join(_test_tmp, "screenshots")

os.makedirs(cfg.CHROMA_DIR, exist_ok=True)
os.makedirs(cfg.DATA_DIR, exist_ok=True)
os.makedirs(cfg.FRONTEND_DIR, exist_ok=True)
os.makedirs(cfg.SCREENSHOTS_DIR, exist_ok=True)

# Now init DBs with patched paths
from backend.db.store import init_db
from backend.db.context_store import init_context_db
init_db()
init_context_db()


@pytest.fixture(autouse=True)
def clean_db_between_tests():
    """Wipe all table data between tests for isolation, but keep schema."""
    import sqlite3
    from backend.db.store import CHAT_CACHE
    CHAT_CACHE.clear()

    yield

    # Clean all tables after each test
    with sqlite3.connect(cfg.DB_PATH) as conn:
        for table in [
            "messages", "sessions", "spaces", "space_documents",
            "proposed_actions", "extracted_entities", "extracted_events",
            "extracted_facts", "document_summaries", "user_memory", "synced_files"
        ]:
            try:
                conn.execute(f"DELETE FROM {table}")
            except Exception:
                pass
        conn.commit()


@pytest.fixture
def client():
    """Create a FastAPI TestClient that skips the real lifespan (no MCP servers)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.routes import history, spaces, actions, context, calendar, memory, integrations

    app = FastAPI()
    app.include_router(history.router)
    app.include_router(spaces.router)
    app.include_router(actions.router)
    app.include_router(memory.router)
    app.include_router(context.router)
    app.include_router(calendar.router)
    app.include_router(integrations.router)

    return TestClient(app)
