"""
MCP session management, tool discovery, and tool execution.

Manages connections to:
- FastMCP HTTP proxy (Playwright, DuckDuckGo, document tools)
- Stdio MCP servers (Filesystem, MS365, Memory)
"""

import json
import base64
import os
import uuid

from fastmcp import Client as MCPClient

from backend.config import FASTMCP_URL, SCREENSHOTS_DIR


# --- Global State ---
# Stdio MCP sessions, populated during FastAPI lifespan
MCP_SESSIONS: dict[str, dict] = {}

# Maps tool names to their session for routing execution
TOOL_TO_SESSION_MAP: dict[str, str] = {}


# --- Tool Discovery ---

async def fetch_tools_as_openai_schema(mode: str = "web") -> list[dict]:
    """Fetch MCP tools and convert to OpenAI function-calling schema, strictly budgeted for free-tier TPM limits."""
    tools = []
    total_chars = 0
    # Strict budget: ~16,000 characters (~4,000 tokens) max for all tool definitions
    MAX_SCHEMA_CHARS = 16000

    def try_add_tool(t_dict, tool_name, session_name):
        nonlocal total_chars
        tool_str = json.dumps(t_dict)
        if total_chars + len(tool_str) > MAX_SCHEMA_CHARS:
            return False
        TOOL_TO_SESSION_MAP[tool_name] = session_name
        tools.append(t_dict)
        total_chars += len(tool_str)
        return True

    if mode == "web" or mode == "mcp":
        # 1. Playwright and Web tools from FastMCP (Highest priority for browsing/screenshots)
        if "playwright" in MCP_SESSIONS:
            try:
                session = MCP_SESSIONS["playwright"]["session"]
                mcp_tools = await session.list_tools()
                for t in mcp_tools:
                    if t.name in ["embed_document", "query_documents", "list_embedded_documents"]:
                        if mode == "web": continue
                    try_add_tool(_tool_to_openai(t), t.name, "playwright")
            except Exception as e:
                print(f"Failed to fetch FastMCP tools: {e}")

        # 2. Stdio MCP tools: Prioritize Filesystem first, then other integrations
        if mode == "mcp":
            ordered_sessions = ["documents", "filesystem", "github", "ms365"]
            for sname in ordered_sessions:
                if sname in MCP_SESSIONS:
                    try:
                        session = MCP_SESSIONS[sname]["session"]
                        result = await session.list_tools()
                        for t in result.tools:
                            if not try_add_tool(_tool_to_openai(t), t.name, sname):
                                break  # Stop adding once budget is reached
                    except Exception as e:
                        print(f"Failed to fetch tools for {sname}: {e}")

    elif mode == "documents":
        # Local stdio MCP tools (Documents)
        if "documents" in MCP_SESSIONS:
            try:
                session = MCP_SESSIONS["documents"]["session"]
                result = await session.list_tools()
                for t in result.tools:
                    if t.name in ["embed_document", "query_documents", "list_embedded_documents"]:
                        try_add_tool(_tool_to_openai(t), t.name, "documents")
            except Exception as e:
                print(f"Failed to fetch Document tools: {e}")

        # Stdio MCP tools (Filesystem)
        if "filesystem" in MCP_SESSIONS:
            try:
                session = MCP_SESSIONS["filesystem"]["session"]
                result = await session.list_tools()
                for t in result.tools:
                    try_add_tool(_tool_to_openai(t), t.name, "filesystem")
            except Exception as e:
                print(f"Failed to fetch tools for filesystem: {e}")

    return tools


def _sanitize_schema(schema: dict) -> dict:
    """Recursively loosen strict boolean types to allow strings for Groq/Qwen XML compatibility."""
    if not isinstance(schema, dict):
        return schema
    new_schema = {}
    for k, v in schema.items():
        if k == "type" and v == "boolean":
            new_schema["anyOf"] = [{"type": "boolean"}, {"type": "string"}]
        elif isinstance(v, dict):
            new_schema[k] = _sanitize_schema(v)
        elif isinstance(v, list):
            new_schema[k] = [_sanitize_schema(item) if isinstance(item, dict) else item for item in v]
        else:
            new_schema[k] = v
    return new_schema


def _tool_to_openai(t) -> dict:
    """Convert an MCP tool definition to OpenAI function-calling format with compact descriptions."""
    desc = (t.description or "").strip()
    if len(desc) > 180:
        desc = desc[:177] + "..."

    params = t.inputSchema or {"type": "object", "properties": {}}
    sanitized_params = _sanitize_schema(params)

    return {
        "type": "function",
        "function": {
            "name": t.name,
            "description": desc,
            "parameters": sanitized_params
        }
    }


# --- Tool Execution ---

async def execute_mcp_tool(tool_name: str, arguments: dict) -> str:
    """Execute an MCP tool by name, routing to the correct session."""
    session_name = TOOL_TO_SESSION_MAP.get(tool_name, "playwright")

    # Clean arguments: cast string booleans ("true"/"false") back to boolean True/False
    cleaned_args = {}
    for k, v in arguments.items():
        if isinstance(v, str):
            if v.strip().lower() == "true":
                cleaned_args[k] = True
            elif v.strip().lower() == "false":
                cleaned_args[k] = False
            else:
                cleaned_args[k] = v
        else:
            cleaned_args[k] = v

    try:
        if session_name == "playwright":
            if "playwright" not in MCP_SESSIONS:
                return json.dumps({"error": "Playwright MCP session not initialized."})
            
            client = MCP_SESSIONS["playwright"]["session"]
            result = await client.call_tool(tool_name, cleaned_args)
            
            # Give SPAs and heavy sites 2 seconds to render before returning control
            if tool_name in ["browser_navigate", "browser_click"]:
                import asyncio
                await asyncio.sleep(2.0)
                
                # Fetch the fully rendered DOM snapshot after sleeping
                try:
                    snapshot_result = await client.call_tool("browser_snapshot", {})
                    
                    # Combine the results so the agent knows the navigation succeeded AND gets the populated DOM
                    parsed_orig = _parse_tool_result(result)
                    parsed_snap = _parse_tool_result(snapshot_result)
                    return f"{parsed_orig}\n\n[Delayed Render Snapshot]:\n{parsed_snap}"
                except Exception as e:
                    print(f"Error fetching delayed snapshot: {e}")
                    pass
                
            return _parse_tool_result(result)
        else:
            session = MCP_SESSIONS[session_name]["session"]
            result = await session.call_tool(tool_name, cleaned_args)
            return _parse_tool_result(result)
    except Exception as e:
        return json.dumps({"error": f"Tool execution failed: {str(e)}"})


def _parse_tool_result(result) -> str:
    """Extract text content from an MCP tool result."""
    texts = []
    items = result.content if hasattr(result, 'content') else result
    if not items:
        return "Tool executed successfully (no output)."

    for item in items:
        if hasattr(item, 'text'):
            texts.append(item.text)
        elif hasattr(item, 'data'):
            texts.append(json.dumps({
                "type": "image",
                "mimeType": getattr(item, 'mimeType', 'image/png'),
                "data": item.data,
            }))
        elif isinstance(item, dict) and "text" in item:
            texts.append(item["text"])
        else:
            texts.append(str(item))
    return "\n".join(texts)


def extract_screenshots(result_str: str) -> list[str]:
    """Extract base64 screenshot images from a tool result and save to disk."""
    screenshots = []
    try:
        result_data = json.loads(result_str)
        if isinstance(result_data, dict):
            img_dict = None
            if result_data.get("type") == "image":
                img_dict = result_data
            elif "screenshot" in result_data and result_data["screenshot"]:
                img_dict = result_data["screenshot"]

            if img_dict and "data" in img_dict:
                filename = f"screenshot_{uuid.uuid4().hex[:8]}.png"
                filepath = os.path.join(SCREENSHOTS_DIR, filename)
                with open(filepath, "wb") as f:
                    f.write(base64.b64decode(img_dict["data"]))
                screenshots.append(f"/static/screenshots/{filename}")

    except (json.JSONDecodeError, TypeError):
        pass
    return screenshots
