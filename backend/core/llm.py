"""
LLM provider routing — unified interface for Groq and Gemini.

call_llm() accepts OpenAI-format messages and tools,
handles provider-specific conversion internally, and returns
a unified response dict: {"content": str, "tool_calls": list|None}
"""

import json
import base64
import asyncio

from groq import AsyncGroq

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

from openai import AsyncOpenAI

from backend.config import GROQ_API_KEY, GOOGLE_API_KEY, NVIDIA_API_KEY


# --- Client Initialization ---
groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GOOGLE_API_KEY) if (genai and GOOGLE_API_KEY) else None
nvidia_client = AsyncOpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=NVIDIA_API_KEY) if NVIDIA_API_KEY else None


# --- Groq OTPM Limits (free tier) ---
# Models with very low output-token-per-minute limits need capping
GROQ_MAX_TOKENS_MAP = {
    "qwen/qwen3.6-27b": 900,          # OTPM limit: 1000
    "openai-gpt-oss-120b": 900,        # conservative
    "openai-gpt-oss-20b": 2048,
}
GROQ_DEFAULT_MAX_TOKENS = 2048


async def call_llm(
    provider: str,
    model: str,
    messages: list,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    tools: list | None = None,
) -> dict:
    """Route an LLM call to the appropriate provider.

    Returns: {"content": str, "tool_calls": list[dict] | None}
    """
    if provider == "groq":
        return await _call_groq(model, messages, max_tokens, temperature, tools)
    elif provider == "gemini":
        return await _call_gemini(model, messages, max_tokens, temperature, tools)
    elif provider == "nvidia":
        return await _call_nvidia(model, messages, max_tokens, temperature, tools)
    else:
        raise ValueError(f"Unknown provider: {provider}")


# --- Groq Provider (with rate-limit retry & token capping) ---

async def _call_groq(model, messages, max_tokens, temperature, tools):
    if not groq_client:
        raise ValueError("Groq API key not configured")

    # Cap max_tokens to stay within OTPM limits for known models
    safe_max_tokens = min(max_tokens, GROQ_MAX_TOKENS_MAP.get(model, GROQ_DEFAULT_MAX_TOKENS))

    kwargs = {
        "model": model,
        "messages": messages,
        "max_tokens": safe_max_tokens,
        "temperature": temperature,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["parallel_tool_calls"] = False

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = await groq_client.chat.completions.create(**kwargs)
            msg = response.choices[0].message
            tool_calls = None
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                tool_calls = []
                for tc in msg.tool_calls:
                    tool_calls.append({
                        "id": tc.id,
                        "type": getattr(tc, "type", "function"),
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    })

            # Fallback: Groq sometimes outputs raw JSON instead of native tool calls
            if not tool_calls and msg.content and '"type": "function"' in msg.content:
                try:
                    content_str = msg.content.strip()
                    if content_str.startswith("{"):
                        parsed = json.loads(content_str)
                        if "name" in parsed and "parameters" in parsed:
                            import uuid
                            tool_calls = [{
                                "id": "call_" + str(uuid.uuid4())[:8],
                                "type": "function",
                                "function": {
                                    "name": parsed["name"],
                                    "arguments": json.dumps(parsed["parameters"]) if isinstance(parsed["parameters"], dict) else parsed["parameters"]
                                }
                            }]
                            msg.content = ""
                except Exception:
                    pass

            return {"content": msg.content or "", "tool_calls": tool_calls}

        except Exception as e:
            error_str = str(e)

            # Rate limit (429) — wait and retry with reduced tokens
            if "429" in error_str or "rate_limit" in error_str:
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 8  # 8s, 16s, 24s backoff
                    print(f"⚠️  Groq rate limit hit (attempt {attempt + 1}/{max_retries}). "
                          f"Retrying in {wait_time}s with reduced tokens...")

                    # Further reduce tokens on retry
                    kwargs["max_tokens"] = max(256, kwargs["max_tokens"] // 2)
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    return {
                        "content": (
                            "⚠️ Rate limit reached on this model. The Groq free tier has strict "
                            "output-token-per-minute limits. Please try again in a minute, or "
                            "switch to a Gemini model from the model selector."
                        ),
                        "tool_calls": None
                    }

            # Other errors
            return {
                "content": f"I encountered an error from the Groq provider: {error_str}\n\n"
                           "Please adjust your prompt or switch models and try again.",
                "tool_calls": None
            }

    # Should not reach here, but safety fallback
    return {"content": "Unexpected error after retries.", "tool_calls": None}


# --- Gemini Provider (with thought_signature preservation) ---

async def _call_gemini(model, messages, max_tokens, temperature, tools):
    if not gemini_client:
        raise ValueError("Google Gemini API key not configured")

    system_instruction = None
    gemini_contents = []

    for msg in messages:
        if msg["role"] == "system":
            system_instruction = msg["content"]

        elif msg.get("role") == "tool":
            gemini_contents.append(types.Content(
                role="user",
                parts=[types.Part.from_function_response(
                    name=msg.get("name", "unknown_tool"),
                    response={"result": msg.get("content", "")}
                )]
            ))

        elif msg.get("role") == "assistant" and msg.get("_gemini_parts"):
            # If we stored the raw Gemini parts, use them directly for perfect fidelity
            gemini_contents.append(types.Content(
                role="model",
                parts=msg["_gemini_parts"]
            ))

        elif msg.get("role") == "assistant" and msg.get("tool_calls"):
            parts = []

            # Re-attach thought_signature if we preserved it
            thought_sig = msg.get("_thought_signature")
            if thought_sig:
                parts.append(types.Part(thought=True, text="", thought_signature=thought_sig))

            if msg.get("content"):
                parts.append(types.Part.from_text(text=msg["content"]))

            for tc in msg["tool_calls"]:
                try:
                    args = json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]
                except (json.JSONDecodeError, TypeError):
                    args = {}
                parts.append(types.Part.from_function_call(
                    name=tc["function"]["name"],
                    args=args
                ))
            gemini_contents.append(types.Content(role="model", parts=parts))

        else:
            if isinstance(msg.get("content"), list):
                parts = []
                for item in msg["content"]:
                    if item["type"] == "text":
                        parts.append(types.Part.from_text(text=item["text"]))
                    elif item["type"] == "image_url":
                        url = item["image_url"]["url"]
                        if url.startswith("data:"):
                            mime = url.split(";", 1)[0].replace("data:", "")
                            b64 = url.split(",", 1)[1]
                            parts.append(types.Part.from_bytes(
                                data=base64.b64decode(b64), mime_type=mime
                            ))
                gemini_contents.append(types.Content(
                    role="user" if msg["role"] == "user" else "model",
                    parts=parts
                ))
            else:
                content_text = msg.get("content") or ""
                if content_text:
                    gemini_contents.append(types.Content(
                        role="user" if msg["role"] == "user" else "model",
                        parts=[types.Part.from_text(text=content_text)]
                    ))

    # Convert OpenAI-format tools to Gemini FunctionDeclarations
    gemini_tools = None
    if tools:
        func_declarations = []
        for t in tools:
            fn = t.get("function", {})
            params = fn.get("parameters", {})
            clean_params = {k: v for k, v in params.items() if k in ("type", "properties", "required")}
            func_declarations.append(types.FunctionDeclaration(
                name=fn.get("name", ""),
                description=fn.get("description", ""),
                parameters_json_schema=clean_params if clean_params else None
            ))
        gemini_tools = [types.Tool(function_declarations=func_declarations)]

    config = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        # Enable thinking to properly support thought_signature
        thinking_config=types.ThinkingConfig(thinking_budget=1024),
    )
    if system_instruction:
        config.system_instruction = system_instruction
    if gemini_tools:
        config.tools = gemini_tools

    try:
        response = await gemini_client.aio.models.generate_content(
            model=model,
            contents=gemini_contents,
            config=config
        )

        tool_calls = None
        thought_signature = None
        raw_parts = []

        # Extract thought_signature and function calls from response parts
        if response.candidates and response.candidates[0].content:
            raw_parts = response.candidates[0].content.parts or []

            for part in raw_parts:
                # Capture thought_signature if present
                if hasattr(part, 'thought_signature') and part.thought_signature:
                    thought_signature = part.thought_signature

        if response.function_calls:
            import uuid
            tool_calls = []
            for fc in response.function_calls:
                tool_calls.append({
                    "id": "call_" + str(uuid.uuid4())[:8],
                    "type": "function",
                    "function": {
                        "name": fc.name,
                        "arguments": json.dumps(fc.args) if fc.args else "{}"
                    }
                })

        content = ""
        # Safely extract text without triggering SDK warning about non-text parts
        # and ensure we don't include thought parts in the final content
        if raw_parts:
            parts_text = []
            for part in raw_parts:
                if hasattr(part, 'text') and part.text and not getattr(part, 'thought', False):
                    parts_text.append(part.text)
            
            if parts_text:
                content = "".join(parts_text)
        else:
            try:
                if response.text:
                    content = response.text
            except Exception:
                pass
            
        if not content and not tool_calls:
            content = "No text was returned."

        result = {"content": content, "tool_calls": tool_calls}

        # Preserve thought_signature so the agent can pass it back on the next turn
        if thought_signature:
            result["_thought_signature"] = thought_signature

        # Preserve raw Gemini parts for perfect round-trip fidelity
        if raw_parts:
            result["_gemini_parts"] = raw_parts

        return result

    except Exception as e:
        error_str = str(e)
        print(f"❌ Gemini API error: {error_str}")

        # If it's a thought_signature issue, retry without thinking enabled
        if "thought_signature" in error_str or "INVALID_ARGUMENT" in error_str:
            print("🔄 Retrying Gemini call without thinking config...")
            try:
                config_retry = types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                )
                if system_instruction:
                    config_retry.system_instruction = system_instruction
                if gemini_tools:
                    config_retry.tools = gemini_tools

                response = await gemini_client.aio.models.generate_content(
                    model=model,
                    contents=gemini_contents,
                    config=config_retry
                )

                tool_calls = None
                if response.function_calls:
                    import uuid
                    tool_calls = []
                    for fc in response.function_calls:
                        tool_calls.append({
                            "id": "call_" + str(uuid.uuid4())[:8],
                            "type": "function",
                            "function": {
                                "name": fc.name,
                                "arguments": json.dumps(fc.args) if fc.args else "{}"
                            }
                        })

                content = ""
                if response.text:
                    content = response.text
                elif not tool_calls:
                    content = "No text was returned."

                return {"content": content, "tool_calls": tool_calls}

            except Exception as retry_e:
                return {
                    "content": f"Gemini error persists after retry: {str(retry_e)}\n\n"
                               "Please try switching to a Groq model.",
                    "tool_calls": None
                }

        return {
            "content": f"I encountered an error from the Gemini provider: {error_str}\n\n"
                       "Please adjust your prompt and try again.",
            "tool_calls": None
        }

# --- NVIDIA Provider ---

async def _call_nvidia(model, messages, max_tokens, temperature, tools):
    if not nvidia_client:
        raise ValueError("NVIDIA API key not configured")

    kwargs = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": True}, "reasoning_budget": max_tokens},
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["parallel_tool_calls"] = False

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = await nvidia_client.chat.completions.create(**kwargs)
            msg = response.choices[0].message
            tool_calls = None
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                tool_calls = []
                for tc in msg.tool_calls:
                    tool_calls.append({
                        "id": tc.id,
                        "type": getattr(tc, "type", "function"),
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    })

            # Extract thinking content if present (stored differently from content)
            # The user's snippet shows it is in delta.reasoning_content for streaming, 
            # but for non-streaming it might be in msg.reasoning_content or msg.content
            # We'll just stick to standard content parsing since we are not streaming here.
            content = msg.content or ""
            return {"content": content, "tool_calls": tool_calls}

        except Exception as e:
            error_str = str(e)
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2
                print(f"⚠️  NVIDIA API error (attempt {attempt + 1}/{max_retries}): {error_str}. Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
                continue
            else:
                return {
                    "content": f"I encountered an error from the NVIDIA provider: {error_str}\n\nPlease try again.",
                    "tool_calls": None
                }
