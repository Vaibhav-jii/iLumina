"""
Chat API routes — handles message processing, agent execution, and streaming.
"""

import json
import asyncio
import base64
import re
import traceback
import time
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import StreamingResponse

from backend.config import DEFAULT_GROQ_VISION
from backend.models import ChatResponse
from backend.db.store import load_session, append_message
from backend.core.llm import call_llm
from backend.core.agent import (
    AgentState, SYSTEM_PROMPTS, DELEGATE_TO_WRITER_TOOL, PROPOSE_CALENDAR_EVENT_TOOL, STORE_MEMORY_TOOL, PROPOSE_ACTION_TOOL,
    build_graph, strip_reasoning,
)
from backend.core.context.resolver import resolve_context_prompt, resolve_document_scope
from backend.mcp.client import fetch_tools_as_openai_schema

router = APIRouter()


def _build_available_tools(raw_tools: list, mode: str) -> list:
    """Filter tools and add virtual tools based on mode."""
    if mode == "chat":
        return []

    # Virtual tools available across all modes
    virtual_tools = [
        PROPOSE_CALENDAR_EVENT_TOOL,
        STORE_MEMORY_TOOL,
        PROPOSE_ACTION_TOOL
    ]
    if mode == "documents":
        virtual_tools.append(DELEGATE_TO_WRITER_TOOL)

    available_tools = [t for t in raw_tools if t["function"]["name"] != "generate_pdf"]
    
    # Cap total tools to 120 (Groq strict limit is 128)
    max_raw = 120 - len(virtual_tools)
    if len(available_tools) > max_raw:
        available_tools = available_tools[:max_raw]

    return available_tools + virtual_tools


def _build_chat_messages(mode: str, history: list, space_id: Optional[str] = None) -> list:
    """Build the message list with system prompt and recent history."""
    system_prompt = SYSTEM_PROMPTS.get(mode, SYSTEM_PROMPTS["chat"])
    
    # Inject active workspace context (calendar, memories, entities)
    context_block = resolve_context_prompt(space_id)
    if context_block:
        system_prompt += context_block
    
    # Inject document scope constraint for Knowledge Base mode
    if mode == "documents" and space_id:
        scope_msg = resolve_document_scope(space_id)
        if scope_msg:
            system_prompt += "\n\n" + scope_msg
        
    chat_messages = [{"role": "system", "content": system_prompt}]
    for m in history[-20:]:
        chat_messages.append({"role": m["role"], "content": m["content"]})
    return chat_messages


# --- Standard (non-streaming) Chat Endpoint ---

@router.post("/api/chat", response_model=ChatResponse)
async def chat(
    message: str = Form(...),
    session_id: str = Form("default"),
    provider: str = Form("nvidia"),
    model_name: str = Form("nvidia/nemotron-3.5-lightning-30b-a3b"),
    mode: str = Form("chat"),
    space_id: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
):
    """Process a chat message with tool calling and LLM routing."""
    # Safety split in case the frontend sends the raw "provider:model" string
    if ":" in provider and len(provider.split(":", 1)) == 2:
        parts = provider.split(":", 1)
        provider = parts[0]
        model_name = parts[1]

    try:
        history = load_session(session_id)

        # Process image if uploaded
        image_base64 = None
        image_mime = None
        if image:
            image_data = await image.read()
            image_base64 = base64.b64encode(image_data).decode('utf-8')
            image_mime = image.content_type or "image/png"

        append_message(session_id, "user", message, mode, space_id)
        history = load_session(session_id)

        # === IMAGE MODE ===
        if image_base64:
            result = await _handle_image(provider, model_name, message, image_base64, image_mime)
            append_message(session_id, "assistant", result)
            return ChatResponse(response=result)

        # === TEXT MODE: Agent Loop ===
        raw_tools = await fetch_tools_as_openai_schema(mode=mode)
        available_tools = _build_available_tools(raw_tools, mode)
        chat_messages = _build_chat_messages(mode, history, space_id)

        agent_app = build_graph()
        final_state = await agent_app.ainvoke({
            "messages": chat_messages,
            "session_id": session_id,
            "provider": provider,
            "model_name": model_name,
            "mode": mode,
            "available_tools": available_tools,
            "tool_calls_made": [],
            "screenshots": [],
            "iterations": 0,
        })

        result_text = _extract_final_response(final_state)
        append_message(session_id, "assistant", result_text, mode, space_id)

        return ChatResponse(
            response=result_text,
            screenshots=final_state.get("screenshots", []),
            tool_calls_made=final_state.get("tool_calls_made", []),
        )

    except Exception as e:
        traceback.print_exc()
        error_msg = f"⚠️ Error: {str(e)}"
        append_message(session_id, "assistant", error_msg, mode, space_id)
        return ChatResponse(response=error_msg)


# --- Streaming Chat Endpoint (SSE via fetch + ReadableStream) ---

@router.post("/api/chat/stream")
async def chat_stream(
    message: str = Form(...),
    session_id: str = Form("default"),
    provider: str = Form("nvidia"),
    model_name: str = Form("nvidia/nemotron-3.5-lightning-30b-a3b"),
    mode: str = Form("chat"),
    space_id: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
):
    """Streaming chat endpoint — returns SSE events for real-time UI updates."""
    # Safety split in case the frontend sends the raw "provider:model" string
    if ":" in provider and len(provider.split(":", 1)) == 2:
        parts = provider.split(":", 1)
        provider = parts[0]
        model_name = parts[1]

    history = load_session(session_id)

    image_base64 = None
    image_mime = None
    if image:
        image_data = await image.read()
        image_base64 = base64.b64encode(image_data).decode('utf-8')
        image_mime = image.content_type or "image/png"

    append_message(session_id, "user", message, mode, space_id)
    history = load_session(session_id)

    async def event_generator():
        start_time = time.time()
        try:
            # === IMAGE MODE ===
            if image_base64:
                result = await _handle_image(provider, model_name, message, image_base64, image_mime)
                append_message(session_id, "assistant", result, mode, space_id)
                yield _sse({"type": "response", "text": result})
                yield _sse({"type": "done", "duration_ms": int((time.time() - start_time) * 1000)})
                return

            # === TEXT MODE: Agent Loop with trace events ===
            raw_tools = await fetch_tools_as_openai_schema(mode=mode)
            available_tools = _build_available_tools(raw_tools, mode)
            chat_messages = _build_chat_messages(mode, history, space_id)

            event_queue = asyncio.Queue()
            agent_app = build_graph(event_queue=event_queue)

            initial_state = {
                "messages": chat_messages,
                "session_id": session_id,
                "provider": provider,
                "model_name": model_name,
                "mode": mode,
                "available_tools": available_tools,
                "tool_calls_made": [],
                "screenshots": [],
                "iterations": 0,
            }

            # Run agent in background, drain events from the queue
            agent_task = asyncio.create_task(agent_app.ainvoke(initial_state))
            trace = []

            while not agent_task.done():
                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=0.2)
                    trace.append(event)
                    yield _sse(event)
                except asyncio.TimeoutError:
                    continue

            # Drain any remaining events
            while not event_queue.empty():
                event = await event_queue.get()
                trace.append(event)
                yield _sse(event)

            final_state = agent_task.result()
            result_text = _extract_final_response(final_state)
            append_message(session_id, "assistant", result_text, mode, space_id)

            yield _sse({
                "type": "response",
                "text": result_text,
                "screenshots": final_state.get("screenshots", []),
                "tool_calls_made": final_state.get("tool_calls_made", []),
            })
            yield _sse({
                "type": "done",
                "duration_ms": int((time.time() - start_time) * 1000),
                "trace": trace,
            })

        except Exception as e:
            traceback.print_exc()
            error_msg = f"⚠️ Error: {str(e)}"
            append_message(session_id, "assistant", error_msg, mode, space_id)
            yield _sse({"type": "error", "text": error_msg})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# --- Helpers ---

async def _handle_image(provider: str, model_name: str, message: str, image_b64: str, mime: str) -> str:
    """Handle an image upload with a vision-capable model."""
    vision_content = [
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
        {"type": "text", "text": message or "What do you see in this image?"}
    ]
    v_model = DEFAULT_GROQ_VISION if provider == "groq" else model_name
    messages = [
        {"role": "system", "content": "You are iLumina, a helpful AI assistant. Analyze the image and answer the user's question about it. Be detailed and helpful. Format your response in markdown."},
        {"role": "user", "content": vision_content}
    ]
    result = await call_llm(provider, v_model, messages, temperature=0.3)
    return result["content"]


def _extract_final_response(final_state: dict) -> str:
    """Extract and clean the final response text from the agent state."""
    result_text = final_state["messages"][-1].get("content") or "Finished tool execution."
    result_text = strip_reasoning(result_text)
    for url in final_state.get("screenshots", []):
        result_text += f"\n\n![Screenshot]({url})"
    return result_text


def _sse(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data)}\n\n"
