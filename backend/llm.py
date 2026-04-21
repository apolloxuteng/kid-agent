"""
LLM integration: system prompt, chat completion, tool calling, and summary.
Supports Ollama by default and LM Studio's OpenAI-compatible API when
LLM_PROVIDER=lmstudio.
"""

import asyncio
import json
import logging
import os

import httpx

from config import DEBUG_NO_HISTORY, OLLAMA_CHAT_TIMEOUT, OLLAMA_SUMMARY_TIMEOUT, RECENT_MESSAGES_COUNT
from fastapi import HTTPException

logger = logging.getLogger(__name__)


_ollama_client: httpx.AsyncClient | None = None

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_CHAT_URL = os.environ.get("OLLAMA_CHAT_URL") or OLLAMA_URL.replace("/api/generate", "/api/chat")
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").strip().lower()
LMSTUDIO_BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1").rstrip("/")
LMSTUDIO_CHAT_URL = os.environ.get("LMSTUDIO_CHAT_URL") or f"{LMSTUDIO_BASE_URL}/chat/completions"
MODEL_NAME = os.environ.get(
    "MODEL_NAME",
    "lmstudio/google/gemma-4-26b-a4b" if LLM_PROVIDER == "lmstudio" else "qwen2.5",
)
MAX_TOOL_LOOP_ITERATIONS = 5


def set_ollama_client(client: httpx.AsyncClient | None) -> None:
    """Set the shared Ollama HTTP client (called from server lifespan)."""
    global _ollama_client
    _ollama_client = client


def get_ollama_client() -> httpx.AsyncClient | None:
    """Return the shared Ollama client (for streaming in server)."""
    return _ollama_client


def _provider_name() -> str:
    return "LM Studio" if LLM_PROVIDER == "lmstudio" else "Ollama"


def _parse_tool_calls(raw_tool_calls: list[dict]) -> list[dict]:
    """Normalize tool calls into {name, arguments, id} for Ollama/OpenAI-compatible APIs."""
    tool_calls = []
    for index, tc in enumerate(raw_tool_calls):
        fn = tc.get("function") if isinstance(tc, dict) else None
        if not fn:
            continue
        name = fn.get("name")
        args_raw = fn.get("arguments")
        if isinstance(args_raw, str):
            try:
                args = json.loads(args_raw) if args_raw.strip() else {}
            except json.JSONDecodeError:
                args = {}
        else:
            args = args_raw if isinstance(args_raw, dict) else {}
        if name:
            tool_calls.append({
                "name": name,
                "arguments": args,
                "id": tc.get("id") or f"tool_call_{index}",
            })
    return tool_calls


def _append_stream_tool_call_delta(acc: dict[int, dict], raw_tool_calls: list[dict]) -> None:
    """Accumulate OpenAI-compatible streaming tool-call deltas by index."""
    for position, tc in enumerate(raw_tool_calls):
        if not isinstance(tc, dict):
            continue
        index = tc.get("index")
        if index is None:
            index = position
        item = acc.setdefault(index, {"id": None, "name": "", "arguments": ""})
        if tc.get("id"):
            item["id"] = tc["id"]
        fn = tc.get("function") or {}
        if fn.get("name"):
            item["name"] += fn["name"]
        if fn.get("arguments"):
            item["arguments"] += fn["arguments"]


def _stream_tool_call_accumulator_to_list(acc: dict[int, dict]) -> list[dict]:
    raw = []
    for index in sorted(acc):
        item = acc[index]
        if not item.get("name"):
            continue
        raw.append({
            "id": item.get("id") or f"tool_call_{index}",
            "function": {
                "name": item["name"],
                "arguments": item.get("arguments") or "{}",
            },
        })
    return _parse_tool_calls(raw)


SYSTEM_PROMPT_BASE = """CRITICAL — you must use tools for jokes, stories, facts, space pictures, images, quizzes, and calculations:
- If the child asks for a joke or something funny → call get_joke. Do not tell a joke from your own knowledge.
- If they ask for a story or tale → call get_story. Do not make up a story yourself.
- If they ask for a fact or something interesting → call get_fact. Do not invent a fact.
- If they ask for a space/astronomy picture → call get_space_picture.
- If they ask for a picture of something (e.g. dog, castle) → call search_image.
- If they ask for a quiz or trivia question → call get_quiz.
- If the child asks for a calculation or math (e.g. what is 5+3, how much is 10 times 2) → call calculate with the expression. Do not compute math yourself.
Always call the tool first, then use the tool's result in your reply. Never answer those requests without calling the matching tool.
When you receive a tool result (joke, story, fact, picture description, quiz, calculator result), present ONLY that content in a warm way — do not add another joke, story, fact, or answer from your own knowledge.

You are a warm, friendly teacher talking to an 8-year-old child.

Your goal: Be simple and easy to understand, but accurate. Explain real ideas in plain language — never dumb down facts so much that they become wrong or vague. It's okay to use a real word (e.g. "gravity", "planet") and then explain it in one short phrase.

Rules you always follow:
- Use clear, plain language and short sentences. Maximum 3–4 sentences per reply.
- Be accurate. If the child asks "why" or "how," give a correct explanation in simple terms rather than a cutesy wrong one. If you're not sure, say so simply.
- Be warm and encouraging without being babyish. Avoid excessive exclamations, baby talk, or repeating their words back in a cutesy way every time.
- Explain with simple examples when they help (animals, everyday things), but keep the underlying idea correct.
- You do not need to ask a question every time. Often just reply with a short, warm statement (a reaction, a fact, or encouragement) and let the child lead. Only ask a question occasionally when it fits naturally.
- Avoid long explanations or jargon. Prefer one clear, accurate idea over a long or fuzzy one.
- Reply in English only. Do not mix in Chinese or other languages unless the child explicitly asks you to (e.g. "say it in Chinese" or "what's the Chinese word for …").
- Reply with only your words. Do not include "User:", "Assistant:", or any role labels in your reply.

Silly and mischief requests:
- When the child asks for a silly joke, a "poopoo" or "peepee" joke, or other mischief, stay in the conversation and play along. Do not refuse, lecture, or redirect to a different topic just because the request is silly or mildly potty-themed.
- Mild potty humor and mischief (e.g. light bathroom or silly body jokes) are acceptable and fun for kids. Reply with a short, silly, kid-appropriate joke or reaction. Keep it brief and playful, not crude or explicit.
- Do not say anything truly violating: nothing explicit, harmful, or inappropriate for young children. The line is mischief and fun, not inappropriate.
- If a joke is provided below, deliver it in a warm, kid-friendly way.

"""


def get_system_prompt(profile: dict) -> str:
    """Return the system prompt, optionally including the child profile (name, interests)."""
    out = SYSTEM_PROMPT_BASE
    name = profile.get("name")
    interests = profile.get("interests") or []
    if name or interests:
        out += "Child Profile:\n"
        if name:
            out += f"- Name: {name}\n"
        if interests:
            out += f"- Interests: {', '.join(interests)}\n"
        out += "\nUse this to personalize when it fits (e.g. use their name sometimes, mention their interests). Do not reference the profile in every message — keep it natural.\n\n"
    return out


# Stop words for image search keyword fallback (heuristic to avoid LLM call when possible)
_IMAGE_SEARCH_STOP_WORDS = frozenset(
    {"show", "me", "a", "an", "the", "picture", "of", "i", "want", "to", "see", "image", "photo", "get", "can", "draw", "please", "give", "something", "is", "it", "for", "and", "or"}
)


def image_search_keywords_heuristic(user_message: str) -> str:
    """
    Extract keywords from the user message using a simple heuristic (strip stop words, first 5 words).
    Use this first to avoid an LLM call; call extract_image_search_keywords only when this returns empty.
    """
    if not user_message or not user_message.strip():
        return ""
    msg = user_message.strip()[:500].lower().replace(",", " ").replace(".", " ")
    words = [w for w in msg.split() if w.isalnum() and w not in _IMAGE_SEARCH_STOP_WORDS][:5]
    return " ".join(words)[:100].strip()


async def extract_image_search_keywords(user_message: str) -> str:
    """
    Extract 2-5 English keywords for Pixabay image search from the child's message.
    Uses a one-shot LLM call; falls back to heuristic if LLM fails or returns empty.
    """
    if not user_message or not user_message.strip():
        return ""
    user_message = user_message.strip()[:500]
    prompt = (
        "The child asked for an image. Reply with only 2 to 5 comma-separated English keywords for an image search. Nothing else.\n"
        f"Child's request: {user_message}"
    )
    out = await call_ollama(prompt, timeout=15, raise_on_error=False)
    if out:
        # Take first 100 chars, strip, remove extra commas/spaces
        keywords = " ".join(out.strip().replace(",", " ").split())[:100].strip()
        if keywords:
            return keywords
    return image_search_keywords_heuristic(user_message)


async def call_ollama(prompt: str, timeout: int = 30, raise_on_error: bool = False) -> str:
    """Send a single prompt to the configured LLM; return stripped response text."""
    if _ollama_client is None:
        if raise_on_error:
            raise HTTPException(status_code=500, detail=f"{_provider_name()} client not initialized.")
        return ""
    try:
        if LLM_PROVIDER == "lmstudio":
            r = await _ollama_client.post(
                LMSTUDIO_CHAT_URL,
                json={
                    "model": MODEL_NAME,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
                timeout=timeout,
            )
        else:
            r = await _ollama_client.post(
                OLLAMA_URL,
                json={"model": MODEL_NAME, "prompt": prompt, "stream": False},
                timeout=timeout,
            )
        if r.status_code == 404:
            if raise_on_error:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"{_provider_name()} returned 404 — model or endpoint not found. "
                        f"Check MODEL_NAME='{MODEL_NAME}' and the configured server URL."
                    ),
                )
            return ""
        r.raise_for_status()
        data = r.json()
        if LLM_PROVIDER == "lmstudio":
            choices = data.get("choices") or []
            if choices:
                msg = choices[0].get("message") or {}
                return (msg.get("content") or "").strip()
            return ""
        return data.get("response", "").strip()
    except httpx.HTTPStatusError:
        if raise_on_error:
            raise HTTPException(status_code=500, detail="Ollama request failed.")
        return ""
    except httpx.ConnectError:
        if raise_on_error:
            raise HTTPException(
                status_code=500,
                detail=f"Could not reach {_provider_name()}. Is the server running?",
            )
        return ""
    except httpx.TimeoutException:
        if raise_on_error:
            raise HTTPException(
                status_code=500,
                detail="Ollama took too long to respond. Try again or check your model.",
            )
        return ""
    except (httpx.RequestError, ValueError) as e:
        if raise_on_error:
            raise HTTPException(status_code=500, detail=f"Ollama request failed: {str(e)}")
        return ""


async def stream_ollama(prompt: str, timeout: int = 60):
    """Stream tokens from the configured LLM as an async generator."""
    if _ollama_client is None:
        return
    if LLM_PROVIDER == "lmstudio":
        url = LMSTUDIO_CHAT_URL
        payload = {
            "model": MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }
    else:
        url = OLLAMA_URL
        payload = {"model": MODEL_NAME, "prompt": prompt, "stream": True}
    async with _ollama_client.stream("POST", url, json=payload, timeout=timeout) as response:
        if response.status_code == 404:
            return
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.strip():
                continue
            if LLM_PROVIDER == "lmstudio":
                if not line.startswith("data: "):
                    continue
                payload_text = line.removeprefix("data: ").strip()
                if payload_text == "[DONE]":
                    break
                try:
                    obj = json.loads(payload_text)
                    choices = obj.get("choices") or []
                    delta = (choices[0].get("delta") or {}) if choices else {}
                    part = delta.get("content") or ""
                    if part:
                        yield part
                except json.JSONDecodeError:
                    continue
                continue
            try:
                obj = json.loads(line)
                part = obj.get("response", "")
                if part:
                    yield part
                if obj.get("done"):
                    break
            except json.JSONDecodeError:
                continue


async def update_summary(history: list[dict], old_summary: str) -> str:
    """Summarize the conversation for a children's assistant in under 40 words. Returns new summary or old if LLM fails."""
    if not history:
        return old_summary or ""
    lines = []
    for entry in history:
        role = "User" if entry["role"] == "user" else "Assistant"
        lines.append(f"{role}: {entry['content'].strip()}")
    conv_block = "\n".join(lines)
    prev = f"Previous summary: {old_summary}\n\n" if old_summary else ""
    prompt = f"""Summarize the conversation for a children's assistant in under 40 words.

{prev}Conversation:
{conv_block}

Summary:"""
    return await call_ollama(prompt, timeout=OLLAMA_SUMMARY_TIMEOUT) or old_summary or ""


def strip_role_labels(text: str) -> str:
    """Remove leading 'Assistant:' / 'User:' so only the reply text is returned."""
    if not text:
        return text
    out = text.strip()
    while True:
        lower = out.lower().lstrip()
        if lower.startswith("assistant:"):
            out = out[out.lower().find("assistant:") + len("assistant:") :].strip()
        elif lower.startswith("user:"):
            out = out[out.lower().find("user:") + len("user:") :].strip()
        else:
            break
    return out.strip()


async def chat_with_tools(
    messages: list[dict],
    tools: list[dict],
    timeout: int = 60,
) -> tuple[str, list[dict]]:
    """
    Send a chat request with tool definitions. Returns (message_content, tool_calls).
    tool_calls is a list of { "name": str, "arguments": dict } (or empty if model replied without tools).
    """
    if _ollama_client is None:
        raise HTTPException(status_code=500, detail=f"{_provider_name()} client not initialized.")
    payload = {"model": MODEL_NAME, "messages": messages, "stream": False}
    if tools:
        payload["tools"] = tools
    try:
        url = LMSTUDIO_CHAT_URL if LLM_PROVIDER == "lmstudio" else OLLAMA_CHAT_URL
        r = await _ollama_client.post(url, json=payload, timeout=timeout)
        if r.status_code == 404:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"{_provider_name()} returned 404 — model '{MODEL_NAME}' not found or endpoint is unavailable."
                ),
            )
        r.raise_for_status()
        data = r.json()
        if LLM_PROVIDER == "lmstudio":
            choices = data.get("choices") or []
            msg = (choices[0].get("message") or {}) if choices else {}
        else:
            msg = data.get("message") or {}
        content = (msg.get("content") or "").strip()
        tool_calls = _parse_tool_calls(msg.get("tool_calls") or [])

        # Debug: log LLM response (tool selection vs plain reply)
        if tool_calls:
            logger.info(
                "LLM returned tool_calls: %s (content preview: %s)",
                [tc["name"] for tc in tool_calls],
                (content[:150] + "..." if len(content) > 150 else content) or "(empty)",
            )
        else:
            logger.info(
                "LLM returned no tool_calls; plain reply (first 200 chars): %s",
                (content[:200] + "..." if len(content) > 200 else content) or "(empty)",
            )
        return (content, tool_calls)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=500, detail=f"{_provider_name()} chat request failed: {e}")
    except httpx.ConnectError:
        raise HTTPException(status_code=500, detail=f"Could not reach {_provider_name()}. Is it running?")
    except httpx.TimeoutException:
        raise HTTPException(status_code=500, detail=f"{_provider_name()} took too long to respond.")


async def chat_with_tools_stream(messages: list[dict], tools: list[dict], timeout: int = 60):
    """
    Like chat_with_tools but with stream=True. Yields content deltas (str) as they arrive;
    at the end yields ("_done_", full_content, tool_calls) so the caller can forward tokens
    and then handle the final (content, tool_calls).
    """
    if _ollama_client is None:
        raise HTTPException(status_code=500, detail=f"{_provider_name()} client not initialized.")
    payload = {"model": MODEL_NAME, "messages": messages, "stream": True}
    if tools:
        payload["tools"] = tools
    try:
        url = LMSTUDIO_CHAT_URL if LLM_PROVIDER == "lmstudio" else OLLAMA_CHAT_URL
        async with _ollama_client.stream("POST", url, json=payload, timeout=timeout) as response:
            if response.status_code == 404:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"{_provider_name()} returned 404 — model '{MODEL_NAME}' not found or endpoint is unavailable."
                    ),
                )
            response.raise_for_status()
            full_content_parts: list[str] = []
            tool_calls: list[dict] = []
            openai_tool_call_deltas: dict[int, dict] = {}
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                if LLM_PROVIDER == "lmstudio":
                    if not line.startswith("data: "):
                        continue
                    payload_text = line.removeprefix("data: ").strip()
                    if payload_text == "[DONE]":
                        break
                    try:
                        data = json.loads(payload_text)
                    except json.JSONDecodeError:
                        continue
                    choices = data.get("choices") or []
                    delta = (choices[0].get("delta") or {}) if choices else {}
                    content_delta = delta.get("content") or ""
                    if content_delta:
                        full_content_parts.append(content_delta)
                        yield content_delta
                    raw_tool_calls = delta.get("tool_calls") or []
                    if raw_tool_calls:
                        _append_stream_tool_call_delta(openai_tool_call_deltas, raw_tool_calls)
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = data.get("message") or {}
                delta = msg.get("content") or ""
                if delta:
                    full_content_parts.append(delta)
                    yield delta
                # Ollama can send tool_calls in a chunk with done: false; accumulate from every chunk.
                raw_tool_calls = msg.get("tool_calls") or []
                if raw_tool_calls:
                    parsed = _parse_tool_calls(raw_tool_calls)
                    if parsed:
                        tool_calls = parsed
                if data.get("done"):
                    break
            full_content = "".join(full_content_parts).strip()
            if LLM_PROVIDER == "lmstudio":
                tool_calls = _stream_tool_call_accumulator_to_list(openai_tool_call_deltas)
            if tool_calls:
                logger.info("LLM stream returned tool_calls: %s", [t["name"] for t in tool_calls])
            else:
                logger.info("LLM stream returned plain reply (first 200 chars): %s", (full_content[:200] + "..." if len(full_content) > 200 else full_content) or "(empty)")
            yield ("_done_", full_content, tool_calls)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=500, detail=f"{_provider_name()} chat request failed: {e}")
    except httpx.ConnectError:
        raise HTTPException(status_code=500, detail=f"Could not reach {_provider_name()}. Is it running?")
    except httpx.TimeoutException:
        raise HTTPException(status_code=500, detail=f"{_provider_name()} took too long to respond.")


# Tool names that fetch pictures; used to emit early "Finding a picture..." progress.
_PICTURE_TOOLS = frozenset({"get_space_picture", "search_image"})


async def run_chat_with_tools_orchestrator(
    profile: dict,
    conversation_summary: str,
    conversation_history: list[dict],
    profile_id: str,
    last_assistant_message: str | None,
    timeout: int = OLLAMA_CHAT_TIMEOUT,
):
    """
    Run the tool-calling chat loop; yields ("progress", message) for early UI feedback
    (e.g. when a picture tool is chosen) and ("result", (reply, attachments)) when done.
    Attachments is a list of (image_bytes, media_type).
    """
    from routing.context import RoutingContext
    from routing.registry import get_ollama_tool_definitions, run_tool

    # Short instruction so the model sees it in the same turn as the user message (in case system is ignored).
    _TOOL_USE_REMINDER = (
        "When the user asks for a joke, story, fact, space picture, image, quiz, or a calculation, you MUST call the matching tool "
        "(get_joke, get_story, get_fact, get_space_picture, search_image, get_quiz, calculate). Do not answer from your own knowledge.\n\n"
    )

    def _build_messages() -> list[dict]:
        out = [{"role": "system", "content": get_system_prompt(profile)}]
        if conversation_summary and not DEBUG_NO_HISTORY:
            out.append({"role": "system", "content": f"Conversation summary: {conversation_summary.strip()}"})
        if DEBUG_NO_HISTORY:
            # Debug: no history — only the current user message so we can see if the model calls the tool.
            for entry in reversed(conversation_history):
                if entry.get("role") == "user":
                    content = (entry.get("content") or "").strip()
                    if content:
                        out.append({"role": "user", "content": _TOOL_USE_REMINDER + content})
                    break
        else:
            # Only send the last N messages so context stays small and the model sees the current request.
            recent = conversation_history[-RECENT_MESSAGES_COUNT:] if len(conversation_history) > RECENT_MESSAGES_COUNT else conversation_history
            for i, entry in enumerate(recent):
                role = entry.get("role", "user")
                content = entry.get("content", "")
                if role in ("user", "assistant") and content:
                    is_last_user = role == "user" and i == len(recent) - 1
                    if is_last_user:
                        content = _TOOL_USE_REMINDER + content
                    out.append({"role": role, "content": content})
        return out

    messages = _build_messages()
    if DEBUG_NO_HISTORY:
        logger.info("DEBUG_NO_HISTORY: sent no conversation history (system + current user message only)")
    tools = await get_ollama_tool_definitions()
    tool_names = [t.get("function", {}).get("name") for t in tools if t.get("function")]
    logger.info("Tool-calling chat: sent %d tools to %s: %s", len(tools), _provider_name(), tool_names)
    ctx = RoutingContext(
        user_message=conversation_history[-1]["content"] if conversation_history and conversation_history[-1].get("role") == "user" else "",
        last_assistant_message=last_assistant_message,
        profile_id=profile_id,
        conversation_history=conversation_history,
    )
    attachments: list[tuple[bytes, str]] = []
    content = ""

    for call_index in range(MAX_TOOL_LOOP_ITERATIONS):
        if call_index == 0:
            logger.info("LLM call #1 (tool selection): %d messages", len(messages))
        else:
            logger.info("LLM call #%d (after tool result): %d messages", call_index + 1, len(messages))
        content = ""
        tool_calls: list[dict] = []
        async for event in chat_with_tools_stream(messages, tools, timeout=timeout):
            if isinstance(event, tuple) and len(event) == 3 and event[0] == "_done_":
                content, tool_calls = event[1], event[2]
                break
            yield ("token", event)
        if not tool_calls:
            reply = strip_role_labels(content or "")
            yield ("result", (reply, attachments))
            return

        # Emit progress so the client can show "Finding a picture..." immediately.
        if any((tc.get("name") or "") in _PICTURE_TOOLS for tc in tool_calls):
            yield ("progress", "Finding a picture...")

        logger.info("Executing tools: %s", [tc["name"] for tc in tool_calls])
        # Append assistant message with tool_calls in the format expected by the active provider.
        assistant_msg = {"role": "assistant", "content": content or ""}
        if LLM_PROVIDER == "lmstudio":
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.get("id") or f"tool_call_{i}",
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc.get("arguments") or {}),
                    },
                }
                for i, tc in enumerate(tool_calls)
            ]
        else:
            assistant_msg["tool_calls"] = [
                {"type": "function", "function": {"index": i, "name": tc["name"], "arguments": tc.get("arguments") or {}}}
                for i, tc in enumerate(tool_calls)
            ]
        messages.append(assistant_msg)

        # Run all tools in parallel
        results = await asyncio.gather(*[run_tool(tc["name"], ctx, tc.get("arguments") or {}) for tc in tool_calls])

        # Append tool result messages.
        # Instruct the model to present ONLY this content so it doesn't add its own joke/story/fact.
        _TOOL_RESULT_INSTR = (
            "Present ONLY the content below to the child in a warm, kid-friendly way. "
            "Do not add another joke, story, fact, or quiz from your own knowledge.\n\n"
        )
        for i, result in enumerate(results):
            if i < len(tool_calls):
                tool_name = tool_calls[i]["name"]
            else:
                tool_name = "unknown"
            text = result.text if result else "Tool failed or not found."
            tool_msg = {"role": "tool", "content": _TOOL_RESULT_INSTR + text}
            if LLM_PROVIDER == "lmstudio":
                tool_msg["tool_call_id"] = tool_calls[i].get("id") or f"tool_call_{i}"
            else:
                tool_msg["tool_name"] = tool_name
            messages.append(tool_msg)
            if result and result.image:
                attachments.append(result.image)

    # Max iterations reached; use last content as reply
    reply = strip_role_labels(content if content else "I'm having a little trouble. Want to try again?")
    yield ("result", (reply, attachments))


def build_prompt(
    profile: dict,
    conversation_summary: str,
    conversation_history: list[dict],
    joke: tuple[str, str] | None = None,
    injected_fact: str | None = None,
    story_seed: str | None = None,
) -> str:
    """Assemble SYSTEM PROMPT + CHILD PROFILE + CONVERSATION SUMMARY + [JOKE/FACT/STORY BLOCKS] + RECENT MESSAGES (last 6)."""
    parts = [get_system_prompt(profile)]

    if conversation_summary:
        parts.append("Conversation summary:\n")
        parts.append(conversation_summary.strip())
        parts.append("\n\n")

    if joke is not None:
        setup, punchline = joke
        parts.append("Joke to deliver (use this):\n")
        parts.append(f"Setup: {setup}\n")
        parts.append(f"Punchline: {punchline}\n\n")
        parts.append("Deliver this joke in a warm, kid-friendly way in one or two sentences.\n\n")

    if injected_fact:
        parts.append("Use this fact when answering:\n")
        parts.append(f"{injected_fact}\n\n")
        parts.append("Explain it simply in 2–3 sentences so the child can understand. Keep it warm and engaging.\n\n")

    if story_seed:
        parts.append("Use this idea for a short, funny story:\n")
        parts.append(f"{story_seed}\n\n")
        parts.append(
            "Tell an engaging story based on this idea. For this reply only, you may write a longer story (e.g. 6–10 sentences or a short paragraph) "
            "with a clear beginning, middle, and end. Keep it kid-friendly and fun. The usual 3–4 sentence limit does not apply here.\n\n"
        )

    recent = conversation_history[-RECENT_MESSAGES_COUNT:] if conversation_history else []
    if recent:
        parts.append("Recent messages:\n")
        for entry in recent:
            role = "User" if entry["role"] == "user" else "Assistant"
            parts.append(f"{role}: {entry['content'].strip()}\n")
        parts.append("\n")

    parts.append("Assistant:")
    return "".join(parts)
