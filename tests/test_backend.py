"""
Comprehensive test suite for the iLumina backend.

Covers:
- DB layer: store.py (Chat CRUD, Spaces CRUD)
- DB layer: context_store.py (Actions, Entities, Events, Memory, Sync)
- API routes: history, spaces, actions, memory, context, calendar, integrations
- Pydantic schemas
- MCP client helpers
- Chat route helpers
- Edge cases

Run:  uv run pytest tests/ -v --cov=backend --cov-report=term-missing
"""

import json
import pytest
from unittest.mock import patch, MagicMock


# ===========================================================================
# 1. DB LAYER — store.py
# ===========================================================================

class TestChatStore:
    """Tests for backend.db.store CRUD functions."""

    def test_append_and_load_session(self):
        from backend.db.store import append_message, load_session
        append_message("sess-1", "user", "Hello")
        append_message("sess-1", "assistant", "Hi there")

        history = load_session("sess-1")
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["content"] == "Hi there"

    def test_load_empty_session(self):
        from backend.db.store import load_session
        assert load_session("nonexistent") == []

    def test_list_chats(self):
        from backend.db.store import append_message, list_chats
        append_message("s1", "user", "First chat message")
        append_message("s2", "user", "Second chat message")

        chats = list_chats()
        assert len(chats) == 2

    def test_update_title(self):
        from backend.db.store import append_message, update_title, list_chats
        append_message("s1", "user", "msg")
        update_title("s1", "My Custom Title")

        chats = list_chats()
        titles = {c["id"]: c["title"] for c in chats}
        assert titles["s1"] == "My Custom Title"

    def test_delete_session(self):
        from backend.db.store import append_message, delete_session, load_session, CHAT_CACHE
        append_message("del-me", "user", "temp message")
        assert len(load_session("del-me")) == 1

        delete_session("del-me")
        CHAT_CACHE.pop("del-me", None)
        assert load_session("del-me") == []

    def test_cache_works(self):
        from backend.db.store import append_message, load_session, CHAT_CACHE
        append_message("cached", "user", "msg1")
        load_session("cached")
        assert "cached" in CHAT_CACHE
        assert len(CHAT_CACHE["cached"]) == 1

    def test_get_session_metadata_with_space(self):
        from backend.db.store import append_message, create_space, get_session_metadata
        create_space("sp-1", "Test Space")
        append_message("s1", "user", "hello", space_id="sp-1")

        meta = get_session_metadata("s1")
        assert meta["space_id"] == "sp-1"

    def test_get_session_metadata_missing(self):
        from backend.db.store import get_session_metadata
        assert get_session_metadata("nonexistent") == {}

    def test_list_chats_with_mode_filter(self):
        from backend.db.store import append_message, list_chats
        append_message("chat-1", "user", "hello", mode="chat")
        append_message("research-1", "user", "hello", mode="research")

        chat_only = list_chats(mode="chat")
        research_only = list_chats(mode="research")
        assert len(chat_only) == 1
        assert len(research_only) == 1

    def test_list_chats_preview_truncation(self):
        from backend.db.store import append_message, list_chats
        long_msg = "x" * 100
        append_message("long-chat", "user", long_msg)

        chats = list_chats()
        assert len(chats) == 1
        assert chats[0]["preview"].endswith("...")


# ===========================================================================
# 2. DB LAYER — Spaces CRUD
# ===========================================================================

class TestSpacesStore:

    def test_create_and_list_spaces(self):
        from backend.db.store import create_space, list_spaces
        create_space("sp-1", "Research")
        create_space("sp-2", "Projects")

        spaces = list_spaces()
        assert len(spaces) == 2

    def test_delete_space(self):
        from backend.db.store import create_space, delete_space, list_spaces
        create_space("sp-del", "To Delete")
        assert len(list_spaces()) == 1
        delete_space("sp-del")
        assert len(list_spaces()) == 0

    def test_add_and_get_documents(self):
        from backend.db.store import create_space, add_document_to_space, get_space_documents, get_space_documents_full
        create_space("sp-docs", "Docs Space")
        add_document_to_space("sp-docs", "doc-1", "/path/to/file.pdf", "onedrive")

        assert "doc-1" in get_space_documents("sp-docs")
        full = get_space_documents_full("sp-docs")
        assert full[0]["filepath"] == "/path/to/file.pdf"

    def test_remove_document_from_space(self):
        from backend.db.store import create_space, add_document_to_space, remove_document_from_space, get_space_documents
        create_space("sp-rm", "Remove Test")
        add_document_to_space("sp-rm", "doc-x", "/path", "local")
        remove_document_from_space("sp-rm", "doc-x")
        assert get_space_documents("sp-rm") == []

    def test_duplicate_document_insert(self):
        from backend.db.store import create_space, add_document_to_space, get_space_documents
        create_space("sp-dup", "Dup Test")
        add_document_to_space("sp-dup", "doc-1", "/path", "local")
        add_document_to_space("sp-dup", "doc-1", "/path", "local")  # duplicate
        assert len(get_space_documents("sp-dup")) == 1


# ===========================================================================
# 3. DB LAYER — context_store.py
# ===========================================================================

class TestContextStore:

    def test_create_and_get_action(self):
        from backend.db.context_store import create_action, get_action
        from backend.schemas.actions import ProposedActionCreate

        action = ProposedActionCreate(
            action_type="calendar.create",
            provider="google_calendar",
            title="Team Meeting",
            description="Weekly sync",
            payload={"summary": "Meeting", "start": "2026-09-15T10:00:00"},
            reason="User requested",
            session_id="sess-1"
        )
        action_id = create_action(action)
        retrieved = get_action(action_id)
        assert retrieved["title"] == "Team Meeting"
        assert retrieved["status"] == "pending"
        assert retrieved["payload"]["summary"] == "Meeting"

    def test_list_actions_with_filter(self):
        from backend.db.context_store import create_action, list_actions, update_action_status
        from backend.schemas.actions import ProposedActionCreate

        a1 = create_action(ProposedActionCreate(
            action_type="test", provider="test", title="A1", payload={"k": "v"}
        ))
        a2 = create_action(ProposedActionCreate(
            action_type="test", provider="test", title="A2", payload={"k": "v"}
        ))
        update_action_status(a1, "approved")

        pending = list_actions(status="pending")
        assert len(pending) == 1
        assert pending[0]["title"] == "A2"

        all_actions = list_actions()
        assert len(all_actions) == 2

    def test_update_action_status_with_result(self):
        from backend.db.context_store import create_action, update_action_status, get_action
        from backend.schemas.actions import ProposedActionCreate

        aid = create_action(ProposedActionCreate(
            action_type="test", provider="test", title="Action", payload={}
        ))
        update_action_status(aid, "executed", result='{"ok": true}')
        action = get_action(aid)
        assert action["status"] == "executed"
        assert action["result"] == '{"ok": true}'

    def test_get_nonexistent_action(self):
        from backend.db.context_store import get_action
        assert get_action("nonexistent-id") is None

    def test_entity_crud(self):
        from backend.db.context_store import insert_extracted_entity, get_entities_by_document
        insert_extracted_entity({
            "document_id": "doc-1", "entity_type": "person",
            "value": "John Doe", "confidence": 0.95,
        })
        entities = get_entities_by_document("doc-1")
        assert len(entities) == 1
        assert entities[0]["value"] == "John Doe"

    def test_event_crud(self):
        from backend.db.context_store import insert_extracted_event, get_events_by_document
        insert_extracted_event({
            "document_id": "doc-1", "title": "Conference",
            "event_type": "meeting", "start_date": "2026-10-01",
        })
        events = get_events_by_document("doc-1")
        assert len(events) == 1
        assert events[0]["title"] == "Conference"

    def test_clear_document_context(self):
        from backend.db.context_store import (
            insert_extracted_entity, insert_extracted_event,
            clear_document_context, get_entities_by_document, get_events_by_document
        )
        insert_extracted_entity({"document_id": "d1", "entity_type": "org", "value": "ACME"})
        insert_extracted_event({"document_id": "d1", "title": "Event", "event_type": "deadline"})
        clear_document_context("d1")
        assert get_entities_by_document("d1") == []
        assert get_events_by_document("d1") == []

    def test_document_summary_crud(self):
        from backend.db.context_store import insert_document_summary, get_document_summary
        insert_document_summary("doc-1", "This is a summary.")
        assert get_document_summary("doc-1") == "This is a summary."
        insert_document_summary("doc-1", "Updated summary.")
        assert get_document_summary("doc-1") == "Updated summary."

    def test_get_missing_summary(self):
        from backend.db.context_store import get_document_summary
        assert get_document_summary("nonexistent") is None

    def test_memory_crud(self):
        from backend.db.context_store import create_memory, list_memories, delete_memory
        mid = create_memory("User prefers dark mode", "preference")
        memories = list_memories()
        assert len(memories) == 1
        assert memories[0]["content"] == "User prefers dark mode"
        delete_memory(mid)
        assert list_memories() == []

    def test_synced_file_crud(self):
        from backend.db.context_store import upsert_synced_file, get_synced_file
        upsert_synced_file("file-1", "onedrive", "2026-09-10T12:00:00")
        result = get_synced_file("file-1")
        assert result["source"] == "onedrive"
        upsert_synced_file("file-1", "onedrive", "2026-09-12T12:00:00")
        result = get_synced_file("file-1")
        assert result["last_modified"] == "2026-09-12T12:00:00"

    def test_get_missing_synced_file(self):
        from backend.db.context_store import get_synced_file
        assert get_synced_file("nonexistent") is None


# ===========================================================================
# 4. API ROUTES — History
# ===========================================================================

class TestHistoryRoutes:

    def test_get_chats_empty(self, client):
        resp = client.get("/api/chats")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_chat_history(self, client):
        from backend.db.store import append_message
        append_message("api-sess", "user", "hello from api")
        resp = client.get("/api/chats/api-sess")
        assert resp.status_code == 200
        assert len(resp.json()["messages"]) == 1

    def test_update_chat_title(self, client):
        from backend.db.store import append_message
        append_message("title-sess", "user", "msg")
        resp = client.put("/api/chats/title-sess/title", json={"title": "New Title"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    def test_delete_chat(self, client):
        from backend.db.store import append_message
        append_message("del-sess", "user", "msg")
        resp = client.delete("/api/chats/del-sess")
        assert resp.status_code == 200


# ===========================================================================
# 5. API ROUTES — Spaces
# ===========================================================================

class TestSpacesRoutes:

    def test_create_space(self, client):
        resp = client.post("/api/spaces", json={"name": "Research", "document_ids": []})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Research"

    def test_list_spaces(self, client):
        client.post("/api/spaces", json={"name": "Space1"})
        client.post("/api/spaces", json={"name": "Space2"})
        resp = client.get("/api/spaces")
        assert len(resp.json()) == 2

    def test_delete_space(self, client):
        resp = client.post("/api/spaces", json={"name": "Temp"})
        space_id = resp.json()["id"]
        del_resp = client.delete(f"/api/spaces/{space_id}")
        assert del_resp.status_code == 200

    def test_attach_and_list_documents(self, client):
        resp = client.post("/api/spaces", json={"name": "Doc Space"})
        space_id = resp.json()["id"]
        client.post(f"/api/spaces/{space_id}/documents", json={
            "document_id": "doc-1", "filepath": "/test.pdf", "source": "local"
        })
        docs_resp = client.get(f"/api/spaces/{space_id}/documents")
        assert len(docs_resp.json()) == 1

    def test_detach_document(self, client):
        resp = client.post("/api/spaces", json={"name": "Detach"})
        space_id = resp.json()["id"]
        client.post(f"/api/spaces/{space_id}/documents", json={
            "document_id": "doc-2", "filepath": "/f.pdf", "source": "gdrive"
        })
        client.delete(f"/api/spaces/{space_id}/documents/doc-2")
        docs = client.get(f"/api/spaces/{space_id}/documents").json()
        assert len(docs) == 0

    def test_create_space_with_preattached_docs(self, client):
        resp = client.post("/api/spaces", json={
            "name": "Pre-attached", "document_ids": ["d1", "d2", "d3"]
        })
        space_id = resp.json()["id"]
        docs = client.get(f"/api/spaces/{space_id}/documents").json()
        assert len(docs) == 3


# ===========================================================================
# 6. API ROUTES — Actions
# ===========================================================================

class TestActionsRoutes:

    def _seed_action(self):
        from backend.db.context_store import create_action
        from backend.schemas.actions import ProposedActionCreate
        return create_action(ProposedActionCreate(
            action_type="test.action", provider="test",
            title="Test Action", payload={"key": "val"},
            reason="Testing", session_id="sess-1"
        ))

    def test_list_actions(self, client):
        self._seed_action()
        resp = client.get("/api/actions")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_list_pending_actions(self, client):
        self._seed_action()
        resp = client.get("/api/actions/pending")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_get_single_action(self, client):
        aid = self._seed_action()
        resp = client.get(f"/api/actions/{aid}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Test Action"

    def test_get_nonexistent_action(self, client):
        resp = client.get("/api/actions/nonexistent")
        assert resp.status_code == 404

    def test_reject_action(self, client):
        aid = self._seed_action()
        resp = client.post(f"/api/actions/{aid}/reject")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    def test_reject_already_rejected(self, client):
        aid = self._seed_action()
        client.post(f"/api/actions/{aid}/reject")
        resp = client.post(f"/api/actions/{aid}/reject")
        assert resp.status_code == 400

    def test_approve_nonexistent(self, client):
        resp = client.post("/api/actions/nonexistent/approve")
        assert resp.status_code == 404

    def test_reject_nonexistent(self, client):
        resp = client.post("/api/actions/nonexistent/reject")
        assert resp.status_code == 404


# ===========================================================================
# 7. API ROUTES — Memory
# ===========================================================================

class TestMemoryRoutes:

    def test_add_memory(self, client):
        resp = client.post("/api/memory", json={"content": "Likes Python", "category": "preference"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    def test_list_memories(self, client):
        client.post("/api/memory", json={"content": "Fact 1", "category": "fact"})
        client.post("/api/memory", json={"content": "Fact 2", "category": "fact"})
        resp = client.get("/api/memory")
        assert len(resp.json()) == 2

    def test_delete_memory(self, client):
        resp = client.post("/api/memory", json={"content": "Temp", "category": "general"})
        memory_id = resp.json()["id"]
        del_resp = client.delete(f"/api/memory/{memory_id}")
        assert del_resp.status_code == 200


# ===========================================================================
# 8. API ROUTES — Context
# ===========================================================================

class TestContextRoutes:

    def test_get_events_empty(self, client):
        resp = client.get("/api/context/events")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_entities_empty(self, client):
        resp = client.get("/api/context/entities")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_events_with_data(self, client):
        import sqlite3
        import backend.config as cfg
        with sqlite3.connect(cfg.DB_PATH) as conn:
            conn.execute(
                "INSERT INTO extracted_events (id, document_id, title, event_type, start_date, confidence, evidence) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("ev-1", "doc-1", "Meeting", "calendar", "2026-10-01", 0.8, "Found on page 3")
            )
            conn.commit()
        resp = client.get("/api/context/events")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_get_entities_with_type_filter(self, client):
        import sqlite3
        import backend.config as cfg
        with sqlite3.connect(cfg.DB_PATH) as conn:
            conn.execute(
                "INSERT INTO extracted_entities (id, document_id, entity_type, value, confidence, evidence) VALUES (?, ?, ?, ?, ?, ?)",
                ("e-1", "d1", "person", "Alice", 0.9, "Mentioned in intro")
            )
            conn.execute(
                "INSERT INTO extracted_entities (id, document_id, entity_type, value, confidence, evidence) VALUES (?, ?, ?, ?, ?, ?)",
                ("e-2", "d1", "org", "ACME", 0.8, "Company header")
            )
            conn.commit()
        resp = client.get("/api/context/entities?type=person")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_get_events_filtered_by_space(self, client):
        import sqlite3
        import backend.config as cfg
        from backend.db.store import create_space, add_document_to_space
        create_space("sp-filter", "Filter Space")
        add_document_to_space("sp-filter", "doc-in", "/path", "local")
        with sqlite3.connect(cfg.DB_PATH) as conn:
            conn.execute(
                "INSERT INTO extracted_events (id, document_id, title, event_type, confidence, evidence) VALUES (?, ?, ?, ?, ?, ?)",
                ("ev-in", "doc-in", "In Space", "meeting", 0.8, "agenda item")
            )
            conn.execute(
                "INSERT INTO extracted_events (id, document_id, title, event_type, confidence, evidence) VALUES (?, ?, ?, ?, ?, ?)",
                ("ev-out", "doc-out", "Outside", "meeting", 0.8, "unrelated")
            )
            conn.commit()
        resp = client.get("/api/context/events?space_id=sp-filter")
        assert len(resp.json()) == 1

    def test_entities_empty_space_filter(self, client):
        from backend.db.store import create_space
        create_space("empty-sp", "Empty")
        resp = client.get("/api/context/entities?space_id=empty-sp")
        assert resp.json() == []


# ===========================================================================
# 9. API ROUTES — Calendar
# ===========================================================================

class TestCalendarRoutes:

    def test_get_calendar_status(self, client):
        with patch("backend.routes.calendar.get_calendar_status", return_value={"status": "disconnected"}):
            resp = client.get("/api/calendar/status")
            assert resp.status_code == 200
            assert resp.json()["status"] == "disconnected"

    def test_get_events_disconnected(self, client):
        with patch("backend.routes.calendar.get_calendar_status", return_value={"status": "disconnected"}):
            resp = client.get("/api/calendar/events")
            assert resp.status_code == 403

    def test_get_events_connected(self, client):
        with patch("backend.routes.calendar.get_calendar_status", return_value={"status": "connected"}):
            with patch("backend.routes.calendar.list_upcoming_events", return_value=[
                {"id": "1", "title": "Meeting", "start": "2026-10-01T10:00:00"}
            ]):
                resp = client.get("/api/calendar/events")
                assert resp.status_code == 200
                assert len(resp.json()) == 1


# ===========================================================================
# 10. API ROUTES — Integrations
# ===========================================================================

class TestIntegrationsRoutes:

    def test_get_integrations(self, client):
        with patch("backend.routes.integrations.get_calendar_status", return_value={"status": "connected"}):
            with patch("backend.routes.integrations.MCP_SESSIONS", {}):
                resp = client.get("/api/integrations")
                assert resp.status_code == 200
                providers = {i["provider"] for i in resp.json()}
                assert "google_calendar" in providers
                assert "github" in providers

    def test_integrations_with_mcp_sessions(self, client):
        mock_sessions = {"github": {}, "filesystem": {}, "ms365": {}}
        with patch("backend.routes.integrations.get_calendar_status", return_value={"status": "connected"}):
            with patch("backend.routes.integrations.MCP_SESSIONS", mock_sessions):
                resp = client.get("/api/integrations")
                data = {i["provider"]: i["status"] for i in resp.json()}
                assert data["github"] == "connected"
                assert data["filesystem"] == "connected"
                assert data["ms365"] == "connected"


# ===========================================================================
# 11. SCHEMA VALIDATION
# ===========================================================================

class TestSchemas:

    def test_proposed_action_create_valid(self):
        from backend.schemas.actions import ProposedActionCreate
        action = ProposedActionCreate(
            action_type="test", provider="test", title="Title", payload={"key": "val"}
        )
        assert action.action_type == "test"

    def test_proposed_action_response(self):
        from backend.schemas.actions import ProposedActionResponse
        resp = ProposedActionResponse(
            action_type="test", provider="test", title="T", payload={},
            id="abc", status="pending", created_at="2026-09-12"
        )
        assert resp.status == "pending"

    def test_memory_create_defaults(self):
        from backend.schemas.memory import MemoryCreate
        m = MemoryCreate(content="Some fact")
        assert m.category == "general"

    def test_memory_response(self):
        from backend.schemas.memory import MemoryResponse
        r = MemoryResponse(content="test", category="fact", id="1",
                           created_at="2026-01-01", updated_at="2026-01-01")
        assert r.id == "1"

    def test_chat_title_update(self):
        from backend.models import ChatTitleUpdate
        assert ChatTitleUpdate(title="New Title").title == "New Title"

    def test_chat_response_defaults(self):
        from backend.models import ChatResponse
        r = ChatResponse(response="Hello")
        assert r.screenshots == []
        assert r.tool_calls_made == []
        assert r.trace == []

    def test_context_schemas(self):
        from backend.schemas.context import ExtractedEntity, ExtractedEvent, ExtractedFact
        e = ExtractedEntity(id="1", document_id="d1", entity_type="person",
                            value="Alice", confidence=0.9, evidence="Found in doc",
                            created_at="2026-01-01")
        assert e.value == "Alice"

        ev = ExtractedEvent(id="1", document_id="d1", title="Meeting",
                            event_type="calendar", confidence=0.8, evidence="Line 5",
                            created_at="2026-01-01")
        assert ev.title == "Meeting"

        f = ExtractedFact(id="1", document_id="d1", subject="Alice",
                          predicate="works_at", object="ACME", confidence=0.9,
                          evidence="Paragraph 2")
        assert f.subject == "Alice"


# ===========================================================================
# 12. MCP CLIENT HELPERS (unit tests, no MCP server needed)
# ===========================================================================

class TestMCPClientHelpers:

    def test_sanitize_schema_boolean(self):
        from backend.mcp.client import _sanitize_schema
        schema = {"type": "object", "properties": {"flag": {"type": "boolean"}}}
        result = _sanitize_schema(schema)
        assert "anyOf" in result["properties"]["flag"]

    def test_sanitize_schema_nested(self):
        from backend.mcp.client import _sanitize_schema
        schema = {"type": "object", "properties": {"nested": {"type": "object", "properties": {"b": {"type": "boolean"}}}}}
        result = _sanitize_schema(schema)
        assert "anyOf" in result["properties"]["nested"]["properties"]["b"]

    def test_sanitize_schema_no_booleans(self):
        from backend.mcp.client import _sanitize_schema
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        result = _sanitize_schema(schema)
        assert result["properties"]["name"]["type"] == "string"

    def test_parse_tool_result_empty(self):
        from backend.mcp.client import _parse_tool_result
        mock_result = MagicMock()
        mock_result.content = []
        assert _parse_tool_result(mock_result) == "Tool executed successfully (no output)."

    def test_parse_tool_result_text(self):
        from backend.mcp.client import _parse_tool_result
        mock_item = MagicMock()
        mock_item.text = "Hello world"
        mock_item.data = None
        # hasattr check: text exists
        mock_result = MagicMock()
        mock_result.content = [mock_item]
        result = _parse_tool_result(mock_result)
        assert "Hello world" in result

    def test_extract_screenshots_no_image(self):
        from backend.mcp.client import extract_screenshots
        assert extract_screenshots("just plain text") == []
        assert extract_screenshots('{"type": "text", "data": "abc"}') == []

    def test_extract_screenshots_invalid_json(self):
        from backend.mcp.client import extract_screenshots
        assert extract_screenshots("not json at all {{{") == []


# ===========================================================================
# 13. CHAT ROUTE HELPERS (unit tests)
# ===========================================================================

class TestChatHelpers:

    def test_build_available_tools_chat_mode(self):
        from backend.routes.chat import _build_available_tools
        result = _build_available_tools([{"function": {"name": "tool1"}}], "chat")
        assert result == []  # chat mode returns no tools

    def test_build_available_tools_web_mode(self):
        from backend.routes.chat import _build_available_tools
        raw = [{"function": {"name": "browser_click"}}, {"function": {"name": "generate_pdf"}}]
        result = _build_available_tools(raw, "web")
        # generate_pdf should be filtered out, virtual tools added
        names = [t["function"]["name"] if "function" in t else t.get("name", "") for t in result]
        assert "generate_pdf" not in [t["function"]["name"] for t in result if "function" in t]

    def test_sse_helper(self):
        from backend.routes.chat import _sse
        result = _sse({"type": "response", "text": "hi"})
        assert result.startswith("data: ")
        assert result.endswith("\n\n")
        parsed = json.loads(result.replace("data: ", "").strip())
        assert parsed["type"] == "response"

    def test_extract_final_response(self):
        from backend.routes.chat import _extract_final_response
        state = {"messages": [{"content": "Final answer"}], "screenshots": []}
        result = _extract_final_response(state)
        assert "Final answer" in result

    def test_extract_final_response_with_screenshots(self):
        from backend.routes.chat import _extract_final_response
        state = {"messages": [{"content": "Answer"}], "screenshots": ["/static/img.png"]}
        result = _extract_final_response(state)
        assert "![Screenshot]" in result

    def test_extract_final_response_none_content(self):
        from backend.routes.chat import _extract_final_response
        state = {"messages": [{"content": None}], "screenshots": []}
        result = _extract_final_response(state)
        assert "Finished tool execution" in result


# ===========================================================================
# 14. CALENDAR SERVICE (unit tests with mocks)
# ===========================================================================

class TestCalendarService:

    def test_get_calendar_status_no_creds(self):
        with patch("backend.services.calendar_service.get_calendar_service", return_value=None):
            from backend.services.calendar_service import get_calendar_status
            assert get_calendar_status()["status"] == "disconnected"

    def test_get_calendar_status_with_service(self):
        with patch("backend.services.calendar_service.get_calendar_service", return_value=MagicMock()):
            from backend.services.calendar_service import get_calendar_status
            assert get_calendar_status()["status"] == "connected"

    def test_list_upcoming_events_no_service(self):
        with patch("backend.services.calendar_service.get_calendar_service", return_value=None):
            from backend.services.calendar_service import list_upcoming_events
            assert list_upcoming_events() == []

    def test_execute_calendar_create_no_service(self):
        with patch("backend.services.calendar_service.get_calendar_service", return_value=None):
            from backend.services.calendar_service import execute_calendar_create
            with pytest.raises(Exception, match="not connected"):
                execute_calendar_create({"title": "Test"})

    def test_execute_calendar_create_missing_date(self):
        mock_service = MagicMock()
        with patch("backend.services.calendar_service.get_calendar_service", return_value=mock_service):
            from backend.services.calendar_service import execute_calendar_create
            with pytest.raises(Exception, match="missing start date"):
                execute_calendar_create({"title": "Test"})


# ===========================================================================
# 15. EDGE CASES
# ===========================================================================

class TestEdgeCases:

    def test_update_title_nonexistent_session(self):
        from backend.db.store import update_title
        update_title("new-sess", "Brand New")  # should not raise

    def test_delete_nonexistent_session(self):
        from backend.db.store import delete_session
        delete_session("ghost-session")  # should not raise

    def test_init_db_idempotent(self):
        from backend.db.store import init_db
        init_db()  # running twice should not crash
        init_db()

    def test_init_context_db_idempotent(self):
        from backend.db.context_store import init_context_db
        init_context_db()
        init_context_db()
