"""
FastAPI Backend — Main chat server with Groq and Gemini LLM integration.

Uses a two-phase approach:
1. LLM analyzes user intent and decides tool actions
2. Backend executes MCP tools and feeds results back to LLM for final response

Run: python main.py
Endpoint: http://localhost:8000
"""

import os
import re
import json
import asyncio
import base64
import traceback
import sqlite3
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from fastmcp import Client as MCPClient


# LLM Providers
from groq import AsyncGroq
from openai import AsyncOpenAI

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

load_dotenv()

# --- Configuration ---
FASTMCP_URL = os.getenv("FASTMCP_URL", "http://localhost:8001/mcp")

# Keys
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")

# Default Models
DEFAULT_GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
DEFAULT_GROQ_VISION = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")

# --- FastAPI App ---
app = FastAPI(
    title="iLumina Chatbot",
    description="AI Chatbot with Playwright browser automation via MCP",
    version="1.0.0",
)

# --- LLM Clients ---
groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GOOGLE_API_KEY) if (genai and GOOGLE_API_KEY) else None
nvidia_client = AsyncOpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=NVIDIA_API_KEY) if NVIDIA_API_KEY else None

# --- Persistent Chat History (SQLite + Cache) ---
DB_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "pulse_chat.db")

# In-Memory Cache for blazing fast reads/writes
CHAT_CACHE = {}

def init_db():
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
                title TEXT
            )
        ''')
        # Index for fast lookups
        conn.execute('CREATE INDEX IF NOT EXISTS idx_session_id ON messages(session_id)')
        conn.commit()

init_db()

def load_session(session_id: str) -> list:
    """Load session from RAM cache first, fallback to SQLite."""
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

def append_message(session_id: str, role: str, content: str):
    """Atomically append a single message to Cache and SQLite."""
    # Update Cache
    if session_id not in CHAT_CACHE:
        load_session(session_id)
    CHAT_CACHE[session_id].append({"role": role, "content": content})
    
    # Update SQLite safely
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            'INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)',
            (session_id, role, content)
        )
        conn.commit()


# --- Request/Response Models ---
class ChatResponse(BaseModel):
    response: str
    screenshots: list[str] = []
    tool_calls_made: list[str] = []

class ChatTitleUpdate(BaseModel):
    title: str


# --- Intent Detection (Removed in favor of Native LLM Tool Calling) ---

# --- Tool Registry ---
async def fetch_tools_as_openai_schema() -> list[dict]:
    """Fetch MCP tools and convert them to OpenAI JSON Schema format for native tool calling."""
    tools = []
    try:
        async with MCPClient(FASTMCP_URL) as client:
            mcp_tools = await client.list_tools()
            for t in mcp_tools:
                tools.append({
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description or "",
                        "parameters": t.inputSchema or {"type": "object", "properties": {}}
                    }
                })
    except Exception as e:
        print(f"Failed to fetch MCP tools for LLM schema: {e}")
    return tools


# --- MCP Tool Execution ---
async def execute_mcp_tool(tool_name: str, arguments: dict) -> str:
    try:
        async with MCPClient(FASTMCP_URL) as client:
            result = await client.call_tool(tool_name, arguments)
            texts = []
            items = result.content if hasattr(result, 'content') else result
            for item in items:
                if hasattr(item, 'text'):
                    texts.append(item.text)
                elif hasattr(item, 'data'):
                    texts.append(json.dumps({
                        "type": "image",
                        "mimeType": getattr(item, 'mimeType', 'image/png'),
                        "data": item.data,
                    }))
                else:
                    texts.append(str(item))
            return "\n".join(texts)
    except Exception as e:
        traceback.print_exc()
        return json.dumps({"error": str(e)})


def _extract_screenshots(result_str: str) -> list[str]:
    screenshots = []
    try:
        result_data = json.loads(result_str)
        if isinstance(result_data, dict):
            # Check for direct image or nested in "screenshot"
            img_dict = None
            if result_data.get("type") == "image":
                img_dict = result_data
            elif "screenshot" in result_data and result_data["screenshot"]:
                img_dict = result_data["screenshot"]
                
            if img_dict and "data" in img_dict:
                import uuid
                import os
                
                # Create screenshots directory
                screenshots_dir = os.path.join(os.path.dirname(__file__), "frontend", "screenshots")
                os.makedirs(screenshots_dir, exist_ok=True)
                
                # Save to disk
                filename = f"screenshot_{uuid.uuid4().hex[:8]}.png"
                filepath = os.path.join(screenshots_dir, filename)
                
                with open(filepath, "wb") as f:
                    f.write(base64.b64decode(img_dict["data"]))
                    
                # Return the URL path
                screenshots.append(f"/static/screenshots/{filename}")
                
    except (json.JSONDecodeError, TypeError):
        pass
    return screenshots


SUMMARY_SYSTEM = """You are iLumina — a helpful AI assistant with browser automation.
You just performed a browser action and received the results below.
Provide a helpful, well-formatted markdown summary of what was found.
CRITICAL: You must directly address any specific questions, tasks, or ratings the user asked for in their original message! Do not just summarize if they asked for something specific.
If there's an error, explain it clearly and suggest what the user can try."""


# --- LLM Router ---
async def call_llm(provider: str, model: str, messages: list, max_tokens=4096, temperature=0.7, tools=None):
    """Wrapper to call either Groq or Gemini with uniform interface."""
    
    if provider == "groq":
        if not groq_client:
            raise ValueError("Groq API key not configured")
        
        # Groq native call
        response = await groq_client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools if tools else None
        )
        msg = response.choices[0].message
        return {
            "content": msg.content or "",
            "tool_calls": getattr(msg, "tool_calls", None)
        }
        
    elif provider == "nvidia":
        if not nvidia_client:
            raise ValueError("NVIDIA API key not configured")
            
        response = await nvidia_client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools if tools else None
        )
        msg = response.choices[0].message
        return {
            "content": msg.content or "",
            "tool_calls": getattr(msg, "tool_calls", None)
        }

    elif provider == "gemini":
        if not gemini_client:
            raise ValueError("Google Gemini API key not configured")
            
        # Convert messages to Gemini format
        system_instruction = None
        gemini_contents = []
        
        for msg in messages:
            if msg["role"] == "system":
                system_instruction = msg["content"]
            else:
                # Handle vision dict inputs
                if isinstance(msg["content"], list):
                    parts = []
                    for item in msg["content"]:
                        if item["type"] == "text":
                            parts.append(types.Part.from_text(text=item["text"]))
                        elif item["type"] == "image_url":
                            # extract base64 from data URI
                            url = item["image_url"]["url"]
                            if url.startswith("data:"):
                                mime, b64 = url.split(";", 1)[0].replace("data:", ""), url.split(",", 1)[1]
                                parts.append(types.Part.from_bytes(data=base64.b64decode(b64), mime_type=mime))
                    
                    gemini_contents.append(types.Content(
                        role="user" if msg["role"] == "user" else "model",
                        parts=parts
                    ))
                else:
                    gemini_contents.append(types.Content(
                        role="user" if msg["role"] == "user" else "model",
                        parts=[types.Part.from_text(text=msg["content"])]
                    ))

        # Note: True function calling conversion for Gemini omitted for brevity here since Groq is default.
        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        if system_instruction:
            config.system_instruction = system_instruction
            
        response = await gemini_client.aio.models.generate_content(
            model=model,
            contents=gemini_contents,
            config=config
        )
        return {
            "content": response.text or "No text was returned.",
            "tool_calls": None
        }

    else:
        raise ValueError(f"Unknown provider: {provider}")


# --- Chat Endpoint ---
@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    message: str = Form(...),
    session_id: str = Form("default"),
    provider: str = Form("groq"),
    model_name: str = Form("llama-3.3-70b-versatile"),
    image: Optional[UploadFile] = File(None),
):
    """Process a chat message with tool calling and LLM Routing."""
    
    # Get or create session history
    history = load_session(session_id)

    # Process image if uploaded
    image_base64 = None
    image_mime = None
    if image:
        image_data = await image.read()
        image_base64 = base64.b64encode(image_data).decode('utf-8')
        image_mime = image.content_type or "image/png"

    append_message(session_id, "user", message)
    history = load_session(session_id)

    screenshots = []
    tool_calls_made = []

    try:
        # === IMAGE MODE: Use vision model directly ===
        if image_base64:
            vision_content = [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{image_mime};base64,{image_base64}"}
                },
                {"type": "text", "text": message or "What do you see in this image?"}
            ]
            
            # Use appropriate vision model based on provider
            v_model = model_name
            if provider == "groq" and "scout" not in model_name:
                v_model = DEFAULT_GROQ_VISION # Groq needs specific vision models
            
            messages = [
                {"role": "system", "content": "You are iLumina, a helpful AI assistant. Analyze the image and answer the user's question about it. Be detailed and helpful. Format your response in markdown."},
                {"role": "user", "content": vision_content}
            ]

            result = await call_llm(provider, v_model, messages, temperature=0.3)
            result_text = result["content"]
            append_message(session_id, "assistant", result_text)
            return ChatResponse(response=result_text)

        # === TEXT MODE: Native LLM Tool Calling ===
        
        # Fetch available tools
        available_tools = await fetch_tools_as_openai_schema()
        
        # Build message history for the LLM
        chat_messages = [
            {"role": "system", "content": "You are iLumina, a helpful AI assistant with browser automation. Use tools when necessary to fulfill the user's request. CRITICAL RULES: 1) `get_page_snapshot` returns TEXT, not an image. 2) Only `take_screenshot` and `navigate_and_summarize` return actual images. 3) NEVER say 'Here is a screenshot' unless you actually called a tool that returns an image. 4) If you only read text, just provide the summary."},
        ]
        for m in history[-20:]:
            chat_messages.append({"role": m["role"], "content": m["content"]})
            
        # First LLM Call: Decide to chat or use a tool
        result = await call_llm(
            provider,
            model_name,
            messages=chat_messages,
            temperature=0.3,
            tools=available_tools
        )
        
        if result["tool_calls"]:
            # Tool calling executed by LLM
            for tc in result["tool_calls"]:
                tool_name = tc.function.name
                try:
                    tool_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}
                    
                tool_calls_made.append(tool_name)
                print(f"🔧 LLM executed tool: {tool_name}({tool_args})")
                
                # Execute the tool
                tool_result = await execute_mcp_tool(tool_name, tool_args)
                screenshots.extend(_extract_screenshots(tool_result))
                
                # Clean result for context window
                clean_result = tool_result
                try:
                    parsed = json.loads(tool_result)
                    if isinstance(parsed, dict):
                        if "screenshot" in parsed and parsed["screenshot"]:
                            parsed["screenshot"] = "[screenshot captured]"
                        if "data" in parsed:
                            parsed["data"] = "[image data]"
                        clean_result = json.dumps(parsed, indent=2)
                except (json.JSONDecodeError, TypeError):
                    if len(clean_result) > 6000:
                        clean_result = clean_result[:6000] + "\n... (truncated)"
                
                # Append tool results to messages and call LLM again for the final response
                chat_messages.append({"role": "assistant", "content": f"I decided to use the {tool_name} tool to help with this."})
                chat_messages.append({"role": "user", "content": f"The tool '{tool_name}' returned the following result:\n{clean_result}\n\nPlease provide a helpful summary or answer based on this result."})
                
                final_result = await call_llm(provider, model_name, messages=chat_messages, temperature=0.3)
                result_text = final_result["content"]
        else:
            # No tool called, just normal chat response
            result_text = result["content"]

        # Inject screenshots into markdown so they persist in the DB
        for url in screenshots:
            result_text += f"\n\n![Screenshot]({url})"

        append_message(session_id, "assistant", result_text)
        return ChatResponse(
            response=result_text,
            screenshots=screenshots,
            tool_calls_made=tool_calls_made,
        )

    except Exception as e:
        traceback.print_exc()
        error_msg = f"⚠️ Error: {str(e)}"
        append_message(session_id, "assistant", error_msg)
        return ChatResponse(response=error_msg)


@app.get("/api/tools")
async def list_tools():
    """List available MCP tools from the FastMCP server."""
    try:
        async with MCPClient(FASTMCP_URL) as client:
            tools = await client.list_tools()
            return [
                {"name": t.name, "description": t.description or ""}
                for t in tools
            ]
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Could not connect to MCP server: {str(e)}"}
        )


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    mcp_status = "unknown"
    try:
        async with MCPClient(FASTMCP_URL) as client:
            await client.list_tools()
            mcp_status = "connected"
    except Exception:
        mcp_status = "disconnected"

    return {
        "status": "ok",
        "mcp_server": mcp_status,
        "groq_configured": bool(GROQ_API_KEY),
        "gemini_configured": bool(GOOGLE_API_KEY),
    }

@app.get("/api/documents")
async def list_documents():
    """List embedded documents from the MCP server."""
    try:
        async with MCPClient(FASTMCP_URL) as client:
            result = await client.call_tool("list_embedded_documents", {})
            # extract string content
            texts = []
            items = result.content if hasattr(result, 'content') else result
            for item in items:
                if hasattr(item, 'text'):
                    texts.append(item.text)
                else:
                    texts.append(str(item))
            res_str = "\n".join(texts)
            try:
                return json.loads(res_str)
            except:
                return {"files": []}
    except Exception as e:
        return {"files": []}

@app.get("/api/chats")
async def list_chats():
    """List all saved chat sessions directly from SQLite."""
    sessions = []
    with sqlite3.connect(DB_PATH) as conn:
        # Get all unique sessions ordered by latest activity
        cursor = conn.execute('''
            SELECT m.session_id, MAX(m.timestamp), s.title
            FROM messages m
            LEFT JOIN sessions s ON m.session_id = s.session_id
            GROUP BY m.session_id
            ORDER BY MAX(m.timestamp) DESC
        ''')
        for row in cursor.fetchall():
            sid = row[0]
            title = row[2]
            
            if title:
                preview = title
            else:
                # Fetch first user message for preview
                cursor2 = conn.execute('SELECT content FROM messages WHERE session_id = ? AND role = "user" ORDER BY id ASC LIMIT 1', (sid,))
                first_user = cursor2.fetchone()
                
                preview = "Empty chat"
                if first_user:
                    msg_content = first_user[0]
                    preview = msg_content[:60] + "..." if len(msg_content) > 60 else msg_content
                
            sessions.append({"id": sid, "preview": preview})
            
    return sessions

@app.get("/api/chats/{session_id}")
async def get_chat(session_id: str):
    """Load a specific chat session."""
    return load_session(session_id)

@app.put("/api/chats/{session_id}/title")
async def update_chat_title(session_id: str, request: ChatTitleUpdate):
    """Update the title of a chat session."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                'INSERT OR REPLACE INTO sessions (session_id, title) VALUES (?, ?)',
                (session_id, request.title)
            )
            conn.commit()
        return {"status": "success"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.delete("/api/chats/{session_id}")
async def delete_chat(session_id: str):
    """Delete a specific chat session."""
    # Remove from cache
    if session_id in CHAT_CACHE:
        del CHAT_CACHE[session_id]
        
    # Remove from SQLite
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute('DELETE FROM messages WHERE session_id = ?', (session_id,))
            conn.commit()
        
        # Also attempt to delete the old JSON file if it exists, just to be thorough
        json_path = os.path.join(os.path.dirname(__file__), "data", "chats", f"{session_id}.json")
        if os.path.exists(json_path):
            os.remove(json_path)
            
        return {"status": "success"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# Serve frontend static files
frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


@app.get("/")
async def serve_frontend():
    """Serve the frontend."""
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return JSONResponse({"message": "Frontend not found."})


# --- Run ---
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("FASTAPI_PORT", "8000"))
    print(f"🤖 Starting iLumina Chatbot Backend on http://localhost:{port}")
    print(f"📡 FastMCP Server URL: {FASTMCP_URL}")
    uvicorn.run(app, host="0.0.0.0", port=port)
