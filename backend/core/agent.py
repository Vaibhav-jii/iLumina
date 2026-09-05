"""
LangGraph agent workflow — defines the multi-agent execution graph.

Contains:
- AgentState: graph state schema
- System prompts for chat/web/documents modes
- LangGraph nodes (llm_node, tool_node, writer_node)
- Graph builder and runner (with SSE streaming support)
"""

import re
import json
import time
import asyncio
from typing import TypedDict

from langgraph.graph import StateGraph, END

from backend.config import MAX_ITERATIONS, DEFAULT_GROQ_VISION
from backend.core.llm import call_llm
from backend.mcp.client import (
    fetch_tools_as_openai_schema,
    execute_mcp_tool,
    extract_screenshots,
)


# --- Agent State ---

class AgentState(TypedDict):
    messages: list
    session_id: str
    provider: str
    model_name: str
    mode: str
    available_tools: list
    tool_calls_made: list
    screenshots: list
    iterations: int


# --- System Prompts (Compact — saves ~1500 tokens per request) ---

SYSTEM_PROMPTS = {
    "chat": """You are iLumina — a friendly AI assistant in CHAT mode (no tools).
Respond in clean Markdown. If the user needs web browsing, suggest Web MCP mode. For documents, suggest Knowledge Base mode.""",

    "web": """You are iLumina — an MCP-powered assistant with browser automation and web search.

Tools: `browser_navigate`, `browser_click`, `browser_type`, `browser_take_screenshot`, `browser_snapshot`, `web_search`.

Rules:
1. Determine intent → pick minimum tools → execute → verify → answer.
2. Never assume — always verify via tool output.
3. For web pages: use `browser_navigate` to load the page. The system will automatically return the DOM snapshot.
4. To interact: use `browser_click` to click elements, and `browser_type` to fill in forms (emails, passwords, etc) using the CSS selectors found in the DOM snapshot.
5. For search: use `web_search` for broad queries, and `browser_navigate` for specific URLs.
6. Format responses in Markdown.""",

    "documents": """You are iLumina — a knowledge-powered assistant with access to an embeddings vector database.

IMPORTANT CONTEXT:
- All files from Google Drive, OneDrive, and local uploads are automatically synced into ChromaDB embeddings every 5 minutes.
- Use `query_documents` for semantic search across embeddings.
- Use `list_embedded_documents` to see all available documents.

Rules:
1. Determine intent → pick tools → execute → loop until done → answer.
2. You can call tools multiple times. After each tool result, decide if more calls are needed.
3. For comparisons (e.g. "compare doc A and doc B"): call `query_documents` for each document separately, then synthesize results.
4. For PDF reports: gather all data first via `query_documents`, then call `delegate_to_writer` ONLY after you have the content. Never delegate without querying first.
5. Never assume — always verify via tool output.
6. Format responses in Markdown.""",
}

# mcp mode uses the same prompt as web
SYSTEM_PROMPTS["mcp"] = SYSTEM_PROMPTS["web"]


# --- Delegate Tool Definition ---

DELEGATE_TO_WRITER_TOOL = {
    "type": "function",
    "function": {
        "name": "delegate_to_writer",
        "description": "Delegate raw research notes to the Expert Writer Agent to generate beautifully formatted PDF reports. Use this ONLY after you have gathered all necessary information.",
        "parameters": {
            "type": "object",
            "properties": {
                "user_intent": {
                    "type": "string",
                    "description": "What the user actually wants to accomplish. Write a full, specific sentence."
                },
                "retrieved_document_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "The names or titles of the documents found."
                },
                "retrieval_confidence": {
                    "type": "string",
                    "description": "A confidence score on how good the search results are (e.g. 95%)."
                }
            },
            "required": ["user_intent", "retrieved_document_names", "retrieval_confidence"]
        }
    }
}

PROPOSE_CALENDAR_EVENT_TOOL = {
    "type": "function",
    "function": {
        "name": "propose_calendar_event",
        "description": "Propose the creation of a Google Calendar event. This will ask the user for human approval. Use this when the user asks to schedule something, or when it naturally makes sense based on context.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start_date": {"type": "string", "description": "ISO 8601 string, e.g. 2026-10-15T09:00:00Z"},
                "end_date": {"type": "string", "description": "ISO 8601 string, e.g. 2026-10-15T10:00:00Z"},
                "location": {"type": "string"},
                "description": {"type": "string"},
                "reason": {"type": "string", "description": "Why you are proposing this event"}
            },
            "required": ["title", "start_date", "end_date"]
        }
    }
}

STORE_MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "store_memory",
        "description": "Store a permanent fact, preference, or project detail about the user. Use this when the user tells you something you should remember for future conversations.",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The fact or preference to remember. Be concise but specific."},
                "category": {"type": "string", "description": "'preference', 'fact', 'project', or 'general'"}
            },
            "required": ["content"]
        }
    }
}

PROPOSE_ACTION_TOOL = {
    "type": "function",
    "function": {
        "name": "propose_action",
        "description": "Propose an external action (like creating a GitHub issue, modifying a file, or sending an email) for human approval. Use this for ANY tool execution that writes data externally (except for calendar events which have their own tool).",
        "parameters": {
            "type": "object",
            "properties": {
                "tool_name": {"type": "string", "description": "The exact name of the MCP tool you want to execute."},
                "tool_args": {"type": "object", "description": "The arguments for the MCP tool."},
                "title": {"type": "string", "description": "A short, readable title for the UI describing this action."},
                "description": {"type": "string", "description": "A longer description for the user."},
                "reason": {"type": "string", "description": "Why you are proposing this action."}
            },
            "required": ["tool_name", "tool_args", "title"]
        }
    }
}


# --- Graph Node Factories ---

def _build_nodes(event_queue: asyncio.Queue | None = None):
    """Build the LangGraph node functions. If event_queue is provided,
    nodes will push trace events for SSE streaming."""

    async def _emit(event: dict):
        if event_queue:
            await event_queue.put(event)

    async def llm_node(state: AgentState):
        provider = state["provider"]
        model_name = state["model_name"]
        messages = state["messages"]
        available_tools = state.get("available_tools")

        if state.get("iterations", 0) >= MAX_ITERATIONS:
            messages.append({
                "role": "system",
                "content": "You have reached the maximum number of tool execution steps. Please summarize the information you have gathered so far and provide a final answer to the user."
            })
            result = await call_llm(provider, model_name, messages, temperature=0.3, tools=None)
            messages.append({"role": "assistant", "content": result["content"]})
            return {"messages": messages}

        result = await call_llm(
            provider, model_name, messages,
            temperature=0.3,
            tools=available_tools if available_tools else None
        )

        msg = {"role": "assistant", "content": result.get("content")}

        # Preserve Gemini thought_signature for multi-turn tool calling fidelity
        if result.get("_thought_signature"):
            msg["_thought_signature"] = result["_thought_signature"]
        if result.get("_gemini_parts"):
            msg["_gemini_parts"] = result["_gemini_parts"]

        if result.get("tool_calls"):
            tool_calls = result["tool_calls"]
            # Safeguard: don't allow delegate_to_writer in parallel with other tools
            if len(tool_calls) > 1:
                has_delegate = any(tc["function"]["name"] == "delegate_to_writer" for tc in tool_calls)
                if has_delegate:
                    print("⚠️  Stripping parallel delegate_to_writer call to enforce sequential workflow.")
                    tool_calls = [tc for tc in tool_calls if tc["function"]["name"] != "delegate_to_writer"]
            msg["tool_calls"] = tool_calls

        messages.append(msg)
        return {
            "messages": messages,
            "iterations": state.get("iterations", 0) + 1
        }

    async def tool_node(state: AgentState):
        messages = state["messages"]
        last_message = messages[-1]
        tool_calls = last_message.get("tool_calls", [])

        tool_names = []
        new_screenshots = []

        for tc in tool_calls:
            tool_name = tc["function"]["name"]
            tool_names.append(tool_name)
            tool_call_id = tc["id"]
            try:
                tool_args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                tool_args = {}

            print(f"🔧 LLM executing tool: {tool_name}({tool_args})")
            await _emit({"type": "tool_start", "tool": tool_name})
            start_time = time.time()
            
            try:
                if tool_name == "propose_calendar_event":
                    from backend.schemas.actions import ProposedActionCreate
                    from backend.db.context_store import create_action
                    
                    action = ProposedActionCreate(
                        action_type="calendar.create",
                        provider="google_calendar",
                        title=tool_args.get("title", "New Event"),
                        description=tool_args.get("description", ""),
                        payload=tool_args,
                        reason=tool_args.get("reason", "Requested by user"),
                        session_id=state["session_id"]
                    )
                    action_id = create_action(action)
                    tool_result = f"Successfully proposed calendar action to user. Waiting for human approval. Action ID: {action_id}"
                    
                elif tool_name == "store_memory":
                    from backend.db.context_store import create_memory
                    
                    content = tool_args.get("content", "")
                    category = tool_args.get("category", "general")
                    memory_id = create_memory(content, category)
                    tool_result = f"Successfully saved memory (ID: {memory_id}). I will remember this for future conversations."
                    
                elif tool_name == "propose_action":
                    from backend.schemas.actions import ProposedActionCreate
                    from backend.db.context_store import create_action
                    
                    payload = {
                        "tool_name": tool_args.get("tool_name"),
                        "tool_args": tool_args.get("tool_args", {})
                    }
                    action = ProposedActionCreate(
                        action_type="mcp",
                        provider="mcp",
                        title=tool_args.get("title", "New Action"),
                        description=tool_args.get("description", ""),
                        payload=payload,
                        reason=tool_args.get("reason", "Requested by user"),
                        session_id=state["session_id"]
                    )
                    action_id = create_action(action)
                    tool_result = f"Successfully proposed action ({tool_args.get('tool_name')}) to user. Waiting for human approval. Action ID: {action_id}"
                    
                else:
                    tool_result = await execute_mcp_tool(tool_name, tool_args)
            except Exception as e:
                tool_result = e

            duration_ms = int((time.time() - start_time) * 1000)

            if isinstance(tool_result, Exception):
                tool_result_str = json.dumps({"error": str(tool_result)})
                await _emit({"type": "tool_end", "tool": tool_name, "status": "error", "duration_ms": duration_ms})
            else:
                tool_result_str = str(tool_result)
                new_screenshots.extend(extract_screenshots(tool_result_str))
                await _emit({"type": "tool_end", "tool": tool_name, "status": "ok", "duration_ms": duration_ms})

            clean_result = _clean_tool_result(tool_name, tool_result_str)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "content": clean_result
            })

        return {
            "messages": messages,
            "tool_calls_made": state.get("tool_calls_made", []) + tool_names,
            "screenshots": state.get("screenshots", []) + new_screenshots
        }

    async def writer_node(state: AgentState):
        messages = state["messages"]
        last_message = messages[-1]
        tool_calls = last_message.get("tool_calls", [])

        delegate_call = next((tc for tc in tool_calls if tc["function"]["name"] == "delegate_to_writer"), None)
        if not delegate_call:
            return {"messages": messages}

        await _emit({"type": "tool_start", "tool": "delegate_to_writer"})
        writer_start = time.time()

        # Gather context from prior retrieval results
        queries_made = 0
        raw_context_data = []
        for m in reversed(messages):
            if m.get("role") == "user":
                break
            if m.get("role") == "tool" and m.get("name") in ["query_documents", "embed_document", "search_embedded_documents"]:
                queries_made += 1
                raw_context_data.append(m.get("content", ""))

        content = "\n\n--- NEXT DOCUMENT ---\n\n".join(raw_context_data)

        try:
            args = json.loads(delegate_call["function"]["arguments"])
            user_intent = args.get("user_intent", "Unknown Intent")
            docs = args.get("retrieved_document_names", [])
            if not isinstance(docs, list):
                docs = [docs]
            confidence = args.get("retrieval_confidence", "Unknown")
        except Exception as e:
            duration_ms = int((time.time() - writer_start) * 1000)
            await _emit({"type": "tool_end", "tool": "delegate_to_writer", "status": "error", "duration_ms": duration_ms})
            return {"messages": messages + [{
                "role": "tool", "tool_call_id": delegate_call["id"],
                "name": "delegate_to_writer", "content": f"Failed to parse arguments: {e}"
            }]}

        if queries_made == 0:
            print("⚠️  Rejecting early delegation. 0 queries made.")
            duration_ms = int((time.time() - writer_start) * 1000)
            await _emit({"type": "tool_end", "tool": "delegate_to_writer", "status": "error", "duration_ms": duration_ms})
            messages.append({
                "role": "tool",
                "tool_call_id": delegate_call["id"],
                "name": "delegate_to_writer",
                "content": "ERROR: You attempted to delegate prematurely without making ANY queries. You MUST use the `query_documents` tool to gather context first."
            })
            return {"messages": messages, "tool_calls_made": state.get("tool_calls_made", []) + ["delegate_to_writer_REJECTED"]}

        provider = state["provider"]
        model_name = state["model_name"]

        print(f"✍️  Writer Agent received instructions. Intent: {user_intent} (Got {len(docs)} doc labels)")

        # 1. Audit Report
        audit_prompt = f"""You are the Audit Report Generator.
Create an internal Audit Report explaining the research process.
Intent Detected: {user_intent}
Documents Retrieved: {', '.join(docs) if isinstance(docs, list) else docs}
Retrieval Confidence: {confidence}

Write a structured Markdown document that includes the above metadata, plus a 'Reasoning Summary' of how the retrieved content fulfills the user intent. Do not include the final deliverable here. Keep it analytical and objective."""

        print("📄 Generating Audit Report...")
        await _emit({"type": "tool_start", "tool": "generate_pdf (audit)"})
        audit_result = await call_llm(provider, model_name,
            [{"role": "system", "content": audit_prompt}, {"role": "user", "content": f"Context Data:\n{content}"}],
            temperature=0.1
        )
        audit_markdown = audit_result.get("content", "")
        audit_pdf_res = await execute_mcp_tool("generate_pdf", {
            "content": audit_markdown,
            "filename": f"audit_report_{user_intent.replace(' ', '_')[:20]}.pdf"
        })
        if "error" in audit_pdf_res.lower():
            print(f"❌ ERROR GENERATING AUDIT PDF: {audit_pdf_res}")
        await _emit({"type": "tool_end", "tool": "generate_pdf (audit)", "status": "ok", "duration_ms": 0})

        # 2. Final Deliverable
        final_prompt = f"""You are the Expert Technical Writer.
Your ONLY job is to generate the final, polished deliverable based strictly on the provided context.
User Intent: {user_intent}
Retrieval Confidence: {confidence}

Rules:
1. Use ONLY the provided context. DO NOT hallucinate or guess.
2. Focus heavily on beautiful typography, clear markdown headings (## and ###), bullet points, and data presentation.
3. If doing a comparison, use clear, distinct sections for each subject and use Markdown Tables to compare their traits side-by-side.
4. CRITICAL: DO NOT use git-diff style formatting (do NOT use `+` or `-` to represent different candidates). Use proper English sentences and structured lists.
5. You MUST display the "Retrieval Confidence Score" (e.g., Confidence: {confidence}) prominently at either the very top or very bottom of the document.
6. No reasoning or conversational filler. Just the polished user-facing output."""

        print("📄 Generating Final Deliverable...")
        await _emit({"type": "tool_start", "tool": "generate_pdf (final)"})
        final_result = await call_llm(provider, model_name,
            [{"role": "system", "content": final_prompt}, {"role": "user", "content": f"Context Data:\n{content}"}],
            temperature=0.1
        )
        final_markdown = final_result.get("content", "")
        final_pdf_result = await execute_mcp_tool("generate_pdf", {
            "content": final_markdown,
            "filename": f"final_deliverable_{user_intent.replace(' ', '_')[:20]}.pdf"
        })
        if "error" in final_pdf_result.lower():
            print(f"❌ ERROR GENERATING FINAL PDF: {final_pdf_result}")
        await _emit({"type": "tool_end", "tool": "generate_pdf (final)", "status": "ok", "duration_ms": 0})

        duration_ms = int((time.time() - writer_start) * 1000)
        await _emit({"type": "tool_end", "tool": "delegate_to_writer", "status": "ok", "duration_ms": duration_ms})

        messages.append({
            "role": "tool",
            "tool_call_id": delegate_call["id"],
            "name": "delegate_to_writer",
            "content": f"Agent 2 successfully generated both PDFs.\n\nAudit Report Generated.\nFinal Deliverable PDF Status: {final_pdf_result}\n\nFinal Text Preview:\n{final_markdown[:1000]}..."
        })
        return {
            "messages": messages,
            "tool_calls_made": state.get("tool_calls_made", []) + ["delegate_to_writer", "generate_pdf", "generate_pdf"]
        }

    return llm_node, tool_node, writer_node


# --- Graph Construction ---

def build_graph(event_queue: asyncio.Queue | None = None) -> StateGraph:
    """Build and compile the LangGraph agent workflow."""
    llm_node, tool_node, writer_node = _build_nodes(event_queue)

    def should_continue(state: AgentState):
        last_message = state["messages"][-1]
        if last_message.get("tool_calls"):
            for tc in last_message["tool_calls"]:
                if tc["function"]["name"] == "delegate_to_writer":
                    return "writer"
            return "tools"
        return END

    workflow = StateGraph(AgentState)
    workflow.add_node("agent", llm_node)
    workflow.add_node("tools", tool_node)
    workflow.add_node("writer", writer_node)
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", should_continue, {
        "tools": "tools",
        "writer": "writer",
        END: END
    })
    workflow.add_edge("tools", "agent")
    workflow.add_edge("writer", "agent")

    return workflow.compile()


# --- Tool Result Cleaning ---

def _clean_tool_result(tool_name: str, result_str: str) -> str:
    """Clean and compress tool results to preserve LLM context tokens."""
    clean_result = result_str

    # Strip screenshot data from JSON
    try:
        parsed = json.loads(result_str)
        if isinstance(parsed, dict):
            if "screenshot" in parsed and parsed["screenshot"]:
                parsed["screenshot"] = "[screenshot captured]"
            if "data" in parsed:
                parsed["data"] = "[image data]"
            clean_result = json.dumps(parsed, indent=2)
    except (json.JSONDecodeError, TypeError):
        pass

    # Compress large Playwright page snapshots
    if tool_name in ("get_page_snapshot", "browser_click_element", "browser_type_text", "navigate_and_summarize"):
        try:
            parsed_result = json.loads(clean_result)
            if isinstance(parsed_result, dict) and "page_content" in parsed_result:
                raw_content = parsed_result["page_content"]
                lines = raw_content.split('\n')
                compressed_lines = []
                for line in lines:
                    lower_line = line.lower()
                    if any(kw in lower_line for kw in ("link", "button", "heading", "textbox", "listitem")) or len(line.strip()) > 40:
                        compressed_lines.append(line)
                parsed_result["page_content"] = "\n".join(compressed_lines)
                clean_result = json.dumps(parsed_result, indent=2)
        except (json.JSONDecodeError, TypeError):
            lines = clean_result.split('\n')
            compressed_lines = []
            for line in lines:
                lower_line = line.lower()
                if any(kw in lower_line for kw in ("link", "button", "heading", "textbox", "listitem")) or len(line.strip()) > 40:
                    compressed_lines.append(line)
            clean_result = "\n".join(compressed_lines)

    # Final size cap
    if len(clean_result) > 30000:
        half = 14500
        clean_result = clean_result[:half] + "\n... [MIDDLE CONTENT TRUNCATED] ...\n" + clean_result[-half:]

    return clean_result


# --- Post-Processing ---

def strip_reasoning(text: str) -> str:
    """Strip Qwen-style <think>...</think> reasoning blocks from model output."""
    return re.sub(r'<think>.*?</think>\s*', '', text, flags=re.DOTALL).strip()
